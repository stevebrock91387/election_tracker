# Step 2: Alabama reader (design)

Date: 2026-11-24. Approval: Steve's standing approval for the remaining state readers (2026-11-24);
dependency allowed by Steve ("Allow xlrd", 2026-11-24).

## Intent

Load Alabama's certified 2026 general election results at precinct level, from the Secretary of
State's own file, into the common long format (`pipeline/schema.py`). Alabama's election-night page
(`www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx`) says "Results Coming Soon"
between elections, so the certified file is the only reachable source now. Its election-night
counterpart is a separate job for 2028.

## Source (seen 2026-11-24)

`https://www.sos.alabama.gov/sites/default/files/election-data/2026-11/2026GeneralElectionPrecinctResults.zip`,
listed on the SOS election-data page (1,032,122 B, Last-Modified 2026-11-16, script download works).
It holds 67 county workbooks named `2026_GENERAL_ELECTION-<COUNTY>.xls`: legacy BIFF `.xls`, one
sheet "Precinct Results" each.

Layout (all 67 surveyed):
- Row 0: `Contest Title`, `Party`, `Candidate`, then one column per counting unit. Most units are
  precincts ("10 JONES COMM_ CTR_", "PREC 1010 - HUFFMAN BAPTIST CH"). Some are absentee or
  provisional units: ABSENTEE (66 counties), PROVISIONAL (63), the misspelling PROVSIONAL (3),
  PROVISIONAL ABSENTEE, ABSENTEE PROVISIONAL, PROVISIONAL OFFICIAL, BESSEMER/BIRMINGHAM ABSENTEE.
- Rows 1–3: REGISTERED VOTERS - TOTAL, BALLOTS CAST - TOTAL, BALLOTS CAST - BLANK.
- Then one row per (contest, choice). Choices include party-labelled candidates, `Write-In`
  (party NON), `Over Votes` and `Under Votes` (party blank), `Yes`/`No` for amendments. Cells are
  padded with trailing spaces.
- Cells are floats (all integral) or empty. Empty cells appear only for whole (contest, unit)
  blocks: the contest is not on that unit's ballot.
- No ids anywhere (contest, choice, precinct, county). No county or statewide totals. No vote types:
  absentee and provisional ballots are separate units.
- Registered voters are 0 for every unit in 31 counties (e.g. Autauga, Mobile). Published that way;
  not corrected.
- For most units, a contest's lines (choices + over + under) sum to the unit's ballots cast. The
  exceptions are concentrated in absentee and provisional units (e.g. Autauga PROVISIONAL: ballots
  cast 0, contest lines 24–38).

## Approaches

1. **xlrd reads the workbooks (chosen).** Pinned, hash-checked `xlrd==2.0.2` in a gitignored
   `.venv`; every other reader stays stdlib-only. Steve chose this.
2. Hand-convert to CSV once. Rejected by Steve's choice; loses the link between the official file's
   hash and the parsed rows.
3. Skip Alabama. Rejected by Steve's choice.

## Design

- **Dependency.** `requirements.txt` pins `xlrd==2.0.2` with its PyPI SHA-256. Setup:
  `/opt/homebrew/bin/python3 -m venv .venv && .venv/bin/python -m pip install --require-hashes --only-binary :all: -r requirements.txt`.
  The reader imports xlrd inside the function that opens workbooks, so the rest of the package and
  its tests still run under the bare interpreter; the AL tests skip there with the reason "needs
  xlrd (.venv)". The canonical test command becomes `.venv/bin/python -m unittest discover -s pipeline/tests -t .`.
- **Fetch.** One request: the ZIP, through `pipeline/fetch.py` (`ext="zip"`, 120 s interval), then a
  pass record `{"source_id", "state", "started_utc", "files": [{"kind": "zip", "path"}]}`.
- **Two layers.** `read_workbook(data: bytes) -> list[list]` turns one workbook's first sheet into a
  grid of Python values (str, float, or `None` for an empty cell); `parse_county(county, grid)`
  works on the grid only, so synthetic tests edit grids rather than binary files.
