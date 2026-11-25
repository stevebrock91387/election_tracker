# Step 2 New Jersey Clarity counties Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Read the 15 New Jersey Clarity counties' detail XML at precinct level with vote types.

**Architecture:** `parse_county_xml(zip_path, state, county, source_id) -> (rows, summary, turnout)` in `pipeline/readers/clarity.py`; `format = "county_xml"` in `run_clarity.py` (fetch as `xml`); 15 config entries.

**Tech Stack:** Python 3.14 stdlib.

**Spec:** `docs/superpowers/specs/2026-11-25-step2-nj-clarity-counties-design.md`

## Global Constraints

- Stdlib only; existing Clarity behaviour for CO SC WV IA unchanged.
- Nothing corrected; anomalies listed; a check that couldn't run is `None`; malformed input listed, not crashed.

## Review Focus

- A contest-level `VoteType` (regVotersCounty) must not become a choice or a row.
- A non-integer `votes` attribute: listed, row votes "", sums not checked (not a crash).
- A precinct in results but not in the turnout table, and the reverse.
- A file whose `Region` isn't the configured county.
- A choice with no VoteType children (total only).

---

### Task 1: Parser, config, runner

**Files:** Modify `pipeline/readers/clarity.py`, `pipeline/run_clarity.py`, `pipeline/sources_clarity.toml`; create `pipeline/tests/test_clarity_county.py`, fixture `pipeline/tests/fixtures/clarity_nj_atlantic.zip` (real, unmodified).

- [ ] Fixture tests: Senate precinct `Absecon W1 D1` Election Day rows; county TOTAL Murphy 38,951; vote types; turnout 145 precincts, county total 206,628 / 95,945; `contest_vote_types`; clean checks.
- [ ] Synthetic tests (edited XML): one per summary list, non-integer votes, choice without vote types.
- [ ] Config: 15 counties; runner `county_xml` parse path; test the config entries and the runner dispatch.
- [ ] Watch fail, implement, watch pass. Commit.

### Task 2: 2026 run and docs

- [ ] Fetch-parse the 15 counties; `docs/nj.md`; `CLAUDE.md`. Commit.
