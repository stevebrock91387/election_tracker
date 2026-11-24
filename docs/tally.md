# Tally ENR results API: AR, ND

Seen 2026-11-21 in the built-in browser (page network requests) and with single recon downloads; then downloaded through `pipeline/fetch.py` (`pipeline/run_tally.py`) on 2026-11-24 UTC and parsed with `pipeline/readers/tally.py`. Design: `docs/superpowers/specs/2026-11-21-step2-tally-reader-design.md`. **County level, federal and statewide contest types only.**

## Where the data is

| State | API base | Client id | Election id (2026 general) | Contest types read |
|---|---|---|---|---|
| AR | `https://enr-results-api.totalresults.com/` | `arkansas` | `11b07106-031e-4d7c-911a-d01fb473d6dd` | `Federal`, `Statewide` |
| ND | `https://api.resultsnd.sos.nd.gov/` | `north-dakota` | `348` | `SW` |

A pass makes 3–4 requests, 10 s apart:

- `Election/GetElectionInfo?cId=…&electionID=…`: election name and date, parties, counties by FIPS code (each with its precincts), vote types.
- `Contest/GetContestSearchList?cid=…&electionID=…` (lower-case `cid`, as the site sends it): every contest's name, voteFor, choice names.
- `Contest/GetContestResults?cId=…&electionID=…&contestType=<T>`: per contest the statewide choice totals and each county's (`locations`, keyed by FIPS).

Every response carries `versionID`, `lastUpdated`, `electionID`, `isOfficial`, `errorMessage`. Files fetched at one moment share a `versionID`; the summary lists the distinct ids, so a pass that straddled an update shows two.

## Parsed (2026-11-24, passes started 00:31 UTC)

| State | Files | Bytes | Contests | Counties | Rows (county + state) | Version | Official | Anomalies |
|---|---|---|---|---|---|---|---|---|
| AR | 4 | 2,430,340 | 16 (Senate, House 1–4, 7 statewide offices, Issues 1–4) | 75 | 1,993 + 34 | v235 | yes | none |
| ND | 3 | 844,868 | 12 (House, 9 statewide offices and judges, 2 measures) | 53 | 1,855 + 35 | v1304 | yes | none |

County sums equal each contest's own statewide totals for every choice in both states. No write-ins in the files.

- Choice names carry a party prefix as published ("REP Tom Cotton").
- AR's House contests list only the counties in each district (6–33); the Senate and statewide contests list all 75.
- ND's ballot-measure choices (Yes/No) have `partyID` of three spaces; read as no party.
- AR moved from v234 (seen 2026-11-21) to v235 (lastUpdated 2026-11-23 20:28 UTC) after the results were already marked official; the change was not investigated.
- No vote types in these files. AR's info lists Absentee, Election Day, Early Voting and one more, and its site config has `showVoteBuckets: true`, but the call that returns them was not found. ND lists only "All".

## Running

```
/opt/homebrew/bin/python3 -m pipeline.run_tally fetch-parse tally-AR-2026-general
```

## Not yet known / not done

- AR vote types (the endpoint is unknown).
- Precinct level (info lists each county's precincts; results file not examined at that level).
- Other contest types (legislative, county, city, ...).
- A new election needs its id in `pipeline/sources_tally.toml`; `Election/GetElectionList` lists them but isn't used.
