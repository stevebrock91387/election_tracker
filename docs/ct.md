# Connecticut: CT EMS public reporting (static JSON), town level

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_ct.py`) on 2026-11-24 at 23:59 UTC, then parsed with `pipeline/readers/ct.py`. Design: `docs/superpowers/specs/2026-11-24-step2-ct-reader-design.md`. **Town level; the 251 state and district offices** (statewide, Congress, state senate, state representative, judge of probate). Town offices and town ballot questions are out.

## Where the data is

Base `https://ctemspublic.tgstg.net/ng-app/data/election/108/` (election 108 = "11/03/2026 -- November 2026 State Election", from `../../Elections.json`). A pass reads `Version.json` (`{"Version": n}`), then seven files under `<n>/`, 10 s apart:

| Kind | File | Bytes (v56593) | SHA-256 (first 12) |
|---|---|---|---|
| version | `Version.json` | 23 | `71ddddb5c627` |
| lookup | `Lookupdata.json` | 213,573 | `1166e746d9c2` |
| state | `stateVotes_Electiondata.json` | 35,851 | `b024bf63acac` |
| town | `townVotes_Electiondata.json` | 251,654 | `6c33b97a7fb8` |
| townstatus | `townStatus_Electiondata.json` | 10,586 | `054333b7f8b0` |
| turnout | `voterTurnout_Electiondata.json` | 26,420 | `a32c21c9ba27` |
| grouping | `candidateGrouping_Electiondata.json` | 7,527 | `c479298597f9` |
| officeprecincts | `officePrecincts_Electiondata.json` | 7,348 | `34aa150600a7` |

The version moved from 56592 (recon, earlier the same day) to 56593: the feed is still being updated three weeks after the election. In 56593, `officePrecincts` changed size (6,693 → 7,348 bytes); the vote files didn't.

## Parsed (2026-11-24, version 56593)

- **Output:** 6,886 rows: 617 state rows (one per party line) and 6,269 town rows. 169 turnout rows.
- **Coverage:** 251 offices (state rows by type: A 397, S 105, PD 73, SW 23, C 19), 617 party lines, 169 towns.
- **Town sums equal the state values for every line**; no line in one file and not the other; every grouping total equals the sum of its office's same-named lines; the turnout "Total" entry equals the town sums for all eight fields.
- **Listed:**
  - `unknown_parties`: 5 lines whose party id (1060, 1064, 1069, 1072) isn't in the party list (State Rep 12, 14, 124; State Senate 11, 23). Their `party` is empty.
  - `multi_line_names_without_grouping`: 3 probate districts (18, 31, 40) where one candidate runs on two lines with no grouping entry (e.g. Matt Jalowiec, Probate 18, D and R).
  - `multi_line_names`: 165 (office, name) pairs with more than one line. Informational: these are the joins steps 5–6 need.
  - `office_precincts_below_100`: 67 in-scope offices whose `officePrecincts` value is below 100% although every town shows 100%. Meaning unknown.
- **Turnout:** registered (`EV`) 2,276,199; ballots (`VV`) 1,307,022. Hartford's turnout `PR` reads "25 of 24 (104.17%)"; its town status reads "24 of 24 (100.00%)".
- **Example, Governor and Lieutenant Governor (unofficial):** Lamont/Bysiewicz D 742,437 + WF 29,820; Fazio/Corey R 496,473 + IND 27,767; three write-in tickets 28, 18, 18.

## Quirks

- **Level "town":** rows use `level = "town"` with the town id and name in `county_id`/`county_name` (`pipeline/schema.py` documents this). The turnout table also carries the town's county name.
- **Party lines:** each line is its own candidate id and row; no combined person rows are made up. The feed has no person id, so combining lines means joining on (office, name) within Connecticut.
- **Candidate addresses:** the lookup file carries each candidate's home address (`AD`). The reader never copies it, and the test fixtures have it removed.
- **No timestamp** in any file; `source_created_at` is empty and the version number is in the summary.
- **Turnout codes:** `EV` sums to the registered total and `VV` to the ballots total; `ABR ABC EBR EBC EDR EDC` are kept as published (absentee / early / election-day registration, received and counted, by the look of them; unverified).
- No FIPS codes (towns have Census county-subdivision codes, not in the feed); no vote types; no polling-place results.

## Not done

- Town offices and town ballot questions.
- Polling-place results; town FIPS mapping.
- What `officePrecincts` below 100% means, and the turnout codes other than `EV`/`VV`.
- Whether an old version's folder stays online after `Version.json` moves on (a pass that hits a 404 stops; the next pass reads the new version).
