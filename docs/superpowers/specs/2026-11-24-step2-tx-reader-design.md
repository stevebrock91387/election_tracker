# Step 2: Texas reader (Civix ENR, county level)

Status: **ready for Steve's approval** (builder check done 2026-11-24; nothing it raised needed a new decision). Approach chosen by Steve 2026-11-24 ("Recommendations"): both files (county data plus the statewide file as a check), all 584 federal, statewide and district races, totals and early votes.

## Why

Texas has a 2028 Senate race (Class 3) and 38 House seats. The Secretary of State's election-night site (Civix IVIS ENR) serves two JSON files that a script can download and that together give every federal, statewide and district race, statewide and by county. County-level offices are not in these files (see Scope).

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

- **Site:** `https://goelect.txelections.civixapps.com/ivis-enr-ui/races` (Angular app behind Cloudflare). Election ids come from `…/api-ivis-system/api/s3/enr/electionConstants`; the 2026 general is `53815` ("2026 NOVEMBER GENERAL ELECTION"). All three URLs answered 200 to curl with our User-Agent `election-tracker-fetch/0.1`, and `electionConstants` and one election file answered 200 to Python's `urllib` with the same User-Agent (the stack `pipeline/fetch.py` uses); responses are `Cache-Control: no-cache, no-store`.
- **Encoding:** responses are JSON objects whose values are **base64-encoded JSON** (UTF-8).
- **Statewide file** `…/api-ivis-system/api/s3/enr/election/53815` (1,648,956 bytes, SHA-256 `2c6da20b1f4f…`). Keys: `Version` (plain string `"enr/53815/117/"`), and base64 values `Home`, `Federal`, `StateWide`, `StateWideQ`, `Districted`, `Lookups`, `OfficeSummary`, `Race`, `ReportList`, `ElementControl`.
  - `Home`: `ElecDate` "11032026", `LastUpdatedTime` "Nov 04, 2026 22:48:37" (the page shows "Nov 4 2026, 4:48:37 pm CST"), `CountiesReporting` {CR 254, CT 254}, `PrecinctsReporting` {PR 202, PT 200} (more reported than total; meaning unknown), `PollingReporting` {PLR 5303, PLT 5303}.
  - `Federal` (39 races: US Senator, US Representative 1–38), `StateWide` (14), `StateWideQ` (0 in 2026; statewide propositions), `Districted` (531: state senate and house, State Board of Education, appellate and district courts, district attorneys, multicounty courts at law). Each has `OffType` ("FEDERAL OFFICES" etc.), `OffTypeID`, and `Races`: `id`, `N` (name), `T` (total), `Candidates`: `ID`, `N`, `P` (party), `V` (votes), `EV` (early votes), `PE` (percent), `C` (colour), `O` (order), `LN`, `FN`.
  - `Race` (an index) lists five office types: DISTRICT OFFICES 531, FEDERAL OFFICES 39, STATEWIDE OFFICES 14, COUNTY WIDE 1,326, COUNTY RACE 1,265. The 2,591 county-level races appear only in this index: neither data file carries their results.
  - `Lookups.County`: 254 × {`ID` (1–254), `CN` (name), `MID` (FIPS, e.g. 48001 Anderson)}.
- **County file** `…/api-ivis-system/api/s3/enr/election/countyInfo/53815` (4,349,849 bytes, SHA-256 `e6e5e7e006b1…`). One key `upload`, base64 of {county ID: {`N`, `TV`, `C`, `Summary`, `Races`: {office id: {`OID`, `N`, `T`, `OT` (`FD`/`SW`/`SR`), `C`: {candidate id: the same fields as statewide candidates, except the id key is lowercase `id`}, `PR`, `TP`, `TPR`, `OTRV`, `TV`, `O`, `SO`, `OR`}}}}.
  - `Summary` per county: `RV` (registered 31,222 for Anderson), `VC` (voters 15,290), `VT` (turnout %), `PRR` and `PRP` (both 23.0 for Anderson; equal in all 254 counties; meaning of `PRP` unknown), `P` (100.0 everywhere, apparently precincts-reporting %), `NPL`/`PLR`/`PLP` (polling locations total / reporting / %). Numbers are JSON floats (31222.0).
  - County `Summary` sums don't match `Home`: polling locations `NPL` and `PLR` each sum to 5,301 vs `Home` 5,303/5,303; `PRR` sums to 9,867 vs `Home` precincts 202/200.
  - Race `PR`/`TP`: precincts reporting / total for that race in that county (Anderson 23/23, as the page shows).
- **The two files agree exactly:** all 584 statewide races appear in the county file, and for all 917 candidates the county sums of `V` and of `EV` equal the statewide values. No county race is missing from the statewide file.
- **US Senate (unofficial, Nov 4 snapshot):** Talarico (DEM) 5,444,982; Paxton (REP) 4,249,373; Brown (LIB) 190,237; four write-ins. Total 9,889,704.
- **Parties as published:** REP 476, DEM 397, W (write-in) 17, LIB 11, GRE 7, L 3, G 3, I 2, IND 1 — the same party appears under two codes.
- **Propositions** (none in 2026: `StateWideQ` decodes to OffType null, no races). Seen in election 51031 ("2025 NOVEMBER 4TH CONSTITUTIONAL AMENDMENT", one download 2026-11-24): OffType "STATEWIDE PROPOSITIONS", 17 races such as `id` 87 "PROPOSITION 1 (SJR 59)"; choices `FOR` and `AGAINST` with **`ID` null** and `P` null, `V` and `EV` present. In that election the `Federal`, `StateWide` and `Districted` values decode to null. The county file for 51031 was not fetched.
- **No vote types beyond early votes**, no precincts, no `vote_for`, no election name in the statewide file (the name is in `electionConstants`).
- **Freshness:** last updated Nov 4. Whether the site reflects later canvass changes is unknown.

