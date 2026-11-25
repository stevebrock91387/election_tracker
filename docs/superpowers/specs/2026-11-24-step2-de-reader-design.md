# Step 2: Delaware reader (Department of Elections ENR JSON, election-district level)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24).** Calls made without asking are marked "(my call)".

## Why

Delaware has one House seat and 3 electoral votes in 2028 (no Senate race until 2030). The Department of Elections' results page reads JSON files a script can download, down to the 530 election districts, with three vote types.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

Files under `https://elections.delaware.gov/results/enr/` (the page adds `?t=<timestamp>`), all 200 to Python `urllib` with our User-Agent; JSON lists of flat objects; counts are strings with thousands separators ("140,838") except in the county file (integers).

- **`Election_StatewideResults_ID_GE2026.json`** (65,002 B, 124 lines): Election Id/Name/Date, Results Type ("OFFICIAL RESULTS"), Total Precincts / Precincts Reported (530/530), Party Id/Name, Contest Sorting Order, Contest Title, **Candidate Id**, Candidate Name, Pos, Machine Votes, Absentee Votes, Early Voting Votes, Total Votes, Percentage, ReportTime.
- **`Election_ByElectionDistrict_ID_GE2026.json`** (3,750,122 B, 9,385 lines): the same without ids or precinct counts, plus "Election District" ("Election District 01-01"; 530 districts).
- **`Election_ByCountyWithWilmington_ID_GE2026.json`** (45,166 B, 124 lines): per candidate, integer columns Wilmington, Rest of New Castle, New Castle, Sussex, Kent, State.
- **`Election_VoterTurnout_ID_GE2026.json`** (8,166 B, 42 lines): per Representative District: Ballots Cast, Reg Voters, Percentage.
- Also `Election_ByRepresentativeDistrict_ID_…json`, a data.delaware.gov CSV (statewide lines only), a write-in PDF.
- **Agreement:** for all four vote counts, election-district sums equal the statewide values on every one of 124 (contest, candidate name) lines; the county file's State column equals the statewide totals, New Castle + Sussex + Kent = State and Wilmington + Rest of New Castle = New Castle on every line. (Contest, name) is unique.
- Contests: U.S. Senator, Representative in Congress, Attorney General, Auditor, Treasurer, state senate and house districts.

## Approaches considered

1. **Statewide + election-district + county + turnout JSON (chosen; my call).** Ids from the statewide file; precincts with vote types; counties.
2. The open-data CSV: statewide only.

## Scope

Every contest in the statewide file (federal, statewide, legislative).

## Design

- **Config** `pipeline/sources_de.toml` `[de-2026-general]`: `state = "DE"`, `base_url = "https://elections.delaware.gov/results/enr/"`, `election_id = "GE2026"`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass:** the four files in the order statewide, district, county, turnout (kinds `statewide`, `district`, `county`, `turnout`), each URL with `?t=<unix ms>` as the page does (my call), 10 s apart.
- **Reader** `pipeline/readers/de.py` → `(rows, summary, turnout)`:
  - Vote types: `TOTAL`, `Machine Votes`, `Absentee Votes`, `Early Voting Votes` (the source's names); numbers parsed after removing thousands separators (format, not correction; a value that still isn't an integer is listed).
  - **State rows** from the statewide file (`choice_id` = Candidate Id, `party` = Party Name, `reporting_status` "Precincts Reported/Total Precincts precincts", `source_created_at` = ReportTime).
  - **County rows** from the county file, TOTAL only: New Castle (`county_id` "10003"), Kent ("10001"), Sussex ("10005") (FIPS; my call); Wilmington and Rest of New Castle aren't counties and aren't rows (they are checked).
  - **Precinct rows** from the district file: `precinct_id` = the district code ("01-01"), `precinct_name` as published, four vote types.
  - `choice_id` on county and precinct rows from the statewide file by (contest, name); `contest_id` = Contest Sorting Order (my call: the only contest key; unique per contest in 2026, checked); `election_name`, `election_date`, `contest_scope "statewide"`.
  - **Turnout table:** one row per representative district: ballots cast, registered.
  - **Checks, listed:** district sums ≠ statewide per vote type; county columns ≠ statewide and parts ≠ wholes; lines in one file and not another (all directions); duplicate (contest, name) or (district, contest, name); a contest sorting order shared by two titles; non-integer counts; malformed entries; unreadable or missing files (checks needing them `None`).

## Not done / later

- Representative-district results; write-ins (PDF); certified vs official distinction.
