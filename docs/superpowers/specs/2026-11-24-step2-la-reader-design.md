# Step 2: Louisiana reader (SOS live results blobs, parish level)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24).** Calls made without asking are marked "(my call)".

## Why

Louisiana has a 2028 Senate race (Class 3) and 6 House seats. The Secretary of State's live results site (`https://voterportal.sos.la.gov/graphical`) reads JSON "blobs" that a script can download, with race and choice ids, parish breakdowns and early votes.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

Blobs are served at `https://voterportal.sos.la.gov/ElectionResults/ElectionResults/Data?blob=<path>` (JSON, `application/json`; 200 to Python `urllib` with our User-Agent). The site banner says "Unofficial Results - Site may contain test data prior to day of election".

- **`ElectionDates.htm`** (91,777 B): 320 election dates back to 09/11/1982 (no election names); `11/03/2026` is `PKElectionID` 344, `ResultsOfficial` "1"; the default is the 12/12/2026 runoff (345).
- **`20261103/RacesCandidates_Multiparish.htm`** (51,488 B): `Races.WriteTime` "2026-11-24T05:01:04.247" and 97 multi-parish races: `ID`, `SpecificTitle`, `GeneralTitle`, `OfficeLevel`, `NumberToBeElected`, `IsClosedParty`, choices `{ID, Desc ("Julia Letlow (REP)"), Color}`.
- **`20261103/Votes_Multiparish.htm`** (33,155 B): per race `PrecinctsReporting`/`Expected`, `NumAbsenteeReporting`/`Expected`, `VoterCountQualified`, `VoterCountVoted`, choices `{ID, VoteTotal, Outcome}`; `VersionDateTime` "1900-01-01T00:00:00".
- **`20261103/VotesRaceByParish/Votes_<race>.htm`** (Senate 19,473 B): 64 parishes `{ParishValue "01".."64", PrecinctsReporting, PrecinctsExpected, NumAbsenteeReporting, NumAbsenteeExpected, VoterCountQualified, VoterCountVoted, Choice[{ID, VoteTotal, Outcome}]}`.
- **`20261103/VotesEarly/Votes_<race>.htm`** (7,730 B): 64 parishes `{ParishValue, HasReported, Choice[{ID, VoteTotal}]}`.
- Also `ParishesInElection.htm` (precinct counts per parish), `VotesRaceByPrecinct/Votes_<race>_<parish>.htm` (precincts; one file per race per parish), stats files. `CurrentVersion.htm` is 404 after the election.
- **District races:** the parish and early files list only the district's parishes (House 5: 24 parishes, all reporting early votes), and their sums equal the district totals (House 5: 791 precincts; nine candidates, two marked `Runoff`).
- **Choice ids** are unique only within a race: every amendment uses `3` (YES) and `4` (NO). `Outcome` values: Elected, Defeated, Runoff (House 5 and 6 go to the 12/12 runoff), Approved, and null.
- **Parish names** aren't in any blob: the app's JavaScript bundle (`/bundles/graphicalresults?v=…`) holds `parishList` [{id "01", name "Acadia"} … {id "64", name "Winn"}], alphabetical.
- **US Senate:** parish sums equal the statewide totals (Letlow REP 746,466 Elected; "Jamie" Davis DEM 720,516); qualified 2,975,700, voted 1,493,171 and 3,722 precincts also sum. Early votes: Davis 281,624, Letlow 245,865.
- **Race types** (OfficeLevel): 140 U.S. Senator (1), 145 U.S. Representative (6), 160 Public Service Commission (2), 165 BESE (1), 205 State Representative (1, a multi-parish district), 998 Constitutional Amendment (10), plus district judges, district attorneys, municipal offices and a local proposition (999).

## Approaches considered

1. **Multi-parish totals + per-race parish and early files (chosen; my call).** Parish level with ids and early votes; 2 + 2 × 21 = 44 requests per pass (about 7⅓ minutes at 10 s).
2. Precinct files: one request per race per parish (over 1,000 a pass); later, if needed.

## Scope

