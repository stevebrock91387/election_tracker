# Step 2: Tally ENR reader (AR, ND), county level

Status: **approved by Steve 2026-11-21** ("Yes" to the design as proposed in chat).

## Why

Step 2 needs one reader per results platform. Arkansas (moved off Clarity for 2026) and North Dakota (new site for 2026) run the same results engine: a JSON API behind a "Tally ENR" front end.

## What recon found (2026-11-21, 2026 general, browser + single downloads)

| State | API base | Client id | Election id | Contest types in scope |
|---|---|---|---|---|
| AR | `https://enr-results-api.totalresults.com/` | `arkansas` | `11b07106-031e-4d7c-911a-d01fb473d6dd` | `Federal` (Senate, House 1–4), `Statewide` (11) |
| ND | `https://api.resultsnd.sos.nd.gov/` | `north-dakota` | `348` | `SW` (12, includes the House seat; no Senate race in 2026) |

- `Election/GetElectionInfo?cId=<cid>&electionID=<eid>`: election `name`, `date`, `parties` {partyID: {partyName}}, `contestTypes`, `voteTypes`, `locations` {FIPS: {locationName, locations: precincts}} (AR 598 KB, ND 159 KB).
- `Contest/GetContestSearchList?cid=<cid>&electionID=<eid>`: every contest {contestId: {contestName, contestTypeCode, voteFor, choices {id: {name, partyID, isWriteIn}}}} (AR 1.3 MB, 1,314 contests; ND 375 KB, 531).
- `Contest/GetContestResults?cId=<cid>&electionID=<eid>&contestType=<T>`: per contest `contestID`, `precinctsReporting`, `precinctsPartiallyReporting`, `totalPrecincts`, `totalVotes`, `choices` [{choiceID, totalVotes, partyID}], `writeInChoices`, and `locations` {FIPS: same fields per county, `writeinChoices` (lower-case i)}.
- Every response has `versionID`, `lastUpdated`, `electionID`, `isOfficial`, `message`, `errorMessage`. All files of one moment share a `versionID` (AR v234, ND v1213).
- County sums equal each contest's own choice totals in all three files checked (AR Federal 13 choices, AR Statewide 21, ND SW 35): 0 mismatches. No write-in entries. Both marked official.
- Choice names carry a party prefix as published ("REP Tom Cotton").
- AR lists vote types (Absentee, Election Day, Early Voting, one more) and its config has `showVoteBuckets: true`, but the call that returns them was not found. ND has only "All".

## Approaches considered

1. **The JSON API: info + contest list + one results file per contest type (chosen).** IDs and FIPS codes everywhere, statewide totals in the same file.
2. The site's Download button: not examined; would duplicate what the API gives.
3. Scraping the HTML: no reason to, given the API.

## Scope

Federal and statewide contest types, county level. Not now: vote types (AR), precinct level, other contest types.

## Design

- **Config** `pipeline/sources_tally.toml`: `state`, `api`, `cid`, `election_id`, `contest_types`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** (`pipeline/run_tally.py fetch SOURCE_ID`): fetch info (`<id>-info`), contest list (`<id>-list`), then each contest type's results (`<id>-results-<T>`), 10 s apart, through `pipeline/fetch.py`. Any failure stops the pass (4 requests; nothing to salvage). Writes a pass record `data/raw/<id>/pass-<UTC ts>.json` listing `{kind, type, path}`. URL parameters are URL-encoded; parameter names keep the site's casing (`cId` for info and results, `cid` for the list).
- **Reader** `pipeline/readers/tally.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary)`:
  - State rows from each contest's `choices`, county rows from each location's `choices`; `vote_type = "TOTAL"`, `contest_scope = "statewide"`, `contest_id = contestID`, `choice_id = choiceID`.
  - Names from the contest list (`contest_name`, `vote_for`, `choice` as published), party from info `parties[partyID].partyName` (empty when partyID is null), `county_id` = the FIPS key, `county_name` from info `locations`.
  - `reporting_status` "`<reporting>/<total> precincts`", plus "`, <n> partial`" when partially-reporting > 0.
  - `source_sha256` of the results file the row came from; `source_created_at` = that file's `lastUpdated`; `election_name`/`election_date` from info (date part only).
- **Summary** (nothing corrected; everything listed): contests per type, choices, counties; `is_official` per file; `version_ids` (distinct versionIDs across the pass's files; more than one means the files are from different moments); `election_id_mismatches` (response `electionID` ≠ configured); `errors` (non-empty `errorMessage`); contests or choices missing from the list (rows still emitted with empty names); unknown party or location ids; `mismatches_counties_vs_state` `(contest, choice, state, county sum)`; write-ins found (listed, not emitted as rows); non-integer vote counts (row kept with votes "", listed, left out of sums).
- **CLI** `fetch | parse SOURCE_ID PASS_RECORD | fetch-parse`, output `data/parsed/<id>/<UTC ts>.csv`; prints list lengths and the first 5 entries of non-empty lists.
- **Tests** on fixtures cut from real downloads (AR Senate and one statewide contest, ND House; info cut to the needed parties and counties; list cut to those contests), plus synthetic variants for each summary list.

## Left to the builder

Fixture cutting, exact summary key names, test layout (mirror the ResultsAjax tests).

## Not done / later

AR vote types; precinct level (info lists precincts per county); other contest types; discovering a new election id automatically (`Election/GetElectionList` exists).
