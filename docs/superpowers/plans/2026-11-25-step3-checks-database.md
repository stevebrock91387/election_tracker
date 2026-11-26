# Step 3: checks on a results database — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load every reader's parsed CSVs into one SQLite file and run three report-only checks on it.

**Architecture:** `pipeline/db.py` owns the schema, the loader (snapshot identity, re-parse
replacement, retention of the latest two snapshots) and the CLI. `pipeline/turnout_map.toml` says how
each turnout layout joins to results. `pipeline/db_checks.py` holds the three checks as SQL (composed
per layout where key columns differ) and writes one report CSV per check.

**Tech Stack:** Python 3 stdlib (`sqlite3`, `csv`, `tomllib`), unittest.

**Spec:** `docs/superpowers/specs/2026-11-25-step3-checks-database-design.md`

## Global Constraints

- stdlib only; runs under `/opt/homebrew/bin/python3` and `.venv/bin/python`.
- Database `data/results.sqlite`; reports `data/reports/<UTC>/`. Nothing under a directory named `checks/` (gitignored).
- Values are stored exactly as the reader's CSV has them; `votes` "" → NULL, digits → INTEGER. Nothing corrected.
- Checks report only: never block, never edit. A check that can't run for a source is a `not_checked` entry with a reason, never an empty clean list.
- Retention: result and turnout rows for the latest two snapshots per source; older snapshot rows kept, `pruned = 1`.
- Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .`

## Review Focus

- Loading the same CSV twice, or two parses of one snapshot: one snapshot, newest parse's rows, a `load_note`.
- A CSV whose hash isn't in the manifest: not loaded, noted, no crash.
- A snapshot older than both kept ones arriving late: not loaded, noted; the kept two unchanged.
- An empty `votes` cell on either side of a comparison: `not_checked` / skipped, never a mismatch or decrease.
- A turnout CSV whose header matches no layout: loaded with `raw` only, noted; check 2 "not checked" for that source.

---

### Task 1: Schema and result loading

**Files:** Create `pipeline/db.py`; Test `pipeline/tests/test_db_load.py`.

**Interfaces — Produces:**
- `connect(path: str) -> sqlite3.Connection` (creates tables `snapshot`, `result`, `turnout`, `load_note` if absent; `PRAGMA journal_mode=WAL`).
- `load(conn, parsed_dir="data/parsed", manifest="data/raw/manifest.csv", turnout_map=None) -> dict` with keys `loaded`, `skipped_known`, `replaced`, `not_loaded` (lists of CSV paths).
- `snapshot` columns: `snapshot_id INTEGER PRIMARY KEY`, `source_id`, `state`, `first_seen_utc`, `csv_path`, `csv_sha256`, `turnout_path`, `loaded_utc`, `pruned INTEGER DEFAULT 0`; unique (`source_id`, `first_seen_utc`).
- `result`: `snapshot_id` + every column of `pipeline.schema.COLUMNS`; `votes INTEGER` (NULL for "").
- `load_note`: `csv_path`, `kind`, `detail`. Kinds: `hash_not_in_manifest`, `replaced_parse`, `older_than_kept`, `turnout_layout_unknown`, `turnout_columns_unknown`.

Snapshot time: for each distinct `source_sha256` in the CSV, its earliest `fetched_utc` in the manifest; `first_seen_utc` = the latest of those. A CSV is "known" when its `csv_sha256` is already a snapshot's. Same (`source_id`, `first_seen_utc`) as a loaded snapshot: replace its rows only if this CSV's file name stamp is newer, else skip. Parsed files are `data/parsed/<source_id>/<YYYYMMDDTHHMMSSZ>.csv`; `-turnout.csv` files are found next to their CSV, not loaded as results.

Tests build tiny CSVs (header `COLUMNS`) and a manifest in a temp dir with a helper `write_parse(dir, source_id, stamp, rows)`.

- [ ] **Step 1: Write failing tests**
  - `test_load_one_csv`: one CSV of 3 rows, hash in manifest at `2026-11-24T15:02:22Z` → 1 snapshot, `first_seen_utc == "2026-11-24T15:02:22Z"`, 3 result rows, a "" vote stored as NULL, "12" as 12.
  - `test_same_csv_twice_is_skipped`: second `load` → `skipped_known == [path]`, still 3 rows.
  - `test_newer_parse_of_same_snapshot_replaces`: two CSVs, same hashes, stamps `…T010000Z` and `…T020000Z`, different vote → 1 snapshot, the `020000` values, a `replaced_parse` note.
  - `test_unchanged_file_keeps_first_fetch_time`: hashes A (fetched 11-24 and 11-26) + B (11-24) in CSV 1; A + C (11-26) in CSV 2 → two snapshots, times 11-24 and 11-26.
  - `test_hash_not_in_manifest`: not loaded, `hash_not_in_manifest` note, no exception.
  - `test_retention_keeps_latest_two`: three snapshots → rows only for the latest two; oldest `pruned == 1`.
  - `test_late_older_snapshot_not_loaded`: load snapshots 2 and 3, then 1 → 1 not loaded, `older_than_kept` note.
- [ ] **Step 2:** Run `.venv/bin/python -m unittest pipeline.tests.test_db_load` → FAIL (no module).
- [ ] **Step 3:** Implement in `pipeline/db.py`. Insert with `executemany` in one transaction per CSV; index `result(snapshot_id, level, contest_id)`.
- [ ] **Step 4:** Run → PASS; full suite → OK.
- [ ] **Step 5:** Commit `Step 3: results database schema and loader (snapshot identity, re-parses, latest-two retention)`.

### Task 2: Turnout map and turnout loading

**Files:** Create `pipeline/turnout_map.toml`; Modify `pipeline/db.py`; Test `pipeline/tests/test_db_load.py`.

**Interfaces — Produces:** `load_turnout_map(path) -> dict[name, layout]`; `layout_for(map, source_id, header) -> (name, layout) | None` (first layout whose any `prefixes` entry starts `source_id` and whose `header` equals the CSV header). `turnout` table: `snapshot_id`, `layout`, `county_id`, `county_name`, `precinct_id`, `precinct_name`, `contest_id` (copied when the CSV has the column, else NULL), `registered_voters INTEGER`, `ballots_cast INTEGER`, `raw TEXT` (JSON of the row).

Layout fields: `prefixes`, `header`, `result_level`, `key` (column names present in both result rows and turnout rows), optional `strip_suffix` (`{column = suffix}`, applied to both sides before grouping), `registered` (column or absent), `ballots` (column or absent), `total_vote_type` (default `"TOTAL"`), optional `not_joinable` (reason). Entries (key / registered / ballots):

| name | prefixes | level | key | registered | ballots | other |
|---|---|---|---|---|---|---|
| ak | ak- | precinct | precinct_id | registered_voters | ballots | |
| al | al- | precinct | county_id, precinct_id | registered_voters | ballots_cast | |
| clarity_state | clarity- | county | county_name | registered_voters | ballots_cast | WV: separate entry `clarity_wv` (prefix `clarity-WV-`, listed first) with `total_vote_type = "Election Day"` |
| clarity_county | clarity-NJ- | precinct | precinct_name | registered_voters | ballots_cast | |
| ct | ct- | town | county_id | registered_voters | ballots | |
| dc | dc- | precinct | precinct_id | registered_voters | ballots_cast | |
| de | de- | — | — | — | — | `not_joinable = "turnout per representative district, results per election district"` |
| hi | hi- | precinct | precinct_name | registered_voters | ballots | `strip_suffix = {precinct_name = " VSC"}` |
| in | in- | county | county_id | registered_voters | voters_voting | |
| la | la- | county | county_id, contest_id | voters_qualified | voters_voted | |
| oh | oh- | county | county_id | registered_voters | ballots_cast | |
| tx | tx- | county | county_id | registered_voters | (none) | comment: `voters` meaning unknown (docs/tx.md) |
| vt | vt- | town | county_id | registered_voters | ballots | town parts group by `county_id` |
| wy | wy- | precinct | county_id, precinct_id | (none) | ballots_cast | |

`header` for each is the exact `TURNOUT_COLUMNS` (or `COUNTY_TURNOUT_COLUMNS`) list of its reader.

- [ ] **Step 1: Write failing tests**
  - `test_map_covers_every_reader_layout`: every `TURNOUT_COLUMNS` / `COUNTY_TURNOUT_COLUMNS` in `pipeline/readers/*.py` equals some entry's `header`.
  - `test_turnout_loaded_with_mapped_columns`: an HI-layout turnout CSV next to its results CSV → `turnout` rows with `registered_voters`, `ballots_cast` filled, `raw` parses as JSON equal to the CSV row.
  - `test_unknown_turnout_header`: raw only, `turnout_layout_unknown` note.
  - `test_wv_layout_chosen_before_clarity_state`: `layout_for(map, "clarity-WV-2026-general", <statewide header>)[0] == "clarity_wv"`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS; suite OK.
- [ ] **Step 5:** Commit `Step 3: turnout map (14 readers) and turnout loading`.

### Task 3: Check 1, never decrease

**Files:** Create `pipeline/db_checks.py`; Test `pipeline/tests/test_db_checks.py`.

**Interfaces — Produces:** every check is `check_<name>(conn, source_id=None) -> (exceptions: list[dict], not_checked: list[dict])`; a `not_checked` dict has `source_id`, `scope`, `reason`. `CHECKS = {"decreases": check_decreases, ...}` in order 1, 2, 3.

Key (spec): `level`; `COALESCE(NULLIF(county_id,''), county_name)`; `COALESCE(NULLIF(precinct_id,''), precinct_name)`; `contest_id`; `COALESCE(NULLIF(choice_id,''), choice)`; `party`; `vote_type`. Compare the latest unpruned snapshot with the one before it. Exception dict: the key fields, `old_votes`, `new_votes`, `kind` (`"decrease"` or `"disappeared"`), both `snapshot_id`s.

- [ ] **Step 1: Write failing tests** (load via Task 1 helpers)
  - `test_decrease_listed`: 100 → 99 → one `decrease`, `old_votes 100`, `new_votes 99`.
  - `test_increase_not_listed`.
  - `test_disappeared_row_listed`.
  - `test_null_on_either_side_skipped`: 100 → NULL and NULL → 5 → no exception.
  - `test_one_snapshot_not_checked`: `not_checked == [{"source_id": s, "scope": "source", "reason": "one snapshot"}]`.
- [ ] **Step 2–4:** FAIL, implement, PASS; suite OK.
- [ ] **Step 5:** Commit `Step 3: check 1, totals never decrease`.

### Task 4: Check 3, parts add up

**Files:** Modify `pipeline/db_checks.py`; Test `pipeline/tests/test_db_checks.py`.

Pairs: precinct → county (precinct rows grouped by county key) and county or town → state, on the latest snapshot of each source. Contest key: `contest_id` when `contest_scope = "statewide"`, (`county_name`, `contest_id`) when `"local"`; plus choice (id else name), `party`, `vote_type`. Exception: key, `part_sum`, `whole`, `pair`. A sum with any NULL part, or a NULL whole → `not_checked` with scope `"line"`. A source lacking either level of a pair → `not_checked` scope `"pair"`, reason `"no <level> rows"`. Precinct rows whose county key is empty → pair not checked, reason `"precinct rows have no county"`.

- [ ] **Step 1: Write failing tests**
  - `test_county_sum_mismatch_listed`: counties 10 + 20, state 31 → one exception, `part_sum 30`, `whole 31`.
  - `test_clean_sum_no_exception`.
  - `test_null_part_not_checked`.
  - `test_missing_state_level_not_checked`.
  - `test_party_lines_kept_apart`: same choice id, parties D and WF, each summing correctly → no exception.
  - `test_local_contest_joins_within_county`: two counties both with contest id `1` (local) → precinct sums checked per county.
- [ ] **Step 2–5:** FAIL, implement, PASS, commit `Step 3: check 3, parts add up`.

### Task 5: Check 2, not over registered voters

**Files:** Modify `pipeline/db_checks.py`; Test `pipeline/tests/test_db_checks.py`.

**Interfaces — Consumes:** `load_turnout_map`, `layout_for` (Task 2). `check_registered(conn, source_id=None, turnout_map=None)`.

For each source's latest snapshot: find its layout from the stored `turnout.layout`; `not_joinable`, no turnout rows or no layout → `not_checked` (reason). Group turnout and `result` rows (level = `result_level`, `vote_type` = `total_vote_type`) by `key` after `strip_suffix`, summing. Units with registered 0 → exception kind `"zero_registered"` (listed apart, not compared). Exceptions: `"ballots_over_registered"` (ballots > registered; only when the layout has `ballots`), `"contest_over_registered"` (sum of the contest's rows > registered × vote_for; blank `vote_for` → 1 and a `"blank_vote_for"` entry once per contest), `"result_unit_without_turnout"`, `"turnout_unit_without_results"`. No `registered` column → whole source `not_checked`, reason `"no registered voters"`.

- [ ] **Step 1: Write failing tests**
  - `test_ballots_over_registered`: registered 100, ballots 101.
  - `test_contest_over_registered_uses_vote_for`: registered 100, vote_for 2, choices 120 + 70 = 190 → none; 120 + 90 = 210 → one.
  - `test_zero_registered_listed_not_compared`.
  - `test_hi_vsc_units_rolled_up`: plain `01-01` (reg 100, ballots 40, votes 40) + `01-01 VSC` (reg 0, ballots 30, votes 30) → one unit, no exception, no `zero_registered`.
  - `test_vt_town_parts_summed`: two parts of town 5 (votes 60 + 50), registered 100, vote_for 1 → one `contest_over_registered` with sum 110.
  - `test_de_not_joinable` and `test_wy_no_registered_not_checked`.
  - `test_wv_uses_election_day_total`.
- [ ] **Step 2–5:** FAIL, implement, PASS, commit `Step 3: check 2, not over registered voters`.

### Task 6: CLI, reports, real run, docs

**Files:** Modify `pipeline/db.py` (CLI), `pipeline/db_checks.py` (`run_checks`); Create `docs/db.md`; Modify `CLAUDE.md`; Test `pipeline/tests/test_db_checks.py`.

**Interfaces — Produces:** `run_checks(conn, out_dir, source_id=None) -> dict[name, (n_exceptions, n_not_checked)]`, writing `<out_dir>/<name>.csv` and `<out_dir>/<name>-not-checked.csv` for every check (header even when empty). CLI: `python3 -m pipeline.db load [--db PATH] [--parsed-dir DIR] [--manifest PATH]` and `python3 -m pipeline.db check [--db PATH] [--source ID] [--reports-dir data/reports]`; `check` prints each check's counts and `not checked` entries.

- [ ] **Step 1:** Failing test `test_run_checks_writes_every_report`: 6 files, headers present, counts returned.
- [ ] **Step 2–4:** FAIL, implement, PASS; suite OK.
- [ ] **Step 5:** Real run: `/opt/homebrew/bin/python3 -m pipeline.db load` then `check`. Record load time, DB size, and per-check counts per source in `docs/db.md`; explain the largest exception groups from the readers' docs where they already explain them (AL split districts, MA reader fix between snapshots), mark the rest unexplained. Update CLAUDE.md (step 3 section, test count).
- [ ] **Step 6:** Commit `Step 3: CLI, reports, 2026 run and docs`.
