# Texas: Civix ENR statewide file + county file

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_tx.py`) on 2026-11-24 at 23:35 UTC, then parsed with `pipeline/readers/tx.py`. Design: `docs/superpowers/specs/2026-11-24-step2-tx-reader-design.md`. **County level; the 584 federal, statewide and district races**, total and early votes.

## Where the data is

A pass makes two requests, 10 s apart:

| Kind | URL (2026 general, election id 53815) | What it is |
|---|---|---|
| `election` | `https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/53815` | Statewide totals: `Version`, then base64 JSON values `Home`, `Lookups`, and the result sections `Federal`, `StateWide`, `StateWideQ` (propositions), `Districted` |
| `county` | `https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/countyInfo/53815` | `upload`: base64 JSON of every race in every county, with a turnout `Summary` per county |

Election ids are listed by `…/api-ivis-system/api/s3/enr/electionConstants`. The site is the one the Secretary of State links as "Election Night Returns"; it opens on an older election, so pick the 2026 general in its election menu. The URLs have no extension; files are saved as `.json`.

## Parsed (2026-11-24, pass started 23:35 UTC)

| File | Bytes | SHA-256 (first 12) | Notes |
|---|---|---|---|
| Statewide | 1,648,956 | `2c6da20b1f4f` | `Version` enr/53815/117/; `LastUpdatedTime` "Nov 04, 2026 22:48:37" (the page shows 4:48:37 pm CST) |
| County | 4,349,849 | `e6e5e7e006b1` | 254 counties; no timestamp of its own |

Both are byte-identical to the recon downloads made about 40 minutes earlier.

- **Output:** 36,970 rows: 1,834 state rows (917 choices × total and early) and 35,136 county rows. 254 turnout rows.
- **Coverage:** 584 races (Federal 39, StateWide 14, Districted 531, propositions 0), 917 choices, 254 counties.
- **The two files agree:** no differences between statewide values and county sums (total or early), and no race or choice in one file and not the other.
- **Clean checks:** none of the following occur: county keys without a FIPS lookup, early votes above total, non-integer counts, duplicate choices, an office in two sections, undecodable sections.
- **Listed:**
  - `party_differences`: 16 choices whose party code differs between the files: LIB in the statewide file vs L in the county file (11), G vs GRE (3), I vs IND (2). Each file's code is kept as published.
  - `home_reported_exceeds_total`: precincts 202 of 200 in `Home`.
  - `home_vs_county_summary`: `Home` says 5,303 of 5,303 polling locations; the counties sum to 5,301 of 5,301. `Home` precincts reporting is 202, while the counties' precincts reporting sums to 9,867.
- **Turnout, statewide sums of the county rows:** registered 19,041,684; `voters` (`VC`) 9,889,704; precincts reporting 9,867; polling locations 5,301 of 5,301.
- **Example, US Senate:** Talarico (DEM) 5,444,982; Paxton (REP) 4,249,373; Brown (LIB) 190,237; write-ins Ayers 1,925, Simmons 1,738, Hall 1,263, Mohamed 186. Unofficial, as of the Nov 4 update.

## Quirks

- **Base64 JSON:** every value except `Version` is base64-encoded JSON.
- **Candidate ids:** `ID` in the statewide file, lowercase `id` in the county file. Proposition choices (FOR/AGAINST) have a null `ID` and null party in the statewide file but ids in the county file (2025 amendment election: 8701/8702), so they join on the choice name. Seen only in the 2025 sample; 2026 has no propositions.
- **County FIPS:** `county_id` is `Lookups.County.MID` (Anderson 48001), joined on the county key.
- **`voters` (`VC`) may not be ballots cast:** its statewide sum, 9,889,704, equals the US Senate race total exactly, while the Governor race total is higher (9,907,381). Don't use it as turnout without checking.
- **No timestamp on county rows:** `source_created_at` is `Home.LastUpdatedTime` on state rows only. The county file is fetched about 10 s after the statewide file and states no time.
- **Contest names keep trailing spaces** ("U. S. SENATOR ", "RAILROAD COMMISSIONER ").
- **No vote types beyond early votes**, no precincts, no `vote_for`, no election name in either file.

## Not done

- County-level offices: 2,591 races (COUNTY WIDE 1,326, COUNTY RACE 1,265) are listed in the site's race index, but no results endpoint for them has been found.
- Precinct results (the Secretary of State publishes canvass reports after certification).
- Election-day / mail split.
- Whether the site changes after election night (last update Nov 4).
- What `Home.PrecinctsReporting` (202/200), `Summary.PRP` and the county `TV` fields mean, and what `VC` counts.