- **Scope.** Contest names matching an allowlist: STRAIGHT PARTY; the statewide executive offices
  (Governor, Lieutenant Governor, Attorney General, Secretary of State, State Treasurer, State
  Auditor, Commissioner of Agriculture and Industries, Public Service Commission places); Supreme
  Court (Chief Justice, Associate Justice places), Courts of Civil/Criminal Appeals places; US
  Senator; US Representative districts; State Board of Education districts; State Senator and State
  Representative districts; Proposed Statewide Amendments. 172 names in 2026. Everything else
  (county offices, circuit/district judges, local amendments and referendums: 532 names) is out and
  counted in the summary.
- **Rows.** `level` "precinct"; `county_id` = the filename's county token as published (`ST._CLAIR`),
  `county_name` = that token with `_` read as a space (`ST. CLAIR`); `precinct_id` = `precinct_name`
  = the column header, stripped; `precinct_is_virtual` "Y" when the header contains the word
  ABSENTEE, PROVISIONAL or PROVSIONAL, else "N"; `contest_id` = `contest_name` = the stripped
  title; `contest_scope` "statewide"; `contest_type` "straight party" for STRAIGHT PARTY,
  "measure" for amendments, else "candidate"; `choice` and `party` stripped as published, `choice_id`
  "" (none published); `vote_type` "TOTAL"; `votes` an int. Over Votes and Under Votes are rows.
  An empty block (contest not on the unit's ballot) gives no rows.
- **Turnout table** (one row per unit): state, source_id, source_sha256, county_id, county_name,
  precinct_id, registered_voters, ballots_cast, ballots_blank, as published.
- **Summary lists** (nothing corrected; a check that could not run is `None`):
  - `ballot_balance_mismatches`: (county, unit, contest, lines sum, ballots cast) where an in-scope
    contest's lines don't sum to the unit's ballots cast. Informational (every in-scope contest is
    vote-for-one in 2026; a vote-for-more contest would mismatch by design).
  - `partial_blocks`: (county, unit, contest) where some lines are empty and others not.
  - `non_numeric`: (county, row, column, value) for a count cell that's neither empty nor a number.
  - `non_integer`: same for a float with a fraction.
  - `duplicate_lines`: (county, contest, choice) repeated within a county; the later line is dropped.
  - `duplicate_units`: (county, header) repeated; that county's second column is dropped.
  - `multi_district_units`: (county, unit, office, [contests]) for a real precinct whose ballot
    carries two or more districts of one office (US House, State Senate, State House, State Board of
    Education). Seen in 2026: Jackson's Woodville carries House 22 (407) and 23 (11) of its 418
    ballots. Each such block also appears in `ballot_balance_mismatches`.
  - `blank_units`: (county, column index) for a unit column with a blank header; dropped.
  - `counties_registered_all_zero`: counties whose registered-voter row is 0 for every unit.
  - `missing_header_rows`: (county, name) when REGISTERED VOTERS - TOTAL or BALLOTS CAST - TOTAL is
    absent (the balance check then can't run for that county: listed, not silently skipped).
  - `unreadable_workbooks`: (member, reason): not BIFF, no sheet, or a first row that isn't
    `Contest Title, Party, Candidate`. Extra sheets are listed in `extra_sheets`.
  - `other_members`: ZIP members that don't match `2026_GENERAL_ELECTION-<COUNTY>.xls` style
    (`*-<COUNTY>.xls`).
  - Counts: counties, units, virtual units, contests in scope, contest names out of scope.
  - A missing or unreadable ZIP: `unreadable_files` / `missing_files`, every check `None`.
- **Safety.** ZIP members are read in memory (never extracted); a member over 50 MB uncompressed is
  listed as unreadable without being read.

## Not done / left to the builder

- No statewide or county totals exist to check against; the certified statewide canvass is a PDF.
- No county FIPS mapping (as with other readers that publish names only).
- Election-night reader for 2028 (page empty now).
- Fixture: three real county workbooks (Bullock: registered voters all 0; Coosa: registered voters
  present; Jackson: the PROVSIONAL header) zipped together.
