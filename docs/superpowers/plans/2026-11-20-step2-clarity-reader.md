# Clarity Reader (county level) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the 2026 general results of CO, SC, WV (statewide detail XML) and IA (statewide JSON) into the common output, plus a per-county turnout file for the XML states.

**Architecture:** `pipeline/run_clarity.py` runs a fetch pass (version file first, then data files built from that version) through the unchanged `pipeline/fetch.py`, and a parse step. `pipeline/readers/clarity.py` holds `parse_xml` and `parse_json`. Rows use `pipeline/schema.COLUMNS` unchanged.

**Tech Stack:** Python 3.14 stdlib only (`zipfile`, `gzip`, `xml.etree.ElementTree`, `json`, `tomllib`, `unittest`), Homebrew Python.

**Spec:** `docs/superpowers/specs/2026-11-20-step2-clarity-reader-design.md`

## Global Constraints

- Run everything with `/opt/homebrew/bin/python3`. Tests: `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .`
- Standard library only.
- `min_interval_s = 120` for every Clarity source id; `pipeline/fetch.py` is not modified.
- Raw bodies saved as received (gzip included) before parsing; nothing in the source is corrected; mismatches are listed in the summary.
- County level only: no county-site or precinct fetching.
- Commits: sole authorship, no `Co-Authored-By` trailer.

## Review Focus

1. `current_ver.txt` returns something that isn't a version (an HTML error page, empty) → the pass stops with `FetchError` before any data URL is built. (Task 1 test)
2. A body that is gzip-encoded though the URL says `.json` (Iowa does this) → parsed transparently; a plain body also works. (Task 3 test)
3. A county present under a `VoteType` but missing from that contest's `ParticipatingCounties` → row emitted with `reporting_status` `""`, not a crash. (Task 2 test)
4. An Iowa county's choice array shorter or longer than `sum.json`'s → that county/contest is skipped and listed, other rows still emitted. (Task 3 test)
5. A zip without `detail.xml` → `UnsupportedFormat`, not an empty parse. (Task 2 test)

---

### Task 1: Clarity sources and fetch pass

**Files:**
- Create: `pipeline/sources_clarity.toml`, `pipeline/run_clarity.py` (fetch part), `pipeline/tests/test_run_clarity.py`

**Interfaces:**
- Consumes: `pipeline.fetch.fetch(source_id, url, min_interval_s, raw_dir="data/raw", now=time.time, opener=None) -> path`, `FetchError`.
- Produces:
  - `load_sources(path=DEFAULT_SOURCES) -> dict` (TOML tables keyed by source id; keys `state`, `base`, `format` ∈ {"xml","json"}, `min_interval_s`).
  - `read_body(path) -> bytes`: file bytes, un-gzipped when they start with `b"\x1f\x8b"`.
  - `fetch_pass(source_id, src, raw_dir="data/raw", now=time.time, opener=None) -> dict`: `{"version": "387376", "paths": {"xml": p}}` or `{"version": ..., "paths": {"sum": p, "all": p}}`. Fetch ids: `<source_id>-ver`, then `<source_id>` (xml) or `<source_id>-sum`, `<source_id>-all` (json). URLs: `<base>/current_ver.txt`, `<base>/<v>/reports/detailxml.zip`, `<base>/<v>/json/sum.json`, `<base>/<v>/json/ALL.json`.

`sources_clarity.toml` entries (bases from the spec table): `clarity-CO-2026-general` (xml), `clarity-SC-2026-general` (xml), `clarity-WV-2026-general` (xml), `clarity-IA-2026-general` (json), each `min_interval_s = 120`, with a header comment pointing to the spec and `sources/registry.csv`.

- [ ] **Step 1: Write the failing tests** in `test_run_clarity.py`:
  - `test_sources_complete`: 4 entries; states {"CO","IA","SC","WV"}; every `min_interval_s >= 120`; every `base` starts with `https://` and does not end with `/`; IA is `json`, others `xml`.
  - `test_xml_pass_reads_version_first`: injected opener records URLs and returns `(200, b"387376\r\n")` for the version URL, `(200, b"PK...")` otherwise; with a temp raw dir, `fetch_pass("clarity-CO-2026-general", src)` requests exactly `[base+"/current_ver.txt", base+"/387376/reports/detailxml.zip"]` in that order and returns version `"387376"` with an existing `paths["xml"]`.
  - `test_json_pass_fetches_sum_and_all`: same with IA; URLs end `/387368/json/sum.json` then `/387368/json/ALL.json`; `paths` has `sum` and `all`.
  - `test_bad_version_stops_pass`: version body `b"<html>oops</html>"` → `FetchError`; the opener saw only the version URL.
  - `test_read_body_gunzips`: a file holding `gzip.compress(b'{"a":1}')` reads back as `b'{"a":1}'`; a plain file reads unchanged.
