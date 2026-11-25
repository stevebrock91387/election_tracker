# Delaware Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Election-district-level Delaware results with four vote types, county and state rows, turnout, every disagreement listed. **Spec:** `docs/superpowers/specs/2026-11-24-step2-de-reader-design.md`. Python 3.14 stdlib.

## Global Constraints
- Suite `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (358 before). `min_interval_s = 120`, `request_gap_s = 10`.
- Counts: strip thousands separators, then digits only. County offices excluded by title prefix.
- Nothing corrected; anomalies listed; checks that couldn't run `None`; malformed entries listed, not fatal; cross-checks in both directions. Tests written and seen failing before the reader. No Co-Authored-By; don't touch `sources/`, `tools/`, `dnd_sim/`.

## Review Focus
1. The statewide file unreadable → district rows still emitted, choice ids empty, cross-checks `None` (`test_statewide_unreadable`).
2. A district line for a (contest, name) not in the statewide file, and the reverse → listed (`test_lines_both_directions`).
3. A contest whose district count differs from Total Precincts → listed; AG's 527 is not (`test_district_count_checked`).
4. A county-office contest → no rows (`test_county_offices_excluded`).
5. "1,234" parsed as 1234; "1,23x" listed (`test_count_parsing`).

### Task 1: sources + fetch pass (tests: sources complete; URLs in order with `?t=` from an injected clock; gap; failure stops pass). Commit.
### Task 2: real fetch; `make_de_fixture.py` (contests U.S. Senator, Attorney General, one state senate district, one county office; districts including 02-27); tests first (real values: statewide Coons `13804` TOTAL 240587, Machine 140838; district 01-01 Coons 595; county New Castle 144910 `county_id "10003"`; turnout row; Review Focus; duplicate, malformed, ALL row mismatch, missing file); reader; commit.
### Task 3: parse CLI, real parse, `docs/de.md`, `CLAUDE.md`; commit.
