# Step 2: Indiana reader (Indiana ENR, precinct level)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24).** Calls made without asking are marked "(my call)".

## Why

Indiana has a 2028 Senate race (Class 3) and 9 House seats. The state's election-night site (`https://enr.indianavoters.in.gov/site/index.html`) publishes a precinct-level file of every office plus JSON summaries with office and candidate ids, all reachable by script.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

All files under `https://enr.indianavoters.in.gov/site/`; all answered 200 to Python `urllib` with our User-Agent (the site is behind Cloudflare).

- **`data/settings.json`** (3,578 B): `VersionCode` "20261119_100058", `VersionType` "B" (the app reads data files with suffix `_<VersionType>`; A and B alternate), `CurrentElection` "11/03/2026", `StateFP` "18", `Certified` "F", `PolParties` (31: id, name, abbreviation).
- **`data/statewideElectionsC_B.json`**: office categories by heading. Federal: 1005 US Representative. State: 1041 Secretary of State, 1047 State Comptroller (Auditor of State), 1037 Treasurer of State, 1018 State Senator, 1040 State Representative, plus 1020/1028/1008 judges and 1010 Prosecuting Attorney (county-jurisdiction offices, laid out differently). Local: county and township offices. `JurisdictionsReporting` 5,061 of 5,067 precincts.
- **`data/OffCatC_<category>_B.json`** (e.g. 1005: 116,491 B): `StatewideSummary.Race[]` (`OFFICEID`, `OFFICE_TITLE`, `NumofSeats`, candidates with `NAME_ON_BALLOT`, `PARTY` abbreviation, `TOTAL`; **no candidate id**) and `OfficeCategory.Regions.Region[]` (counties for statewide offices, districts for district offices), each with `Races.Race[]` per county: `OFFICEID`, `OFFICE_TITLE`, `Jurisdiction` {`FIPS` (district offices only), `JURISDICTION_NAME`}, candidates with `CANDIDATEID`, `NAME_ON_BALLOT`, `POLITICALPARTYID`, `PARTY_ABBREV`, `TOTAL_VOTES`. For statewide offices the race's jurisdiction is "Indiana" and the county is the region's `MAP_JURISDICTION_NAME`. A single item may be an object instead of a one-element list. Each file has its own `WriteTime` (10:02:44 to 10:02:55 on Nov 19).
- **`data/statewideTurnout_B.json`** (13,704 B): `root.CountyTurnout[]` (92 counties + "Total"): `REGISTERED_VOTERS`, `VotersVoting`, `InPerson`, `Absentee` (Total: 4,768,979 / 1,980,389 / 1,087,780 / 892,609).
- **`download/AllOfficeResults.csv`** (35,190,191 B; also `.json` 76 MB and `.xml` 150 MB, same data; not versioned; Last-Modified Nov 19 15:04 GMT): one row per (precinct, office, candidate), 195,111 rows, every office: Election, JurisdictionName (the office's jurisdiction), ReportingCountyName, DataEntryJurisdictionName (precinct), DataEntryLevelName ("Precinct" everywhere), Office, OfficeCategory, BallotOrder, NameonBallot, PoliticalParty (full name), Winner, NumberofOfficeSeats, TotalVotes. **No ids.** Office and category names differ in case from the JSON ("Secretary Of State" vs "Secretary of State").
- **Agreement (six in-scope categories):** 137 offices, 271 statewide candidate lines. Joined on (office title, county, name on ballot), compared case-insensitively, all 1,791 county candidate totals equal the precinct sums, and every in-scope precinct row joins. Every statewide total equals the sum of its county totals.
- Example: Secretary of State Bayh D 1,007,815; Engling R 829,083; Ballard Lp 70,068 (unofficial; `Certified` F).

## Approaches considered

1. **Precinct CSV plus the category JSON (chosen; my call).** Precinct rows from the CSV; county and state rows, ids and the cross-checks from the JSON.
2. JSON only: county level, ids, no precincts.
3. The 76 MB JSON download instead of the CSV: same rows, twice the size.

## Scope

Categories 1005, 1041, 1047, 1037, 1018, 1040 (US House, the three statewide offices, state senate and house; 137 offices in 2026). 2028 adds US Senator and Governor categories (ids unknown until then): the config lists category ids, and the reader lists Federal/State categories in `statewideElections` that the config doesn't cover. Judges, prosecutors and local offices are out (my call).

## Design

- **Config** `pipeline/sources_in.toml` `[in-2026-general]`: `state = "IN"`, `base_url`, `categories = ["1005", "1041", "1047", "1037", "1018", "1040"]`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** `pipeline/run_in.py fetch SOURCE_ID`: `data/settings.json` first; its `VersionType` must be one letter (else ValueError, no record); then `data/statewideElectionsC_<v>.json`, each `data/OffCatC_<id>_<v>.json`, `data/statewideTurnout_<v>.json`, and `download/AllOfficeResults.csv` (`ext` "csv"), 10 s apart. The record carries `version_code` and `version_type`. The CSV isn't versioned, so a pass can straddle an update (documented; the cross-checks would show it).
- **Reader** `pipeline/readers/in_.py` (`in` is a Python keyword), `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`:
  - **State rows** from `StatewideSummary`: `contest_id` = `OFFICEID`, `choice_id` = the candidate's `CANDIDATEID` found in that office's county races by name on ballot (empty when not found; listed), `party` = `PARTY`, `level "state"`.
  - **County rows** from each region's races: `county_id` = the county FIPS (from `Jurisdiction.FIPS`; for statewide offices from a county-name → FIPS map built from the district offices' races; listed when a county has no FIPS), `county_name` as published, `contest_id` = `OFFICEID`, `choice_id` = `CANDIDATEID`, `party` = `PARTY_ABBREV`.
  - **Precinct rows** from the CSV for in-scope categories: `level "precinct"`, `precinct_name` = DataEntryJurisdictionName, `county_name` = ReportingCountyName, `contest_name` = Office, `choice` = NameonBallot, `party` = PoliticalParty (full name, as published), `contest_id`/`choice_id`/`county_id` joined from the county data on (office title, county, name) compared case-insensitively; unmatched rows kept with ids empty and listed. In-scope precinct rows are those whose OfficeCategory matches an in-scope category name case-insensitively.
  - `vote_type "TOTAL"`; `vote_for` = `NumofSeats`; `contest_scope "statewide"`; `election_date` = `CurrentElection`; `source_created_at` = each JSON file's `WriteTime` (state and county rows), empty for precinct rows (the CSV has none).
  - **Turnout table:** one row per county (not "Total"): FIPS where known, name, registered, voters voting, in person, absentee.
  - **Checks, listed:** precinct sums ≠ county totals; county totals with no precinct rows, precinct rows with no county total; county sums ≠ statewide totals; statewide candidates with no county id match; turnout "Total" ≠ county sums; non-integer counts; duplicate (office, county, candidate) or (office, county, precinct, name) entries; Federal/State categories in `statewideElections` not in the config (except the judges/prosecutor ids 1020, 1028, 1008, 1010); counties without FIPS; differing `WriteTime`s are printed, not anomalies.
  - Missing or unreadable files listed; checks needing them `None`.
- **CLI** `fetch | parse | fetch-parse`, writing `<stamp>.csv` and `<stamp>-turnout.csv`.
- **Tests:** fixtures cut from the real files (US House district 1, Secretary of State, one state senate district; three counties; the matching CSV rows), synthetic variants per check.

## Left to the builder

Fixture counties, summary key names.

## Not done / later

- Judges, prosecutors, local offices, referendums (`AllRefResults`).
- Vote types (the CSV has totals only).
- Whether the six missing precincts (5,061 of 5,067) matter.
