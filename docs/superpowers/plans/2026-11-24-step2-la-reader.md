# Louisiana Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parish-level Louisiana results (total and early votes) for 21 federal, statewide, legislative and amendment races from the SOS blobs, with state rows, a per-race parish turnout table and every disagreement listed.

**Architecture:** A fetch pass reads the races and multi-parish votes blobs, then a parish file and an early-vote file per in-scope race; `pipeline/readers/la.py` emits state and parish rows. Same shape as the VT/IN readers.

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-la-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (301 before).
- Every download through `pipeline.fetch.fetch`, `ext="json"`, `min_interval_s = 120`, `request_gap_s = 10`.
- Choice keys are always (race, choice). Parish `county_id` = code as published; names from the config list.
- Nothing corrected; every anomaly listed; checks that couldn't run are `None`; malformed entries listed, not fatal. No Co-Authored-By trailers; don't touch `sources/`, `tools/`, `dnd_sim/`.

## Review Focus

1. A race's parish file unreadable → listed; that race's parish rows absent; the parish-sum checks `None` (lists are not per race); other races' rows emitted (test `test_unreadable_parish_file`).
2. A races file that isn't JSON with `Races.Race` → the fetch pass stops, no record (test `test_bad_races_file_stops_pass`).
3. Amendment choices `3`/`4` repeated across races → never merged (test on fixture: two amendments).
4. A parish code not in the config list → listed, row kept with `county_name` "" (test `test_unknown_parish_listed`).
5. Runoff outcomes → listed in `runoff_races` (test on fixture: House 5).

---

### Task 1: Sources and fetch pass
- [ ] Failing tests (`test_run_la.py`): sources complete (date "20261103", six office levels, 64 parishes "01".."64" with "01" Acadia and "64" Winn); URLs in order with a fake races body naming two in-scope races and one out-of-scope; record race ids; gap `[10]*5`; `test_bad_races_file_stops_pass`; failure stops the pass.
- [ ] Implement `pipeline/sources_la.toml`, `pipeline/run_la.py`; suite green; commit.

### Task 2: Fixtures and reader
- [ ] Real fetch; `pipeline/make_la_fixture.py PASS OUT_DIR --races 67997,70199,13833,13836 --parishes 05,17,36`.
- [ ] Failing tests (`test_la.py`), real values from the fixture: Senate state row Letlow (`124655`) 746466, `party "REP"`, `reporting_status "3722/3722 precincts, 64/64 absentee"`; a parish row with `county_id "17"`, `county_name "East Baton Rouge"`; EarlyVoting rows; amendments' `3`/`4` rows per race with `party ""`; `runoff_races` contains `70199`; turnout rows per (race, parish); plus the Review Focus tests and synthetic variants (parish sum mismatch, count mismatch, early > total, choice only in one file, non-integer, duplicate, malformed entry, missing file).
- [ ] Implement `pipeline/readers/la.py`; suite green; commit.

### Task 3: Parse CLI, real-file results, docs
- [ ] Parse tests; CLI as `run_in`; parse the real pass; `docs/la.md`; `CLAUDE.md`; commit.
