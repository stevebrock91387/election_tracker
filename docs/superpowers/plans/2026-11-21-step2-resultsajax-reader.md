# ResultsAjax Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** County-level federal and statewide results for MT, NE, NM, OR, SD from the shared ResultsAjax engine, in the common format, checked against the state's own statewide CSV where one exists.

**Architecture:** A fetch pass reads each configured results page, pulls the race list from its `BuildCounty(...)` calls, fetches the media CSVs and one county JSON per race through `pipeline/fetch.py`, pacing 10 s between requests, and writes a pass record. The reader turns a pass record into common-format rows plus a summary.

**Tech Stack:** Python 3.14 stdlib (`re`, `json`, `csv`, `tomllib`, `unittest`), run with `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-21-step2-resultsajax-reader-design.md`

## Global Constraints

- Stdlib only; tests: `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .`
- Every download goes through `pipeline.fetch.fetch` (raw body + manifest row before parsing); `min_interval_s = 120` per source id; `request_gap_s = 10` between requests within a pass.
- Nothing is corrected; every anomaly is listed in the summary. The only normalisation: `county_id` surrounding whitespace stripped.
- Join on ids, compared as strings (`str(RaceID)`, `str(CandidateID)`).
- MT and OR: `statewide_check = "not available"`, never "0 mismatches".
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. Race id or candidate id typed int in one file and string in the other → must still match (test: `test_media_ids_match_as_strings`).
2. A race whose JSON is `{"d": null}` or `[]` → listed under `races_no_data`, no rows, no crash (test: `test_null_race_listed`).
3. A race appearing on two page types → fetched once (test: `test_duplicate_race_fetched_once`).
4. A race fetch that fails mid-pass → listed in the pass record and the summary, other races still parsed (tests: `test_failed_race_continues`, `test_failed_race_in_summary`).
5. A media CSV row whose race isn't on any page, and a page race missing from the CSV → both listed (test: `test_media_orphans_listed`).

---

### Task 1: Sources and fetch pass

**Files:**
- Create: `pipeline/sources_resultsajax.toml`, `pipeline/readers/resultsajax.py` (only `parse_page` in this task), `pipeline/run_resultsajax.py` (`load_sources`, `fetch_pass`)
- Test: `pipeline/tests/test_run_resultsajax.py`

**Interfaces:**
- Produces: `parse_page(html: str) -> list[tuple[str, str, str, str]]` (type, race_id, osn, party), order kept, duplicates removed.
- Produces: `fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep) -> str` (path of the pass record). Pass record JSON: `{"source_id", "state", "started_utc", "files": [{"kind": "page"|"media"|"race", "type", "race_id", "osn", "party", "path"}], "failed_races": [{"type", "race_id", "error"}]}`.
- URLs: page `{site}ResultsSW.aspx?type={T}&map=CTY`; media `{site}resultsCSV.aspx?text=All&type={T}&map=CTY`; race `{service_root}{service}/GetMapData?type={T}&category=CTY&raceID={id}&osn={osn}&county=0&party={party or 0}`.
- Source ids: `{id}-page-{T}`, `{id}-media-{T}`, `{id}-race-{race_id}`.

- [ ] **Step 1: Write the config** with the five entries from the spec's table (`resultsajax-MT-2026-general` etc.; `media_types`: MT `[]`, NE `["All"]`, NM `["FED", "SW"]`, OR `[]`, SD `["SWR", "BQ"]`).
- [ ] **Step 2: Write failing tests**
  - `test_sources_complete`: 5 entries, states {MT, NE, NM, OR, SD}, `min_interval_s >= 120`, `request_gap_s == 10`, `site` and `service_root` end with `/`.
  - `test_parse_page`: on `"BuildCounty('FED', '11185', '180', '')"` twice plus `"BuildCounty('FED', '11186', '190', '')"` → `[("FED","11185","180",""), ("FED","11186","190","")]`.
  - `test_pass_order_and_urls`: fake opener records URLs; NM-like source with one page holding races 11185/11186 and one media type → URLs in order page, media, race 11185, race 11186; race URL ends `raceID=11185&osn=180&county=0&party=0`; uses `NMResultsAjax.svc`.
  - `test_gap_between_requests`: fake sleep records calls → `[10, 10, 10]` for 4 requests (no sleep before the first).
  - `test_duplicate_race_fetched_once`: same race on two pages → one race URL.
  - `test_failed_race_continues`: opener returns 500 for race 11185 → record lists it in `failed_races`, race 11186 still in `files`.
  - `test_page_failure_stops_pass`: page returns 500 → `FetchError`.
