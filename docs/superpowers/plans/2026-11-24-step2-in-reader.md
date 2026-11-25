# Indiana Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precinct-, county- and state-level Indiana results for six office categories from the Indiana ENR site, with ids from the category JSON, a county turnout table and every disagreement listed.

**Architecture:** A fetch pass reads `settings.json` (version letter), the category index, six category files, the turnout file and the precinct CSV; `pipeline/readers/in_.py` emits state, county and precinct rows, joining precinct rows to ids case-insensitively on (office, county, name).

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-in-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (278 before).
- Every download through `pipeline.fetch.fetch`; `min_interval_s = 120`, `request_gap_s = 10`; source ids `<id>-settings`, `-elections`, `-offcat-<category>`, `-turnout`, `-csv`.
- A single item may be an object, not a one-element list: normalize.
- Nothing corrected; every anomaly listed; a check that could not run is `None`; malformed entries listed, not fatal. No Co-Authored-By trailers; don't touch `sources/`, `tools/`, `dnd_sim/`.

## Review Focus

1. A category file that is HTML or truncated → listed; that category's state and county rows absent; checks that need it `None`; precinct rows for it kept with ids empty (test `test_unreadable_category`).
2. The CSV missing → state and county rows still emitted, precinct checks `None` (test `test_csv_missing`).
3. County names differing in case across files ("Laporte"/"LaPorte") → joined, not listed (test with a renamed county in the fixture).
4. `settings.json` without a one-letter `VersionType` → the pass stops, no record (test `test_bad_version_stops_pass`).
5. A Federal/State category in the index that the config lacks (2028 Senate/Governor) → listed (test `test_uncovered_category_listed`).

---

### Task 1: Sources and fetch pass

- [ ] Failing tests in `pipeline/tests/test_run_in.py`: sources complete; URLs in order (`data/settings.json`, `data/statewideElectionsC_B.json`, six `data/OffCatC_<id>_B.json`, `data/statewideTurnout_B.json`, `download/AllOfficeResults.csv`) with a fake settings body `{"Root": {"VersionType": "B", "VersionCode": "x"}}`; record `version_type "B"`, kinds `settings, elections, offcat-<id>…, turnout, csv`; gap `[10]*9`; `test_bad_version_stops_pass`; failure stops the pass.
- [ ] Implement `pipeline/sources_in.toml`, `pipeline/run_in.py`; suite green; commit `Add IN sources and fetch pass`.

### Task 2: Fixtures and reader

- [ ] Real fetch; `pipeline/make_in_fixture.py PASS OUT_DIR --counties Adams,Lake` keeps, in each category file, only races in those counties (and statewide-summary races whose office ids remain), turnout rows for them plus "Total", CSV rows for in-scope categories in those counties; settings and the index whole.
- [ ] Failing tests in `pipeline/tests/test_in.py`, real values: Secretary of State (`2258`) state row Bayh 1007815 `party "Lp"`-style as published (`"D"`), `choice_id "5486"`; Adams county row Engling (`2361`) 5188, `county_id "18001"`; Lake Bayh 92103 `county_id "18089"`; US House district 1 (`4912`) Lake Mrvan (`4046`) 95679; precinct rows for Lake Bayh sum to 92103 and carry `contest_id "2258"`, `choice_id "5486"`, `county_id "18089"`, `party "Democratic"`-style full name as published; `contest_type "Secretary of State"`; `election_name "2026 General Election"`; `election_date "11/03/2026"`; turnout Adams registered 19761; `precinct_vs_county_mismatches == []`; plus the Review Focus tests and synthetic variants (non-integer votes, duplicate, unmatched precinct row, statewide candidate without id, turnout Total mismatch).
- [ ] Implement `pipeline/readers/in_.py`; suite green; commit `Add IN reader with fixtures from the 2026 files`.

### Task 3: Parse CLI, real-file results, docs

- [ ] Parse tests; CLI as `run_vt`; parse the real pass; `docs/in.md` (files, sizes, hashes, rows by level, lists, quirks: name case, party case, Nv precincts, zero-vs-unreported ambiguity, unversioned CSV); `CLAUDE.md`; commit `Add IN parse CLI; record 2026 results`.
