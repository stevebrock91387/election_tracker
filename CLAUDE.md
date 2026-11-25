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

`pipeline/` package: `fetch.py` (120 s minimum interval per source, raw body + `data/raw/manifest.csv` row before parsing), `schema.py` (common long-format columns), `readers/enhanced_voting.py`, `sources.toml` (AZ GA UT WA VA RI ID), CLI `python3 -m pipeline.run_ev`. Tests: `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (278 with Clarity, ResultsAjax, Tally, NC, OH, TX, CT, FL and VT). All seven 2026 exports parse with 0 statewide-vs-county mismatches **when matched by option id**; an earlier claim of GA/WA source faults was a name-matching bug, corrected in `docs/enhanced-voting.md`. Ranked-choice contests are skipped and listed. Output carries `choice_id` and `contest_scope` (statewide/local; added at Steve's call): join on ids, not names. UT Carbon County repeats option id `2` within two local contests (source fault, recorded in `docs/enhanced-voting.md`; step 3 should check for duplicate ids).

### Step 2: Clarity reader (built 2026-11-20, county level)

Steve chose county level now, precincts later. `pipeline/readers/clarity.py` (`parse_xml` for CO SC WV's statewide `reports/detailxml.zip`; `parse_json` for Iowa's `json/sum.json` + `json/ALL.json`, since Iowa has no XML), `pipeline/sources_clarity.toml`, CLI `python3 -m pipeline.run_clarity fetch|parse|fetch-parse SOURCE_ID`. A pass reads `current_ver.txt` first, then builds data URLs from that version. XML parses also write a per-county turnout CSV (registered voters, ballots cast) for step 3. All four 2026 files parse with 0 mismatches (CO 302 contests, SC 171, WV 126, IA 274). Details and quirks (Iowa gzips unasked; SC "Provionsal"; WV labels all votes "Election Day"; no vote types for Iowa) in `docs/clarity.md`. Not done: precinct results from the 264 county sites; county FIPS mapping.

### Step 2: ResultsAjax reader (built 2026-11-21, county level)

MT NE NM OR SD share one results engine. Steve approved: federal and statewide page types only, county level, 10 s between requests within a pass. `pipeline/readers/resultsajax.py`, `pipeline/sources_resultsajax.toml`, CLI `python3 -m pipeline.run_resultsajax fetch|parse|fetch-parse SOURCE_ID`. A pass reads each results page for its race list (`BuildCounty(...)` calls), the state's media CSV (statewide totals; SD NE NM only), then one county JSON per race, and writes a pass record that parse reads. 2026: MT 3 races, NE 9 (incl. House 1–3), NM 21, OR 18, SD 13. NE and SD match their media CSVs exactly; NM differs by 3 votes in CD2 because Chaves County's Vasquez cell is published as `*` (kept empty, listed, not estimated). MT and OR have no statewide check (MT's is an Excel form-post export; OR's export unread). Details in `docs/resultsajax.md`. Parallel passes corrupted `fetch.py`'s last-fetch file on 2026-11-21 (repaired); `fetch.py` now locks `data/raw/.fetch.lock` and replaces the file atomically, so concurrent runs are safe (multi-process test in `test_fetch.py`). 

### Step 2: Tally reader (built 2026-11-23, county level)

AR and ND share one results API (Tally ENR). Steve approved: federal and statewide contest types, county level, vote types later. `pipeline/readers/tally.py`, `pipeline/sources_tally.toml`, CLI `python3 -m pipeline.run_tally fetch|parse|fetch-parse SOURCE_ID`. A pass fetches election info, the contest list and one results file per contest type (3–4 requests) and writes a pass record. Counties come keyed by **FIPS code** (first platform to do so). 2026: AR 16 contests / 75 counties, ND 12 / 53, both official, county sums equal statewide totals exactly. ND publishes write-ins as an ordinary choice (`9901`, 10 contests): kept, listed. Every file carries a `versionID`; the summary flags a pass whose files come from different moments. AR's vote types exist on the site but the endpoint wasn't found. Details in `docs/tally.md`.

### Step 2: North Carolina reader (built 2026-11-24, precinct level)

First custom-site reader (Steve chose NC, then OH, then TX after surveying the remaining states). Steve approved: the State Board's statewide precinct ZIP as the data, the results dashboard's statewide file as an independent check, contest type S only (statewide and district contests). `pipeline/readers/nc.py`, `pipeline/sources_nc.toml`, CLI `python3 -m pipeline.run_nc fetch|parse|fetch-parse SOURCE_ID`. Two requests per pass. Precinct rows carry four vote methods plus TOTAL; state rows come from the dashboard. **No choice ids in either file**: the check joins on (contest group id, choice name). 2026: 395 contests, 100 counties, 2,842 precincts, 439,030 rows. **The dashboard and the ZIP disagree** in 252 values (89 choices, 60 contests; TOTALs differ by at most 13 votes, e.g. Senate Cooper +8, Whatley −5); the ZIP member is dated 2026-11-13, so a stale ZIP is possible but unverified. Every difference is listed, neither file is preferred. US House 2 write-ins carry a NUL party (354 lines, listed). Whether the ZIP updates on election night is unverified. Details in `docs/nc.md`.

### Step 2: Ohio reader (built 2026-11-24, county level)

Steve approved: the live NIST 1500-100 XML feed now (approach A), certified precinct spreadsheets later as a separate reader; all 162 contests; district totals labelled level "state" like the other readers. `pipeline/readers/oh.py` (`parse_pass` returns rows, summary and a county turnout table), `pipeline/sources_oh.toml`, CLI `python3 -m pipeline.run_oh fetch|parse|fetch-parse SOURCE_ID`. One request per pass; `fetch` gained an optional `ext` (Ohio's URL ends in `download`). 2026: 3,700 rows, 162 contests, 88 counties; all 340 selections' county counts sum exactly to their state/district counts. The feed says `GeneratedDate` 2026-11-13 and the server rebuilds it per request; whether it moves on election night is unverified. Absentee `BallotsCast` exceeds total ballots in every county (meaning unknown; kept under its own name). Details in `docs/oh.md`.

### Step 2: Texas reader (built 2026-11-24, county level)

Steve approved: the Civix ENR statewide file plus its county file (the statewide file as a check), the 584 federal, statewide and district races, total and early votes. `pipeline/readers/tx.py` (rows, summary, county turnout table), `pipeline/sources_tx.toml`, CLI `python3 -m pipeline.run_tx fetch|parse|fetch-parse SOURCE_ID`. Two requests per pass; values are base64 JSON; counties carry FIPS. 2026: 36,970 rows, 584 races, 254 counties; statewide totals equal the county sums for all 917 choices (total and early). Party codes differ between the two files for 16 choices (LIB/L, G/GRE, I/IND; each kept as published, listed). County-level offices (2,591) aren't in these files. The county `VC` figure sums to exactly the US Senate total, so it may not be ballots cast. Last update Nov 4; whether it changes later is unverified. Details in `docs/tx.md`. The custom-site readers (NC, OH, TX) are done.

### Remaining state readers (from 2026-11-24, standing approval)

Steve: "Let's finish building the state readers. Assume I approve, merge, push from now on." Script access checked once per site 2026-11-24. Blocked for scripts (not pursued, per the Arizona rule): NY KS KY ME MI MO NV NH TN WI (403), OK (data API needs the app's built-in password login), MN (download page goes to a Radware CAPTCHA), CA, PA; FL's download files sit on a host whose GoDaddy TLS Root CA - R1 isn't in the Mozilla/Homebrew/macOS stores (verification not disabled); the HTML site verifies. Steve (2026-11-24): skip the blocked states for now, but find a solution later; Florida: option A (trust GoDaddy TLS Root CA - R1 for Florida's file host only, fingerprint checked against GoDaddy's published copy). Reachable: AL AK CT DE DC HI IL IN LA MD MA MS NJ VT WY.

### Step 2: Connecticut reader (built 2026-11-24, town level)

CT EMS static JSON: `Version.json`, then seven files under that version (one snapshot per pass). `pipeline/readers/ct.py`, `pipeline/sources_ct.toml`, CLI `python3 -m pipeline.run_ct fetch|parse|fetch-parse SOURCE_ID`. Scope: office types SW C S A PD (251 offices; town offices out). Rows `level = "town"` (added to the schema doc; town id/name in the county columns). Each party line is its own row (cross-endorsements: Lamont D and WF). 2026 (v56593): 6,886 rows, 169 towns; town sums equal state values everywhere. Listed: 5 lines with unknown party ids, 3 probate fusion candidates without a grouping entry, 50 offices with no per-office reporting status. Candidate home addresses are in the lookup file and never copied. Details in `docs/ct.md`.

### Step 2: Florida reader (built 2026-11-25, county level)

Division of Elections pipe-delimited files (info + votes) plus the tab file for party. `pipeline/readers/fl.py`, `pipeline/sources_fl.toml`, CLI `python3 -m pipeline.run_fl fetch|parse|fetch-parse SOURCE_ID`. The file host chains to GoDaddy TLS Root CA - R1 (not in the default stores); per Steve's option A, implemented narrowly: `fetch` takes an optional `cafile` (default store plus that file, partial-chain trust off) and Florida passes GoDaddy's published R1-cross-signed-by-G2 certificate (`pipeline/certs/`), so the chain ends at Go Daddy Root G2. 2026: 3,063 county rows, 176 races, 67 counties (ids are FIPS), pipe and tab agree everywhere; every record has status I; 91 report 0 precincts. Choice ids 10/20 repeat across retention and amendment races: key on (contest, choice). No statewide rows. Details in `docs/fl.md`.

### Step 2: Vermont reader (built 2026-11-24, town level)

SOS static JSON: the election file names one timestamped snapshot; a pass reads federal, statewide, state senate, state house and turnout files. `pipeline/readers/vt.py`, `pipeline/sources_vt.toml`, CLI `python3 -m pipeline.run_vt fetch|parse|fetch-parse SOURCE_ID`. Rows per town part (24 towns are split by legislative districts; the part is in `precinct_id`), totals at level "state"; blank and over votes are rows. 2026: 20,468 rows, 132 offices, 247 towns; every check clean. Write-in names (many private individuals) are replaced in the committed fixture. Details in `docs/vt.md`.

## Next tasks, in order

1. ~~Diagnose the MA TLS error~~ — done 2026-11-20 (see above).
2. ~~Verify the unverified and 403 rows~~ — done 2026-11-20 (see "Source verification pass"). Original wording: Verify the 29 unverified rows and the 10 403 rows by actually looking at the pages. Find live election-night sources for ME, KS, RI and CT.
3. ~~Start step 2 with the Clarity reader, tested against real 2026 data~~ — done 2026-11-20 after the Enhanced Voting reader (see the two step-2 sections above).

## Queued components (not part of the six-step pipeline)

Order (Steve, 2026-11-20, revised the same day): source verification → scenario model (done) → **finish all six pipeline steps** (step 2 readers: Enhanced Voting and Clarity done 2026-11-20, ResultsAjax 2026-11-21, Tally 2026-11-23, NC, OH and TX 2026-11-24) → league tracker → NPVIC. Neither may touch `sources/` or `tools/`; flag either if it starts growing.

- `scenarios/` — **built 2026-11-20** (design `docs/superpowers/specs/2026-11-20-scenario-model-design.md`, plan `docs/superpowers/plans/2026-11-20-scenario-model.md`). Starts from official FEC 2024 state totals + ME/NE district totals from the Certificates of Ascertainment (Steve chose state totals over county data; the swings are linear, so results are identical except for clipping). Run `/opt/homebrew/bin/python3 -m scenarios.run`; tests `/opt/homebrew/bin/python3 -m unittest discover -s scenarios/tests -t .` (28). Zero settings reproduce 312–226; flip point +1.726 (PA). Known limit: a third-party share drawn from R hits DC first (Trump ≈6.5% there), so large uniform draws stop the run by design (no clamping). Deferred minors listed in the build's final message. Original spec: `docs/queued/scenario-model-spec.md`.
- `league/` — 2028 fantasy league tracker. Spec: `docs/queued/league-tracker-spec.md`.
- NPVIC tracking (`config/npvic.yaml`, `tools/npvic_status.py`; election-night behavior later). Queued 2026-11-20 "behind current work"; placed after the league tracker until Steve says otherwise. Spec: `docs/queued/npvic-spec.md`.

## How I work

- Small, verifiable commits; flag it if scope grows.
- Deterministic, inspectable code; no LLM-based logic unless I ask for it.
- Never present an unverified URL or number as fact. Mark it unverified.
- When something misbehaves, gather diagnostic data before proposing a fix.
- Be direct; no preamble.