- [ ] **Step 3: Run, expect failures** (`ModuleNotFoundError`).
- [ ] **Step 4: Implement** `parse_page` (regex on `BuildCounty\('([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)`), `load_sources`, `fetch_pass`.
- [ ] **Step 5: Run the suite, expect all green.**
- [ ] **Step 6: Commit** `Add ResultsAjax sources and fetch pass`.

### Task 2: Real fetch, fixtures, reader

**Files:**
- Modify: `pipeline/readers/resultsajax.py` (add `parse_race`, `parse_media_csv`, `parse_pass`), `pipeline/run_resultsajax.py` (add `main` with `fetch` command)
- Create: `pipeline/make_resultsajax_fixture.py`, fixtures `pipeline/tests/fixtures/ra_*`
- Test: `pipeline/tests/test_resultsajax.py`

**Interfaces:**
- Produces: `parse_race(body: bytes) -> list[dict] | None` (None for `{"d": null}`, empty list stays empty).
- Produces: `parse_media_csv(text: str) -> dict[(str, str), dict]` keyed by (race_id, candidate_id), value has `votes` (int), `race_name`, `candidate_name`, `party`, `precincts` (wrapper `="…"` stripped).
- Produces: `parse_pass(record_path: str) -> (rows, summary)`; summary keys: `races_on_pages`, `races_parsed`, `races_no_data`, `failed_races`, `counties_per_race`, `duplicate_keys`, `statewide_check`, `mismatches_counties_vs_media`, `media_races_not_on_pages`, `page_races_not_in_media`.

- [ ] **Step 1: Run one real fetch per state** (`python3 -m pipeline.run_resultsajax fetch <id>` after adding a minimal `main`), record pass record paths and request counts.
- [ ] **Step 2: Cut fixtures** with `make_resultsajax_fixture.py`: per state, the page lines for its US Senate race (NE also one CG race), that race's JSON as saved, and for SD/NE/NM the media CSV rows for those races; a `_fixture_source_sha256` note in a sidecar `.json` per fixture; a fixture pass record pointing at them.
- [ ] **Step 3: Write failing tests** (values read from the real files when cutting fixtures; the ones known now): MT Beaverhead race `450000000004069` candidate `27099` votes 2805, party `REP`; NM county ids stripped (`"01"`), votes int; OR candidate `300060094` party `NON` kept, `reporting_status` `"0/17 precincts"` for Baker; NE race 13224 present; every row's keys == `COLUMNS`; `test_media_ids_match_as_strings`; `test_null_race_listed`; `test_failed_race_in_summary`; `test_media_orphans_listed`; `test_county_sum_mismatch` (edit one county +1 → listed as `(race, cand, csv, sum)`); `test_duplicate_key_listed`; MT/OR `statewide_check == "not available"`; SD/NE/NM `"media CSV"` with 0 mismatches on fixtures; state rows exist only for SD/NE/NM.
- [ ] **Step 4: Run, expect failures.**
- [ ] **Step 5: Implement** the three functions.
- [ ] **Step 6: Run the suite, expect green.**
- [ ] **Step 7: Commit** `Add ResultsAjax reader with fixtures from MT NE NM OR SD`.

### Task 3: Parse CLI, real-file results, docs

**Files:**
- Modify: `pipeline/run_resultsajax.py` (`parse PASS_RECORD`, `fetch-parse`), `CLAUDE.md`
- Create: `docs/resultsajax.md`
- Test: `pipeline/tests/test_run_resultsajax.py` (`test_parse_command` writes `<parsed>/<id>/<ts>.csv` with header == `COLUMNS`)

- [ ] **Step 1: Write the failing parse-command test; run, expect failure.**
- [ ] **Step 2: Implement** parse output and the printed summary (lists printed as counts, plus the first 5 items of each non-empty mismatch list).
- [ ] **Step 3: Run the suite, expect green.**
- [ ] **Step 4: Parse each state's real pass record;** record races, counties, rows, mismatches per state in `docs/resultsajax.md` along with the quirks from the spec and anything new.
- [ ] **Step 5: Update `CLAUDE.md`** (step-2 section, test count, next platforms).
- [ ] **Step 6: Commit** `Add ResultsAjax parse CLI; record per-state results`.
