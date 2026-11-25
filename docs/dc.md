# District of Columbia: DCBOE precinct CSV + citywide JSON

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_dc.py`) on 2026-11-24 at 17:13 Pacific (01:13 UTC 11-25), then parsed with `pipeline/readers/dc.py`. Design: `docs/superpowers/specs/2026-11-24-step2-dc-reader-design.md`. **Precinct level; every contest except Advisory Neighborhood Commissions.** DC matters for 2028 through its 3 electoral votes (President); its House delegate doesn't vote.

## Where the data is

| Kind | URL | Bytes | SHA-256 (first 12) |
|---|---|---|---|
| info | `https://electionresults.dcboe.org/electionResults/getElectionInfo/2026-General-Election` | 1,319 | `b5a1827fad5f` |
| csv | the info's `CsvLink`: `…/Downloads/Reports/November_3_2026_General_Election_Pre-certified_Results.csv` | 1,026,690 | `9d9d31611665` |
| citywide | `https://electionresults.dcboe.org/cityWide/getCityWide/2026-General-Election` | 21,977 | `09720bc262f4` |

The CSV's name changes with the results type ("Pre-certified" now), so the pass reads it from the info file each time.

## Parsed (2026-11-24; "Pre-certified Results", last updated 2026-11-20 21:05 UTC)

- **Output:** 6,978 rows: 6,893 precinct, 85 citywide. 144 turnout rows.
- **Coverage:** 16 contests (Delegate, Mayor, Chairman, At-large Council, four ward Council seats, Attorney General, shadow Senator and Representative, four ward State Board of Education seats, Initiative 86), 144 precincts in 8 wards.
- **Every check is clean:** precinct sums equal the citywide votes for all 85 lines, in both directions; no party differences beyond over/under votes; no ward conflicts, duplicates, non-integer votes, missing registered/ballots rows, or ballots above registered; the info's 144 precincts match the CSV.
- **Turnout sums:** registered 457,371; ballots cast 237,342.
- **Example, Delegate (first-rank, RCV):** White DEM 201,900; Rosado REP 14,680; Freeman STG 13,608; write-in 1,533.

## Quirks

- **Ranked-choice contests** (Delegate, Mayor, At-large, Ward 1 and 5 Council, Ward 6 Board of Education) report first-rank counts only (`contest_type` "RCV first rank"); round-by-round results are separate and preliminary.
- **Candidate text carries the party** ("DEM Robert White"), as published; `choice_id` is the citywide `CandidateNumber`.
- **Over and under votes** are rows with an empty `choice_id` and party. The citywide JSON labels them with a candidate's party (e.g. "REP"); the reader takes party from the CSV instead.
- **Ward** is in `precinct_name` ("Ward 1 Precinct 20") and the turnout table. `county_id` is 11001 (DC's FIPS).
- The CSV has no timestamp; state rows carry the info's `LastUpdated`.

## Not done

- RCV rounds; ANCs; President (2028) will appear as a new contest.
- Election-night behaviour is unverified: whether the CSV updates live, and whether the info's `PrecinctsCounted` equals the CSV's precinct count mid-count (only the post-election state was seen).
