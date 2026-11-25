# NJ Clarity JSON counties Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the seven JSON-only NJ Clarity counties at precinct level with vote types.

**Architecture:** `run_clarity.fetch_pass` gains a `county_json` branch that writes a pass record;
`pipeline/readers/clarity.py` gains `parse_county_json(record_path, base_dir)`; `parse_files` dispatches.

**Tech Stack:** Python 3 stdlib, unittest.

**Spec:** `docs/superpowers/specs/2026-11-25-step2-nj-clarity-json-counties-design.md`

## Global Constraints

- stdlib only; fetch only through `pipeline/fetch.py` (project UA, 120 s per source id).
- Nothing corrected; unrunnable check → `None`; uncomparable value → `*_not_checked`; malformed → listed.
- Committed fixtures carry no write-in names of private individuals.
- Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .`

## Review Focus

- A `"protected"` cell (string) anywhere: votes "", listed, comparisons not_checked, no crash.
- A county with no vote types (`Types` []): no type files fetched, vote-type checks `None`.
- A type name with `/` or spaces: file name `State_Fed.json`.
- An area whose `C`, `V`, `T` lengths differ, or a contest vote array of the wrong length: skipped, listed.
- A missing or unreadable file in the pass record: listed in `unreadable`, its checks `None`, no crash.

---

### Task 1: Fetch pass for `county_json`

**Files:** Modify `pipeline/run_clarity.py`, `pipeline/sources_clarity.toml`; Test `pipeline/tests/test_run_clarity.py`.

**Interfaces:** Produces `fetch_pass(...)` returning, for county_json, `{"version", "record"}` where the
record JSON is `{"source_id","state","county","version","started_utc","files":[{"kind","vote_type","path"}]}`,
kinds `sum`, `all`, `vt`, `status`, `type`. `type_file_name(name) -> str`.

- [ ] Tests: order of URLs (ver, sum, ALL, vt, status, then each type file); `type_file_name("State/Fed") == "State_Fed.json"`,
  `"Early Voting"` → `Early_Voting.json`; empty Types → no type requests; a vt.json that isn't JSON or lacks
  `Types` stops the pass (FetchError); config has 7 `county_json` entries (total 19).
- [ ] Implement; run; commit.

### Task 2: Real 2026 fetch and fixtures

- [ ] Fetch all seven counties through the runner.
- [ ] `pipeline/tests/make_clarity_json_fixture.py`: trims a pass to the given contest keys and areas
  (keeps `-1`, recomputed? no: `-1` kept as published only when every precinct is kept; otherwise the
  fixture keeps the real `-1` and the tests expect the resulting mismatch), and replaces choice names
  after `Write-In` with `Write-in name N`. Fixtures: Cumberland (contests 1, 5) and Morris (0004 and a
  contest with protected cells).
- [ ] Commit fixtures.

### Task 3: `parse_county_json`

**Files:** Modify `pipeline/readers/clarity.py`; Test `pipeline/tests/test_clarity_county_json.py`.

**Interfaces:** `parse_county_json(record_path, base_dir=".") -> (rows, summary, turnout)`; turnout in
`COUNTY_TURNOUT_COLUMNS`.

- [ ] Tests on the fixtures: row counts per level and vote type; a known county TOTAL and a known
  precinct value; every check list clean on Cumberland; Morris protected cells listed with votes "" and
  their comparisons in `*_not_checked`; synthetic cases from the Review Focus; determinism.
- [ ] Implement; run; commit.

### Task 4: CLI parse, real parse, docs

- [ ] `parse_files` and `main` accept a pass record for `county_json`; test via `main([...])`.
- [ ] Parse all seven real passes; record results in `docs/nj.md` and `CLAUDE.md`; commit.
