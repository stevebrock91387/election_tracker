# Step 2 Massachusetts reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parse Massachusetts' 2026 general results (PD43+ list pages + one precinct CSV per in-scope contest and statewide question) into precinct and state rows with the list, TOTALS and Total Votes Cast checks.

**Architecture:** `parse_search(html)` / `parse_questions(html)` (stdlib `html.parser` tree) select ids; `fetch_pass` fetches lists then CSVs; `parse_csv(text, kind)`; `parse_pass(record_path, base_dir) -> (rows, summary, turnout)` (turnout always empty: no turnout in the source).

**Tech Stack:** Python 3.14 stdlib.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-ma-reader-design.md`

## Global Constraints

- Stdlib only. Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .`.
- Nothing corrected; anomalies listed; a check that couldn't run is `None`; a value that can't be compared goes to a `*_not_checked` list.
- A failed request stops the pass; 5 s between requests.

## Review Focus

- The list page's malformed `<thead><tr>…<tr>` (an unclosed row) must not swallow candidate rows.
- A contest with no opponents (`won against no opponents`) still has its candidate table read.
- A CSV whose party row is missing (questions) vs present (contests): never read a precinct as the party row.
- Thousands separators: `"1,401"` is 1401, `1,40` or `1.401` is non-numeric.
- The same candidate name twice in one contest (two columns): listed, second dropped.

---

### Task 1: List parsers, sources, fetch pass

**Files:** Create `pipeline/readers/ma.py` (list parsers), `pipeline/sources_ma.toml`, `pipeline/run_ma.py`, `pipeline/tests/test_run_ma.py`, fixtures (`ma_search.html`, `ma_questions.html`, four CSVs, `ma_pass.json`), `pipeline/make_ma_fixture.py`.

- [ ] Tests: `parse_search` on the fixture gives the four ids with office/district and the Senate candidates (Markey Democratic 1,718,276 … All Others 3,811, Blanks 51,371, Total 2,749,609); `parse_questions` gives 11789 Statewide Question 1 and 11758 local; `select(...)` picks 173531, 173571, 173668 and 11789; fetch pass order (search, questions, contests, question), gap between requests, record kinds; failure stops the pass.
- [ ] Watch fail, implement, watch pass. Commit.

### Task 2: CSV parser, rows, checks, CLI, 2026 run

- [ ] Fixture tests: Abington precinct 1 Senate rows (Markey 779 Democratic …), state TOTALS rows, House 2nd unopposed, Question 1 rows `measure`; party label differences listed (Ayyadurai Unenrolled vs Independent); all other checks empty.
- [ ] Synthetic tests (edited CSV text), one per summary list; missing search → list checks None; HTML instead of CSV → unreadable.
- [ ] Watch each fail, implement, watch pass; parse CLI test. Commit.
- [ ] Fetch-parse 2026 (236 requests, ~20 min, background); `docs/ma.md`; `CLAUDE.md`. Commit.
