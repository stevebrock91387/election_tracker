# Ohio Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** County-level Ohio results for all 162 contests in the live NIST 1500-100 XML feed, in the common format, plus a county turnout table, with every anomaly listed.

**Architecture:** A fetch pass saves the feed once through `pipeline/fetch.py` and writes a pass record; `pipeline/readers/oh.py` emits one row per (selection, GpUnit count) and a turnout row per county, and lists what doesn't add up. Nothing is corrected.

**Tech Stack:** Python 3.14 stdlib (`xml.etree.ElementTree`), `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-oh-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (133 before this plan).
- Every download through `pipeline.fetch.fetch`; `min_interval_s = 120`; one request per pass.
- Namespace `http://grouper.ieee.org/groups/1622/groups/2/V1/1622_2-election_results_reporting.xsd`.
- `vote_type = "TOTAL"`; `contest_scope = "statewide"`; the contest's own-unit count (state or district) is `level = "state"`; county counts are `level = "county"`.
- Nothing corrected; every anomaly listed; a check that could not run is `None` ("not checked").
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. The body is not XML (a Cloudflare challenge page, an empty body) → listed under `unreadable_files`, no rows, every check `None` (test `test_html_body_not_checked`).
2. The root is in a different namespace (a feed version change) → listed as `unexpected_namespace`, not read as 0 contests that pass every check (test `test_unexpected_namespace_listed`).
3. A count for a GpUnit that exists but is neither a county nor the contest's own unit (e.g. another district) → listed under `counts_outside_contest`, row still emitted with `level` empty (test `test_count_outside_contest_listed`).
4. Missing optional attributes mid-election (no `VotesAllowed`, no `SubUnitsReported`, no `SummaryCounts`) → empty fields, no crash (test `test_missing_optional_attributes`).
5. A county count that exists while the own-unit count is missing → listed under `own_unit_count_missing`, and the sum check for that selection is skipped rather than compared with 0 (test `test_own_unit_missing_listed`).

---

### Task 1: Saved file extension, sources and fetch pass

**Files:** Modify `pipeline/fetch.py` (optional `ext` keyword); Create `pipeline/sources_oh.toml`, `pipeline/run_oh.py` (`load_sources`, `fetch_pass`, `main` with `fetch`); Test `pipeline/tests/test_fetch.py` (one test), `pipeline/tests/test_run_oh.py`.

**Interfaces:**
- Produces: `fetch(source_id, url, min_interval_s, raw_dir="data/raw", now=time.time, opener=None, ext=None) -> path`; `ext=None` keeps today's behaviour (extension from the URL path, else `bin`), a given `ext` is used as is. `fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None) -> record path`; record JSON `{"source_id", "state", "started_utc", "files": [{"kind": "xml", "path": ...}]}`.

- [ ] Failing tests: `test_fetch_ext_override` in `test_fetch.py` (URL `https://example.test/Api/v1/download?filename=X`, `ext="xml"` → saved path ends `.xml`; without `ext` → `.bin`); in `test_run_oh.py`: `test_sources_complete` (`oh-2026-general` has `state = "OH"`, `xml_url` = `https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob`, `min_interval_s = 120`); `test_pass_record` (fake opener; one request to `xml_url` under source id `oh-2026-general-xml`; record kind `xml`, path ends `.xml`); `test_failure_stops_pass` (a 403 raises `FetchError`, no record written).
- [ ] Run (fail), implement, suite green, commit `Add OH sources and fetch pass; let fetch take a file extension`.

### Task 2: Fixture and reader

**Files:** Create `pipeline/make_oh_fixture.py`, `pipeline/readers/oh.py`, fixtures `pipeline/tests/fixtures/oh.xml`, `oh_pass.json`; Test `pipeline/tests/test_oh.py`.

**Interfaces:**
- Consumes: the pass record from Task 1.
- Produces: `parse_pass(record_path, base_dir=".") -> (rows, summary, turnout)`; `TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters", "ballots_cast", "provisional_outstanding", "uocava_absentee_outstanding", "absentee_ballots_cast_as_published", "precincts_reported", "precincts_total"]`.
- Summary keys (lists unless noted): `contests`, `selections`, `counties` (ints), `election_status` (str, root `Status`), `bad_sums` (contest, selection, own-unit count, county sum), `own_unit_count_missing`, `own_unit_count_repeated`, `unknown_gpunits`, `counts_outside_contest`, `non_numeric_votes`, `unknown_candidates`, `unknown_parties`, `bad_measure_ids`, `duplicate_counts`, `unexpected_count_types`, `absentee_exceeds_total`, `unreferenced_county_units` (int), `same_named_contests`, `write_ins` (contest, selection), `unexpected_namespace`, `unreadable_files`, `missing_files`.

