# Step 2 Maryland reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parse Maryland's live results pages (24 county pages, 9 office pages, 3 question pages) into the common schema with a county-vs-state check.

**Architecture:** `parse_page` (HTML → contests) + `parse_pass` (record → rows, summary, []); runner with `request_gap_s` like `run_la.py`.

**Tech Stack:** Python 3.14 stdlib (`html.parser`).

**Spec:** `docs/superpowers/specs/2026-11-24-step2-md-reader-design.md`

## Global Constraints

- Stdlib only. Nothing corrected; anomalies listed; an unrun check is `None`.
- 5 s between requests in a pass; 120 s per file id.

## Review Focus

- A page mid-count with "NR" cells or "0 of 257" reporting: rows still emitted, votes "" for NR, listed.
- An office page missing or blocked (HTML error page): cross-check `None` for its contests, not clean.
- A contest heading without a table, or a table without a heading: listed, never attached to the wrong contest.
- District names reused across offices ("District 14" for Senate and Delegates): contest ids must include the office.
- A county page that is the wrong county (h1 mismatch): listed.

---

### Task 1: Sources and fetch pass
- [ ] Tests `test_run_md.py`: sources complete (24 counties, pages 1–9, questions 1–3, gap 5); fetch pass requests 36 URLs in order with 35 sleeps of 5; failure stops the pass. Implement `run_md.py`, `sources_md.toml`. Commit.

### Task 2: Page parser and pass parser
- [ ] Fixture tests (`test_md.py`, real pages): Montgomery Governor rows (Moore 76,721 / 128,150 / 93,483 / 12,690 / total 311,044), District 8 county = state, question rows, Kent present, reporting status strings, out-of-scope titles include "County Executive".
- [ ] Synthetic tests per summary list in the spec plus the Review Focus items. Implement `pipeline/readers/md.py`. Commit.

### Task 3: Parse CLI, real run, docs
- [ ] `parse_record` test; implement. Run a real pass; write `docs/md.md`; update `CLAUDE.md`. Commit.
