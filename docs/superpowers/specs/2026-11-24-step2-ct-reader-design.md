# Step 2: Connecticut reader (CT EMS static JSON, town level)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24: "Assume I approve, merge, push from now on").** Calls made without asking are marked "(my call)".

## Why

Connecticut has a 2028 Senate race (Class 3) and 5 House seats. The Secretary of the State's public reporting site (CT Elections Management System) serves static JSON that a script can download, with every state and district office by town.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

- **Site:** `https://ctemspublic.tgstg.net/#/home` (AngularJS; linked from portal.ct.gov via `ctemspublic.pcctg.net`). Files under `https://ctemspublic.tgstg.net/ng-app/data/`; all answered 200 to Python `urllib` with our User-Agent.
- **Election list** `Elections.json`: `[{ID, Name, DefaultElection}]`; the 2026 general is `108` ("11/03/2026 -- November 2026 State Election", default).
- **Version** `election/108/Version.json`: `{"Version":56592}`. Every data file lives under `election/108/<version>/`, so one pass reads one snapshot.
- **Files under the version** (2026 sizes): `Lookupdata.json` 213,573 B; `stateVotes_Electiondata.json` 35,851; `townVotes_Electiondata.json` 251,654; `townStatus_Electiondata.json` 10,586; `voterTurnout_Electiondata.json` 26,420; `candidateGrouping_Electiondata.json` 7,527; `officePrecincts_Electiondata.json` 6,693 (also `election_`, `districts_`, `ballotQuestion_`, `reports_`, not used). The saved 2026 copies have no BOM; the reader accepts one anyway.
- **Lookupdata:** `election` {ID, NM, DT "11/03/2026", DNM "2026 General Election", ...}; `townIds` {id: name} (169); `counties` (8); `countyTowns` [{TownID, CountyID, TownName}]; `officeList` [{id: {ID, NM, OT, OO, DT, D}}] (363); `partyIds` {id: {CD, NM, P}} (54); `candidateIds` {id: {NM, LN, FN, MN, P (party id), **AD (home address)**, CO}} (878).
- **Office types (`OT`):** SW 5 (Governor and Lieutenant Governor, Secretary of the State, Treasurer, Comptroller, Attorney General), C 5 (Representative in Congress 1–5), S 36 (State Senator), A 151 (State Representative), PD 54 (Judge of Probate), SM 112 (town offices: registrar of voters, board of education, RTM districts). No US Senate in 2026.
- **Votes:** `stateVotes` {office id: [{candidate id: {V, TO}}]}; `townVotes` {town id: {office id: [same]}}. `V` is a digit string. **Each party line is its own candidate id** (Lamont D 742,437 and WF 29,820; Fazio R 496,473 and IND 27,767). `candidateGrouping` gives combined totals per person for 165 entries (Lamont 772,257 = 742,437 + 29,820); every one equals the sum of that office's lines with the same name. It is **not complete**: 169 (office, name) pairs have more than one line, and Probate 18, 31 and 40 (one candidate on both the D and R lines) and one town office have no grouping entry. Two grouping entries are for town (SM) offices.
- **Party ids not in `partyIds`:** five 2026 lines (candidates 44430, 44431, 44432, 44433, 44219; party ids 1060, 1064, 1069, 1072; State Rep 12, 14, 124, State Senate 11, 23). The ids appear in `townParties` (ids only, no codes).
- **Town sums equal the state values for all 878 candidate lines.** No office or line in one file and not the other.
- **Reporting:** `townStatus` {town id: {TS "( *Unofficial Results )", PR "7 of 7 (100.00%)"}}; `officePrecincts` {office id: "673 of 774 (86.95%)"} — 143 of 261 entries are below 100% although every town shows 100% and `election_` says 774 of 774; meaning unknown.
- **Turnout:** `voterTurnout` {town id: {NM, PR, EV, VV, ABR, ABC, EBR, EBC, EDR, EDC, TO}} plus a key `170` named "Total". Town `EV` sums to 2,276,199 = the election file's `RV` (registered); `VV` sums to 1,307,022 = `BC` (ballots). The other codes are undocumented (absentee / early / election-day registration, received and counted, by the look of them; unverified).
- No timestamp in any file other than the version number; no FIPS codes (CT towns have Census county-subdivision codes, not in the feed).

## Approaches considered

