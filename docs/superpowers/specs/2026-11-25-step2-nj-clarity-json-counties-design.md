# Step 2: New Jersey Clarity JSON counties (design)

Date: 2026-11-25. Steve: "Go ahead" (build the reader for the seven JSON-only Clarity counties), under
the standing approval for the remaining state readers (2026-11-24). Follows
`2026-11-25-step2-nj-clarity-counties-design.md` (the eight detail-XML counties).

## Intent

Read the seven New Jersey Clarity counties that publish no `reports/detailxml.zip` (Cumberland 127562,
Gloucester 127298, Middlesex 127580, Monmouth 127586, Morris 127576, Passaic 127401, Somerset 127569)
at precinct level, with vote types where the county publishes them, live as counts come in.

## Source (seen 2026-11-25 in the built-in browser; the county results pages load these files)

Under `<base>/<version>/json/` (version from `<base>/current_ver.txt`):

- `sum.json`: county totals per contest (`K` key, `C` name, `VF`, `TP`/`PR` precincts total/reported,
  `CH` choices, `CHAggId` choice ids, `P` parties, `V` votes, `IsRCV`), plus `VPCFE` (meaning unknown).
- `ALL.json`: one area per precinct plus `-1` (the county total): `A` name, `C` contest keys, `V` one
  vote array per contest in `sum.json`'s choice order, `T` one total per contest. Same layout as Iowa's
  `ALL.json`, whose areas are counties.
- `vt.json`: `Types` (vote type names) and, per contest, `Votes` (per choice, one value per type) and
  `T` (per type). Empty `Types` in Gloucester, Monmouth, Passaic and Somerset (no vote types published).
- One precinct file per vote type, laid out like `ALL.json` (with `-1`). File name: the type with
  whitespace and `/` replaced by `_` (the site's own rule, from its JavaScript): `Early_Voting.json`,
  `Vote-by-Mail.json`, `State_Fed.json` (Morris "State/Fed").
- `status.json`: parallel arrays per precinct: `P` name, `S` status code (4 and 32 in 2026, as in the XML
  counties' percentReporting; Morris also 1), `R` registered voters, `B` ballots cast.
- **Privacy filter:** Middlesex and Morris publish the string `"protected"` instead of a number in some
  cells (vote-type files and `vt.json`; 897 and 8,593 cells in 2026). Totals in `ALL.json`/`sum.json`
  are numbers except in Middlesex's `ALL.json`.
- Write-in names (private individuals, e.g. Cumberland's US Senate has 13) are published as choices.

2026 (browser survey): every comparable cell agrees (precinct sums vs county, `-1` vs county, vote types
vs totals, area `T` vs its votes); the only gaps are protected cells. Morris has 4 contests with
`PR` < `TP`.

## Approaches

1. **New `parse_county_json` in the Clarity reader, a pass record for the variable file list (chosen).**
   Config `format = "county_json"`; the runner fetches the version, `sum.json`, `ALL.json`, `vt.json`,
   `status.json`, then one file per type named in `vt.json`, and writes a pass record (as the HI/MA
   readers do) that `parse` reads. 5–11 requests per pass.
2. Fetch only `sum.json` + `ALL.json` with the Iowa parser. Rejected: loses vote types and precinct
   status, and Iowa's parser labels areas as counties.
3. Wait for certified results. Rejected: Steve wants results as they come in.

## Design

- **Config:** seven entries `clarity-NJ-<County>-2026-general`, `state = "NJ"`, `county`, `base`,
  `format = "county_json"`, `min_interval_s = 120`.
- **Fetch:** source ids `<id>-ver`, `<id>-sum`, `<id>-all`, `<id>-vt`, `<id>-status`, `<id>-type-<file
  stem>`. Any failure stops the pass (as for every reader). Pass record
  `<raw>/<id>/pass-<UTC>.json`: source id, state, county, version, files (kind, vote type, path).
- **Rows** (`contest_scope` "local", `county_name` the config county, `contest_type` "" (no question
  flag in these files), `choice_id` = `CHAggId`):
  - county rows: TOTAL from `sum.json`, one per vote type from `vt.json`; `reporting_status`
    "<PR>/<TP> precincts";
  - precinct rows: TOTAL from `ALL.json`, one per vote type from that type's file; `precinct_id` =
    `precinct_name` = the area name; `reporting_status` the `status.json` code as published.
  - A `"protected"` cell gives `votes` "" and is listed; any other non-integer too (`non_numeric`).
- **Turnout:** one row per `status.json` precinct (COUNTY_TURNOUT_COLUMNS: registered voters, ballots
  cast, status code). No county line (the files publish none).
- **Summary** (nothing corrected; a check that couldn't run is `None`; a comparison a protected or
  non-numeric cell prevents goes to a `*_not_checked` list, never a mismatch):
  - `mismatches_precincts_vs_county` (per file kind: ALL vs `sum.json`, type file vs `vt.json`);
  - `mismatches_total_area_vs_county` (the `-1` area against the same county values);
  - `mismatches_vote_types_vs_total` at county level (`vt.json` row vs `sum.json`) and precinct level
    (type files vs `ALL.json`);
  - `mismatches_area_totals` (an area's `T` vs the sum of its votes);
  - `protected_cells`, `non_numeric`, `skipped_contest_length_mismatch`, `skipped_length_mismatch`
    (area vote array length ≠ choices), `skipped_areas` (C/V/T lengths differ), `contests_only_in_areas`,
    `duplicate_areas`, `precincts_not_in_status`, `status_precincts_without_results`,
    `rcv_contests` (listed; first-choice counts kept as published), `partial_contests` (`PR` < `TP`,
    informational).
  - `vote_types` as published; `vpcfe` value as published.

## Not done

- The six non-Clarity counties; statewide aggregation and the contest name map (as for the XML counties).
- Fixture: Cumberland and Morris files trimmed to a few contests and precincts, write-in names replaced.
