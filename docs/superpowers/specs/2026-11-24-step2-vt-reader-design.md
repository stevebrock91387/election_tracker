# Step 2: Vermont reader (SOS static JSON, town level)

Status: **approved under Steve's standing approval for the remaining state readers (2026-11-24).** Calls made without asking are marked "(my call)".

## Why

Vermont has a 2028 Senate race (Class 3) and one House seat. The Secretary of State's results site (`https://electionresults.vermont.gov/`) reads static JSON that a script can download, with every office by town.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

- **Files** on `https://static.electionresults.vermont.gov/elections/` (200 to Python `urllib` with our User-Agent):
  - `elections.json` (78,088 B): list of elections; the 2026 general is guid `68d61e96-1d28-4210-8c1d-8e90512ae105` ("2026 GENERAL ELECTION", `isDefault` true, `isOfficial` true).
  - `<guid>.json` (119,967 B): `electionDetails`; for each tab (`federal`, `stateWide`, `senate`, `house`, `county`, `town`, `turnOut`) a `path` like `elections\<guid>-f-20261117185828.json` (all share one timestamp = one snapshot); `towns` (247: townId, townName); `townDistricts` (283: town → county, senate and house districts); `lastUpdatedDate` "11/17/2026 06:58 PM"; `townsReporting` "247/247"; `unorganisedTowns` (unorganized gores, ids 263+).
  - Results files: `-f-` federal (1 office, 324,255 B), `-s-` statewide (6: Governor, Lt Governor, Treasurer, Secretary of State, Auditor, Attorney General; 1,329,283 B), `-sn-` state senate (16 districts, 356,624 B), `-h-` state house (109 districts, 454,737 B), `-cty-` county offices (probate judge, sheriff etc.; 2,180,658 B), `-t-` town offices, `-turnout-` (3,560,436 B).
- **Results shape:** `{"d": [{"o": [office]}]}`; each office: `oid`, `on`, `vf` (vote for; 2 for 41 house districts), `otc`, district `dc`/`dn` for senate and house, `cs` (one entry per town plus one total entry with `tid` 0 named "STATE WIDE" or "District Wide"), and `cd` (the same in a wide layout; not needed). Each `cs` entry: `tid`, `tn`, `sc` (ballots cast), `sv` (overvotes: 594 statewide for Congress, as the page's "Overvotes"), `bv` (blank votes: 6,241, the page's "Blank Votes"), `distReported`/`townsReported`, `rc` (candidates: `cid`, `cn`, `vc`, `pn` party name, `isWriteIn`, `isWinner`) and `wc` (write-ins: `cid` 0 "OTHER WRITE-IN" plus named write-ins).
- **Checks on real data:** in all four in-scope files the town entries sum exactly to the total entry, for every candidate. In Addison, Congress: candidates and write-ins 744 + blank 11 + over 0 = `sc` 755 = the town's turnout `tvc`.
- **Parties** are names: REPUBLICAN, DEMOCRATIC, INDEPENDENT, PROGRESSIVE, DEM/PROG (fusion shown as one line), PEACE AND JUSTICE, FREEDOM AND UNITY.
- **Write-ins:** the `wc` lists name every person who got a write-in vote, many with one vote and apparently private individuals (e.g. names written once in one town).
- **Turnout** `-turnout-`: per town `tid`, `tn`, `tvr` (registered; sum 506,830), `tvc` (ballots; sum 311,510 = Congress `sc`), `tabs` (absentee/early; sum 193,189), `tdis`/`tdisr` (districts reporting), plus the town's office results again (`hl`, not needed).
- Congress (unofficial page, official per the site): Balint DEM 198,758; Malloy REP 94,078; four independents; total votes cast 311,510.

## Approaches considered

1. **The static JSON (chosen; my call, the only sensible way).** One election file names one snapshot; ids for towns, offices, candidates.
2. The RSS XML: summary only.

## Scope

Federal, statewide, state senate and state house (132 offices). County and town offices are out (my call, as for Connecticut).

## Design

- **Config** `pipeline/sources_vt.toml` `[vt-2026-general]`: `state = "VT"`, `base_url = "https://static.electionresults.vermont.gov/"`, `election_guid`, `kinds = ["federal", "stateWide", "senate", "house", "turnOut"]`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** `pipeline/run_vt.py fetch SOURCE_ID`: `elections/<guid>.json` first; then each kind's `path` (backslashes turned into `/`), 10 s apart; the record carries the snapshot timestamp from the paths; a path missing, not under `elections/`, or with a different timestamp from the others stops the pass (ValueError, no record).
- **Reader** `pipeline/readers/vt.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`:
  - Town entries: `level = "town"`, `county_id` = `tid`, `county_name` = `tn` (as Connecticut). Total entry (`tid` 0): `level = "state"` (district totals too).
  - `contest_id` = `oid` plus the district code for senate and house (`"12:ADD 1"`, since `oid` 12 is every senate district; my call); `contest_name` = `on` plus " – " + `dn` for districts; `contest_type` = the kind (`federal`, `stateWide`, `senate`, `house`); `vote_for` = `vf`.
  - Choices: each `rc` and `wc` entry, `choice_id` = `cid` (as a string; "0" is OTHER WRITE-IN), `choice` = `cn`, `party` = `pn` or "". Plus two rows per entry for the published counts: `choice` "Blank Votes" (`bv`) and "Overvotes" (`sv`), `choice_id` empty (my call: the site shows them as result rows).
  - `reporting_status` = `distReported` or `townsReported` as published; `source_created_at` = `lastUpdatedDate`; `election_name`/`election_date` from `electionDetails`.
  - **Turnout table:** one row per town: `county_id`, `county_name`, `registered_voters` (`tvr`), `ballots` (`tvc`), `absentee` (`tabs`), `districts_reporting` "`tdisr`/`tdis`".
  - **Checks, listed, nothing corrected:** town sums ≠ total entry per (contest, choice) including blank and over; offices with no or several total entries; per entry `sc` ≠ choices + `bv` + `sv`; a town's `sc` for Congress ≠ its turnout `tvc`; town ids not in `towns`; duplicate (contest, town, choice); non-integer counts; candidates in towns but not in the total entry and vice versa; turnout sums vs the statewide Congress `sc`.
  - Missing or unreadable files listed; checks needing them `None`.
- **Write-in names in the test fixture** (my call): the fixture cutter replaces every `isWriteIn` name with "WRITE-IN <cid>"; the reader itself keeps names as published (raw and parsed data are gitignored).
- **CLI** `fetch | parse | fetch-parse`, writing `<stamp>.csv` and `<stamp>-turnout.csv`.
- **Tests** on fixtures cut from the real files (Congress, Governor, one senate district with `vf` 2, one house district; four towns), synthetic variants per check.

## Left to the builder

Fixture towns, summary key names.

## Not done / later

- County and town offices.
- Unorganized gores (no results entries seen).
- Whether files change after the snapshot shown.
