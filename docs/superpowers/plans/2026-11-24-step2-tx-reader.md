# Texas Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** County-level Texas results (total and early votes) for the 584 federal, statewide and district races on the Civix ENR site, in the common format, with state rows from the statewide file, a county turnout table, and every difference between the two files listed.

**Architecture:** A fetch pass saves the statewide file and the county file through `pipeline/fetch.py` and writes a pass record; `pipeline/readers/tx.py` decodes the base64 JSON, emits state rows and county rows, and lists what doesn't agree. Same shape as the NC reader (two files, cross-check) and the OH reader (turnout as a third return value).

**Tech Stack:** Python 3.14 stdlib, `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-tx-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (164 before this plan).
- Every download through `pipeline.fetch.fetch` with `ext="json"`; `min_interval_s = 120`; `request_gap_s = 10`.
- `vote_type` `TOTAL` (`V`) and `Early Votes` (`EV`); `contest_scope = "statewide"`; state rows `level = "state"` (district races too); county rows `level = "county"`, `county_id` = FIPS from `Lookups.County.MID`.
- `source_created_at` = `Home.LastUpdatedTime` on state rows, empty on county rows. `party` as published in each file (no merging).
- Nothing corrected; every anomaly listed; a check that could not run is `None`.
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. Either file comes back as an HTML challenge page or truncated JSON → listed under `unreadable_files`, that file's rows absent, the cross-checks `None`, the other file's rows still emitted (test `test_unreadable_county_file_not_checked`).
2. One statewide section isn't decodable base64 JSON → listed under `unreadable_sections`, the other sections still read (test `test_bad_section_listed`).
3. Proposition choices with a null id in the statewide file → joined to the county file by name, no false "missing" entries (test `test_propositions_join_by_name` on the 2025 fixture).
4. A county key with no `Lookups.County` entry → row kept with `county_id` empty, listed (test `test_unknown_county_listed`).
5. A race present in some counties and absent from others (normal for district races) → not listed; only a race or choice that no county carries, or that the statewide file lacks, is listed (test `test_race_in_some_counties_not_listed`).

---

### Task 1: Sources and fetch pass

**Files:** Create `pipeline/sources_tx.toml`, `pipeline/run_tx.py` (`load_sources`, `fetch_pass`, `main` with `fetch`); Test `pipeline/tests/test_run_tx.py`.

**Interfaces:**
- Produces: `fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep) -> record path`; record `{"source_id", "state", "started_utc", "files": [{"kind": "election", ...}, {"kind": "county", ...}]}`.

- [ ] Failing tests: `test_sources_complete` (`tx-2026-general`: `state = "TX"`, `election_url = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/53815"`, `county_url = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/countyInfo/53815"`, `min_interval_s = 120`, `request_gap_s = 10`); `test_pass_urls_in_order` (election then county; source ids `tx-2026-general-election`, `-county`; paths end `.json`); `test_gap_between_requests` (sleep called with `[10]`); `test_failure_stops_pass` (county 403 → `FetchError`, no record).
- [ ] Run (fail), implement, suite green, commit `Add TX sources and fetch pass`.

### Task 2: Fixtures and reader

**Files:** Create `pipeline/make_tx_fixture.py`, `pipeline/readers/tx.py`, fixtures `pipeline/tests/fixtures/tx_election.json`, `tx_county.json`, `tx_pass.json`, `tx2025_election.json`, `tx2025_county.json`, `tx2025_pass.json`; Test `pipeline/tests/test_tx.py`.

**Interfaces:**
- Consumes: the pass record from Task 1.
- Produces: `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`; `TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters", "voters", "precincts_reporting", "polling_locations_reporting", "polling_locations_total"]`.
- Summary keys: `contests`, `choices`, `counties` (ints), `version`, `last_updated` (str), `party_codes` (dict code → state-row choice count), `null_choice_ids` (int), lists `mismatches_state_vs_county` (contest, choice id or name, vote type, state value, county sum), `state_choices_missing_from_county`, `county_choices_missing_from_state` (contest, choice; a whole missing race appears as its choices), `party_differences` (contest, choice id, state party, county party; once per choice), `unknown_counties`, `early_exceeds_total`, `non_numeric_votes`, `duplicate_choices`, `office_in_two_sections`, `home_reported_exceeds_total`, `home_vs_county_summary` (field, Home value, county sum), `unreadable_sections`, `unreadable_files`, `missing_files`.

