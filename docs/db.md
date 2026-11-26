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
  `columns_missing` note. A CSV that can't be read to the end (e.g. still being written) is noted
  `unreadable` and tried again next load; a CSV rewritten under the same name replaces what was loaded from
  it; a turnout table that appears or changes later is loaded then.
- **Coverage:** every check lists sources that were never loaded, a requested source with no snapshot,
  and a pair or source where nothing was compared; `snapshots.csv` in each report gives every snapshot's
  time.
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

## 2026 run (2026-11-26 03:45 UTC, every parse in data/parsed)

Load: 48 snapshots from 47 sources in 64 s; database 1.8 GB. Before this run, the five Enhanced Voting
parses dated 2026-11-20 (no `contest_scope` column) and Maryland's parse (no `source_sha256`, written by an
older reader version) were re-parsed from their saved raw files with the current readers. Not loaded, and
reported as "not loaded" by every check: AZ and UT (parsed from browser downloads made before the fetcher,
so their hashes aren't in the manifest). Checks: about 9 s.

**Check 1:** only NC has two snapshots (its dashboard changed between the 11-24 and 11-26 downloads);
0 decreases, 0 disappeared lines. MA's second download had identical content, so it is the same snapshot.
The other 46 sources: not checked (one snapshot).

**Check 2:** 2,367 exceptions. Not checked: 17 sources without a turnout table (EV ×5, ResultsAjax ×5,
Tally ×2, FL, MA, MD, NC, IA), DE (units don't meet), WY (no registered voters), 2 AL units.

| Source | Kind | Count | Explanation |
|---|---|---|---|
| AL | zero_registered | 947 | 808 in the 32 counties whose every turnout unit shows 0 (`docs/al.md` counts 31 counties publishing 0); 139 elsewhere, unexplained |
| AL | contest_over_registered | 25 | unexplained (AL columns can hold two districts, `docs/al.md`) |
| AL | ballots_over_registered | 1 | unexplained |
| AK | zero_registered | 120 | counting units publish 0 registered voters except HD99 (121 − 1, `docs/ak.md`) |
| NJ (11 counties) | zero_registered | 126 | units with ballots but 0 registered (`docs/nj.md`) |
| HI | contest_over_registered | 39 | 23 in OHA At-Large Trustee (several seats; blank vote_for counted as 1: false alarms); 16 in Councilmember (contest 10), multi-seat not verified |
| HI | zero_registered | 14 | `OS I`, `OS II` (`docs/hi.md`); 12 real precincts (e.g. 01-04, 05-06…05-10) unexplained |
| AL CT DC HI OH TX | blank_vote_for | 1,094 | the readers publish no vote_for there |
| NJ Cape May | result_unit_without_turnout | 1 | unexplained |

**Check 3:** 1,267 exceptions, all precinct → county in Enhanced Voting states. Causes unknown; the EV
reader checks only statewide vs county (clean).
- WA 1,169: 286 are King County lines whose precinct rows sum to 0 against county totals up to 648,386
  (King has 226,710 precinct rows); 6 more zero sums in Whitman and Columbia; the other 877 differ by a
  median of 5 votes (largest 1,320).
- GA 43 and ID 55: differences of at most 3 and 4 votes.

Not compared:
- No county rows, so neither pair runs: AK, AL, DC, HI, MA, NC (precinct and state only).
- No precinct or no state rows: FL, MT, OR (county only); 18 sources have no state rows.
- DE: precinct rows have no county (precinct pair: nothing compared); 377 of its county → state lines
  have no county counterpart.
- LA: 71 lines with no state row.
- TOTAL lines of the NJ XML counties and CO/SC/WV (no TOTAL at the lower level; their vote-type lines are
  compared).
- 19,424 GA lines and the NJ privacy-filter lines with empty counts.
- Precinct → state (for sources with no county rows) isn't a pair the design defines.

## Limits (from the final review)

- Check 1 compares only the latest two snapshots. If one load brings in two or more new snapshots of a
  source, the older ones are never the newer side of a comparison (noted as `pruned_unchecked`); run
  `check` after every `load`.
- A source that reverts to content it published before maps to that earlier snapshot's time, so check 1
  doesn't see the reversion (open: Steve's call).
- `check` reads without a transaction; don't run it while a `load` is running.

## Not done

AP cross-check; checks across sources; contest/county name maps; any use of `turnout_unit_without_results`
beyond listing it.