- [ ] `make_oh_fixture.py SRC OUT`: copy the real feed keeping every GpUnit and Election attribute, only these contests, and only the Candidates, Parties and Offices they reference:
  - `_55A742EA56A709A3E0633390EE0AE290` US Senator
  - `_55A742EA571009A3E0633390EE0AE290` House 10 and `_55A742EA574109A3E0633390EE0AE290` House 8 (both have a Butler part)
  - `_58F2C0185A8C8A6AE0633390EE0AF8C5` State Issue 3
  - `_55A742EA542A09A3E0633390EE0AE290` Governor and Lieutenant Governor
  - `_55A742EA55F109A3E0633390EE0AE290`, `_55A742EA564C09A3E0633390EE0AE290` the two "Justice of the Supreme Court"

  Real fetch first (`run_oh fetch oh-2026-general`), cut from that file.
- [ ] Failing tests, real values from the fixture:
  - Senate, Brown (`_BS55A742EA61EF09A3E0633390EE0AE290`): state row `votes == 2301042`, `level == "state"`, `county_id == ""`; Adams row `votes == 2123`, `county_id == "_55A742EA504C09A3E0633390EE0AE290"`, `county_name == "Adams"`, `reporting_status == "21/21 precincts"`, `choice == "Sherrod Brown"`, `party == "DEM"`, `contest_type == "U.S. Senator"`, `vote_for == "1"`.
  - House 10, Turner (`_BS55A742EA571109A3E0633390EE0AE290`): own-unit row `level == "state"`, `votes == 144086`; Butler row `votes == 14876`.
  - Governor ticket `_BS55A742EA5F7909A3E0633390EE0AE290`: `choice == "Amy Acton and David Pepper"`, `party == "DEM"`, state `votes == 2404178`.
  - Issue 3: `_YES…` → `choice == "Yes"`, state `votes == 2934245`; `_NO…` → `"No"`, `1556864`; `vote_for == ""`.
  - Every row: `source_created_at == "2026-11-13T09:43:04Z"`, `election_date == "2026-11-03"`, `election_name == "November 3, 2026 General Unofficial Canvass"`, `vote_type == "TOTAL"`, keys == `COLUMNS`.
  - Summary: `bad_sums == []`, `election_status == "UnofficialComplete"`, `unreferenced_county_units == 88`, `len(absentee_exceeds_total) == 88`, the Supreme Court pair in `same_named_contests`, the Senate's three write-in ids in `write_ins`, `counties == 88`.
  - Turnout: 88 rows; Adams `registered_voters == 17079`, `ballots_cast == 9169`, `absentee_ballots_cast_as_published == 62074`, `provisional_outstanding == 129`, `uocava_absentee_outstanding == 4`, `precincts_reported == 21`, `precincts_total == 21`.
- [ ] Failing synthetic tests (the fixture text edited in the test, written to a temp dir): `test_bad_sum_listed` (Brown's Adams count +1), `test_own_unit_missing_listed`, `test_own_unit_repeated_listed`, `test_unknown_gpunit_listed`, `test_count_outside_contest_listed` (a Senate count for `Congressional District 1`), `test_non_numeric_votes_listed` (row kept, `votes == ""`), `test_unknown_candidate_and_party_listed`, `test_bad_measure_id_listed` (`choice == ""`), `test_duplicate_count_listed`, `test_unexpected_count_type_listed`, `test_missing_optional_attributes`, `test_html_body_not_checked`, `test_unexpected_namespace_listed`, `test_missing_file_listed`.
- [ ] Run (fail), implement, suite green, commit `Add OH reader with a fixture from the 2026 feed`.

### Task 3: Parse CLI, real-feed results, docs

**Files:** Modify `pipeline/run_oh.py` (`parse`, `fetch-parse`), `CLAUDE.md`; Create `docs/oh.md`; Test `test_parse_command` in `test_run_oh.py`.

- [ ] Failing `test_parse_command`: parsing the fixture pass writes `<stamp>.csv` and `<stamp>-turnout.csv` (header `TURNOUT_COLUMNS`) and prints summary lines as `run_nc` does ("not checked" for `None`). Implement, suite green.
- [ ] Parse the real pass; record in `docs/oh.md`: where the feed is, file bytes and SHA-256, rows, contests, counties, every non-empty list with counts and examples, and the quirks from the spec (two county units per county, absentee BallotsCast, ballot measures without text, duplicate names, no FIPS, `.xml` from the `ext` override).
- [ ] Update `CLAUDE.md` (step 2 section, next is Texas); commit `Add OH parse CLI; record 2026 results`.