Office levels 140, 145, 160, 165, 205 and 998 (21 races in 2026). Judges, district attorneys, municipal offices and local propositions are out (my call, as in the other readers). Each election date is its own source (the 12/12/2026 runoff would be a second config entry).

## Design

- **Config** `pipeline/sources_la.toml` `[la-2026-general]`: `state = "LA"`, `base_url`, `election_date = "20261103"`, `office_levels = ["140", "145", "160", "165", "205", "998"]`, `min_interval_s = 120`, `request_gap_s = 10`, and `parishes`: the 64 code → name pairs copied from the app's bundle on 2026-11-24 (my call: static, so a pass doesn't fetch JavaScript; documented with its source).
- **Fetch pass** `pipeline/run_la.py fetch SOURCE_ID`: `<date>/RacesCandidates_Multiparish.htm` (`<id>-races`), `<date>/Votes_Multiparish.htm` (`<id>-votes`), then for each in-scope race id (read from the races file, in file order) `VotesRaceByParish/Votes_<id>.htm` (`<id>-parish-<race>`) and `VotesEarly/Votes_<id>.htm` (`<id>-early-<race>`), 10 s apart (about 7⅓ minutes for 2026); `ext="json"`; any failure stops the pass; a races file that isn't JSON with a `Races.Race` list stops it too (ValueError, no record). The record lists the race ids.
- **Reader** `pipeline/readers/la.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`:
  - **State rows** from `Votes_Multiparish`: `level "state"`, `vote_type "TOTAL"`, `reporting_status` "`<PrecinctsReporting>/<PrecinctsExpected>` precincts, `<NumAbsenteeReporting>/<NumAbsenteeExpected>` absentee".
  - **Parish rows** from `VotesRaceByParish`: `level "county"`, `county_id` = parish code as published ("01"), `county_name` from the config list, TOTAL; and from `VotesEarly`: vote type "EarlyVoting" (the file's own key; my call), for parishes with `HasReported` "1" (others listed). Whether early voting includes mail absentee is not stated; the reader only checks early ≤ total.
  - `contest_id` = race `ID`; `contest_name` = `SpecificTitle`; `contest_type` = `GeneralTitle`; `vote_for` = `NumberToBeElected`; `choice_id` = choice `ID`; `choice` = `Desc` as published; `party` = the text in the final parentheses of `Desc` when it is upper-case letters (e.g. "REP"), else empty (my call: the label is the only party field); `source_created_at` = the races file's `WriteTime`; `election_date` = the config date as "11/03/2026"; `election_name` empty (no blob names the election); `contest_scope "statewide"`. Choice keys are always (race, choice).
  - **Outcomes** (Elected, Runoff, Approved, …) have no schema column: the summary lists each race's outcomes, and races with a `Runoff` outcome separately (my call; step 6 and the runoff source need them).
  - **Turnout table:** one row per (race, parish): race id, parish code and name, qualified, voted, precincts reporting/expected, absentee reporting/expected (it is race-specific: each race has its own electorate).
  - **Checks, listed:** parish sums ≠ the state value per (race, choice); parish sums ≠ state qualified, voted, precincts and absentee counts per race; early > total per parish and choice; choices in one file and not the other; in-scope races with no parish or early file; parish codes not in the config list; non-integer counts (votes ""); duplicate (race, parish, choice); malformed entries (listed, not fatal); unreadable or missing files (checks needing them `None`).
- The pre-election "may contain test data" banner has no counterpart in the blobs; the reader can't detect test data (documented).
- **CLI** `fetch | parse | fetch-parse`, writing `<stamp>.csv` and `<stamp>-turnout.csv`.
- **Tests:** fixtures cut from the real files (Senate, one House district, one amendment; three parishes), synthetic variants per check.

## Left to the builder

Fixture parishes, summary key names.

## Not done / later

- Precinct results (per race per parish files).
- The 12/12/2026 runoff and other dates (config entries).
- Judges, district attorneys, municipal races, local propositions.
- Statewide early totals (not published as such; parish sums only).
