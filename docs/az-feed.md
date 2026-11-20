# Arizona results feed (Enhanced Voting JSON)

Source: Arizona Secretary of State media page, https://azsos.gov/pressazsosgov (per Steve, 2026-11-20).

Feed URL (2026 general):
`https://app.enhancedvoting.com/cdn/results/Arizona/export-110326GeneralElection.json`

**Rate limit:** the SOS allows automated downloads no more than once every 2 minutes. Any reader must enforce that as a hard minimum interval.

`results.arizona.vote` returns 403 to scripts; don't scrape it. Use this feed.

## First fetch (2026-11-20T20:29:34Z, curl, no custom User-Agent)

- HTTP 200, `Content-Type: application/octet-stream` (the body is JSON despite the type), 72,662,370 bytes
- SHA-256 `396fbefcfd03d2e185c891e0b421dcb4053e3a5496a07ad66fa344b4cb085565`
- Copy kept at `data/raw/az-2026/export-110326GeneralElection-20261120T202934Z.json` (gitignored)
- `electionName` "2026 General Election", `electionDate` 2026-11-03, `createdAt` 2026-11-20T17:20:35Z

## Structure

```
{
  electionDate, electionName, createdAt,          # createdAt = when the export was generated (UTC)
  results: {                                       # statewide
    id, name: "Arizona",
    ballotItems: [ BallotItem ],                   # 99 items: 76 candidate contests, 23 ballot measures
    reportingStatuses: [ {groupName, status} ]
  },
  localResults: [                                  # one per county; all 15 counties present
    { id: "06", name: "Greenlee County", ballotItems: [ BallotItem ], reportingStatuses: [...] }
  ]
}

BallotItem = {
  type: "State", id: "AZ-1", name: "U.S. Representative in Congress - District No. 1",
  voteFor, ballotOrder, contestType: "Candidate" | "BallotMeasure",
  precinctsParticipating, precinctsReporting,      # null at statewide level; filled at county level
  rankedChoiceResults,                             # null everywhere in this file
  ballotOptions: [ {
    id, name, ballotOrder, voteCount, politicalParty,
    groupResults: [ {groupName, voteCount, isFromVirtualPrecinct} ],   # vote type split
    precinctResults: null | [                      # null statewide; filled in county items
      { id, name: "001 Eagle", isVirtual, voteCount, reportingStatus, groupResults: [...] }
    ]
  } ]
}
```

- **Contests are matched across levels by `id`** (e.g. `AZ-6`); county `ballotItems` hold only the contests on that county's ballot.
- **Vote types (`groupName`):** `Election Day`, `Early Voting`, `Provisional`, `Early A.R.S. 16-579`, `Late Early*`. Same five names statewide and in counties.
- **Status values:** `Fully Reported`, `Partially Reported`, `Not Reported`, `Not Participating`.
- **Federal contests in this file:** U.S. House districts 1–9. No U.S. Senate contest (correct: Arizona had no Senate race in 2026). Also Governor.
- **Precinct level:** every county carries precinct results (143,533 precinct-option rows; Maricopa 83,215).

## Checks run on this file

- Statewide `voteCount` equals the sum of county `voteCount` for all 415 contest/option pairs present in both: **0 mismatches**.
- Every statewide option's `groupResults` sum to its `voteCount`: **0 mismatches**.

## Oddities (don't rely on these fields without checking)

- **Statewide `reportingStatuses` all say `Not Reported`** while every county says `Fully Reported` (or `Not Participating` for one vote type). The statewide status field does not reflect the count.
- **Precinct `reportingStatus` is mostly `Partially Reported`** (117,320 of 143,533 rows) even in counties marked fully reported. Its meaning is unknown; check the media JSON guide.
- `Content-Type` is `application/octet-stream`, not `application/json`.

## Format reference: Arizona Media JSON Guide

- Linked as "Arizona Media JSON Guide" on the SOS press page (`https://azsos.gov/press`, which `/pressazsosgov` redirects to) → `https://azsos.gov/media/752` → PDF at `https://azsos.gov/sites/default/files/docs/Arizona%20Media%20JSON%20Guide.pdf`.
- Read in the browser 2026-11-20: HTTP 200, `application/pdf`, 221,174 bytes, Last-Modified 2026-10-16, SHA-256 `ff9a1fd41ff5a23a8f5d4d4feb3d765d3434aeddbf77dc4d6e5991e3da559636`.
- **Not yet saved into `docs/`:** azsos.gov returns 403 to curl (with and without a browser User-Agent), and the browser-download path couldn't be confirmed. Any copy saved here must match the SHA-256 above.

The same press page links "Unofficial Results" to `https://app.enhancedvoting.com/results/public/Arizona/110326GeneralElection` — the same `/results/public/<state>` pattern GA, UT and WA redirect to.

## Not yet known

- How often `createdAt` changes on election night (needs a second fetch at least 2 minutes later; not done).
- Whether the file name pattern (`export-<MMDDYY><ElectionName>.json`) holds for other elections.
