# Step 2 Wyoming reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parse Wyoming's certified 2026 ZIP (three `.xlsx` workbooks) into precinct, county and state rows with the county and total checks.

**Architecture:** `read_xlsx(data) -> [(sheet, grid)]` (stdlib zip + ElementTree) + `parse_blocks(grid) -> (contests, problems)` + `parse_pass(record_path, base_dir) -> (rows, summary, turnout)`. Runner follows `run_al.py` (one ZIP).

**Tech Stack:** Python 3.14 stdlib.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-wy-reader-design.md`

## Global Constraints

- Stdlib only. Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .`.
- Nothing corrected; anomalies listed; a check that couldn't run is `None`; a value that can't be compared goes to a not-checked list, never a mismatch.
- ZIP members read in memory, never extracted; members over 50 MB refused.

## Review Focus

- A block whose last columns have empty row-4 headers (trailing padding) must not create choices.
- A `-` cell vs an empty cell vs `0`: `-` and empty give no row, `0` gives a 0 row; empty in a block with other values is listed.
- A sheet whose row numbers skip (gaps) must keep row 3/4 detection by row number, not list index.
- Contest names that differ only by whitespace or line breaks between PbP and summaries.
- A workbook member missing from the ZIP: its checks None, the others still run.

---

### Task 1: Sources, fetch pass, workbook reader, block parser

**Files:** Create `pipeline/sources_wy.toml`, `pipeline/run_wy.py`, `pipeline/readers/wy.py`, `pipeline/tests/test_run_wy.py`, `pipeline/tests/test_wy.py`, fixture `pipeline/tests/fixtures/wy_results.zip` (the real ZIP) and `wy_pass.json`.

- [ ] Tests: sources complete; fetch pass record (kind `zip`, `.zip`); failure stops the pass; `read_xlsx` on the fixture gives the 23 county sheet names in order and `Total` rows; `parse_blocks` on synthetic grids (two blocks, trailing empty headers, `-` cells, row-number gaps).
- [ ] Watch fail, implement, watch pass. Commit.

### Task 2: Rows, checks, CLI, 2026 run

- [ ] Fixture tests (real data): Albany precinct `13-1` US Senate rows (Hageman 403 R, Byrd 820 D, Write-Ins 7, Overvotes 0, Undervotes 14); Albany county row from the summaries (5,450); state Total row (Hageman 122,174); ballot issue rows are `measure`; turnout `13-1` 1,244; all checks empty on the real file.
- [ ] Synthetic tests (edited grids through a test hook), one per summary list in the spec; missing member → its checks None.
- [ ] Watch each fail, implement, watch pass; `parse` CLI test. Commit.
- [ ] Fetch-parse the real ZIP; `docs/wy.md`; `CLAUDE.md`. Commit.
