# Step 2: Alaska reader (Division of Elections precinct CSV, first-choice results)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24).** Calls made without asking are marked "(my call)".

## Why

Alaska has a 2028 Senate race (Class 3), one House seat and 3 electoral votes. The Division of Elections posts one precinct-level CSV per election with ids and five vote types.

## What recon found (2026-11-24, built-in browser + one download to the scratchpad)

- Election page `https://www.elections.alaska.gov/election-results/e/?id=26genr`: "Results Status: Official", last updated November 23, 2026. Links: the summary PDF, **`https://www.elections.alaska.gov/enr/26GENR/results/GA_ENR_Precinct_State_of_Alaska.csv`** (labelled "Summary (csv)"), per-house-district PDFs, a combined HTML report, and the cast vote record ZIP (JSON, for ranked-choice tabulation). 200 to Python `urllib` with our User-Agent.
- **The CSV** (3,335,767 B; Last-Modified Nov 23 21:01 GMT; 20,046 data lines; header ends with a trailing comma, so every line has an empty 42nd field): Precinct_name, Reporting_flag (all 0), Pct_Id, Pct_seq_nbr, Reg_voters, Aggregation_ID (all empty), Contest_Id, Contest_seq_nbr, Contest_title, Contest_party_name (all empty), Selectable_Options (all 1), Candidate_State_ID, candidate_id, candidate_name, Candidate_Type (all C), cand_seq_nbr, Party_Code, total_ballots, total_votes, total_under_votes, total_over_votes, then ballots/votes/under/over for each of Election Day, Absentee, Early Voting, Question, Remote.
- **Units:** 523 names: 402 real precincts ("01-600 Ketchikan No. 1"; Pct_Id equals the name prefix) and 121 counting units: Absentee, Early Voting and Question per house district (40 each; Reg_voters 0) and "HD99 Fed Overseas Absentee" (Reg_voters 822; U.S. Senator and Representative only). Pct_Id is empty for all 80 Early Voting and Question units; Absentee units use ids like `1-1`, `99-999`. Real precincts carry only Election Day votes; the other vote types come only from the counting units.
- **Ballots vary by contest** for 12 counting units (the Absentee, Early Voting and Question units of districts 30, 36, 37 and 39 span judicial districts). U.S. Senator is the first contest for every unit.
- **Ballots exceed votes + under + over** in 2,166 of 8,238 (unit, contest) pairs, always by a positive gap (+886 statewide for U.S. Senator). The file has no write-in lines; the gap is most likely write-in votes (unverified).
- **First choice only:** Alaska's general uses ranked-choice voting; these counts are first choices (round 1). Final rounds are a separate tabulation.
- **Checks on real data:** per line the five vote types sum to the totals for ballots, votes, under and over (0 exceptions); no duplicate (unit, contest, candidate); no non-integer counts.
- **No independent statewide file** in machine-readable form (the summary is a PDF).
- U.S. Senator first choices statewide (sum of lines): Peltola (DEM) 144,583; Sullivan, Dan S. (REP) 132,022; Heikes (REP) 6,107; Sullivan, Daniel J. Jr. (no party code) 4,767.
- Contests: U.S. Senator, U.S. Representative, Governor/Lt Governor, ballot measures, judicial retention (Supreme Court, Superior Court), state legislature.

## Approaches considered

1. **The precinct CSV (chosen; my call, the only machine-readable file).**
2. The cast vote record: ballot-level rankings; for a later ranked-choice reader.

## Scope

Every contest in the CSV (state-run contests only in this file).

## Design

- **Config** `pipeline/sources_ak.toml` `[ak-2026-general]`: `state = "AK"`, `csv_url`, `min_interval_s = 120`.
- **Fetch pass:** one request (`<id>-csv`, ext csv).
- **Reader** `pipeline/readers/ak.py` → `(rows, summary, turnout)`:
  - **Precinct rows:** `level "precinct"`, `precinct_id` = Pct_Id, or the unit name when Pct_Id is empty (my call; the 80 Early Voting and Question units), `precinct_name` = Precinct_name, `precinct_is_virtual` "Y" for names not starting "NN-NNN " (district counting units), else "N" (my call); `contest_id` = Contest_Id, `contest_name` = Contest_title, `choice_id` = candidate_id, `choice` = candidate_name, `party` = Party_Code, `vote_for` = Selectable_Options; vote types `TOTAL` (total_votes) and the source's `Election Day`, `Absentee`, `Early Voting`, `Question`, `Remote` (each `<type>_votes`); `contest_type` "first choice" (my call: flags that these aren't final RCV results); `contest_scope "statewide"`.
  - **No state rows** (no statewide file; sums would be derived).
  - **Turnout table:** one row per unit: precinct id, name, registered voters, and ballots from the unit's U.S. Senator lines (my call; listed: units whose ballots differ between contests, 12 in 2026, and units with no U.S. Senator line).
  - **Write-in gap (informational, not an anomaly):** the summary gives, per contest, the statewide sum of ballots − votes − under − over over its units; no row is made up for it.
  - **Checks, listed:** per line, vote types ≠ total (votes, under, over and ballots);  duplicate (precinct, contest, candidate); a unit name with two Pct_Ids or two Reg_voters; a real precinct ("NN-NNN …") whose Pct_Id differs from its name prefix; non-integer counts; Reporting_flag values other than those seen (0) counted; header changes; malformed lines; unreadable file.
- **Tests:** fixture cut from the real CSV (U.S. Senator, Governor, one ballot measure; three real precincts plus a district Absentee unit and an Early Voting unit (empty Pct_Id)).

## Not done / later

- Ranked-choice final rounds (tabulation reports or the CVR).
- Statewide rows (only in the PDF).
- Election night: the CSV's behaviour before certification is unverified.