- [ ] Real fetch (`run_tx fetch tx-2026-general`). `make_tx_fixture.py ELECTION COUNTY OUT_PREFIX --races IDS --counties KEYS`: keep `Version`, `Home`, `Lookups` (all 254 counties) and the four result sections filtered to the given races (a null section stays null); drop `OfficeSummary`, `Race`, `ReportList`, `ElementControl`; county file filtered to the given counties and races; re-encode base64. Cut:
  - 2026 from the real pass: races `5075` (US Senator), `5070` (US Rep 5), `5048` (US Rep 19), `3579` (Governor), `4984` (State Rep 8); counties `1` Anderson, `2` Andrews, `3` Angelina.
  - 2025 from the recon copies of election `51031` (scratchpad `txrecon2/e51031.json`, `c51031.json`, downloaded once 2026-11-24): race `87` (Proposition 1), counties `1`–`3`.
- [ ] Failing tests, real values:
  - Senate state row Paxton (`choice_id "42424"`): TOTAL 4249373, Early Votes 3232667, `party "REP"`, `contest_type "FEDERAL OFFICES"`, `contest_name "U. S. SENATOR "`, `source_created_at "Nov 04, 2026 22:48:37"`, `election_date "11032026"`.
  - Anderson county row Paxton: `county_id "48001"`, `county_name "ANDERSON"`, TOTAL 10930, Early Votes 7529, `reporting_status "23/23 precincts"`, `source_created_at ""`, `contest_type "FEDERAL OFFICES"`.
  - Ted Brown (`33528`) state party `"LIB"`, Anderson party `"L"`; `party_differences` contains `(5075, "33528", "LIB", "L")` once.
  - `mismatches_state_vs_county` contains `(5075, "42424", "TOTAL", 4249373, 31279)` and `(5075, "42424", "Early Votes", 3232667, 22249)`; a variant with each statewide value set to the fixture's county sum gives `[]`.
  - Turnout: 3 rows; Anderson `registered_voters 31222`, `voters 15290`, `precincts_reporting 23`, `polling_locations_reporting 23`, `polling_locations_total 23` (ints).
  - `home_reported_exceeds_total` contains the precincts entry `("PrecinctsReporting", 202, 200)`; `version "enr/53815/117/"`; every row's keys == `COLUMNS`.
  - 2025 fixture: `test_propositions_join_by_name`: state rows `choice "FOR"` / `"AGAINST"`, `choice_id ""`, TOTAL 2041859 / 916217; county rows `choice_id "8701"` / `"8702"`; both missing-lists empty; `null_choice_ids == 2`; `contest_type "STATEWIDE PROPOSITIONS"`.
- [ ] Failing synthetic tests (fixture JSON decoded, edited, re-encoded in the test): the Review Focus tests above, plus `test_early_exceeds_total_listed`, `test_non_numeric_votes_listed` (votes `""`, out of sums), `test_duplicate_choice_listed`, `test_office_in_two_sections_listed`, `test_missing_choice_both_directions_listed`, `test_missing_file_listed`.
- [ ] Run (fail), implement, suite green, commit `Add TX reader with fixtures from the 2026 and 2025 files`.

### Task 3: Parse CLI, real-file results, docs

**Files:** Modify `pipeline/run_tx.py` (`parse`, `fetch-parse`), `CLAUDE.md`; Create `docs/tx.md`; Test `test_parse_command`, `test_parse_prints_not_checked` in `test_run_tx.py`.

- [ ] Failing tests: parsing the 2026 fixture pass writes `<stamp>.csv` (header `COLUMNS`) and `<stamp>-turnout.csv` (header `TURNOUT_COLUMNS`, 3 rows) and prints `party_differences:` and `version: enr/53815/117/`; a pass with only the election file prints `mismatches_state_vs_county: not checked`. Implement as `run_oh.parse_record`; suite green.
- [ ] Parse the real pass; record in `docs/tx.md`: URLs, bytes and SHA-256 of both files, rows, contests, counties, every non-empty list with counts and examples, the quirks from the spec (base64, lowercase `id`, party codes differing between files, null proposition ids, Home vs county sums, no county-level offices, Nov 4 timestamp).
- [ ] Update `CLAUDE.md` (step 2 section; the custom-site readers NC, OH, TX are done); commit `Add TX parse CLI; record 2026 results`.
