# New Jersey: county Clarity sites (precinct level, live)

Seen 2026-11-24/25 in the built-in browser. Downloaded through `pipeline/fetch.py` (`pipeline/run_clarity.py`) on 2026-11-25 at 00:21–00:23 Pacific, then parsed with `parse_county_xml` in `pipeline/readers/clarity.py`. Design: `docs/superpowers/specs/2026-11-25-step2-nj-clarity-counties-design.md`. **Eight counties at precinct level with each county's vote types, from the same files the counties' election-night pages use.**

## Where the data is

New Jersey's Division of Elections posts no results; `https://nj.gov/state/elections/election-night-results.shtml` links each county's site. 15 of 21 counties use Clarity at `https://results.enr.clarityelections.com/NJ/<County>/<election id>/`. A pass per county reads `current_ver.txt`, then `<version>/reports/detailxml.zip` (two requests). Source ids `clarity-NJ-<County>-2026-general` in `pipeline/sources_clarity.toml`.

- **Read (8, publish detail XML):** Atlantic 127487, Burlington 127582, Cape May 127585, Essex 127486, Hudson 127495, Mercer 127554, Ocean 127556, Union 127567.
- **Not read yet (7, JSON only):** Cumberland 127562, Gloucester 127298, Middlesex 127580, Monmouth 127586, Morris 127576, Passaic 127401, Somerset 127569. `detailxml.zip` is 404; their pages load `json/sum.json`, `json/ALL.json` and one JSON file per vote type. Election ids from the state page, except Passaic and Somerset (from each county's Clarity election list).
- **Not Clarity (6):** Bergen, Camden, Hunterdon, Salem, Sussex, Warren run their own sites.

## Parsed (2026-11-25)

| County | Rows | Contests | Precincts | File timestamp |
|---|---|---|---|---|
| Atlantic | 13,785 | 65 | 145 | 11/19/2026 1:05 PM |
| Burlington | 1,288,232 | 135 | 445 | 11/18/2026 12:44 PM |
| Cape May | 20,598 | 38 | 129 | 11/17/2026 2:52 PM |
| Essex | 88,820 | 55 | 578 | 11/18/2026 9:13 AM |
| Hudson | 53,898 | 39 | 468 | 11/20/2026 1:51 PM |
| Mercer | 48,469 | 38 | 266 | 11/17/2026 3:29 PM |
| Ocean | 59,898 | 93 | 420 | 11/19/2026 11:05 AM |
| Union | 68,502 | 72 | 438 | 11/18/2026 8:35 PM |

- **Clean:** in every county each precinct sum equals its vote type and each choice's vote types sum to its total; nothing in the `*_not_checked` lists; every county has a turnout table.
- **Listed:** Cape May has a results unit "2ND CON Removed Resident" that isn't in its turnout table.
- **Example (county rows, unofficial):** U.S. Senate, Atlantic: Booker 52,882, Murphy 38,951; Burlington: Booker 112,010, Murphy 54,964; Mercer: Booker 88,517, Murphy 26,347.

## Quirks

- **Contest names and keys are each county's own** (`United States Senate`, `US Senate`, `U.S. Senate`; keys like `0004` local to the file), so `contest_scope` is "local". No statewide aggregation yet: that needs a contest name map, and there is no official state total to check it against until certification.
- **Vote type names differ by county:** Election Day / Election Day ICP / Election Day Machines; Vote by Mail / Mail-In / Mail-in; Provisional / Provisionals; plus Emergency, Emergency Votes, Federal, Federal Votes, State/Federal, Overseas where used. Kept as published.
- **Contest-level counts:** Burlington, Essex and Mercer publish Overvotes and Undervotes per contest (rows with that choice name, vote type TOTAL); the other five publish `regVotersCounty`, 0 everywhere (counted, no rows).
- **Write-ins:** Burlington publishes every write-in name as a choice (U.S. Senate 121 choices), so it has most of the rows; many names are private individuals. The parsed data is not committed; the test fixture is Atlantic's file.
- Precinct `reporting_status` is the turnout table's `percentReporting` code as published: `4` on most precincts of these final files, `32` on 25 (Cape May 1, Essex 3, Mercer 17, Union 4). Meaning unverified.
- **Units with 0 registered voters but ballots cast:** 73 turnout units (Burlington 44, Cape May 1, Essex 5, Mercer 17, Ocean 2, Union 4), including every `32` unit (e.g. a Mercer unit with 0 registered and 674 ballots). Likely mail or provisional counting units, unverified; step 3's "votes never exceed registered voters" check will flag them.
- **Join key:** contest keys repeat across counties with different meanings (Atlantic `0008` is a county office, Cape May `0008` a city council seat), and `county_id` is empty: key local contests on (`county_name` or `source_id`, `contest_id`, `choice_id`). Overvotes and Undervotes both have `choice_id` "": include `choice` in the key (as for DC's over/under votes).

## Not done

- The seven JSON-only Clarity counties and the six non-Clarity counties.
- Statewide aggregation (contest name map) and a check against the state's certified results.
- Election-night behaviour: these files are from after the count; the live pages are the same platform, but mid-count snapshots haven't been seen.
- **Size on election night (decision owed):** Burlington's write-ins make one parse 1.29M rows, about 2 GB of memory and a 441 MB CSV; polled every 2 minutes that's about 13 GB of output an hour for one county. Options: stream rows to the CSV, or parse only when `current_ver.txt` changes.
