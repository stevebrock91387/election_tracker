# Connecticut Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Town-level Connecticut results for the 251 state and district offices in the CT EMS static JSON, in the common format, with state rows, a town turnout table and every disagreement listed.

**Architecture:** A fetch pass reads `Version.json`, then seven files under that version, through `pipeline/fetch.py`; `pipeline/readers/ct.py` emits state rows and town rows (level "town") and lists what doesn't agree. Same shape as the TX reader.

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-ct-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (193 before this plan).
- Every download through `pipeline.fetch.fetch` with `ext="json"`; `min_interval_s = 120`; `request_gap_s = 10`.
- In-scope office types `SW C S A PD`; `vote_type = "TOTAL"`; `contest_scope = "statewide"`; state rows `level "state"`, town rows `level "town"` with the town id/name in `county_id`/`county_name`.
- Candidate addresses (`AD`) never reach rows, summary, fixtures or docs.
- Nothing corrected; every anomaly listed; a check that could not run is `None`. Files read as `utf-8-sig`.
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. A file that is an HTML page or truncated JSON → listed, its rows absent, dependent checks `None`, other rows still emitted (test `test_unreadable_town_file_not_checked`).
2. The Lookup file unreadable → no names or office types to scope by: no rows at all rather than unscoped rows, every check `None` (test `test_unreadable_lookup_not_checked`).
3. A party id missing from `partyIds` → party "", listed with the id, row kept (test on real fixture data, candidate 44432 / party 1060).
4. The same name on several lines in one office with no grouping entry → listed (test on real fixture: Probate 18, Matt Jalowiec D and R).
5. A town key in the votes that isn't in `townIds`, and the turnout "Total" key → the first listed, the second used only as a check (tests `test_unknown_town_listed`, `test_turnout_total_row_checked`).

---

### Task 1: Sources and fetch pass

**Files:** Create `pipeline/sources_ct.toml`, `pipeline/run_ct.py` (`load_sources`, `fetch_pass`, `main` with `fetch`); Test `pipeline/tests/test_run_ct.py`.

**Interfaces:**
- Produces: `fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep) -> record path`; record `{"source_id", "state", "started_utc", "version", "office_types", "files": [{"kind", "path"}]}` with kinds `version, lookup, state, town, townstatus, turnout, grouping, officeprecincts` in that order.

- [ ] Failing tests: `test_sources_complete` (`ct-2026-general`: `state "CT"`, `base_url "https://ctemspublic.tgstg.net/ng-app/data/election/108/"`, `office_types ["SW","C","S","A","PD"]`, 120, 10); `test_pass_urls_in_order` (fake opener returns `{"Version":56592}` for `Version.json`; then URLs `<base>56592/Lookupdata.json`, `stateVotes_Electiondata.json`, `townVotes_Electiondata.json`, `townStatus_Electiondata.json`, `voterTurnout_Electiondata.json`, `candidateGrouping_Electiondata.json`, `officePrecincts_Electiondata.json`; record `version 56592`); `test_gap_between_requests` (`[10]*7`); `test_bad_version_stops_pass` (`Version.json` body not JSON → `ValueError`, no record); `test_failure_stops_pass` (404 on the town file → `FetchError`, no record).
- [ ] Run (fail), implement, suite green, commit `Add CT sources and fetch pass`.

### Task 2: Fixtures and reader

**Files:** Create `pipeline/make_ct_fixture.py`, `pipeline/readers/ct.py`, fixtures `pipeline/tests/fixtures/ct_*.json`, `ct_pass.json`; Modify `pipeline/schema.py` (docstring: level adds "town"); Test `pipeline/tests/test_ct.py`.

**Interfaces:**
- Produces: `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`; `TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "county", "registered_voters", "ballots", "abr", "abc", "ebr", "ebc", "edr", "edc", "precincts_reporting"]` (`county_id`/`county_name` = town; `county` = the CT county name).
- Summary keys: `version`, `contests`, `choices`, `towns` (ints), `office_precincts_below_100` (int), lists `mismatches_state_vs_town`, `state_lines_missing_from_towns`, `town_lines_missing_from_state`, `grouping_mismatches`, `multi_line_names_without_grouping`, `grouping_without_lines`, `multi_line_names` ((office, name, [line ids]), informational), `unknown_parties` (line id, party id), `unknown_towns`, `unknown_offices`, `unknown_candidates`, `unknown_office_types`, `in_scope_offices_without_state_entry`, `non_numeric_votes`, `duplicate_lines`, `turnout_total_mismatches`, `unreadable_files`, `missing_files`.

- [ ] Real fetch (`run_ct fetch ct-2026-general`). `make_ct_fixture.py RECORD OUT_DIR --offices IDS --towns IDS`: keep the given offices and towns in every file (Lookup: `election`, `townIds`, `counties`, `countyTowns`, `partyIds` whole; `officeList` and `candidateIds` filtered; **`AD` removed from every candidate**; `pollingplaceIds`/`townPollingPlaces`/`townParties` dropped), keep the turnout "Total" key, write `ct_<kind>.json` and `ct_pass.json`. Cut offices `19663` (Governor), `19666` (CD1), `19667` (CD2), `19826` (State Senator 2), `19898` (Probate 18), `19797` (the unknown-party line's office), `20014` (Registrar, SM); towns `1` Andover, `64` Hartford, `164` Windsor, `25` and `131` (Probate 18), plus the town of office `19797`.
- [ ] Failing tests, real values: Governor state row Lamont D line `44186` = 742437, party "D", WF line `44299` = 29820 party "WF"; Hartford town row CD1 Bronin (`44188`) = 16135, `level "town"`, `county_id "64"`, `county_name "Hartford"`, `reporting_status "24 of 24 (100.00%)"`; state row `contest_type "C"`, `election_date "11/03/2026"`, `election_name "2026 General Election"`; no row for office `20014`; `unknown_parties` contains `("44432", "1060")`; `multi_line_names_without_grouping` contains `("19898", "Matt Jalowiec")`; turnout Hartford `registered_voters 67292`, `ballots 19447`, `precincts_reporting "25 of 24 (104.17%)"`, `county "Hartford"`; `version 56592`; no row, summary value or turnout value contains a candidate address (assert the fixture has no `AD` key and the text "Street" doesn't appear in rows).
- [ ] Failing synthetic tests: the Review Focus tests above, plus `test_mismatch_listed` (a town value +1), `test_missing_lines_both_directions_listed`, `test_grouping_mismatch_listed`, `test_non_numeric_votes_listed`, `test_duplicate_line_listed`, `test_unknown_office_type_listed`, `test_missing_file_listed`.
- [ ] Run (fail), implement, suite green, commit `Add CT reader with fixtures from the 2026 files`.

### Task 3: Parse CLI, real-file results, docs

**Files:** Modify `pipeline/run_ct.py` (`parse`, `fetch-parse`), `CLAUDE.md`; Create `docs/ct.md`; Test `test_parse_command`, `test_parse_prints_not_checked`.

- [ ] Failing tests (as in `test_run_tx`); implement as `run_tx.parse_record`; suite green.
- [ ] Parse the real pass; record in `docs/ct.md` the URLs, version, file sizes and SHA-256, rows, offices, towns, every non-empty list with counts and examples, the quirks (party lines, grouping gaps, unknown party ids, officePrecincts below 100%, Hartford 25 of 24, "Total" key, no timestamp, addresses in the lookup never copied).
- [ ] Update `CLAUDE.md`; commit `Add CT parse CLI; record 2026 results`.
