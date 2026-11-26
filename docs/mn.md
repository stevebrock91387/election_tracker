# Minnesota reader (step 2, county level)

Built 2026-11-26. Steve approved reading the file host directly (2026-11-26): the file answers the
project fetcher, but the page that lists the files sits behind a Radware bot check
(`docs/blocked-states.md`, "Minnesota follow-up").

    /opt/homebrew/bin/python3 -m pipeline.run_mn fetch|parse|fetch-parse mn-2026-general

Code: `pipeline/readers/mn.py`, `pipeline/run_mn.py`, `pipeline/sources_mn.toml`; tests
`pipeline/tests/test_mn.py` (fixture: the real lines of counties 01 and 02 for 12 offices).

## Source

`https://electionresultsfiles.sos.mn.gov/20261103/allracesbycounty.txt`, one request per pass.
ISO-8859-1, CRLF, no header, 16 semicolon-separated fields, one line per (county, office, candidate).
**Field meanings are read from the data, not from a spec** (the spec page is behind the bot check):
state; county id; precinct (empty); office id; office name; district; candidate id; candidate name; two
empty fields; party; precincts reporting; precincts in the office's part of the county; votes; percent;
office total in the county. County ids run 01–87 (not FIPS); the file has no county names.

## Scope (my call under the reader standing approval)

Office ids in `office_ranges`: U.S. Senator 0102, U.S. Representative 0104–0111, State Senator
0121–0187, State Representative 0188–0321, Governor and constitutional officers 0331–0335,
amendment 0351, Supreme Court and Court of Appeals 7000–7099. Not read (listed by id in the summary):
district courts, county offices, soil and water, county questions (140 offices in 2026).

## Rows

Level `county`, `contest_id` = office id, `contest_scope` "statewide", vote type TOTAL only (the file has
no vote types), `reporting_status` "<reporting>/<total>" per county and office (a district contest counts
only its own precincts in the county: U.S. House 5 in county 02 is "21/21", the Senate "128/128").
Write-ins (id 9901, party WI) and the amendment's "ESTIMATED BLANKS" (id 9003) are ordinary choices, as
published. Candidate ids repeat across offices: key on (office, candidate).

## 2026 run (2026-11-26)

Two downloads, identical (sha256 `ba71d3fa…`): 8,285 lines, 4,952 rows, 87 counties, 222 contests (1 + 8 +
67 + 134 + 4 + 1 + 7). Every (county, office) sums to its office total; precincts reporting are consistent
and never above the total; no duplicates, malformed lines or non-integer counts. Step 3: loaded; no check
could compare anything yet (one snapshot, no turnout table, no state rows).

## Not done / unverified

- Field meanings (above). Whether the file updates on election night. A statewide or precinct file
  (none read; URLs not guessed). County names (no lookup file read).
- No statewide totals to check the county sums against.
