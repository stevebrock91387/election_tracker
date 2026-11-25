# Alabama: Secretary of State certified precinct ZIP (67 county .xls)

Seen 2026-11-24 in the built-in browser and with one recon download. Downloaded through `pipeline/fetch.py` (`pipeline/run_al.py`) on 2026-11-24 at 21:13 Pacific (05:13 UTC 11-25), then parsed with `pipeline/readers/al.py`. Design: `docs/superpowers/specs/2026-11-24-step2-al-reader-design.md`. **Precinct level, certified results, state-level contests only. The first reader with a dependency: xlrd 2.0.2 (Steve: "Allow xlrd", 2026-11-24).**

## Setup

The workbooks are legacy BIFF `.xls`, which the standard library can't read. `requirements.txt` pins xlrd with its PyPI SHA-256; install it into a gitignored venv:

    /opt/homebrew/bin/python3 -m venv .venv
    .venv/bin/python -m pip install --require-hashes --only-binary :all: -r requirements.txt

Run the reader and the tests with `.venv/bin/python`. Under the bare interpreter the AL tests skip ("needs xlrd (.venv)") and everything else runs.

## Where the data is

`https://www.sos.alabama.gov/sites/default/files/election-data/2026-11/2026GeneralElectionPrecinctResults.zip`, listed on `https://www.sos.alabama.gov/alabama-votes/voter/election-data` (Last-Modified 2026-11-16). One request per pass. The election-night page (`www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx`) said "Results Coming Soon" on 2026-11-24.

| File | Bytes | SHA-256 (first 12) |
|---|---|---|
| ZIP | 1,032,122 | `fd67927fa84c` |

## Parsed (2026-11-24)

- **Output:** 233,594 rows (one per unit × contest line, vote type TOTAL); 2,071 turnout rows.
- **Coverage:** 67 counties; 2,071 units: 1,933 precinct columns and 138 absentee/provisional units; 172 state-level contests. 529 other contest names (county offices, circuit and district judges, local amendments and referendums) are out of scope and counted.
- **Clean:** no unreadable workbooks, extra sheets, stray ZIP members, partly empty blocks, non-numeric or fractional cells, repeated lines or unit headers, blank headers or missing header rows.
- **Listed:**
  - 31 counties publish 0 registered voters for every unit (e.g. Autauga, Mobile, Jackson). Kept as 0 in the turnout table.
  - 425 split polling places: a real precinct column carrying two or more districts of one office (269 State House, 99 State Senate, 57 US House). Example: Jackson's Woodville carries House 22 (407 lines) and 23 (11) of 418 ballots cast. **For the House, these units have to be split by district, not taken whole.**
  - 2,276 (unit, contest) blocks whose lines (choices + over + under) don't sum to the unit's ballots cast: 1,432 in absentee/provisional units (e.g. Autauga PROVISIONAL: ballots cast 0, contest lines 24–38), 793 in split polling places (expected: each district holds part of the ballots), and 51 elsewhere, in six counties (Tuscaloosa 26, Houston 20; e.g. Houston's Calvary Bapt Ch: 872 lines against 871 ballots in 20 of its 25 contests). Causes not investigated.
- **Example, U.S. Senator (sum of the file's precinct rows; not checked against a certified statewide figure):** Moore (REP) 918,207; Wess (DEM) 759,018; write-in 2,042; over 196; under 14,825. Ballots cast over all units: 1,694,618.

## Quirks

- **No ids** for counties, units, contests or choices. `county_id` is the filename token (`ST._CLAIR`), `county_name` the token with `_` as a space; `precinct_id` = `precinct_name` = the column header; `contest_id` = the title; `choice_id` is empty. Headers and names have trailing spaces in the source (stripped). Precinct headers use `_` for `.` (e.g. "COMM_ CTR_").
- **Virtual units** are headers containing ABSENTEE, PROVISIONAL or the misspelling PROVSIONAL (Jackson, Marshall, Tallapoosa). Others: PROVISIONAL ABSENTEE, ABSENTEE PROVISIONAL, PROVISIONAL OFFICIAL, Bessemer and Birmingham ABSENTEE (Jefferson). PROVIDENCE-named precincts are real.
- **Empty cells** mean the contest isn't on that unit's ballot; those blocks give no rows. Over Votes and Under Votes are rows; Write-In has party NON.
- `contest_type`: "straight party", "measure" (statewide amendments) or "candidate". `contest_scope` is "statewide" for all (district contests included). `vote_for` isn't published.
- No vote types (absentee and provisional are units, not types), no county or state totals.

## Not done

- No statewide check: the files carry no totals; the certified statewide canvass wasn't read.
- The 51 unexplained balance differences, and why provisional units show 0 ballots cast in some counties.
- County FIPS codes; the 2028 election-night reader (the page is empty between elections).
