# LiveVoterTurnout ENR (New Jersey: Bergen, Salem; county level)

Surveyed 2026-11-26 in the built-in browser; both files fetched through `pipeline/fetch.py` the same night (200, project user agent).

## Where the data is

Two of New Jersey's six non-Clarity counties publish results on LiveVoterTurnout's ENR pages, linked from each clerk's results page:

| County | Clerk page | Results page | Summary XML |
|---|---|---|---|
| Bergen | `bergencountyclerk.gov/Election` | `livevoterturnout.com/ENR/bergennjenr/20/en/Index_20.html` | `…/bergennjenr/20/summary_20.xml` |
| Salem | `salemcountyclerk.org/election-results/` | `livevoterturnout.com/ENR/salemnjenr/13/en/Index_13.html` | `…/salemnjenr/13/summary_13.xml` |

The election id (20, 13) changes per election. The results page embeds the numbers in its HTML; its script (`/ENR/shared/scripts/LiveResultsScripts_v4.2.js`, `GetXmlTableValues`) reads `../summary_<id>.xml` for the vote-type tables, and the reader takes that file. The page sets `hdnAutoRefresh` 600 (10 minutes).

The other four aren't readable as data: Camden, Sussex and Warren post PDFs (summary and district reports); Hunterdon posts PDFs and had no 2026 general report on its page yet (2026-11-26).

## The file

`<NewDataSet>`; Bergen opens with `TotalBallotsCast` 323,766, `RegisteredVoters` 678,327, `VoterTurnout`, `GeneratedDate` 2026-11-18T11:13:38-05:00 (Salem has none of these). Then one `<Table>` per race and choice: `RaceID`, `RaceName`, `VoteFor`, `ContestantID`, `ContestantName`, `Party` (REP, DEM, or minor-party codes in Salem; empty for many), vote types, `TotalVotes`, and the race's `TimesCounted`, `OverVotes`, `UnderVotes`, `BlankVoted` repeated on every choice. Vote-type element names differ by county:

- Bergen: `EarlyVotingVotes`, `VotebyMailBallotsVotes`, `ElectionDayVotes`, `ProvisionalVotes`. (The page's own table header shows only mail, election day and total; the XML has all four, and they sum to `TotalVotes`.)
- Salem: `EarlyVotes`, `MailBallotVotes`, `ElectionDayVotes`, `ProvisionalVotes`, `CustomVotes` (meaning of Custom unknown; small, e.g. 4 for Murphy).

`Votes` and `BlankVoted` are 0 everywhere.

**Salem's write-ins:** each race has a `Write-In` choice followed by every written-in name as its own choice (2,299 in 2026, including joke names). The `Write-In` line equals the sum of the names after it in all 36 races, and the race balances (vote for × times counted = choices up to Write-In + over + under) only without them, so they are a breakdown. Nothing in the record marks them except their position (and ids and sequence numbers higher than the Write-In line's).

**Salem's district results** exist only inside the 12.7 MB results page HTML (59 districts, "VIEW RESULTS BY DISTRICT"), not in the XML. Bergen's page has no district results (its district report is a PDF). Not read.

## The reader

`pipeline/readers/lvt.py` (`parse_pass`), `pipeline/run_lvt.py` (`fetch | parse | fetch-parse SOURCE_ID`), `pipeline/sources_lvt.toml` (`lvt-NJ-Bergen-2026-general`, `lvt-NJ-Salem-2026-general`). One request per pass.

- Rows: `level` "county", `county_name` from the config, `contest_scope` "local" (as the NJ Clarity counties: join on county + `contest_id` + `choice_id`), one per choice and vote type (element name unchanged) plus TOTAL; `OverVotes` and `UnderVotes` as choices with `choice_id` "". `GeneratedDate` → `source_created_at`.
- All contests (federal, county, municipal, school, questions), my call, as for the Clarity counties.
- Salem's named write-ins are not rows (they'd count twice; the names are private individuals): counted (`write_in_names_dropped`) and their sum checked against the `Write-In` line. Bergen's "Personal Choice" is an ordinary choice.
- Summary lists (nothing corrected): vote types not summing to `TotalVotes`, race fields differing between a race's choices, duplicate choice ids, non-integer counts, write-in breakdown mismatches, unknown `…Votes` fields, nonzero `Votes`/`BlankVoted`, withdrawn choices, ballot-balance differences (informational).
- Bergen's registered voters and ballots cast are in the summary only; no turnout table for step 3 (one county-wide pair).
- Fixtures: `pipeline/tests/fixtures/lvt_bergen_summary.xml` (races 1–3, 138, 150), `lvt_salem_summary.xml` (races 1–3, write-in names replaced by `WRITE-IN NAME n`).

## 2026 run (2026-11-27 07:09 UTC)

| County | Rows | Contests | Vote types | Checks |
|---|---|---|---|---|
| Bergen | 3,909 | 192 | 4 | all clean; balance off by 1 in Maywood Board of Education (7,160 vs 7,159) |
| Salem | 720 | 36 | 5 | all clean; 2,299 write-in names left out; balance off by 1 in 5 races (two county commissioner races, Penns Grove school board, Pilesgrove committee and school board) |

U.S. Senate, Bergen: Booker 193,707, Murphy 115,114; Salem: Murphy 10,730, Booker 10,072. Step 3 loaded both (51 snapshots); nothing to compare yet (one snapshot each, no precinct or state rows).

## Unverified / not done

- Election-night behaviour: these are the final (official) files; whether the XML updates with the page during the count, and how partial reporting shows, is unseen. No reporting status field in the XML.
- What `CustomVotes` counts; what Salem's party codes ETC and SWP stand for.
- Salem's district results (in the page HTML only) and Bergen's district PDF.
- Camden, Hunterdon, Sussex, Warren: PDFs only. Camden and Sussex are read by the PDF reader (`docs/pdfreport.md`, 2026-11-27); Warren's PDFs answer scripts with 403; Hunterdon has posted nothing yet.
