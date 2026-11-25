# Step 2: District of Columbia reader (DCBOE results, precinct level)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24).** Calls made without asking are marked "(my call)".

## Why

DC casts 3 electoral votes for President in 2028; its House delegate does not vote. The Board of Elections' results site publishes a precinct-level CSV and citywide JSON that a script can download.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

All 200 to Python `urllib` with our User-Agent (Cloudflare in front).

- **`https://electionresults.dcboe.org/electionResults/getElectionInfo/2026-General-Election`** (JSON, 1,319 B): `ElectionName` "General Election", `ElectionDate`, `LastUpdated` "2026-11-20T21:05:31.567Z", `PrecinctsCounted`/`TotalPrecincts` 144/144, `ElectionResultsTypeName` "Pre-certified Results", `IsLive` false, `IsRCV` true, and `CsvLink` `https://electionresults.dcboe.org/Downloads/Reports/November_3_2026_General_Election_Pre-certified_Results.csv` (the file name changes with the results type).
- **CSV** (1,026,690 B, 10,011 rows): ElectionDate ("11/3/2026 12:00:00 AM"), ElectionName, ContestNumber, ContestName, PrecinctNumber (144), WardNumber (8), Candidate (with party prefix: "DEM Robert White"; also "Write-in", "OVER VOTES", "UNDER VOTES"), Party ("DEM", "NPN", "" …; "CITYWIDE" on the two special rows), Votes. ContestNumber −2 "REGISTERED VOTERS - TOTAL" and −1 "BALLOTS CAST - TOTAL" per precinct.
- **`cityWide/getCityWide/2026-General-Election`** (JSON, 21,977 B): 16 contests (citywide and ward contests, not ANCs) with `ContestNumber`, `OfficeName`, `IsRCV`, `ElectionData` [{`Contestant` (same text as the CSV's Candidate), `Votes`, `TotalVotes`, `IsWinner`, `CandidateNumber`, `PartyCode`}].
- **Party codes differ** between the files on 32 of 85 lines: the JSON gives OVER VOTES and UNDER VOTES a candidate's party (REP, DEM, NPN, IND) where the CSV has "". The JSON's `TotalVotes` leaves over and under votes out (contest 4: 236,852 vs 231,721).
- **Agreement:** all 85 citywide lines equal the CSV's precinct sums, joined on (ContestNumber, Contestant = Candidate).
- **Contests:** 4 Delegate to the House (RCV), 5 Mayor (RCV), 6 Chairman, 7 At-large Council (RCV), 8–11 ward Council members, 12 Attorney General, 13 United States Senator and 14 United States Representative (the shadow delegation), 15–18 ward State Board of Education, 19+ Advisory Neighborhood Commission single-member districts, 364 Initiative Measure No. 86. RCV contests (`IsRCV` true: 4, 5, 7, 8, 10, 18) report first-rank counts only; round-by-round results are separate and preliminary.

## Approaches considered

1. **CSV for precincts + citywide JSON for totals and candidate numbers (chosen; my call).** Three requests.
2. Citywide JSON only: no precincts.

## Scope

Every contest except the ANC single-member districts (contest names starting "ANC-") (my call: ANCs are neighborhood offices). 2028 adds President and Vice President.

## Design

- **Config** `pipeline/sources_dc.toml` `[dc-2026-general]`: `state = "DC"`, `base_url = "https://electionresults.dcboe.org/"`, `election_slug = "2026-General-Election"`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** `pipeline/run_dc.py fetch`: `electionResults/getElectionInfo/<slug>` (`<id>-info`), then its `CsvLink` (`<id>-csv`, ext csv; must start with `base_url` + `Downloads/`, else ValueError, no record), then `cityWide/getCityWide/<slug>` (`<id>-citywide`); 10 s apart; JSON files saved as `.json`.
- **Reader** `pipeline/readers/dc.py`, `parse_pass(...) -> (rows, summary, turnout)`:
  - **Precinct rows** from the CSV (contest number ≥ 0, not ANC): `level "precinct"`, `precinct_id` = PrecinctNumber, `precinct_name` = "Ward <w> Precinct <p>" (my call: the ward has no column of its own), `county_id` "11001", `county_name` "District of Columbia" (my call: DC is its own county-equivalent, FIPS 11001), `contest_id` = ContestNumber, `contest_name` = ContestName, `choice` = Candidate as published, `choice_id` = the citywide `CandidateNumber` for that (contest, Contestant) where found, `party` = Party as published, `vote_type "TOTAL"`.
  - **State rows** from the citywide JSON: `level "state"`, the same ids, `party` = the CSV's Party for that (contest, candidate) (my call: the JSON's party on over/under votes is wrong-looking; differing `PartyCode`s are listed, over/under excepted), or `PartyCode` when the CSV is unread.
  - **Over and under votes** stay rows as published, with `choice_id` "" (as Vermont's blank and over votes; my call), so they are never mistaken for candidates.
  - `election_name` = `ElectionName`, `election_date` = the info `ElectionDate` date part ("2026-11-03"), `source_created_at` = `LastUpdated` on state rows (the CSV has none), `reporting_status` on state rows "`PrecinctsCounted`/`TotalPrecincts` precincts, `<ElectionResultsTypeName>`", `contest_type` "RCV first rank" for RCV contests, else ""; `vote_for` "" (not published); `contest_scope "statewide"` (ward contests are in the citywide file).
  - **Turnout table:** one row per precinct: precinct, ward, registered voters (−2), ballots cast (−1).
  - **Checks, listed:** precinct sums ≠ citywide votes (and lines in one but not the other, both directions, for non-ANC contests); precincts with a ward differing between rows; duplicate (contest, precinct, candidate); non-integer votes; precincts missing the registered or ballots row; ballots > registered per precinct; info `PrecinctsCounted` ≠ the CSV's precinct count; malformed entries; unreadable or missing files (checks needing them `None`).
- **Tests:** fixtures cut from the real files (Delegate, Mayor, Chairman, one ward council, one ANC to prove exclusion; three precincts in two wards).

## Not done / later

- RCV round-by-round results; ANCs; certified results (a new CsvLink when the results type changes).
