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

`pipeline/` package: `fetch.py` (120 s minimum interval per source, raw body + `data/raw/manifest.csv` row before parsing), `schema.py` (common long-format columns), `readers/enhanced_voting.py`, `sources.toml` (AZ GA UT WA VA RI ID), CLI `python3 -m pipeline.run_ev`. Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .` (909 with Clarity incl. NJ counties, the step 3 database, step 4 expected vote, ResultsAjax, Tally, NC, OH, TX, CT, FL, VT, IN, LA, DC, DE, AK, AL, MD, HI, WY, MA, MN, LiveVoterTurnout and the PDF reports; run with `.venv/bin/python` since AL needs xlrd and the PDF reader pypdfium2, see `docs/al.md`; the bare interpreter `/opt/homebrew/bin/python3` skips 45 tests: 36 AL, 9 PDF). All seven 2026 exports parse with 0 statewide-vs-county mismatches **when matched by option id**; an earlier claim of GA/WA source faults was a name-matching bug, corrected in `docs/enhanced-voting.md`. Ranked-choice contests are skipped and listed. Output carries `choice_id` and `contest_scope` (statewide/local; added at Steve's call): join on ids, not names. UT Carbon County repeats option id `2` within two local contests (source fault, recorded in `docs/enhanced-voting.md`; step 3 should check for duplicate ids).

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

Steve: "Let's finish building the state readers. Assume I approve, merge, push from now on." Script access checked once per site 2026-11-24. Blocked for scripts (not pursued, per the Arizona rule): NY KS KY ME MI MO NV NH TN WI (403), OK (data API needs the app's built-in password login), MN (download page goes to a Radware CAPTCHA; the file host itself answers, reader built 2026-11-26 with Steve's OK), CA, PA; FL's download files sit on a host whose GoDaddy TLS Root CA - R1 isn't in the Mozilla/Homebrew/macOS stores (verification not disabled); the HTML site verifies. Steve (2026-11-24): skip the blocked states for now, but find a solution later (research 2026-11-25 in `docs/blocked-states.md`: MN has a 2026 county file on a separate host, CA a media feed on request, PA KS ME NV NY post-certification files; none verified with the project fetcher yet); Florida: option A (trust GoDaddy TLS Root CA - R1 for Florida's file host only, fingerprint checked against GoDaddy's published copy). Reachable: AL AK CT DE DC HI IL IN LA MD MA MS NJ VT WY.

### Step 2: Connecticut reader (built 2026-11-24, town level)

CT EMS static JSON: `Version.json`, then seven files under that version (one snapshot per pass). `pipeline/readers/ct.py`, `pipeline/sources_ct.toml`, CLI `python3 -m pipeline.run_ct fetch|parse|fetch-parse SOURCE_ID`. Scope: office types SW C S A PD (251 offices; town offices out). Rows `level = "town"` (added to the schema doc; town id/name in the county columns). Each party line is its own row (cross-endorsements: Lamont D and WF). 2026 (v56593): 6,886 rows, 169 towns; town sums equal state values everywhere. Listed: 5 lines with unknown party ids, 3 probate fusion candidates without a grouping entry, 50 offices with no per-office reporting status. Candidate home addresses are in the lookup file and never copied. Details in `docs/ct.md`.

### Step 2: Florida reader (built 2026-11-25, county level)

Division of Elections pipe-delimited files (info + votes) plus the tab file for party. `pipeline/readers/fl.py`, `pipeline/sources_fl.toml`, CLI `python3 -m pipeline.run_fl fetch|parse|fetch-parse SOURCE_ID`. The file host chains to GoDaddy TLS Root CA - R1 (not in the default stores); per Steve's option A, implemented narrowly: `fetch` takes an optional `cafile` (default store plus that file, partial-chain trust off) and Florida passes GoDaddy's published R1-cross-signed-by-G2 certificate (`pipeline/certs/`), so the chain ends at Go Daddy Root G2. 2026: 3,063 county rows, 176 races, 67 counties (ids are FIPS), pipe and tab agree everywhere; every record has status I; 91 report 0 precincts. Choice ids 10/20 repeat across retention and amendment races: key on (contest, choice). No statewide rows. Details in `docs/fl.md`.

### Step 2: Vermont reader (built 2026-11-24, town level)

SOS static JSON: the election file names one timestamped snapshot; a pass reads federal, statewide, state senate, state house and turnout files. `pipeline/readers/vt.py`, `pipeline/sources_vt.toml`, CLI `python3 -m pipeline.run_vt fetch|parse|fetch-parse SOURCE_ID`. Rows per town part (24 towns are split by legislative districts; the part is in `precinct_id`), totals at level "state"; blank and over votes are rows. 2026: 20,468 rows, 132 offices, 247 towns; every check clean. Write-in names (many private individuals) are replaced in the committed fixture. Details in `docs/vt.md`.

### Step 2: Indiana reader (built 2026-11-24, precinct level)

Indiana ENR: `settings.json` (version letter A/B), six category JSON files (state and county totals with office, candidate and FIPS ids), county turnout, and the 35 MB precinct CSV of every office (no ids; joined on office/county/name, case-insensitive). `pipeline/readers/in_.py` (`in` is a keyword), `pipeline/sources_in.toml`, CLI `python3 -m pipeline.run_in fetch|parse|fetch-parse SOURCE_ID`. Categories: US House, Secretary of State, Comptroller, Treasurer, state senate and house (2028: add US Senator and Governor ids; uncovered Federal/State categories are listed). 2026: 82,906 rows (80,844 precinct), every check clean. No reporting flag: zero-vote precincts are ambiguous for step 4. Details in `docs/in.md`.

### Step 2: Louisiana reader (built 2026-11-24, parish level)

SOS live-results JSON blobs: multi-parish races and totals, then per race a parish file and an early-vote file (44 requests, ~7⅓ min). `pipeline/readers/la.py`, `pipeline/sources_la.toml` (holds the 64 parish names, copied from the site's JavaScript), CLI `python3 -m pipeline.run_la fetch|parse|fetch-parse SOURCE_ID`. Scope: 21 federal, statewide, legislative and amendment races. 2026: 4,163 rows, 64 parishes, every check clean; House 5 and 6 go to the 12/12 runoff (a separate date: add a config entry). Amendment choice ids 3/4 repeat across races. Details in `docs/la.md`.

### Step 2: DC reader (built 2026-11-24, precinct level)

DCBOE: the info JSON names the precinct CSV (`CsvLink`), checked against the citywide JSON. `pipeline/readers/dc.py`, `pipeline/sources_dc.toml`, CLI `python3 -m pipeline.run_dc fetch|parse|fetch-parse SOURCE_ID`. Scope: every contest except ANCs (DC matters for 2028 through its 3 electoral votes). 2026: 6,978 rows, 144 precincts in 8 wards, every check clean; RCV contests are first-rank counts; over/under votes have no choice id. Details in `docs/dc.md`.

### Step 2: Delaware reader (built 2026-11-24, election-district level)

Department of Elections ENR JSON: statewide (ids, vote types), 530 election districts, counties (with Wilmington), turnout. `pipeline/readers/de.py`, `pipeline/sources_de.toml`, CLI `python3 -m pipeline.run_de fetch|parse|fetch-parse SOURCE_ID`. County offices out. 2026: 29,261 rows, 57 contests, every check clean; machine/absentee/early vote types. Details in `docs/de.md`.

### Step 2: Alaska reader (built 2026-11-24, precinct level, first choice)

Division of Elections precinct CSV (one request): ids, five vote types, registered voters, under/over votes. `pipeline/readers/ak.py`, `pipeline/sources_ak.toml`, CLI `python3 -m pipeline.run_ak fetch|parse|fetch-parse SOURCE_ID`. **First-choice (round 1) counts only**; ranked-choice rounds are separate. No state rows (statewide only as PDF). 2026: 120,276 rows, 523 units (402 precincts + district counting units); checks clean except 12 counting units whose ballots differ by contest (listed); a ballots-minus-votes gap (likely write-ins, unverified) is reported per contest. Details in `docs/ak.md`.

### Step 2: Alabama reader (built 2026-11-24, precinct level, certified)

Steve: "Allow xlrd" (2026-11-24). First dependency: `requirements.txt` pins xlrd 2.0.2 by hash, installed in a gitignored `.venv` (setup in `docs/al.md`); every other reader stays stdlib-only. Source: the SOS certified precinct ZIP (67 county `.xls`, one request); the election-night page is empty between elections. `pipeline/readers/al.py`, `pipeline/sources_al.toml`, CLI `.venv/bin/python -m pipeline.run_al fetch|parse|fetch-parse SOURCE_ID`. Scope: 172 state-level contests (statewide offices and courts, US Senate and House, State Board of Education, legislature, statewide amendments, straight party); 529 county and local names counted. No ids or totals in the files. 2026: 233,594 rows, 2,071 units (138 absentee/provisional). Listed: 31 counties publish 0 registered voters everywhere; **352 precinct columns carry two or more districts of one office, 268 with votes in more than one (25 for US House), so House work must split those units**; 2,276 contest blocks don't sum to ballots cast (1,432 absentee/provisional, 771 split-district blocks, 73 others in eight counties, unexplained). No President in the scope list yet (2028: add it). `sources/registry.csv` still describes AL's election-night page as of 2026-11-20. Details in `docs/al.md`.

### Step 2: Maryland reader (built 2026-11-24, county level, live)

Steve (2026-11-24): build the HTML reader, "I want the results as they come in, not when they're done." Stdlib `html.parser`. A pass: 24 county pages (the data: every contest, four vote types, precincts reported per county) then 9 office pages and 3 statewide question pages (the check), 5 s apart, about 3 minutes. `pipeline/readers/md.py`, `pipeline/sources_md.toml`, CLI `python3 -m pipeline.run_md fetch|parse|fetch-parse SOURCE_ID`. No ids: joins on names; contest ids carry the office and its nested headings; circuit judges get the county appended on county pages. 2026 (final pages, "Last refreshed 11/23/2026 07:40:42 PM"): 8,470 rows, 145 contests, all cross-checked clean. Rows carry the page hash and its "Last refreshed" time. A failed page stops the whole pass, like the other readers (Steve, 2026-11-24). Live behaviour (NR cells, partial reporting) tested only synthetically. Details in `docs/md.md`.

### Step 2: Hawaii reader (built 2026-11-24, precinct level, certified)

Steve: "Go for it" (2026-11-24) on surveying HI WY MS MA IL NJ. Survey: HI, WY, MA workable; NJ: 15 of 21 counties on Clarity (county Clarity XML has `<Precinct>`, not `<County>`: the Clarity reader needs extending; Clarity 403s curl's default client but serves the project fetcher); MS results page still empty; IL has only the March primary posted. Hawaii: Office of Elections "Certified Text Files" (`summary.txt` statewide, `media.txt` precinct; tab-separated, two requests). `pipeline/readers/hi.py`, `pipeline/sources_hi.toml`, CLI `python3 -m pipeline.run_hi fetch|parse|fetch-parse SOURCE_ID`. Every precinct is two units keyed by splitId: plain (registered voters, mail votes) and `VSC` (in-person votes); add them for a precinct's total. Party comes from a name prefix `(D)`. All 92 contests. 2026: 78,732 rows, 496 units, every check clean (precinct sums equal the summary for all 202 lines). No county anywhere. Election-night use of these files unverified. Details in `docs/hi.md`.

### Step 2: Wyoming reader (built 2026-11-24, precinct level, certified)

SOS official results ZIP (one request): three `.xlsx` workbooks read with the stdlib (precinct results per county, ballots cast per precinct, statewide summaries by county). `pipeline/readers/wy.py`, `pipeline/sources_wy.toml`, CLI `python3 -m pipeline.run_wy fetch|parse|fetch-parse SOURCE_ID`. Precinct rows from the precinct workbook, county and state rows from the summaries; checks: Total rows, county (summaries vs precinct Totals), ballots cast, per-precinct ballot balance (informational). 2026: 31,832 rows, 23 counties, 432 precincts, 108 contests. Listed: Teton HD 22 winner spelled "Andrew Byron" vs "Andrew P Byron"; 93 ballot-balance differences (58 split precincts, 11 partial-Senate, 24 unexplained, mostly Natrona ±1–2); Carbon/Converse/Crook precinct names stored as Excel dates and rendered through their own format (`mm-dd`, equals the TBC names). No live feed. Fixture is the real ZIP. Details in `docs/wy.md`.

### Step 2: Massachusetts reader (built 2026-11-25, precinct level, certified)

PD43+ archive (`electionstats.state.ma.us`, TLS 1.3): a pass reads the 2026 general contest list and the question list, then one precinct CSV per in-scope contest and statewide question (234 requests, 5 s apart, ~20 min). `pipeline/readers/ma.py`, `pipeline/sources_ma.toml`, CLI `python3 -m pipeline.run_ma fetch|parse|fetch-parse SOURCE_ID`. Scope: federal, statewide, Governor's Council, legislature (223 contests) + Questions 1–9; config `stages = ["General Election"]` because the General search also returns special elections (2 in 2026, held under the same seat names; an early run merged them, caught in review). Precinct rows (town in county columns, `precinct_id` `<Ward>/<Pct>`) and state rows from each CSV's TOTALS; the list page's totals are an independent check. 2026: 163,020 rows, 2,393 precincts, every check clean except 11th Plymouth All Others (CSV 0, absent from the list); 16 party-label differences (CSV registration "Unenrolled" vs list ballot label "Independent" etc.). Details in `docs/ma.md`.

### Step 2: New Jersey Clarity counties (built 2026-11-25, precinct level, live)

No statewide feed; 15 of 21 counties publish on Clarity. `parse_county_xml` in `pipeline/readers/clarity.py` reads one county's `detail.xml` (units are `<Precinct>`); config `format = "county_xml"` in `pipeline/sources_clarity.toml`, CLI as for Clarity. **8 counties publish detail XML** (Atlantic, Burlington, Cape May, Essex, Hudson, Mercer, Ocean, Union): read, every internal check clean. **7 publish JSON only** (Cumberland, Gloucester, Middlesex, Monmouth, Morris, Passaic, Somerset): `parse_county_json`, `format = "county_json"` (built 2026-11-25; a pass reads sum.json, ALL.json, vt.json, status.json and one precinct file per vote type, 5–11 requests, and writes a pass record that `parse` takes). 2026: 0 mismatches in all seven; Middlesex (897 cells) and Morris (8,982) publish `"protected"` instead of some counts (privacy filter: votes empty, listed, sums not checked, not estimated); Gloucester, Monmouth, Passaic and Somerset publish no vote types; Cumberland lists write-in names (fixtures redact them). 6 aren't Clarity (Bergen, Camden, Hunterdon, Salem, Sussex, Warren; Bergen and Salem read since 2026-11-27, see the LiveVoterTurnout section). Contest names, keys and vote-type names are each county's own (`contest_scope` "local"; join on county + contest_id + choice_id + choice); no statewide aggregation or state check yet (no certified state results). Contest-level Overvotes/Undervotes (Burlington, Essex, Mercer) are rows; `regVotersCounty` (always 0) isn't. Burlington lists every write-in name as a choice: 1.29M rows per pass. Steve chose both fixes (2026-11-25): county_xml rows stream to the CSV (peak memory 2.1 → 1.0 GB, same output), and `fetch-parse` skips a pass whose Clarity version it already parsed (`--force` overrides). Details in `docs/nj.md`.

### Step 2: LiveVoterTurnout reader (built 2026-11-27, county level, NJ Bergen and Salem)

Two of NJ's six non-Clarity counties publish on LiveVoterTurnout ENR; the other four (Camden, Hunterdon, Sussex, Warren) post PDFs only (Camden and Sussex read since 2026-11-27: see the PDF section). A pass reads the county's `summary_<election id>.xml` (one request), the file the results page's script reads. `pipeline/readers/lvt.py`, `pipeline/sources_lvt.toml`, CLI `python3 -m pipeline.run_lvt fetch|parse|fetch-parse SOURCE_ID`. Rows per choice and vote type (element names differ by county) plus TOTAL, over/under votes as choices, all contests, `contest_scope` "local". Salem lists every written-in name after its `Write-In` line (a breakdown: equal to it in all 36 races, no flag but position): not rows (double count, private names), counted and checked. 2026: Bergen 3,909 rows / 192 contests, Salem 720 / 36; vote types sum to totals everywhere; ballot balance off by 1 in 6 races (listed). Salem's district results are only in the page HTML (not read); Bergen's district PDF is read by the PDF reader (2026-11-27). Election-night behaviour unverified. Details in `docs/lvt.md`.

### Step 2: PDF results reports (built 2026-11-27, precinct level, NJ Camden, Sussex and Bergen)

Steve: "Add one now" (2026-11-27), a PDF dependency. Second dependency: **pypdfium2 5.15.2** (PDFium; no Python dependencies) pinned by hash in `requirements.txt` (macOS arm64 wheel only), chosen over pypdf (glues abutting numbers together) and pdfminer.six (four extra packages). `pipeline/readers/pdfreport.py`, `pipeline/run_pdfreport.py`, `pipeline/sources_pdfreport.toml`, CLI `.venv/bin/python -m pipeline.run_pdfreport fetch|parse|fetch-parse SOURCE_ID`. Two layouts: Camden (one PDF: summary with four vote types plus a rotated precinct table, one contest per page; 13 pages print two questions side by side and are split by character position) and Sussex (countywide summary plus a precinct report; vote types only where printed). No ids: contest and choice names, `contest_scope` "local". Placeholders ("No Nomination Made") are dropped and checked for 0; per-precinct registered voters and ballots go to `-turnout.csv` (layout `pdfreport`). 2026: Camden 16,601 rows, 92 contests, 387 units; Sussex 3,351 rows, 71 contests, 119 precincts. Every precinct sum equals the county total (Camden also its tables' Totals lines). Sussex withholds all counts for Walpack Twp (9 voters, 6 contests): empty, listed, not estimated. Not read: Warren (403 to scripts), Hunterdon (no 2026 general posted), write-in name sections, Camden's municipality tables. Election-night reports unseen. **Bergen** (`layout = "bergen"`, `pipeline/readers/sovtable.py`): the clerk's 735-page district report, rotated statement-of-votes tables with blank cells left out, read by character position; 108,290 rows, 192 contests, 637 districts, vote types; every district/municipality/county sum clean, all 526 county totals equal the LVT file. Total Votes includes write-ins printed in no column (the remainder equals LVT's Personal Choice in all 192 contests: listed, not rows). No vote_for in the PDF, so step 3 flags 274 multi-seat contests (all fine with LVT's vote_for). Details in `docs/pdfreport.md`.

### Step 2: Minnesota reader (built 2026-11-26, county level)

SOS `allracesbycounty.txt` on `electionresultsfiles.sos.mn.gov` (one request; its listing page is behind a Radware bot check, so Steve approved reading the file host directly). `pipeline/readers/mn.py`, `pipeline/sources_mn.toml` (office-id ranges: federal, statewide, legislature, appellate courts), CLI `python3 -m pipeline.run_mn fetch|parse|fetch-parse SOURCE_ID`. No header; **field meanings inferred from the data, unverified** (the spec is behind the bot check). 2026: 4,952 rows, 87 counties (ids 01–87, not FIPS, no names), 222 contests; every county office sums to its office total. No state rows, no vote types. Details in `docs/mn.md`.

### Step 3: results database and checks (built 2026-11-25)

Steve chose step 3 next, then option C (SQLite, checks as queries) and retention A (latest two snapshots per source). `pipeline/db.py` (schema, loader, CLI `python3 -m pipeline.db load|check`), `pipeline/db_checks.py`, `pipeline/turnout_map.toml` (14 turnout layouts). Database `data/results.sqlite`, reports `data/reports/<UTC>/`; report only. Checks: never decrease (latest two snapshots), not over registered voters (per turnout unit; TOTAL or else the sum of vote types; HI VSC and VT town parts added), parts add up (precinct → county → state; party not in the key). 2026 run: 48 snapshots from 47 sources (AZ, UT not loaded: not in the manifest; EV and MD re-parsed first); 0 decreases (only NC has two snapshots; MA's pre-fix parse, which also downloaded two special elections, moved to `data/parsed-superseded/`, Steve 2026-11-26); 2,367 registered-voter exceptions, mostly 0-registered units and blank vote_for (HI's 39: 23 multi-seat Trustee false alarms, 16 Councilmember unverified); 1,267 parts exceptions, all EV precinct → county (WA 1,169 incl. 286 King County lines whose precincts sum to 0; GA 43, ID 55 at most 4 votes; causes unknown). Snapshots (Steve, 2026-11-26, options A then B): a snapshot is the download a parse read, so a source reverting to earlier content is a new snapshot check 1 compares; a download identical to the previous one joins it (newest parse wins). Details in `docs/db.md`.

### Step 4: expected vote (built 2026-11-27, branch `step4-expected-vote`, not merged)

Design `docs/superpowers/specs/2026-11-27-step4-expected-vote-design.md`, plan `docs/superpowers/plans/2026-11-27-step4-expected-vote.md`, results `docs/expected.md`. `pipeline/expected/` (stdlib only), CLI `python3 -m pipeline.expected.run fetch | check YEAR | baseline YEAR | registration | compute TARGET | score TARGET | all TARGET`, outputs in `data/expected/`. Each county's expected top-race vote from the last two comparable elections (2018 and 2022 for a midterm), MEDSL precincts summed to counties, each (state, office) checked against the FEC's federal-elections workbook. Steve's choices: option A (comparable years), B (MEDSL + FEC check), C (exact check, differences fixed in `pipeline/expected/medsl_fixes.toml`), then (2026-11-27) **pass on named candidates**: write-in-only differences are recorded, not failed. MEDSL 2018 is the deprecated GitHub copy (Dataverse needs a guestbook; Steve chose GitHub). Check: 2018 56/85, 2022 41/85 pass; 6 fixes (NJ 2022 total rows, VT 2022 and MI 2018 mis-flagged write-ins, OR 2018 Tillamook duplicate incl. Governor); 48 offices off by at most 1% stay failed (cause unverified); the C/D causes are tabled in the doc (missing counties or contests, DC shadow races, ID Power County). Governor isn't FEC-checked (scan: no eligible county above 1.28× its federal votes). No 2018/2022 registration in the project, so every county is "raw" or "one year". 2026 dry run: 1,133 counties scored in 18 states, 17.8% inside the range (raw 30.6%, one year 0%), median miss 4.9%, median |actual − point| 7.1%. Ask Steve before merging or pushing (outside the reader standing approval).

## Next tasks, in order

1. ~~Diagnose the MA TLS error~~ — done 2026-11-20 (see above).
2. ~~Verify the unverified and 403 rows~~ — done 2026-11-20 (see "Source verification pass"). Original wording: Verify the 29 unverified rows and the 10 403 rows by actually looking at the pages. Find live election-night sources for ME, KS, RI and CT.
3. ~~Start step 2 with the Clarity reader, tested against real 2026 data~~ — done 2026-11-20 after the Enhanced Voting reader (see the two step-2 sections above).

## Queued components (not part of the six-step pipeline)

Order (Steve, 2026-11-20, revised the same day): source verification → scenario model (done) → **finish all six pipeline steps** (step 2 readers: Enhanced Voting and Clarity done 2026-11-20, ResultsAjax 2026-11-21, Tally 2026-11-23, NC, OH, TX, CT, FL, VT, IN, LA, DC, DE, AK, AL and MD 2026-11-24) → league tracker → NPVIC. Neither may touch `sources/` or `tools/`; flag either if it starts growing.

- `scenarios/` — **built 2026-11-20** (design `docs/superpowers/specs/2026-11-20-scenario-model-design.md`, plan `docs/superpowers/plans/2026-11-20-scenario-model.md`). Starts from official FEC 2024 state totals + ME/NE district totals from the Certificates of Ascertainment (Steve chose state totals over county data; the swings are linear, so results are identical except for clipping). Run `/opt/homebrew/bin/python3 -m scenarios.run`; tests `/opt/homebrew/bin/python3 -m unittest discover -s scenarios/tests -t .` (28). Zero settings reproduce 312–226; flip point +1.726 (PA). Known limit: a third-party share drawn from R hits DC first (Trump ≈6.5% there), so large uniform draws stop the run by design (no clamping). Deferred minors listed in the build's final message. Original spec: `docs/queued/scenario-model-spec.md`.
- `league/` — 2028 fantasy league tracker. Spec: `docs/queued/league-tracker-spec.md`.
- NPVIC tracking (`config/npvic.yaml`, `tools/npvic_status.py`; election-night behavior later). Queued 2026-11-20 "behind current work"; placed after the league tracker until Steve says otherwise. Spec: `docs/queued/npvic-spec.md`.

## How I work

- Small, verifiable commits; flag it if scope grows.
- Deterministic, inspectable code; no LLM-based logic unless I ask for it.
- Never present an unverified URL or number as fact. Mark it unverified.
- When something misbehaves, gather diagnostic data before proposing a fix.
- Be direct; no preamble.
