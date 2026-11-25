# DC Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precinct-level DC results (non-ANC contests) from the DCBOE CSV, with citywide totals and candidate numbers from the citywide JSON, a precinct turnout table and every disagreement listed.

**Architecture:** Fetch info JSON → its CsvLink → citywide JSON; `pipeline/readers/dc.py` emits precinct and state rows and cross-checks them both ways.

**Tech Stack:** Python 3.14 stdlib. **Spec:** `docs/superpowers/specs/2026-11-24-step2-dc-reader-design.md`

## Global Constraints
- Stdlib only; suite `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (329 before). `min_interval_s = 120`, `request_gap_s = 10`.
- Over/under votes: rows with `choice_id ""`. ANC contests ("ANC-…") and contest numbers < 0 excluded from rows.
- Nothing corrected; anomalies listed; checks that couldn't run `None`; malformed entries listed, not fatal; cross-checks both directions. No Co-Authored-By; don't touch `sources/`, `tools/`, `dnd_sim/`.

## Review Focus
1. A CsvLink outside `base_url + "Downloads/"` → pass stops, no record (`test_bad_csvlink_stops_pass`).
2. The citywide JSON unreadable → precinct rows still emitted, choice ids empty, cross-checks `None` (`test_citywide_unreadable`).
3. A citywide line with no CSV rows, and a CSV candidate with no citywide line → both listed (`test_lines_both_directions`).
4. JSON party on over/under votes → not used; real party differences listed (`test_party_from_csv`).
5. A precinct whose ward differs between rows → listed (`test_ward_conflict_listed`).

### Task 1: sources and fetch pass (tests: sources complete, URLs in order, gap [10, 10], bad CsvLink, failure stops pass). Commit.
### Task 2: real fetch; `make_dc_fixture.py` (contests 4, 5, 6, 8 and one ANC; precincts in two wards); tests first (real values: Delegate citywide White 201900 `choice_id` = its CandidateNumber; a precinct row; turnout; over/under rows with `choice_id ""`; Review Focus; non-integer, duplicate, ballots > registered, missing special rows, malformed); then `pipeline/readers/dc.py`; commit.
### Task 3: parse CLI, real parse, `docs/dc.md`, `CLAUDE.md`; commit.