## Approaches considered

1. **Both files (chosen).** County rows from the county file, state rows from the statewide file, every difference listed (as the NC reader does). Two requests, 10 s apart, ~6 MB.
2. County file only: one request, but no independent statewide figure.

## Scope

The 584 races in the statewide file's four result sections (federal, statewide, statewide propositions, districted), county level plus statewide totals. County-level offices (2,591 in the `Race` index) are out: their results are not in these files and would need endpoints not yet found. Vote types: `TOTAL` (`V`) and `Early Votes` (`EV`), as published; no derived election-day figure.

## Design

- **Config** `pipeline/sources_tx.toml` `[tx-2026-general]`: `state = "TX"`, `election_url`, `county_url` (both with `53815` in the path), `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** `pipeline/run_tx.py fetch SOURCE_ID`: two requests through `pipeline/fetch.py` (source ids `<id>-election`, `<id>-county`, `ext="json"`), 10 s apart; any failure stops the pass; record kinds `election`, `county`. Same pattern as `run_nc`.
- **Reader** `pipeline/readers/tx.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`:
  - **State rows** (from the statewide file): `level = "state"`, one per (race, candidate, vote type), `reporting_status` empty. District races are level "state" too, as in the other readers.
  - **County rows** (from the county file): `level = "county"`, `county_id` = the county's FIPS (`MID` from `Lookups.County`, joined on the county key = `ID`), `county_name` = `N` as published, `reporting_status = "<PR>/<TP> precincts"`.
  - `contest_id` = office id (`id`/`OID`); `contest_name` = `N` as published (trailing spaces kept, e.g. "RAILROAD COMMISSIONER "); `contest_type` = the statewide file's `OffType` for that office, on county rows too (joined on office id); `vote_for` empty; `contest_scope = "statewide"`.
  - `choice_id` = candidate id (`ID` statewide, `id` in the county file), empty where the id is null (propositions); `choice` = `N`; `party` = `P` as published, empty when null (no merging of LIB/L, GRE/G). Candidates join across files on (office id, candidate id), or on (office id, choice name) when the id is null; null ids are counted in the summary.
  - `vote_type`: `TOTAL` from `V`, `Early Votes` from `EV`.
  - `source_sha256` per file; `source_created_at` = `Home.LastUpdatedTime` as published on state rows and empty on county rows (my call: the county file states no time, and it is fetched ~10 s after the statewide file, so stamping it with the statewide time would claim something unverified); `election_date` = `Home.ElecDate` as published ("11032026"); `election_name` empty.
  - **Turnout table** (third value, as in the OH reader): one row per county with FIPS, name, registered voters (`RV`), voters (`VC`), precincts reporting (`PRR`), polling locations reporting / total (`PLR`/`NPL`); float values that are whole numbers become integers, others kept as published. `PRP`, `P`, `VT` and `PLP` are left out (my call: `PRP`'s meaning is unknown, the others are percentages).
  - **Checks, listed, nothing corrected:**
    - per (race, candidate, vote type): statewide value ≠ sum of county values;
    - races or candidates in one file and not the other (both directions);
    - county keys not in `Lookups.County` (row kept, `county_id` empty);
    - early votes greater than total votes (state or county);
    - non-integer `V`/`EV` (row kept, votes empty, left out of sums);
    - duplicate (race, candidate) within a county or within the statewide file;
    - an office id appearing in two statewide sections;
    - `Home` reporting counts with reported > total (expected today: precincts 202/200);
    - county `Summary` sums that differ from `Home` (expected today: polling locations 5,301 vs 5,303; precincts 9,867 vs 202/200; counties reporting are compared with the number of counties in the county file);
    - a section whose value decodes to null is read as no races (as 2026's `StateWideQ` and 2025's other sections), not an anomaly;
    - a statewide-file value that isn't decodable base64 JSON, or a county file without `upload`: listed, and the checks that need it are `None`.
    - `Version` and the party codes with counts are printed, not anomalies.
- **CLI** `fetch | parse SOURCE_ID PASS_RECORD | fetch-parse`, writing `<stamp>.csv` and `<stamp>-turnout.csv` as `run_oh` does.
- **Tests** on fixtures cut from the real files: the US Senate and two US House districts, one statewide office, one districted race, across 3 counties including one with a write-in vote (statewide values kept real, so they differ from the 3-county sums: the mismatch list must name each). Synthetic variants for each listed anomaly, and a statewide fixture with a `StateWideQ` section built from the 2025 proposition sample (null ids) to cover propositions.

## Left to the builder

Fixture cutting, summary key names, test layout.

## Not done / later

- Precinct results (not on this site; the SOS publishes canvass reports after certification).
- Election-day / mail split (only total and early).
- Whether the site changes after election night.
- The meaning of `Home.PrecinctsReporting` 202/200, `Summary.PRP` and the county-level `TV` fields.
- County-level offices (endpoints not found).
- Election name from `electionConstants` (a third request; not needed for the data).