- [ ] **Step 2: Run** `/opt/homebrew/bin/python3 -m unittest pipeline.tests.test_run_clarity -v` → FAIL (module missing).
- [ ] **Step 3: Implement** the TOML and the three functions. Version = `read_body(path).decode().strip()`; must match `^\d+$` else `FetchError`.
- [ ] **Step 4: Run** the module tests → PASS; full suite → 25 + 5 pass.
- [ ] **Step 5: Live pass, once per state** (network; 2–3 requests per state): `/opt/homebrew/bin/python3 -c "from pipeline.run_clarity import *; s=load_sources(); [print(k, fetch_pass(k, v)) for k, v in s.items()]"`. Expected: four versions, files under `data/raw/clarity-*`, rows in `data/raw/manifest.csv`. Record bytes and versions in the ledger.
- [ ] **Step 6: Commit** `pipeline/sources_clarity.toml pipeline/run_clarity.py pipeline/tests/test_run_clarity.py` — "Add Clarity sources and version-first fetch pass".

### Task 2: XML reader and fixtures (CO, SC, WV)

**Files:**
- Create: `pipeline/readers/clarity.py` (XML part), `pipeline/make_clarity_fixture.py`, `pipeline/tests/test_clarity.py`, fixtures `pipeline/tests/fixtures/clarity_co.zip`, `clarity_sc.zip`, `clarity_wv.zip`
- Modify: `pipeline/schema.py` — `write_csv(rows, path, columns=COLUMNS)`

**Interfaces:**
- Consumes: `read_body` (Task 1) is not needed here (zip is read with `zipfile`).
- Produces:
  - `UnsupportedFormat(ValueError)`.
  - `TURNOUT_COLUMNS = ["state","source_id","source_sha256","county_name","registered_voters","ballots_cast","precincts_participating","precincts_reported"]`.
  - `parse_xml(zip_path, state, source_id) -> (rows, summary, turnout)`. Summary keys: `election_name`, `timestamp`, `contests`, `counties`, `vote_types` (sorted distinct names), `mismatches_vote_types_vs_total` [(contest_id, choice_id, total, vt_sum)], `mismatches_counties_vs_vote_type` [(contest_id, choice_id, vote_type, vt_votes, county_sum)], `unknown_elements` [(contest_id, tag)].
  - `make_clarity_fixture.py`: `make_xml_fixture(src_zip, out_zip, contest_keys)` keeps the header elements, `ElectionVoterTurnout` whole, and only the listed contests (all their counties); writes `detail.xml` into `out_zip` with a leading comment `fixture source sha256 <sha of src_zip>`.

Row rules (spec "Design"): state rows = `TOTAL` (choice `totalVotes`) + one per `VoteType` as published; county rows = one per (vote type, county) as published, no county `TOTAL`; `contest_scope="statewide"`, `county_id=""`, `county_name`=County `name`; `contest_id`=Contest `key`, `choice_id`=Choice `key`, `choice`=`text`, `party`=`party`, `vote_for`=`voteFor`, `contest_type="question"` iff `isQuestion=="true"`; `source_created_at`=`Timestamp` text and `election_date`=`ElectionDate` text as published; votes as `int`; county `reporting_status` = `f"{precinctsReported}/{precinctsParticipating} precincts"` from the contest's `ParticipatingCounties` entry with that name, else `""`; state rows `""`. Turnout: one row per `ElectionVoterTurnout/Counties/County` (`totalVoters` → registered_voters, ints).

- [ ] **Step 1: Cut fixtures** from the Task 1 raw zips: CO contest `20`; SC contests `21500,40111`; WV contest `100`.
- [ ] **Step 2: Write the failing tests** in `test_clarity.py` (values from the real files):
  - CO: state `TOTAL` for choice_id `"2"` (John Hickenlooper, DEM) = 1629521; county row Adams, vote_type `"Total Votes"`, choice_id `"1"` = 62394 with `reporting_status` `"395/395 precincts"`; no county row has vote_type `TOTAL`; turnout Adams = registered 330215, ballots 202413, precincts 401/401; `summary["election_name"] == "2026 General"`.
  - SC: Abbeville, contest `21500`, choice_id `"003"` (REP Alan Wilson / Mike Reichenbach) by vote type = {"Election Day": 3824, "Early Voting": 1877, "Absentee By Mail": 38, "Failsafe": 0, "Provisional": 2, "Failsafe Provisional": 0}; state `TOTAL` 1051334; contest `40111` rows all `contest_type == "question"`, `contest_scope == "statewide"`.
  - WV: Barbour, contest `100`, choice_id `"001"` (SHELLEY MOORE CAPITO) vote_type `"Election Day"` = 2330; state TOTAL 266772.
  - All three: `list(r) == COLUMNS` for every row; both mismatch lists empty.
  - `test_vote_type_mismatch_reported`: fixture copy with one `VoteType@votes` +1 → listed in `mismatches_vote_types_vs_total` and in `mismatches_counties_vs_vote_type`; the row keeps the published (edited) value.
  - `test_county_missing_from_participating`: remove Adams from `ParticipatingCounties` → Adams rows have `reporting_status == ""`.
  - `test_zip_without_detail_xml`: zip holding only `other.xml` → `UnsupportedFormat`.
  - `test_unknown_element_listed`: add `<Foo/>` under a Contest → `(contest_id, "Foo")` in `unknown_elements`, rows unchanged.
  - `test_turnout_csv`: `write_csv(turnout, path, TURNOUT_COLUMNS)` header equals `TURNOUT_COLUMNS`.
