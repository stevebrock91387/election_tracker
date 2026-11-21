# Tally ENR Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** County-level federal and statewide results for AR and ND from the Tally ENR JSON API, in the common format, checked against each contest's own statewide totals.

**Architecture:** A fetch pass saves election info, the contest list and one results file per contest type through `pipeline/fetch.py` and writes a pass record; the reader joins results to names by id and emits rows plus a summary.

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-21-step2-tally-reader-design.md`

## Global Constraints

- Stdlib only; tests: `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .`
- Every download through `pipeline.fetch.fetch`; `min_interval_s = 120` per source id; `request_gap_s = 10` within a pass.
- Nothing corrected; every anomaly listed. Ids compared as strings.
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. Files from different moments in one pass (versionIDs differ) → listed, not silently mixed (test `test_version_mismatch_listed`).
2. A response for a different election, or with `errorMessage` set → listed (tests `test_election_id_mismatch_listed`, `test_error_message_listed`).
3. A results contest or choice missing from the contest list → rows kept with empty names, listed (test `test_missing_names_listed`).
4. A county id not in info, a party id not in info → listed (test `test_unknown_ids_listed`).
5. A write-in entry or a non-integer vote count → listed, write-in not emitted, bad count kept empty (tests `test_write_ins_listed`, `test_non_numeric_votes`).

---

### Task 1: Sources and fetch pass

**Files:** Create `pipeline/sources_tally.toml`, `pipeline/run_tally.py` (`load_sources`, `fetch_pass`, `main` with `fetch`); Test `pipeline/tests/test_run_tally.py`.

**Interfaces:** `fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep) -> str` (pass record path). Record: `{"source_id", "state", "started_utc", "election_id", "files": [{"kind": "info"|"list"|"results", "type", "path"}]}`.

- [ ] **Step 1:** Write the config (`tally-AR-2026-general`, `tally-ND-2026-general`, values from the spec table).
- [ ] **Step 2: Failing tests:** `test_sources_complete` (2 entries, AR/ND, intervals, `api` ends with `/`); `test_pass_urls_in_order` (fake opener: info `…Election/GetElectionInfo?cId=north-dakota&electionID=348`, list `…Contest/GetContestSearchList?cid=north-dakota&electionID=348`, results `…Contest/GetContestResults?cId=north-dakota&electionID=348&contestType=SW`); `test_contest_type_url_encoded` (type `State Senate` → `contestType=State+Senate` or `%20`, either, asserted by decoding); `test_gap_between_requests` (sleep calls `[10, 10]` for 3 requests); `test_failure_stops_pass` (500 on list → `FetchError`, no record written).
- [ ] **Step 3:** Run, expect failure. **Step 4:** Implement. **Step 5:** Suite green. **Step 6:** Commit `Add Tally sources and fetch pass`.

### Task 2: Real fetch, fixtures, reader

**Files:** Create `pipeline/readers/tally.py`, `pipeline/make_tally_fixture.py`, fixtures `pipeline/tests/fixtures/tally_*`; Test `pipeline/tests/test_tally.py`.

**Interfaces:** `parse_pass(record_path, base_dir=".") -> (rows, summary)`; summary keys: `contests`, `choices`, `counties`, `is_official`, `version_ids`, `election_id_mismatches`, `errors`, `contests_missing_from_list`, `choices_missing_from_list`, `unknown_party_ids`, `unknown_location_ids`, `mismatches_counties_vs_state`, `write_ins`, `non_numeric_votes`.

- [ ] **Step 1:** Run one real fetch per state (sequential is not required any more, but run them one after another anyway), note pass records.
- [ ] **Step 2:** Cut fixtures: AR Federal results cut to the Senate contest and AR Statewide cut to its first contest; ND SW cut to the House contest; info cut to the parties and counties those contests use; list cut to those contests; a `_fixture_source_sha256` map in the fixture pass record.
- [ ] **Step 3: Failing tests:** real-fixture values (AR Senate state TOTAL for Cotton 481,495, party "Republican", choice "REP Tom Cotton"; one AR county row with FIPS id and county name; ND House present with 53 counties); every row's keys == `COLUMNS`; real fixtures have no anomalies and `version_ids` of length 1; the five Review Focus tests; `test_county_sum_mismatch`.
- [ ] **Step 4:** Run, expect failure. **Step 5:** Implement. **Step 6:** Suite green. **Step 7:** Commit `Add Tally reader with fixtures from AR and ND`.

### Task 3: Parse CLI, real-file results, docs

**Files:** Modify `pipeline/run_tally.py` (`parse`, `fetch-parse`), `CLAUDE.md`; Create `docs/tally.md`; Test `test_parse_command` in `pipeline/tests/test_run_tally.py`.

- [ ] **Step 1:** Failing parse-command test (CSV header == `COLUMNS`). **Step 2:** Implement (summary printing as in `run_resultsajax`, "not checked" for None). **Step 3:** Suite green.
- [ ] **Step 4:** Parse both real pass records; record contests, counties, rows, anomalies in `docs/tally.md` with the quirks from the spec.
- [ ] **Step 5:** Update `CLAUDE.md` (step-2 section, test count, next platforms). **Step 6:** Commit `Add Tally parse CLI; record per-state results`.
