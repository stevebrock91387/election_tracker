# Step 2 (Enhanced Voting reader) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch the seven Enhanced Voting states' official exports politely, save each raw file with a hash before parsing, and parse them into one common long-format CSV.

**Architecture:** `pipeline/fetch.py` (rate-limited fetch + raw store + manifest), `pipeline/schema.py` (common columns + writer), `pipeline/readers/enhanced_voting.py` (parser), `pipeline/sources.toml` + `pipeline/run_ev.py` (CLI). Tests use small fixtures cut from real files.

**Tech Stack:** Python 3.14 (`/opt/homebrew/bin/python3`), standard library only, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-20-step2-ev-reader-design.md`

## Global Constraints

- Raw body saved unchanged and a manifest row written **before** any parse.
- `min_interval_s = 120` for every EV source; a fetch inside the interval raises, it never waits or retries silently.
- No repair of source data; mismatches are reported in the parse summary only.
- `vote_type` is `TOTAL` or the state's group name unchanged (including trailing spaces in names elsewhere: keep all strings raw).
- Nothing in `scenarios/` is touched. `data/` stays gitignored.
- Tests: `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .`

## Review Focus

1. A `reportingStatuses` value of `null` (as in UT) → no crash; county rows get empty status. (Task 2 test.)
2. An option with `groupResults` empty or absent → only a `TOTAL` row for it. (Task 2 test.)
3. Two fetches of the same source 119 s apart → second raises `FetchTooSoon`; 120 s apart → allowed. (Task 1 test.)
4. An HTTP error (non-200) → body still saved and manifest row written with the status, then `FetchError` raised. (Task 1 test.)
5. A ballot item with non-null `rankedChoiceResults` → `UnsupportedFormat`. (Task 2 test.)

---

### Task 1: Rate-limited fetch and raw store

**Files:** Create `pipeline/__init__.py`, `pipeline/fetch.py`; Test `pipeline/tests/__init__.py`, `pipeline/tests/test_fetch.py`

**Interfaces:**
- Produces: `class FetchTooSoon(RuntimeError)`, `class FetchError(RuntimeError)`; `fetch(source_id: str, url: str, min_interval_s: float, raw_dir: str = "data/raw", now: Callable[[], float] = time.time, opener: Callable[[str], tuple[int, bytes]] | None = None) -> str` (path of saved file). Default opener uses `urllib.request` with a 120 s timeout; `opener` is injected in tests.
- Saved path: `<raw_dir>/<source_id>/<YYYYMMDDTHHMMSSZ>.<ext>` (ext from the URL path, default `bin`). Manifest: `<raw_dir>/manifest.csv` with header `source_id,url,fetched_utc,http_status,bytes,sha256,path`. Last-fetch state: `<raw_dir>/.last_fetch.json` `{source_id: epoch_seconds}`; updated on every attempt that reaches the network.

- [ ] **Step 1: Failing tests** (temp dir as `raw_dir`, fake opener, fake clock):
  - `test_saves_body_and_manifest_before_return`: returned path's bytes == opener body; manifest last row has matching sha256 (hashlib) and bytes
  - `test_too_soon_raises` (RF3): fetch at t=1000, then t=1119 → `FetchTooSoon`; t=1120 → OK
  - `test_interval_survives_new_process`: second call reads `.last_fetch.json` written by the first (call `fetch` with a fresh clock only)
  - `test_http_error_saved_then_raises` (RF4): opener returns (404, b"nope") → `FetchError`; file and manifest row with status 404 exist
- [ ] **Step 2:** Run; FAIL (import). **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit "Add rate-limited fetch with raw store and manifest".

### Task 2: Common schema and Enhanced Voting parser

**Files:** Create `pipeline/schema.py`, `pipeline/readers/__init__.py`, `pipeline/readers/enhanced_voting.py`, `pipeline/make_ev_fixture.py`; fixtures `pipeline/tests/fixtures/ev_az_greenlee.json`, `pipeline/tests/fixtures/ev_ut_piute.json`; Test `pipeline/tests/test_enhanced_voting.py`

**Interfaces:**
- Produces: `schema.COLUMNS` (exact order: `state, source_id, source_sha256, source_created_at, election_name, election_date, level, county_id, county_name, precinct_id, precinct_name, precinct_is_virtual, contest_id, contest_name, contest_type, vote_for, choice, party, vote_type, votes, reporting_status`); `schema.write_csv(rows: Iterable[dict], path: str) -> int`.
- Produces: `class UnsupportedFormat(ValueError)`; `parse(path: str, state: str, source_id: str) -> tuple[list[dict], dict]`. Summary keys: `election_name, created_at, counties, has_precincts, has_vote_types, mismatches_state_vs_counties: list[(contest_id, choice, statewide, county_sum)], mismatches_groups_vs_total: list[(level, county_id, contest_id, choice, total, groups_sum)]`.
- Rows: per statewide option → one `TOTAL` row (level `state`) + one per group; per county option → `TOTAL` + groups (level `county`, `reporting_status` = county status for that group, empty for `TOTAL` and when statuses are null); per precinct → `TOTAL` + groups (level `precinct`, status = precinct `reportingStatus`). `source_sha256` = SHA-256 of the file at `path`. Statewide status fields ignored.
- `make_ev_fixture.py SRC OUT --county NAME --contests ID,ID`: copies top-level fields, statewide items filtered to the contests, and only the named county filtered to the contests; adds `"_fixture_source_sha256"` with the source file's hash. No values changed.

Fixtures to build: AZ from `data/raw/az-2026/export-110326GeneralElection-20261120T202934Z.json`, county "Greenlee County", contests `AZ-6,AZ-10`; UT from `data/raw/ev-2026/UT-export-General11032026-20261120T233411Z.json`, county "Piute County", contest `636107054` (its first item).

- [ ] **Step 1: Build fixtures** with the script (it has no logic beyond filtering; its test is that the parser tests below pass on real values).
- [ ] **Step 2: Failing tests** on the fixtures (values taken from the real files):
  - `test_az_county_totals`: Greenlee AZ-6 TOTAL rows: Juan Ciscomani (Republican) 1181, JoAnna Mendoza (Democratic) 824, Jereme Lance Peters (Libertarian) 35
  - `test_az_vote_types`: Ciscomani Greenlee groups Election Day 436, Early Voting 600, Provisional 12, Early A.R.S. 16-579 0, Late Early* 133; status for "Early A.R.S. 16-579" row is "Not Participating"
  - `test_az_precinct_row`: precinct "001 Eagle" (id 2800) Ciscomani TOTAL 17, status "Partially Reported", is_virtual False
  - `test_az_statewide_rows`: AZ-6 statewide TOTAL Mendoza 190058, Ciscomani 160972
  - `test_mismatch_reported_not_fixed`: on the AZ fixture (one county only) the summary lists state-vs-county mismatches for AZ-6 (e.g. Mendoza 190058 vs 824) and the statewide TOTAL row still says 190058
  - `test_ut_missing_detail` (RF1, RF2): UT Piute contest 636107054 county TOTAL rows: CELESTE MALOY 613, KENT S. UDELL 62, CASSIE EASLEY 21, AYDEN SCOTT 7; no group rows; no precinct rows; `has_precincts` and `has_vote_types` False; empty county status
  - `test_ranked_choice_raises` (RF5): a copy of the UT fixture with `rankedChoiceResults` set on one item → `UnsupportedFormat`
  - `test_columns_and_csv`: every row has exactly `COLUMNS`; `write_csv` header equals `COLUMNS`
  - `test_full_az_file` (skipped if the raw file is absent): `mismatches_state_vs_counties == []`, `mismatches_groups_vs_total == []` at state level, 15 counties
- [ ] **Step 3:** Run; FAIL. **Step 4:** Implement. **Step 5:** Run; PASS.
- [ ] **Step 6:** Commit "Add common results schema and Enhanced Voting parser".

### Task 3: Seven-state sources and CLI; confirm each state parses

**Files:** Create `pipeline/sources.toml`, `pipeline/run_ev.py`; Test `pipeline/tests/test_run_ev.py`

**Interfaces:**
- Consumes: `fetch` (Task 1), `parse`, `write_csv` (Task 2).
- Produces: `load_sources(path) -> dict[str, dict]` keyed by source_id with `state`, `url`, `min_interval_s`; CLI `python3 -m pipeline.run_ev fetch SOURCE_ID` / `parse PATH SOURCE_ID` / `fetch-parse SOURCE_ID`, writing `data/parsed/<source_id>/<timestamp>.csv` and printing the summary.
- `sources.toml` entries (URLs from `docs/enhanced-voting.md` and the registry): `ev-AZ-2026-general` (app.enhancedvoting.com/cdn/results/Arizona/export-110326GeneralElection.json), `ev-GA-2026-general`, `ev-UT-2026-general`, `ev-WA-2026-general`, `ev-VA-2026-general`, `ev-RI-2026-general`, `ev-ID-2026-general`; all `min_interval_s = 120`.

- [ ] **Step 1: Failing tests:** `test_sources_complete` (7 entries, states {AZ,GA,UT,WA,VA,RI,ID}, every interval ≥ 120, every URL https and ending in `.json`); `test_parse_command_writes_csv` (runs the `parse` command on the AZ fixture into a temp dir; CSV header == COLUMNS).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5: Live confirmation (network, once per state):** `fetch-parse` for GA, WA, VA, RI, ID (AZ and UT are already saved; parse those). Record each summary (counties, has_precincts, has_vote_types, mismatch counts) in `docs/enhanced-voting.md`. Any parse failure → stop and fix the parser with a new test from that file first.
- [ ] **Step 6:** Commit "Add EV sources and CLI; record per-state parse results".
