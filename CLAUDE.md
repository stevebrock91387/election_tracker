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
- **2024 President check (2026-11-20).** `tools/medsl_county.py` sums MEDSL precincts to counties (rules in its docstring: TOTAL preferred per precinct-candidate, `*` not counted, tally rows dropped, no silent corrections). `tools/compare_fec_president.py` compares state Trump/Harris totals with the FEC's official compilation (`data/raw/fec-2024/2024presgeresults.xlsx`, hash in `evidence/fetch-fec-2024presgeresults.csv`). Result in `evidence/compare-2024-president-medsl-vs-fec.csv`: **28/51 states match exactly**; 20 differ by under ~17k votes combined (causes not investigated; CA/NM/NV/KS have suppressed `*` cells); 3 are unusable as-is:
  - LA: about half the vote is missing (−590,637 Trump, −366,433 Harris); only precinct TOTAL rows exist.
  - NJ: +283k/+280k. Gloucester has a "COUNTY TOTAL" row as a precinct; Bergen's TOTAL rows are about 2× its split-mode rows.
  - IN: +87k/+60k. Hendricks precinct "1229-Washington 29" appears twice, once with ~50k Trump votes (looks like a county total).
- Goal (Steve): the 2024 replay is practice; the real dry run is against 2026 results. Replay plan: hide part of each state's counties, project the rest, score against the final count. Needs a 2020 baseline (not yet downloaded) and Steve's decision on step 5.
- Not yet obtained: precinct boundaries (UF Election Lab has 2024 shapes; license unverified, some downloads need an account), 2022 codebook/sources not read, MEDSL county-president and House-district datasets (unverified links).

### Source verification pass (2026-11-20)

Every registry row was looked at in the built-in browser. **48 verified, 3 partial (IL, MA, MS), 0 unverified.** Each row's `evidence` says where the link came from and what the page showed.

- Platforms worth one reader each: **Enhanced Voting** (AZ GA UT WA VA RI ID; shared JSON export, see `docs/enhanced-voting.md`), **Clarity** (CO IA SC WV; election ID changes per election, bare `/<ST>/` is a generic shell), the **ResultsAjax.svc** family (MT NE NM OR SD), and Tally-style ENR (AR ND).
- Sites that moved for 2026: AR (tally-enr), TX (civixapps), ND (resultsnd), KS (kssos.org → ent.sos.ks.gov).
- No statewide election-night feed from the state: NH, ME, WY, MS, IL, MA, plus MI, NJ, WI.
- Blockers for automation: CA (Incapsula), PA (reCAPTCHA). Don't bypass either.
- Not yet done: no API or export other than AZ's has been downloaded or parsed.

### Step 2: Enhanced Voting reader (built 2026-11-20)

`pipeline/` package: `fetch.py` (120 s minimum interval per source, raw body + `data/raw/manifest.csv` row before parsing), `schema.py` (common long-format columns), `readers/enhanced_voting.py`, `sources.toml` (AZ GA UT WA VA RI ID), CLI `python3 -m pipeline.run_ev`. Tests: `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (45 with Clarity). All seven 2026 exports parse with 0 statewide-vs-county mismatches **when matched by option id**; an earlier claim of GA/WA source faults was a name-matching bug, corrected in `docs/enhanced-voting.md`. Ranked-choice contests are skipped and listed. Output carries `choice_id` and `contest_scope` (statewide/local; added at Steve's call): join on ids, not names. UT Carbon County repeats option id `2` within two local contests (source fault, recorded in `docs/enhanced-voting.md`; step 3 should check for duplicate ids).

### Step 2: Clarity reader (built 2026-11-20, county level)

Steve chose county level now, precincts later. `pipeline/readers/clarity.py` (`parse_xml` for CO SC WV's statewide `reports/detailxml.zip`; `parse_json` for Iowa's `json/sum.json` + `json/ALL.json`, since Iowa has no XML), `pipeline/sources_clarity.toml`, CLI `python3 -m pipeline.run_clarity fetch|parse|fetch-parse SOURCE_ID`. A pass reads `current_ver.txt` first, then builds data URLs from that version. XML parses also write a per-county turnout CSV (registered voters, ballots cast) for step 3. All four 2026 files parse with 0 mismatches (CO 302 contests, SC 171, WV 126, IA 274). Details and quirks (Iowa gzips unasked; SC "Provionsal"; WV labels all votes "Election Day"; no vote types for Iowa) in `docs/clarity.md`. Not done: precinct results from the 264 county sites; county FIPS mapping. Next: the other step-2 platforms (ResultsAjax MT NE NM OR SD; Tally AR ND; custom sites), or step 3.

## Next tasks, in order

1. ~~Diagnose the MA TLS error~~ — done 2026-11-20 (see above).
2. ~~Verify the unverified and 403 rows~~ — done 2026-11-20 (see "Source verification pass"). Original wording: Verify the 29 unverified rows and the 10 403 rows by actually looking at the pages. Find live election-night sources for ME, KS, RI and CT.
3. Only after that, start step 2 with the Clarity reader, tested against real 2026 data.

## Queued components (not part of the six-step pipeline)

Order (Steve, 2026-11-20, revised the same day): source verification → scenario model (done) → **finish all six pipeline steps** (step 2 readers: Enhanced Voting first, then Clarity) → league tracker → NPVIC. Neither may touch `sources/` or `tools/`; flag either if it starts growing.

- `scenarios/` — **built 2026-11-20** (design `docs/superpowers/specs/2026-11-20-scenario-model-design.md`, plan `docs/superpowers/plans/2026-11-20-scenario-model.md`). Starts from official FEC 2024 state totals + ME/NE district totals from the Certificates of Ascertainment (Steve chose state totals over county data; the swings are linear, so results are identical except for clipping). Run `/opt/homebrew/bin/python3 -m scenarios.run`; tests `/opt/homebrew/bin/python3 -m unittest discover -s scenarios/tests -t .` (28). Zero settings reproduce 312–226; flip point +1.726 (PA). Known limit: a third-party share drawn from R hits DC first (Trump ≈6.5% there), so large uniform draws stop the run by design (no clamping). Deferred minors listed in the build's final message. Original spec: `docs/queued/scenario-model-spec.md`.
- `league/` — 2028 fantasy league tracker. Spec: `docs/queued/league-tracker-spec.md`.
- NPVIC tracking (`config/npvic.yaml`, `tools/npvic_status.py`; election-night behavior later). Queued 2026-11-20 "behind current work"; placed after the league tracker until Steve says otherwise. Spec: `docs/queued/npvic-spec.md`.

## How I work

- Small, verifiable commits; flag it if scope grows.
- Deterministic, inspectable code; no LLM-based logic unless I ask for it.
- Never present an unverified URL or number as fact. Mark it unverified.
- When something misbehaves, gather diagnostic data before proposing a fix.
- Be direct; no preamble.
