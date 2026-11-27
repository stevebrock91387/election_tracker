# Step 4: Expected Vote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** County expected-vote ranges for the 2026 general from MEDSL 2018/2022 baselines checked exactly against the FEC, scored against the certified 2026 results already in `data/results.sqlite`.

**Architecture:** A new package `pipeline/expected/`. The stages are inputs (fetch), medsl (precinct → county with recorded fixes), fec (official state totals), check (per state, year and office), baseline (top race per county), registration (2026, from the step-3 database), compute (point/low/high) and score (2026 dry run). Each stage writes a CSV under `data/expected/`; a CLI runs them.

**Tech Stack:** Python 3.14 stdlib only; `pipeline.fetch.fetch` for downloads; `pipeline.readers.wy.read_xlsx` for the FEC xlsx; `tools.medsl_county.NON_CANDIDATES` imported, not modified.

**Spec:** `docs/superpowers/specs/2026-11-27-step4-expected-vote-design.md`

## Global Constraints

- Stdlib only; run with `/opt/homebrew/bin/python3` (tests also pass under `.venv/bin/python`).
- `tools/` and `sources/` are not modified.
- Downloads go through `pipeline/fetch.py` (project user agent `election-tracker-fetch/0.1`, manifest row, TLS verification on).
- MEDSL 2022: `data/raw/medsl-2022-precinct` (commit `a8126c5790b8`). MEDSL 2018: Harvard Dataverse, U.S. Senate `doi:10.7910/DVN/DGNAFS`, U.S. House `doi:10.7910/DVN/IVIXLK`, State `doi:10.7910/DVN/ZFXEJU`, pinned by dataset version and file SHA-256.
- FEC: `https://www.fec.gov/documents/2706/federalelections2018.xlsx`, `https://www.fec.gov/documents/5676/federalelections2022.xlsx`.
- Offices for the top race: `US SENATE`, `GOVERNOR`, `US HOUSE` (summed over the county's districts); a tie goes in that order.
- The check is exact, per (state, year, office). Counties use only offices that passed; GOVERNOR only if both federal offices in the state passed (`checked_via = "federal rows"`).
- Fixes live in `pipeline/expected/medsl_fixes.toml`, each with state, year, office, change, evidence and before/after differences, and must produce an exact match. No fix without an identified cause.
- Compute formulas (spec, verbatim):
  - "rate × registration": rate_y = votes_y ÷ registered_y; point = rate_latest × registered_target; low/high = min/max of rate_y × registered_target.
  - "raw": point = votes_latest; low/high = min/max of the two years' votes.
  - "one year": point = low = high = that year's value.
  - Both years missing: no row; the county is listed with the reason.
- Nothing imputed, interpolated or clamped. Every row carries its source and check status.
- Outputs go in `data/expected/` (gitignored with `data/`).

## Review Focus

1. Counties in one year but not the other (Connecticut's 2022 planning regions replacing counties, other FIPS changes) must yield "one year" or be listed, never mis-joined. Test: Task 6 `test_county_in_one_year_only`.
2. MEDSL rows with a blank or pseudo county (statewide absentee, UOCAVA "federal" units, Alaska) count in the state check but are no county's baseline, and they're listed. Test: Task 2 `test_blank_county_rows_listed_not_assigned`.
3. House at-large districts are numbered differently (MEDSL "0", "000" or "AT-LARGE"; FEC "00"), so they must normalize to one key, or every at-large state fails the check. Test: Task 3 `test_at_large_district_keys_match`.
4. A 2026 state-legislature contest ("State Senate District 12", "Senate District 4") must not classify as US SENATE in scoring. Test: Task 7 `test_classify_office`.
5. A suppressed `*` precinct row makes a state's office fail the exact check (CA, KS, NM, NV). No fix can restore it, so the office stays failed and the reason says suppression. Test: Task 3 `test_suppressed_rows_fail_with_reason`.

---

### Task 1: Inputs (FEC files, MEDSL 2018 from Dataverse)

**Files:**
- Create: `pipeline/expected/__init__.py`, `pipeline/expected/inputs.py`, `pipeline/expected/inputs.toml`
- Test: `pipeline/tests/test_expected_inputs.py`

**Interfaces:**
- Produces: `fetch_fec(year: int, raw_dir: str, opener=None) -> str` (path to the saved xlsx; source id `fec-<year>-federalelections`).
- Produces: `fetch_dataverse(doi: str, name: str, raw_dir: str, api_get=None, opener=None, sleep=time.sleep) -> str`. It writes and returns `data/raw/medsl-2018-<name>/files.json`: `{"doi", "version", "files": [{"filename", "id", "path", "sha256", "bytes"}]}`. Each file is saved through `fetch` (source id `medsl-2018-<name>-<filename stem>`, 2 s apart).
- `inputs.toml` holds the FEC URLs and the three DOIs with names `senate`, `house`, `state`.

- [ ] **Step 1:** Look before writing. Fetch `https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=<doi>` for each DOI and record the version, file names and sizes in the doc draft.
  - If the three datasets together exceed 2 GB, stop and ask Steve: the 2022 inputs were 89.6 MB.
  - Download via `https://dataverse.harvard.edu/api/access/datafile/<id>?format=original` (the CSV, not the `.tab`).
- [ ] **Step 2:** Write the failing tests `test_fetch_fec_saves_through_fetch` (fake opener returns `b"PK"`; the path ends `.xlsx`; a manifest row exists) and `test_fetch_dataverse_records_version_and_hashes` (a fake `api_get` returns a two-file dataset; `files.json` lists both with sha256 of the bodies and the dataset version; `sleep` is called once).
- [ ] **Step 3:** Run `/opt/homebrew/bin/python3 -m unittest pipeline.tests.test_expected_inputs`. Expected: ImportError.
- [ ] **Step 4:** Implement both functions. `api_get(url) -> dict` defaults to a urllib JSON GET with the project user agent.
- [ ] **Step 5:** Run the tests. Expected: OK.
- [ ] **Step 6:** Run the real fetches (FEC 2018 and 2022; the three Dataverse datasets) and check each file's header line.
- [ ] **Step 7:** Commit (`pipeline/expected/`, the test).

### Task 2: MEDSL precincts → county candidate totals, with fixes

**Files:**
- Create: `pipeline/expected/medsl.py`, `pipeline/expected/medsl_fixes.toml` (empty list with a header comment giving the entry schema)
- Test: `pipeline/tests/test_expected_medsl.py` (fixtures: small CSVs written in the test)

**Interfaces:**
- Consumes: `tools.medsl_county.NON_CANDIDATES`.
- Produces: `read_precincts(paths: list[str], year: int) -> Iterator[dict]`. It yields normalized precinct rows {state_po, county_fips, county_name, precinct, office, district, special, candidate, party, writein, mode, votes (str as in the file)}. Rows: office in {US SENATE, US HOUSE, GOVERNOR}, stage GEN. 2022 zips (`*.zip`, one CSV each) and 2018 CSVs are both accepted. `COLUMNS_2018` maps the 2018 headers to these names; fill it from Task 1 step 6 (identity if they match).
- Produces: `load_fixes(path) -> list[dict]` and `apply_fixes(rows, fixes, applied: list) -> Iterator[dict]`. One fix type for now: `action = "drop"` with `match = {field: value}` (all must equal). `applied` gets (fix id, rows dropped). A new fix type is added only with its own test.
- Produces: `county_totals(rows) -> (totals: list[dict], notes: dict)`.
  - totals: {state_po, county_fips, county_name, office, district, special, candidate, writein, votes, suppressed_rows}, summed with medsl_county's rules (TOTAL mode preferred per precinct-candidate, `*` not counted but counted in suppressed_rows, NON_CANDIDATES dropped).
  - notes: {"blank_county": Counter by state, "suppressed": Counter by (state, office)}.
  - Rows with a blank county_fips go in a county "" bucket that's kept for the state check and noted.

- [ ] **Step 1:** Write the failing tests:
  - `test_total_mode_preferred_and_star_counted`: a precinct-candidate with TOTAL 10 and ELECTION DAY 6 gives 10; a `*` row adds 1 to suppressed_rows.
  - `test_non_candidates_dropped`: "UNDERVOTES" gives no row.
  - `test_blank_county_rows_listed_not_assigned`: a blank county_fips goes to county "" and `notes["blank_county"]["AK"] == 1`.
  - `test_drop_fix_applied_and_recorded`: a fix matching one precinct removes its votes and `applied == [("NJ-2022-1", 1)]`.
  - `test_2018_columns_mapped`: a 2018-header CSV reads the same rows.
- [ ] **Step 2:** Run `/opt/homebrew/bin/python3 -m unittest pipeline.tests.test_expected_medsl`. Expected: ImportError.
- [ ] **Step 3:** Implement. Read zips in place, as `tools/medsl_county.py` does.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit.

### Task 3: FEC totals and the exact check

**Files:**
- Create: `pipeline/expected/fec.py`, `pipeline/expected/check.py`
- Test: `pipeline/tests/test_expected_check.py`

**Interfaces:**
- Consumes: `pipeline.readers.wy.read_xlsx`; `county_totals` output (Task 2).
- Produces: `read_fec(path: str, year: int) -> list[dict]`: {state_po, office ("US SENATE" or "US HOUSE"), district, special, candidate, writein, votes}, one per candidate in the general.
  - The FEC's "Combined Parties" line is used where present (fusion: NY, CT); otherwise the single party line.
  - "Scattered" and "Write-in" lines are writein.
  - Sheet and column names are confirmed from the real file in step 1 and written in the module docstring.
- Produces: `district_key(office, district) -> str`. US SENATE gives "" (plus "special" for a special election); US HOUSE gives a zero-padded two-digit number, with at-large ("0", "00", "000", "AT-LARGE", "AT LARGE") as "00".
- Produces: `check(medsl_totals: list[dict], fec: list[dict], year: int, notes: dict) -> dict[(state_po, office), dict]`, with values {"passed": bool, "differences": [...], "reason": str}.
  - Per (state, office, district key), on each side: sum candidates over counties and party lines (by candidate name on the MEDSL side, by FEC line on the FEC side), sort the non-write-in totals, and add up the write-ins.
  - Passed when, for every district, both sorted lists are equal and the write-in totals are equal (a missing write-in line counts as 0).
  - Otherwise the differences are listed per district (MEDSL list, FEC list).
  - The reason is "suppressed rows" when `notes["suppressed"]` has the (state, office) and the office failed. It's "not in FEC" when the office has no FEC rows (no Senate race that year) and "passed" otherwise. An office absent from both sides isn't a key.

- [ ] **Step 1:** Open both FEC files with `read_xlsx` and write down the Senate and House sheet names and the columns for state, district, candidate, party, general votes and the combined-parties marker.
- [ ] **Step 2:** Write the failing tests:
  - `test_exact_match_passes`;
  - `test_one_vote_off_fails_with_district_listed`;
  - `test_fusion_lines_summed_against_combined`: MEDSL has a candidate on DEM 100 and WOR 5 lines; the FEC has Combined Parties 105;
  - `test_at_large_district_keys_match`: MEDSL "0" and FEC "00" match;
  - `test_suppressed_rows_fail_with_reason`;
  - `test_read_fec_on_real_layout`: a 3-row workbook built in the test with the step-1 sheet and columns.
- [ ] **Step 3:** Run `/opt/homebrew/bin/python3 -m unittest pipeline.tests.test_expected_check`. Expected: ImportError.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run the tests. Expected: OK.
- [ ] **Step 6:** Commit.

### Task 4: Baselines

**Files:**
- Create: `pipeline/expected/baseline.py`
- Test: `pipeline/tests/test_expected_baseline.py`

**Interfaces:**
- Consumes: `county_totals`, `check` results.
- Produces: `baselines(totals: list[dict], checks: dict, year: int, provenance: dict) -> (rows: list[dict], listed: list[tuple])`.
  - rows: {state, county_fips, county_name, year, top_office, votes, suppressed_rows, check, checked_via, medsl_source, fec_file_sha256}.
  - Contest votes = the sum of all candidates, write-ins included. US HOUSE is summed over the county's districts; two Senate contests (a special) are separate contests, the larger counting.
  - Only offices whose check passed are eligible (GOVERNOR only if both federal offices passed or don't exist).
  - Counties with no eligible office are listed (county, reason). County "" is never a row.
- CSV columns: `BASELINE_COLUMNS` (the row keys above, in that order).

- [ ] **Step 1:** Write the failing tests:
  - `test_top_race_is_largest_eligible`: Senate 900 failed, House 950 passed → House 950;
  - `test_governor_needs_both_federal_offices`;
  - `test_tie_order_senate_governor_house`;
  - `test_house_summed_over_districts_in_county`;
  - `test_no_eligible_office_listed`.
- [ ] **Step 2:** Run the tests. Expected: ImportError.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit.

### Task 5: 2026 registration from the step-3 database

**Files:**
- Create: `pipeline/expected/registration.py`
- Test: `pipeline/tests/test_expected_registration.py` (builds a small SQLite database with `pipeline.db.connect` on a temp path)

**Interfaces:**
- Produces: `registration_2026(conn) -> (rows: list[dict], listed: list[tuple])`.
  - rows: {state, county_name, registered, source_id, snapshot_id}.
  - Taken from the `turnout` table for each source's latest snapshot, summed by (state, county_name) where county_name is non-empty and the turnout row is not a town.
  - Town-level sources (CT, VT, MA, and any layout whose result level is "town") are listed, not summed.
  - A state with two sources for the same county takes neither; it's listed as "two sources".
  - Units whose registered voters are NULL are listed.

- [ ] **Step 1:** Write the failing tests:
  - `test_precinct_turnout_summed_to_county`;
  - `test_latest_snapshot_only`;
  - `test_town_layout_listed_not_summed`;
  - `test_two_sources_same_county_listed`.
- [ ] **Step 2:** Run the tests. Expected: ImportError.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit.

### Task 6: Compute expected vote

**Files:**
- Create: `pipeline/expected/compute.py`
- Test: `pipeline/tests/test_expected_compute.py`

**Interfaces:**
- Consumes: baseline rows for the two comparable years; registration rows by (state, county, year).
- Produces: `norm_county(name: str) -> str`.
  - Case-fold and collapse spaces; drop a trailing " county", " parish", " borough", " census area" or " city and borough"; "st." becomes "saint", "ste." becomes "sainte".
  - Rules are listed in the docstring. Independent cities ("Baltimore city", "Richmond city") keep "city", so they stay distinct from same-named counties.
- Produces: `expected(target: int, years: tuple[int, int], baselines: dict[int, list[dict]], registration: dict[tuple, int]) -> (rows: list[dict], listed: list[tuple])`.
  - Counties are joined across years on (state, county_fips).
  - Registration is joined on (state, norm_county(name), year).
  - The formulas are in Global Constraints.
  - rows: {state, county_fips, county_name, target, point, low, high, method, reason, years_used}. Point, low and high are rounded to the nearest integer only at output (`round()`, half to even).

- [ ] **Step 1:** Write the failing tests:
  - `test_raw_method_without_registration`: 2018 1,000 and 2022 1,200 give point 1200, low 1000, high 1200, method "raw", with the reason naming the missing registration years;
  - `test_rate_method`: registered 2018 2,000, 2022 2,400, 2026 2,500 → rates 0.5 and 0.5, point 1250, low 1250, high 1250;
  - `test_county_in_one_year_only`: present only in 2022 → method "one year", point = low = high = 1200;
  - `test_both_years_missing_listed`;
  - `test_norm_county_rules`: "St. Louis County" and "saint louis" match; "Baltimore city" doesn't match "Baltimore County".
- [ ] **Step 2:** Run the tests. Expected: ImportError.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit.

### Task 7: Score the 2026 dry run

**Files:**
- Create: `pipeline/expected/score.py`
- Test: `pipeline/tests/test_expected_score.py`

**Interfaces:**
- Produces: `classify_office(contest_name: str) -> str | None`.
  - US SENATE: the name contains "senat" with "u.s." / "us " / "united states" (case-insensitive) and no "state senat".
  - GOVERNOR: "governor" without "lieutenant" / "lt.".
  - US HOUSE: "house of representatives" with "u.s." / "united states" / "congress", or "representative in congress", or "u.s. representative" / "us representative", with no "state house" / "general assembly" / "delegate".
  - Anything else is None. Rules are listed in the docstring.
- Produces: `actuals_2026(conn) -> (rows: list[dict], listed: list[tuple])`.
  - rows: {state, county_name, county_id, top_office, votes, source_id}, from each source's latest snapshot.
  - Uses `vote_type = 'TOTAL'` rows at level county. Where a source has no county rows, its precinct rows are summed by county_name.
  - Contest votes = all choices except over-votes, under-votes and blank-ballot lines, the same NON_CANDIDATES rule. US HOUSE is summed over contests.
  - Town-level sources are listed as "not scored: towns".
- Produces: `score(expected_rows, actual_rows) -> (per_county: list[dict], summary: dict)`.
  - Join on county FIPS where the actual row's county_id is a 5-digit FIPS (TX, AR, ND, FL); otherwise on (state, norm_county).
  - per_county: {state, county, actual, point, low, high, inside, miss, miss_pct}, where miss = actual − nearest bound (0 if inside) and miss_pct = miss ÷ point.
  - summary per state and overall: scored, inside share, median and 90th-percentile |miss_pct| (nearest-rank), and the not-scored list with reasons.

- [ ] **Step 1:** Write the failing tests:
  - `test_classify_office`: "United States Senator" → US SENATE; "U.S. Senate" → US SENATE; "State Senate District 12" → None; "Senate District 4" → None; "Member of the House of Representatives 1st Congressional District" → US HOUSE; "Lieutenant Governor" → None; "GOVERNOR AND LIEUTENANT GOVERNOR" → GOVERNOR;
  - `test_actuals_sum_precincts_when_no_county_rows`;
  - `test_score_inside_and_miss`: actual 1,300 against low 1,000 and high 1,200 → miss 100, miss_pct 100/point;
  - `test_unmatched_county_listed`.
- [ ] **Step 2:** Run the tests. Expected: ImportError.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit.

### Task 8: CLI and the first real run

**Files:**
- Create: `pipeline/expected/run.py`
- Test: `pipeline/tests/test_expected_run.py`

**Interfaces:**
- Produces: `python3 -m pipeline.expected.run fetch | check YEAR | baseline YEAR | registration | compute TARGET | score TARGET | all TARGET`. TARGET 2026 uses years (2018, 2022). Each writes `data/expected/<stage>-<year or target>.csv` plus a printed summary. `check` writes `check-<year>.csv` (state, office, passed, reason, differences as JSON).

- [ ] **Step 1:** Write the failing test `test_all_on_fixture_inputs`: tiny MEDSL CSVs, a tiny FEC workbook and a temp database run `all 2026` into a temp `data/expected`, giving the four CSVs with expected row counts.
- [ ] **Step 2:** Run it. Expected: fails.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it. Expected: OK. Then run the full suite: `.venv/bin/python -m unittest discover -s pipeline/tests -t .` and `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .`.
- [ ] **Step 5:** Run `python3 -m pipeline.expected.run check 2018` and `check 2022` on the real inputs and record the pass/fail table per state and office.
- [ ] **Step 6:** Commit.

### Task 9: Investigate and fix the failing offices (Steve's option C)

**Files:**
- Modify: `pipeline/expected/medsl_fixes.toml`
- Create: `docs/expected.md` (the investigation log section)

For each failing (state, year, office), in order of House seats (largest first):

- [ ] **Step 1:** List the differing districts and candidates from `check-<year>.csv`.
- [ ] **Step 2:** Find the cause in the MEDSL rows, e.g. a county total stored as a precinct, a duplicated precinct, or a missing county. Confirm it against an official figure: the FEC number plus, where it narrows the cause, the state's certified county or precinct report, cited by URL.
- [ ] **Step 3:** If a cause is identified and a `drop` fix restores the exact match, add the entry (id `<ST>-<year>-<n>`, state, year, office, match, change, evidence URL and figure, before/after differences). Re-run `check YEAR`. Expected: that office now passes. A cause that needs a different fix type: add the type with its own failing test first (Task 2's pattern).
- [ ] **Step 4:** If no cause is found, or the office has suppressed rows, record it in `docs/expected.md` as failed, with what was checked. Make no fix.
- [ ] **Step 5:** Commit after each state (fix entries and the log).
- [ ] **Stop condition:** If more than 10 state-offices remain unexplained after the first pass, stop and report to Steve with the table before continuing.

### Task 10: Dry run, docs, handoff

**Files:**
- Modify: `docs/expected.md`, `CLAUDE.md` (a step-4 section; the test count)

- [ ] **Step 1:** Run `python3 -m pipeline.expected.run all 2026`.
- [ ] **Step 2:** Write `docs/expected.md`:
  - inputs with hashes;
  - check results per state and office, plus fixes;
  - baselines (counties per method);
  - registration coverage;
  - the 2026 score per state and overall;
  - not-scored lists;
  - known limits (from the spec);
  - what's unverified.
- [ ] **Step 3:** Add a step-4 section to CLAUDE.md and update the test count.
- [ ] **Step 4:** Commit. Ask Steve before merging or pushing (step 4 is outside the reader standing approval).
