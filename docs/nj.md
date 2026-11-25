# New Jersey: county Clarity sites (precinct level, live)

Seen 2026-11-24/25 in the built-in browser. Downloaded through `pipeline/fetch.py` (`pipeline/run_clarity.py`) on 2026-11-25: the eight XML counties at 00:21–00:23 Pacific (parsed with `parse_county_xml`), the seven JSON counties at 11:19 Pacific (parsed with `parse_county_json`), both in `pipeline/readers/clarity.py`. Designs: `docs/superpowers/specs/2026-11-25-step2-nj-clarity-counties-design.md` and `docs/superpowers/specs/2026-11-25-step2-nj-clarity-json-counties-design.md`. **All 15 Clarity counties at precinct level with each county's vote types where published, from the same files the counties' election-night pages use.**

## Where the data is

New Jersey's Division of Elections posts no results; `https://nj.gov/state/elections/election-night-results.shtml` links each county's site. 15 of 21 counties use Clarity at `https://results.enr.clarityelections.com/NJ/<County>/<election id>/`. Every pass reads `current_ver.txt` first and builds the data URLs from that version. Source ids `clarity-NJ-<County>-2026-general` in `pipeline/sources_clarity.toml`. Election ids from the state page, except Passaic and Somerset (from each county's Clarity election list).

- **Detail XML (8, format `county_xml`):** Atlantic 127487, Burlington 127582, Cape May 127585, Essex 127486, Hudson 127495, Mercer 127554, Ocean 127556, Union 127567. A pass reads `<version>/reports/detailxml.zip` (two requests).
- **JSON only (7, format `county_json`):** Cumberland 127562, Gloucester 127298, Middlesex 127580, Monmouth 127586, Morris 127576, Passaic 127401, Somerset 127569. `detailxml.zip` is 404. A pass reads `json/sum.json` (county totals), `json/ALL.json` (precinct totals plus a `-1` county area), `json/vt.json` (vote types and county totals per type), `json/status.json` (per precinct: status code, registered voters, ballots cast), then one precinct file per vote type, named as the site names it (whitespace and `/` become `_`: `Early_Voting.json`, Morris's `State_Fed.json`). 5 to 11 requests; the pass record `data/raw/<source id>/pass-<UTC>.json` lists the files, and `parse` takes it.
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

| Cumberland | 98,856 | 43 | 106 | (none in the JSON files) |
| Gloucester | 6,879 | 78 | 231 | |
| Middlesex | 86,495 | 65 | 649 | |
| Monmouth | 14,119 | 148 | 488 | |
| Morris | 61,523 | 106 | 400 | |
| Passaic | 9,260 | 51 | 283 | |
| Somerset | 6,781 | 61 | 267 | |

- **Clean (XML counties):** in every county each precinct sum equals its vote type and each choice's vote types sum to its total; nothing in the `*_not_checked` lists; every county has a turnout table.
- **Clean (JSON counties):** no mismatch anywhere: precinct sums against the county totals (`ALL.json` against `sum.json`, each vote-type file against `vt.json`), the `-1` area against the same, vote types against totals (county and precinct), and every area's published total against its votes (29,519 comparisons in Cumberland). Every precinct is in `status.json` and the reverse.
- **Not checked (JSON counties), privacy filter:** Middlesex (897 cells) and Morris (8,982) publish the string `protected` instead of a count; Middlesex in precinct totals (`ALL.json`, 133) and in each precinct vote-type file (191 each), Morris only in vote-type cells (`vt.json`: Provisional for every choice, 384, plus 5 others; precinct files, mostly Provisional, 8,405). Those rows have `votes` empty, are listed in `protected_cells`, and the sums they enter are in the `*_not_checked` lists. Not estimated. In Morris every precinct has a protected Provisional cell, so no precinct's vote types could be checked against its total (`precinct_vote_types_checked` 0).
- **No vote types (JSON counties):** Gloucester, Monmouth, Passaic and Somerset publish an empty type list: totals only, the vote-type checks are "not checked".
- **Partial (Morris):** four contests report fewer precincts than they have (U.S. Senate 398/400, House 7th 93/94, House 11th 305/306, Board of County Commissioners 398/400). The two units not counted as reported are `7TH CON STATE/FED` and `11TH CON STATE/FED`, the only units with status code `1`. Listed in `partial_contests`.
- **Listed:** Cape May has a results unit "2ND CON Removed Resident" that isn't in its turnout table.
- **Example (county rows, unofficial):** U.S. Senate, Atlantic: Booker 52,882, Murphy 38,951; Burlington: Booker 112,010, Murphy 54,964; Mercer: Booker 88,517, Murphy 26,347; Middlesex: Booker 166,910, Murphy 75,837; Morris: Booker 112,586, Murphy 85,483.

## Quirks

- **Contest names and keys are each county's own** (`United States Senate`, `US Senate`, `U.S. Senate`; keys like `0004` local to the file), so `contest_scope` is "local". No statewide aggregation yet: that needs a contest name map, and there is no official state total to check it against until certification.
- **Vote type names differ by county:** Election Day / Election Day ICP / Election Day Machines; Vote by Mail / Mail-In / Mail-in; Provisional / Provisionals; plus Emergency, Emergency Votes, Federal, Federal Votes, State/Federal, Overseas where used. Kept as published.
- **Contest-level counts:** Burlington, Essex and Mercer publish Overvotes and Undervotes per contest (rows with that choice name, vote type TOTAL); the other five publish `regVotersCounty`, 0 everywhere (counted, no rows).
- **Write-ins:** Burlington publishes every write-in name as a choice (U.S. Senate 121 choices), so it has most of the rows; Cumberland does too (Vineland Board of Education 117 choices). Many names are private individuals. The parsed data is not committed; the XML fixture is Atlantic's file, and the JSON fixtures (Cumberland, Morris, Middlesex, Gloucester, cut to one or two contests by `pipeline/make_clarity_json_fixture.py`) replace every choice after `Write-In` with `Write-in name <n>`.
- **JSON choice names and ids:** `choice_id` is `sum.json`'s `CHAggId`. Passaic and Somerset put the party in the name (`DEM Cory Booker`); kept as published. The JSON files have no question flag, so `contest_type` is empty there.
- Precinct `reporting_status` is the turnout table's `percentReporting` code (XML) or `status.json`'s `S` (JSON) as published: `4` on most precincts of these final files, `32` on 25 XML units (Cape May 1, Essex 3, Mercer 17, Union 4) and 50 JSON units (Cumberland 14, all its `Prov` units; Gloucester 2, Middlesex 31, Monmouth 3), `1` on 2 Morris units. Meaning unverified.
- **Units with 0 registered voters but ballots cast:** 73 XML turnout units (Burlington 44, Cape May 1, Essex 5, Mercer 17, Ocean 2, Union 4), including every `32` unit (e.g. a Mercer unit with 0 registered and 674 ballots), and 52 JSON units (Cumberland 14, Gloucester 2, Middlesex 31, Monmouth 3, Morris 2). Likely mail or provisional counting units, unverified; step 3's "votes never exceed registered voters" check will flag them. Cumberland's `sum.json` counts 92 precincts for county-wide contests while `ALL.json` has 106 units: the 14 `Prov` units aren't counted as precincts.
- **Join key:** contest keys repeat across counties with different meanings (Atlantic `0008` is a county office, Cape May `0008` a city council seat), and `county_id` is empty: key local contests on (`county_name` or `source_id`, `contest_id`, `choice_id`). Overvotes and Undervotes both have `choice_id` "": include `choice` in the key (as for DC's over/under votes).

## Not done

- The six non-Clarity counties.
- Statewide aggregation (contest name map) and a check against the state's certified results.
- Election-night behaviour: these files are from after the count; the live pages are the same platform, but mid-count snapshots haven't been seen. Whether the privacy filter also hides counts mid-count is unknown.
- **Size on election night (decision owed):** Burlington's write-ins make one parse 1.29M rows, about 2 GB of memory and a 441 MB CSV; polled every 2 minutes that's about 13 GB of output an hour for one county. Options: stream rows to the CSV, or parse only when `current_ver.txt` changes.
