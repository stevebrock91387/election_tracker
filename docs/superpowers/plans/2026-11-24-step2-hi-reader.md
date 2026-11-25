# Step 2 Hawaii reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parse Hawaii's `summary.txt` and `media.txt` into the common schema, precinct and state rows, with the state-vs-precinct check.

**Architecture:** `read_table(body, header) -> (preamble, header_index, lines)` + `parse_pass(record_path, base_dir) -> (rows, summary, turnout)`. Runner and sources follow `run_ak.py` with two files.

**Tech Stack:** Python 3.14 stdlib.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-hi-reader-design.md`

## Global Constraints

- Stdlib only. Tests: `.venv/bin/python -m unittest discover -s pipeline/tests -t .`.
- Nothing corrected; anomalies listed; a check that couldn't run is `None`.
- A failed request stops the pass.

## Review Focus

- A quoted field with embedded newlines and tabs must stay one field (Governor names).
- A media file whose preamble line count changes (no `Column1…` line): header still found.
- A unit whose VSC and plain rows share a precinct name must stay two units (keyed by splitId).
- Summary file missing: precinct rows still emitted, cross-checks `None`.
- Candidate names without a `(X)` prefix: party from Choice_party, not guessed.

---

### Task 1: Sources and fetch pass

**Files:** Create `pipeline/sources_hi.toml`, `pipeline/run_hi.py`, `pipeline/tests/test_run_hi.py`.

- [ ] Tests: sources complete; fetch pass requests summary then media, record kinds `["summary", "media"]`, paths end `.txt`; a failure stops the pass with no record.
- [ ] Watch fail, implement (`fetch_pass(source_id, src, raw_dir, now, opener)`), watch pass. Commit.

### Task 2: Reader

**Files:** Create `pipeline/readers/hi.py`, `pipeline/make_hi_fixture.py`, `pipeline/tests/fixtures/hi_summary.txt`, `hi_media.txt`, `hi_pass.json`, `pipeline/tests/test_hi.py`.

**Interfaces:** `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`; `TURNOUT_COLUMNS`.

- [ ] Fixture tests (real data): one plain and one VSC unit's rows for a fixture contest; state rows incl. Blank/Over/Invalid; Governor-style multi-line name collapsed; party from prefix; every row has `COLUMNS`; all cross-checks empty on the fixture.
- [ ] Synthetic tests (edited fixture text), one per summary list in the spec, plus: missing summary → precinct rows, cross-checks None; missing media → all checks None; header changed → unreadable; preamble without the `Column…` line still read.
- [ ] Watch each fail, implement, watch pass. Commit.

### Task 3: Parse CLI and 2026 run

- [ ] Test `parse` writes both CSVs and prints "not checked" for a None check. Implement. Commit.
- [ ] Fetch-parse the real 2026 files; record counts in `docs/hi.md`; update `CLAUDE.md`. Commit.