1. **The static JSON, town level (chosen; my call, only one sensible way).** One version request then seven files, all from one snapshot, ids for everything.
2. HTML pages of the same site: no; the app itself reads these JSON files.

## Scope

Office types SW, C, S, A and PD (state and district offices, 251 in 2026). Town offices (SM) and town ballot questions are out (my call, matching the other readers' state-and-district scope).

## Design

- **Config** `pipeline/sources_ct.toml` `[ct-2026-general]`: `state = "CT"`, `base_url = "https://ctemspublic.tgstg.net/ng-app/data/election/108/"`, `office_types = ["SW", "C", "S", "A", "PD"]`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** `pipeline/run_ct.py fetch SOURCE_ID`: `Version.json` first (source id `<id>-version`), then the seven files under `<version>/` (source ids `<id>-<kind>`, kinds `lookup`, `state`, `town`, `townstatus`, `turnout`, `grouping`, `officeprecincts`), 10 s apart; any failure stops the pass; the record carries `version`. Whether an old version's folder stays online after `Version.json` moves on is unknown (my call: if it doesn't, the pass fails with the 404 saved and the next pass reads the new version; no retry logic).
- **Reader** `pipeline/readers/ct.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`:
  - **Level "town" (my call):** Connecticut reports by town, and towns are not counties (CT counties have no government). Town rows use `level = "town"`, `county_id` = the town id, `county_name` = the town name; `pipeline/schema.py`'s docstring adds "town" (New England towns, held in the county_* columns). State rows `level = "state"` (district offices too).
  - `contest_id` = office id; `contest_name` = `NM`; `contest_type` = `OT` code; `vote_for` empty; `contest_scope = "statewide"`.
  - `choice_id` = candidate (party-line) id; `choice` = `NM`; `party` = the party's `CD` ("D", "R", "WF", "WI" for write-in, ...), empty when the party id isn't in `partyIds`; `vote_type = "TOTAL"`.
  - **Party lines stay separate rows (my call):** one row per line as published; no combined person rows are made up. The grouping file is used only as a check. Combining a candidate's lines for projections and calls is left to steps 5–6, which must join lines by (office, name) within Connecticut, since the feed has no person id; the reader lists every (office, name) with several lines so the joins are visible.
  - `reporting_status`: town rows `townStatus` PR as published; state rows `officePrecincts` value for that office as published, empty when absent.
  - `election_name` = `DNM`, `election_date` = `DT` as published; `source_created_at` empty (no timestamp in the feed); the version number is in the summary.
  - **Candidate addresses (`AD`) are never copied** into rows, summary or fixtures.
  - **Turnout table:** one row per town (not the "Total" key): town id, name, county name (via `countyTowns`), `registered_voters` (`EV`), `ballots` (`VV`), then `abr`, `abc`, `ebr`, `ebc`, `edr`, `edc` as published, `precincts_reporting` (`PR`). Integers where the value is a digit string.
  - **Checks, listed, nothing corrected:** town sums ≠ state value per (office, line); lines or offices in one file and not the other (in-scope offices only); grouping totals ≠ sum of the office's lines with that name, and in-scope (office, name) pairs with several lines but no grouping entry (both directions; in-scope offices only); lines whose party id isn't in `partyIds` (listed with the party id; expected today: 5); the turnout "Total" row ≠ sum of towns, per field; non-integer `V`; unknown town, office, candidate or party ids; in-scope offices with no state entry; office types not in the known set (SW C S A PD SM); duplicate (office, line) entries; town ids in votes but not in `townIds`. `officePrecincts` entries below 100% are counted and printed, not anomalies.
  - Unreadable or missing files: listed; checks needing them are `None`.
- **CLI** `fetch | parse SOURCE_ID PASS_RECORD | fetch-parse`, writing `<stamp>.csv` and `<stamp>-turnout.csv`.
- **Tests** on fixtures cut from the real files (Governor with its fusion lines, two congressional districts, one state senate, one probate district, one town office to prove it's excluded; four towns; addresses removed), with synthetic variants for each listed anomaly.

## Left to the builder

Fixture towns, summary key names, test layout.

## Not done / later

- Town offices and town ballot questions.
- Polling-place (precinct) results: not in this feed.
- Town FIPS (county subdivision) mapping.
- The meaning of `officePrecincts` below 100% and the turnout codes other than `EV`/`VV`.
- Whether the feed changes after election night.
