# Vermont Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Town-part-level Vermont results for federal, statewide, state senate and state house offices from the SOS static JSON, with state/district totals, a town turnout table and every disagreement listed.

**Architecture:** A fetch pass reads the election file, then the four results files and the turnout file it names (one snapshot); `pipeline/readers/vt.py` emits town-part rows and total rows. Same shape as the CT reader.

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-vt-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (251 before).
- Every download through `pipeline.fetch.fetch`, `ext="json"`, `min_interval_s = 120`, `request_gap_s = 10`.
- Town rows `level "town"`, `county_id` = `tid`, `precinct_id` = "`repd`|`send`"; total rows `level "state"`; `contest_scope "statewide"`; `vote_type "TOTAL"`.
- Write-in names (`isWriteIn` true) are replaced by "WRITE-IN <cid>" in committed fixtures only.
- Nothing corrected; every anomaly listed; a check that could not run is `None`. No Co-Authored-By trailers; don't touch `sources/`, `tools/`, `dnd_sim/`.

## Review Focus

1. A split town (Burlington: 6 parts for Congress) → one row per part per choice, no duplicate entries listed (test `test_split_town_rows`).
2. The election file naming paths with different timestamps or outside `elections/` → the pass stops, no record (test `test_mixed_snapshot_stops_pass`).
3. A results file that is HTML or truncated → listed, its rows absent, its checks `None` (test `test_unreadable_results_file`).
4. Federal total entry reporting "0/0" with `townsReported` null → `reporting_status "0/0"` as published (test on fixture).
5. `vf` 3 senate district → `vote_for "3"`, and `sc` checked as vote slots, not ballots (test on fixture, CHI CT 1).

---

### Task 1: Sources and fetch pass

**Files:** Create `pipeline/sources_vt.toml`, `pipeline/run_vt.py`; Test `pipeline/tests/test_run_vt.py`.

- [ ] Failing tests: sources complete (`base_url "https://static.electionresults.vermont.gov/"`, `election_guid "68d61e96-1d28-4210-8c1d-8e90512ae105"`, `kinds ["federal","stateWide","senate","house","turnOut"]`, 120, 10); URLs in order (election file, then the five paths from a fake election file with backslashes → `/`); record `snapshot "20261117185828"`, kinds `election, federal, stateWide, senate, house, turnOut`; gap `[10]*5`; `test_mixed_snapshot_stops_pass`; failure stops the pass.
- [ ] Implement; suite green; commit `Add VT sources and fetch pass`.

### Task 2: Fixtures and reader

**Files:** Create `pipeline/make_vt_fixture.py`, `pipeline/readers/vt.py`, fixtures `pipeline/tests/fixtures/vt_*.json`, `vt_pass.json`; Test `pipeline/tests/test_vt.py`.

**Interfaces:** `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`; `TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters", "ballots", "absentee", "districts_reporting"]`.

- [ ] Real fetch. Cutter keeps offices: federal oid 4; statewide oid 5 (Governor); senate `dc` "CHI CT 1" (`vf` 3); house `dc` "CHI 20"; towns 16 Addison, 50 Burlington, 63 Colchester plus each office's `tid` 0 entry; turnout rows for those towns; election file whole except `towns`/`townDistricts` filtered to the towns; write-in names replaced.
- [ ] Failing tests, real values: Congress total row Balint (`225757`) 198758, `party "DEMOCRATIC"`, `reporting_status "0/0"`, `vote_for "1"`; Burlington Congress Balint rows: 6, votes {3712, 1231, 2311, 2660, 2025, 3263}, one with `precinct_id "CHITTENDEN-13|CHITTENDEN-SOUTHEAST_"`; Governor total Scott 162048 `REPUBLICAN`, Janoo `DEM/PROG`; Governor total "Blank Votes" 2131, "Overvotes" 324; senate CHI CT 1 `contest_id "12:CHI CT 1"`, `vote_for "3"`; house CHI 20 Colchester has two parts (`precinct_id` with `GRAND ISLE_` and `CHITTENDEN-CENTRAL_`); turnout Addison registered 1175, ballots 755, absentee 438; `source_created_at "11/17/2026 06:58 PM"`; summary `duplicate_entries == []`, `sc_mismatches == []`; no fixture name equals a real write-in name (assert every `isWriteIn` name starts with "WRITE-IN ").
- [ ] Failing synthetic tests: sum mismatch listed; total entry missing / repeated; `sc` mismatch; Congress `sc` vs turnout `tvc` per town; unknown town id; duplicate part; non-integer count; candidate in a town but not the total; unreadable results file; missing file.
- [ ] Implement; suite green; commit `Add VT reader with fixtures from the 2026 files`.

### Task 3: Parse CLI, real-file results, docs

- [ ] `test_parse_command`, `test_parse_prints_not_checked`; implement as `run_ct.parse_record`; suite green.
- [ ] Parse the real pass; `docs/vt.md` (URLs, snapshot, bytes, SHA-256, rows, offices, towns, lists, quirks: split towns, `sc` as vote slots, fusion party names, write-in names, reporting fields); `CLAUDE.md`; commit `Add VT parse CLI; record 2026 results`.
