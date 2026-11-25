# Step 2 Alabama reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parse Alabama's certified 2026 precinct ZIP (67 county `.xls`) into the common schema.

**Architecture:** `read_workbook` (xlrd → grid) + `parse_county` (grid → rows, turnout, findings) + `parse_pass` (ZIP → all counties, summary). Runner and sources follow the AK pattern.

**Tech Stack:** Python 3.14, stdlib + xlrd 2.0.2 (hash-pinned, `.venv`).

**Spec:** `docs/superpowers/specs/2026-11-24-step2-al-reader-design.md`

## Global Constraints

- xlrd only in `pipeline/readers/al.py`, imported inside `read_workbook`; no other new dependency.
- Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .`; AL tests skip without xlrd.
- Nothing corrected; anomalies listed; a check that couldn't run is `None`.
- ZIP members read in memory, never extracted; members > 50 MB uncompressed refused.

## Review Focus

- A county whose header rows (registered/ballots) are missing or reordered: balance check must list it, not use another row.
- A header column that is blank or repeats: units must not merge silently.
- A ZIP that is HTML (blocked/error page) or holds no `.xls`: unreadable, all checks `None`.
- A contest block partially empty for one unit: listed, rows for the numeric lines still emitted.
- PROVIDENCE-named precincts must not be flagged virtual.

---

### Task 1: Dependency, sources and fetch pass

**Files:** Create `requirements.txt`, `pipeline/sources_al.toml`, `pipeline/run_al.py`, `pipeline/tests/test_run_al.py`; modify `.gitignore`.

- [ ] Test `test_fetch_pass_writes_record`: fake opener returns bytes; record has one file of kind "zip" ending `.zip`, state "AL".
- [ ] Run, expect FAIL (no module). Implement `fetch_pass(source_id, src, raw_dir, now, opener)` as in `run_ak.py` with `ext="zip"`, key `zip_url`.
- [ ] Run, expect PASS. Commit.

### Task 2: Reader

**Files:** Create `pipeline/readers/al.py`, `pipeline/make_al_fixture.py`, `pipeline/tests/fixtures/al_pass.json`, `pipeline/tests/fixtures/al_results.zip`, `pipeline/tests/test_al.py`.

**Interfaces:** `read_workbook(data: bytes) -> (grid: list[list], sheet_names: list[str])`; `parse_county(county_token: str, grid, base: dict) -> (rows, turnout, findings: dict)`; `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`; `TURNOUT_COLUMNS`.

- [ ] Fixture tests (real data): Coosa `UNITED STATES SENATOR` rows for one precinct, Bullock in `counties_registered_all_zero`, Jackson `PROVSIONAL` unit virtual, a PROVIDENCE precinct not virtual, out-of-scope contests absent, every row has `COLUMNS`.
- [ ] Synthetic grid tests, one per summary list in the spec, plus: empty block gives no rows; HTML zip unreadable with all checks `None`; missing zip file; oversized member refused.
- [ ] Watch each fail, implement, watch pass. Commit.

### Task 3: Parse CLI and 2026 run

- [ ] Test `parse_record` writes both CSVs from the fixture record. Implement. Commit.
- [ ] Fetch-parse the real 2026 ZIP; record counts in `docs/al.md`; update `CLAUDE.md`. Commit.
