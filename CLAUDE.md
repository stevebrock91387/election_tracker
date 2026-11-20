# CLAUDE.md — election-tracker

Steve's own 2028 US election results tracking system, built from official state/county sources rather than AP. Goal is to eventually make my own projections and race calls, like a TV decision desk (think Steve Kornacki).

## Scope

All three federal races on Nov 7, 2028:

- **President** — 538 electoral votes; Maine and Nebraska also award votes by congressional district.
- **Senate** — 34 regular Class 3 seats, plus a likely Tennessee special election (expected, not yet confirmed).
- **House** — all 435 seats. The hard part is districts that split counties.

## Plan

Six steps; full version on the whiteboard: https://claude.ai/artifact/G1GZgLyj8raYiqzHHTCXSY

1. **Source list** — each state's official results site, format, reporting level, update cadence. ← IN PROGRESS
2. **Readers**, one per format (Clarity, custom state feeds, HTML). Save each raw download with a timestamp and SHA-256 hash before parsing.
3. **Checks** — totals never decrease, votes never exceed registered voters, counties add up to the state total. AP numbers are a cross-check only, never a source.
4. **Expected vote** — each county's 2024 turnout, adjusted for the change in registered voters, shown as a range.
5. **Projections** — each county's swing vs. its 2024 result, applied to the vote still out, split by vote type. *Proposal, not yet approved.*
6. **Calls**, plus per-race pages that replace the earlier Mississippi and Alaska Senate tracker pages.

Dry runs: load the 2026 certified results and compare to the official totals; then the 2027 KY/LA/MS state elections; then the 2028 primaries.

## Current state (as of 2026-11-20)

- `sources/registry.csv` — 51 rows (50 states + DC): 13 verified, 9 partial, 29 unverified.
  - **verified** = official URL confirmed from an official page or a 2026 source
  - **partial** = site exists, but format or reporting level not confirmed
  - **unverified** = `candidate_url` is a guess, not yet checked
  - A row becomes verified only after a person (or Claude, in a browser) looks at the page. **An HTTP 200 alone is not verification.**
- `tools/check_sources.py` — stdlib-only, read-only URL checker. Run it with `/opt/homebrew/bin/python3` (needs TLS 1.3; it exits early otherwise and records the Python/SSL versions in each row).
- `evidence/check-20261120T194311Z.csv` — first run from this Mac (Xcode Python 3.9.6, LibreSSL 2.8.3).
- `evidence/check-20261120T195122Z.csv` — re-run under Homebrew Python 3.14.8, OpenSSL 3.6.5.

### What the first check found

- Clarity's 200 for CO/IA/SC/WV is the same generic page (identical hash), so it proves nothing about those states. AR/KY got 403 from Clarity, which may mean they're no longer on it (unconfirmed).
- 403 responses (AZ, AR, KY, MO, NH, NY, OK, TX, NV, WI) most likely mean the site blocks non-browser clients, not that the site is gone.
- GA, UT, WA all redirect to `/results/public/<state>` — possibly one shared platform.
- ME candidate URL is a 404. MA failed with a TLS protocol-version error (resolved, see below). CA returned only 212 bytes (likely a placeholder between elections).
- MI, NJ and WI publish no statewide results on election night; results come from 83 + 21 + 72 county sites.
- PA's daily Supplemental Election Returns Report estimates the share of mail ballots still uncounted — a useful input for step 4.

### MA TLS error: resolved (2026-11-20)

- Root cause: the MA site refuses TLS 1.2; the default `python3` (Xcode 3.9.6, LibreSSL 2.8.3) supports at most TLS 1.2. Under Homebrew Python, MA returns 200. MA is still **unverified** (nobody has looked at the page).
- Other changes in the re-run: NY 403 → 200; NV 403 → `HTTPError 302` (redirect Python gave up on; not diagnosed); MN's 200 now lands on a Radware bot-check page (`validate.perfdrive.com`), not the results site. The checker can't tell a bot-check page from a real 200.
- The registry's `check_20261120` column holds the **first** run's results; it was not rewritten from the re-run.

## Historical results (started 2026-11-20)

Steve chose to start loading past results now, ahead of the source-verification queue, with the House as the priority ("the House is up for grabs in 2028").

- **Precinct level is required for the House.** Several states redrew lines in 2025–26 and more may redraw for 2028 (per news reports, unverified: MD likely, MO measure on the Nov 2026 ballot, CO blocked). District totals go stale; precinct results can be re-added under any map, which also needs precinct boundaries.
- **Senate baseline is 2022, not 2026.** The 2028 Class 3 seats last ran in 2022; 2026 was Class 2.
- `sources/history.csv` — registry of historical datasets (same status vocabulary as the main registry, plus `checked_against_official`).
- `tools/fetch_github_dir.py` — downloads one directory of a GitHub repo pinned to a commit; writes a manifest with bytes, git blob hash and SHA-256. Raw files go to `data/raw/` (gitignored); manifests go to `evidence/`.
- Downloaded 2026-11-20, nothing extracted or parsed yet:
  - MIT MEDSL 2024 precinct, all offices: 51 state zips, 118.4 MB, commit `df531089c78e` (`evidence/fetch-20261120T200250Z.csv`).
  - MIT MEDSL 2022 precinct, all offices: 51 state zips, 89.6 MB, commit `a8126c5790b8` (`evidence/fetch-20261120T200305Z.csv`). One zip has 2 members (not yet identified).
- **MEDSL is a compilation, not an official source.** AZ 2024 comes from OpenElections; GA HI IN NV NJ NY OR SD list no source; MEDSL says AI tools used in collection can hallucinate data. Every state must be checked against official certified totals before use. Vote-mode labels are not standardized across states, and a `TOTAL` row can coexist with split modes (double-count risk).
- **2026:** no compiled dataset exists; states are still certifying (latest around Dec 11, CA, per news reports). Take it from official state sites after certification.
- Not yet obtained: precinct boundaries (UF Election Lab has 2024 shapes; license unverified, some downloads need an account), 2022 codebook/sources not read, MEDSL county-president and House-district datasets (unverified links).

## Next tasks, in order

1. ~~Diagnose the MA TLS error~~ — done 2026-11-20 (see above).
2. Verify the 29 unverified rows and the 10 403 rows by actually looking at the pages. Find live election-night sources for ME, KS, RI and CT.
3. Only after that, start step 2 with the Clarity reader, tested against real 2026 data.

## How I work

- Small, verifiable commits; flag it if scope grows.
- Deterministic, inspectable code; no LLM-based logic unless I ask for it.
- Never present an unverified URL or number as fact. Mark it unverified.
- When something misbehaves, gather diagnostic data before proposing a fix.
- Be direct; no preamble.