- [ ] **Step 3: Run** `-m unittest pipeline.tests.test_clarity -v` → FAIL (import error).
- [ ] **Step 4: Implement** `parse_xml` and the `columns` parameter.
- [ ] **Step 5: Run** module then full suite → PASS.
- [ ] **Step 6: Commit** reader, fixture maker, fixtures, tests, schema — "Add Clarity detail XML reader with fixtures from CO, SC, WV".

### Task 3: JSON reader (IA)

**Files:**
- Modify: `pipeline/readers/clarity.py` (JSON part), `pipeline/make_clarity_fixture.py`, `pipeline/tests/test_clarity.py`
- Create: fixtures `pipeline/tests/fixtures/clarity_ia_sum.json`, `clarity_ia_all.json`

**Interfaces:**
- Consumes: `read_body(path)` from `pipeline.run_clarity` — move it to `pipeline/readers/clarity.py` and import it in `run_clarity` (one definition).
- Produces:
  - `parse_json(sum_path, all_path, state, source_id) -> (rows, summary)`. Summary keys: `contests`, `counties`, `mismatches_counties_vs_state` [(contest_id, choice_id, statewide, county_sum)], `mismatches_total_area_vs_state` [(contest_id, choice_id, statewide, area_value)] (the `-1` area), `skipped_length_mismatch` [(area, contest_id)], `contests_only_in_counties` [(area, contest_id)].
  - `make_json_fixture(sum_src, all_src, out_sum, out_all, contest_keys)`: keeps listed contests in both files (all areas incl. `-1`), writes plain (un-gzipped) JSON with `_fixture_source_sha256` = [sha of sum_src, sha of all_src].

Row rules: state rows from `sum.json` (`TOTAL`, `V[i]`, `choice=CH[i]`, `choice_id=str(CHAggId[i])`, `party=P[i]`, `contest_name=C`, `vote_for=VF`, source_sha256 = sum file hash); county rows from `ALL.json` areas other than `-1` (`TOTAL`, position i of `V[C.index(K)]`, choice/party/id from `sum.json` position i, source_sha256 = ALL file hash); `election_name`, `source_created_at`, `election_date` empty (not in these files); `contest_scope="statewide"`.

- [ ] **Step 1: Cut fixtures** from the Task 1 IA raw files: contest `1000`.
- [ ] **Step 2: Write the failing tests:**
  - Adair, contest `1000`: {choice_id: votes} = {"1": 1921, "2": 1066, "3": 141, "30": 3}; choice for `"2"` is "Josh Turek", party "DEM"; state TOTAL {"1": 631276, "2": 688613, "3": 41829, "30": 1653}; no row has `county_name == "-1"`; both mismatch lists empty.
  - `test_json_gzip_and_plain`: gzip both fixture files into a temp dir → same rows as plain.
  - `test_json_length_mismatch_skipped`: drop the last value from Adair's array → `("Adair", "1000")` in `skipped_length_mismatch`, no Adair rows for 1000, other counties still present.
  - `test_json_county_sum_mismatch`: +1 on Adair choice 0 → `("1000", "1", 631276, 631277)` in `mismatches_counties_vs_state`.
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run** module + full suite → PASS.
- [ ] **Step 6: Commit** — "Add Clarity JSON reader for Iowa".

### Task 4: Parse CLI, real-file run, docs

**Files:**
- Modify: `pipeline/run_clarity.py` (add `main`), `pipeline/tests/test_run_clarity.py`, `CLAUDE.md`
- Create: `docs/clarity.md`

**Interfaces:**
- Produces: `main(argv=None)`; commands `fetch SOURCE_ID`, `parse SOURCE_ID PATH [PATH2]` (XML: zip; JSON: sum then all), `fetch-parse SOURCE_ID`; options `--sources`, `--raw-dir`, `--parsed-dir`. Writes `<parsed-dir>/<source_id>/<UTC ts>.csv` and, for XML, `<UTC ts>-turnout.csv`; prints row counts and mismatch counts like `run_ev`.

- [ ] **Step 1: Failing tests:** `test_parse_command_xml` (CO fixture → CSV header `COLUMNS` and a turnout CSV header `TURNOUT_COLUMNS`); `test_parse_command_json` (IA fixtures → CSV header `COLUMNS`, no turnout file).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Parse all four real files** from Task 1 with `parse`; record per state: rows, contests, counties, vote types, mismatch counts. Expected from recon: 0 mismatches each; CO 302 contests, SC 171, WV 126, IA 274.
- [ ] **Step 6: Docs:** `docs/clarity.md` (bases, file layout, version step, IA gzip and `-1` area, SC "Provionsal", WV "Election Day" label, per-state table from Step 5, precinct sites not covered); `CLAUDE.md` step 2 section gets a Clarity paragraph and the new test count.
- [ ] **Step 7: Commit** — "Add Clarity parse CLI; record per-state parse results".
