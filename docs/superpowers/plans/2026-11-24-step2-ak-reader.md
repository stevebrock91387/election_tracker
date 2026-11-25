# Alaska Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precinct-level Alaska first-choice results (six vote types) from the Division of Elections CSV, with a unit turnout table and every anomaly listed. **Spec:** `docs/superpowers/specs/2026-11-24-step2-ak-reader-design.md`. Python 3.14 stdlib.

## Global Constraints
- Suite `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (388 before). `min_interval_s = 120`. One request per pass.
- Nothing corrected (no write-in line made up); anomalies listed; checks that couldn't run `None`; malformed lines listed, not fatal. Tests first. No Co-Authored-By; don't touch `sources/`, `tools/`, `dnd_sim/`.

## Review Focus
1. Empty Pct_Id → precinct_id = name, `precinct_is_virtual "Y"` (`test_unit_ids`).
2. A line whose vote types don't sum to its total (ballots, votes, under, over) → listed (`test_vote_type_sums`).
3. The file unreadable or with a changed header → listed, no rows, checks `None` (`test_unreadable`, `test_header_change`).
4. A unit name with two Pct_Ids, or a real precinct whose Pct_Id differs from its prefix → listed (`test_unit_id_conflicts`).
5. Write-in gap reported per contest; units whose ballots vary by contest listed (`test_gap_and_varying_ballots`).

### Task 1: sources + fetch pass (sources complete; one URL; failure stops pass). Commit.
### Task 2: real fetch; `make_ak_fixture.py` (contests U.S. Senator, Governor/Lt Governor, one ballot measure; units 01-600, 01-610, 02-?, District 1 - Absentee, District 1 - Early Voting); tests first (real values from the fixture: Ketchikan No. 1 Peltola (`525`) TOTAL 263, Election Day 263, party DEM; Review Focus; duplicates; non-integer; malformed line); reader; commit.
### Task 3: parse CLI, real parse, `docs/ak.md`, `CLAUDE.md`; commit.
