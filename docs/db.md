# Step 3: results database and checks

Design: `docs/superpowers/specs/2026-11-25-step3-checks-database-design.md`; plan:
`docs/superpowers/plans/2026-11-25-step3-checks-database.md`. Code: `pipeline/db.py` (schema, loader, CLI),
`pipeline/db_checks.py` (checks, reports), `pipeline/turnout_map.toml` (turnout layouts).

    /opt/homebrew/bin/python3 -m pipeline.db load    # adds new data/parsed CSVs to data/results.sqlite
    /opt/homebrew/bin/python3 -m pipeline.db check [--source ID]   # reports to data/reports/<UTC>/

Report only: the checks never block or change anything. Each check writes `<name>.csv` (exceptions) and
`<name>-not-checked.csv` (what couldn't be checked, and why).

## How it decides things

- **Snapshots:** a snapshot's time is when its content first appeared (per downloaded file, its earliest
  fetch in `data/raw/manifest.csv`; then the latest of those). Two parses with the same time are one
  snapshot; the newest parse wins. Only the latest two snapshots per source keep their rows (Steve,
  2026-11-25); older ones are marked pruned. Every raw download stays in `data/raw/`.
- **A parse missing a column** (written before the column existed) loads it as NULL, with a
  `columns_missing` note.
- **Check 1, never decrease:** latest snapshot against the one before; every lower count and every
  disappeared line. Key: ids where present, names where not, plus party and vote type.
- **Check 2, registered voters:** per turnout unit (layouts in `turnout_map.toml`): ballots > registered,
  and each contest's votes > registered × vote for. A choice counts its TOTAL rows, or the sum of its
  vote-type rows when it has no TOTAL (CO county rows have only "Total Votes", WV only "Election Day", the
  NJ XML precincts only their vote types). Blank, over and under votes count. Blank `vote_for` counts as 1
  and is listed. 0 registered voters: listed, not compared. HI adds each precinct's `VSC` unit; VT adds
  town parts.
- **Check 3, parts add up:** precinct → county and county (or town) → state (statewide contests), per
  contest, choice and vote type. Party is not in the key: readers spell it differently across levels
  (IN "D" vs "Democratic"), and party lines (CT, DC) are summed alike on both sides.

## 2026 run (2026-11-26 03:33 UTC, every parse in data/parsed)

Load: 47 snapshots from 47 sources in 58 s; 31 MB of memory; database 1.8 GB. Not loaded (noted): AZ and UT
(parsed from browser downloads made before the fetcher, so their hashes aren't in the manifest) and one
empty MD parse. The five other Enhanced Voting parses dated 2026-11-20 lacked `contest_scope`; they were
re-parsed from their saved raw files with the current reader before this run. Checks: 9 s.

**Check 1:** only MA and NC have two snapshots; 0 decreases, 0 disappeared lines. The other 45 sources:
not checked (one snapshot).

**Check 2:** 2,367 exceptions. Not checked: 16 sources without a turnout table (EV ×5, ResultsAjax ×5,
Tally ×2, FL, MA, NC, IA), DE (units don't meet), WY (no registered voters), 2 AL units.

| Source | Kind | Count | Explanation |
|---|---|---|---|
| AL | zero_registered | 947 | 31 counties publish 0 registered voters (`docs/al.md`) |
| AL | contest_over_registered | 25 | unexplained (AL columns can hold two districts, `docs/al.md`) |
| AL | ballots_over_registered | 1 | unexplained |
| AK | zero_registered | 120 | counting units publish 0 registered voters except HD99 (121 − 1, `docs/ak.md`) |
| NJ (11 counties) | zero_registered | 126 | units with ballots but 0 registered (`docs/nj.md`) |
| HI | contest_over_registered | 39 | e.g. OHA At-Large Trustee (several seats) with blank vote_for counted as 1: false alarms |
| HI | zero_registered | 14 | `OS I`, `OS II` (`docs/hi.md`); 12 real precincts (e.g. 01-04, 05-06…05-10) unexplained |
| AL CT DC HI OH TX | blank_vote_for | 1,094 | the readers publish no vote_for there |
| NJ Cape May | result_unit_without_turnout | 1 | unexplained |

**Check 3:** 1,267 exceptions, all precinct → county in Enhanced Voting states: WA 1,169, ID 55, GA 43.
Precinct sums are a few votes below the county row (e.g. WA contest 186554 choice 2 in county 11:
142,341 vs 142,361). Cause unknown; the EV reader checks only statewide vs county (clean). Not checked:
DE precinct rows have no county; NJ XML counties' and CO/SC/WV's TOTAL lines (no TOTAL at the lower level;
their vote-type lines are checked); 19,424 GA lines and the NJ privacy-filter lines with empty counts.

## Not done

AP cross-check; checks across sources; contest/county name maps; any use of `turnout_unit_without_results`
beyond listing it.
