# North Carolina Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precinct-level NC results (contest type S) with vote methods, in the common format, checked against the dashboard's statewide file.

**Architecture:** A fetch pass saves the precinct ZIP and the dashboard's `results_0.txt` through `pipeline/fetch.py` and writes a pass record; the reader emits precinct rows from the ZIP and state rows from the dashboard, and lists every difference between them.

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-23-step2-nc-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .`
- Every download through `pipeline.fetch.fetch`; `min_interval_s = 120`; `request_gap_s = 10`.
- Nothing corrected; every anomaly listed. No choice ids exist: join on (Contest Group ID, choice name as published).
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. Dashboard vs ZIP differences in both directions → listed per vote type (test `test_real_senate_mismatch_listed`).
2. A dashboard row with no ZIP match, a type-S ZIP contest missing from the dashboard → listed (test `test_orphans_listed`).
3. A NUL or other control character in a choice name → listed, row kept (test `test_control_characters_listed`).
4. Methods not summing to Total, non-integer counts, wrong field count, unexpected header → listed, not fatal (tests `test_bad_rows_listed`, `test_unexpected_header_listed`).
5. A ZIP without the expected member, an unreadable dashboard → listed, not fatal, and the check reported "not checked" (tests `test_missing_member_listed`, `test_unreadable_dashboard_not_checked`).

---

### Task 1: Sources and fetch pass

**Files:** Create `pipeline/sources_nc.toml` (`nc-2026-general`), `pipeline/run_nc.py` (`load_sources`, `fetch_pass`, `main` with `fetch`); Test `pipeline/tests/test_run_nc.py`.

- [ ] Failing tests: `test_sources_complete`; `test_pass_urls_in_order` (zip URL, then dashboard URL; record kinds `zip`, `dashboard`); `test_gap_between_requests` (`[10]`); `test_failure_stops_pass`. Run (fail), implement, suite green, commit `Add NC sources and fetch pass`.

### Task 2: Real fetch, fixtures, reader

**Files:** Create `pipeline/readers/nc.py` (`parse_pass(record_path, base_dir=".") -> (rows, summary)`), `pipeline/make_nc_fixture.py`, fixtures `pipeline/tests/fixtures/nc_*`; Test `pipeline/tests/test_nc.py`.

- [ ] Real fetch; cut fixtures: ZIP to contest groups 1383 (US Senate) and 1369 (US House 1) in 3 counties, same member name; dashboard to those two contests, real values.
- [ ] Failing tests: real values (a precinct row's five vote types for Cooper; `precinct_is_virtual` "Y" for an administrative precinct; state rows with the dashboard's five values); `test_real_senate_mismatch_listed` (fixture ZIP holds 3 counties, so the cut dashboard's statewide values differ: assert the list has an entry per (contest, choice, vote type) where they differ, with dashboard and ZIP-sum values); a variant with dashboard values set to the fixture's ZIP sums → empty mismatch list; the Review Focus tests; every row's keys == `COLUMNS`.
- [ ] Run (fail), implement, suite green, commit `Add NC reader with fixtures from the 2026 files`.

### Task 3: Parse CLI, real-file results, docs

**Files:** Modify `pipeline/run_nc.py` (`parse`, `fetch-parse`), `CLAUDE.md`; Create `docs/nc.md`; Test `test_parse_command`.

- [ ] Failing parse-command test; implement (summary printing as in `run_tally`, "not checked" for None); suite green.
- [ ] Parse the real pass; record rows, contests, precincts, the full mismatch count and examples in `docs/nc.md` with the quirks from the spec.
- [ ] Update `CLAUDE.md`; commit `Add NC parse CLI; record 2026 results`.
