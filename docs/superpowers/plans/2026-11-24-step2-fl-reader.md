# Florida Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** County-level Florida results for all 176 races in the Division of Elections' pipe-delimited files, with party from the tab file, fetched over TLS verified to Go Daddy Root G2 via GoDaddy's published cross-certificate.

**Architecture:** `pipeline/fetch.py` gains an optional `cafile`; a fetch pass saves the info, votes and tab files; `pipeline/readers/fl.py` emits one county row per vote record and lists every anomaly.

**Tech Stack:** Python 3.14 stdlib (`ssl`), `/opt/homebrew/bin/python3`.

**Spec:** `docs/superpowers/specs/2026-11-24-step2-fl-reader-design.md`

## Global Constraints

- Stdlib only; tests `/opt/homebrew/bin/python3 -m unittest discover -s pipeline/tests -t .` (225 before this plan).
- Certificate verification is never disabled. `cafile` adds one file to the default store and clears `ssl.VERIFY_X509_PARTIAL_CHAIN`; only Florida's source passes it.
- Cross-certificate SHA-256 `7BCB0F2F2D1031A6AF8D61BAA835D2835A3B8BCC26D94A3B048B1655FB81298C`.
- `min_interval_s = 120`, `request_gap_s = 10`; `ext = "txt"`; URLs get `?v=<unix seconds>`.
- Choices keyed on (race id, candidate id); `county_id` = unit id (FIPS, e.g. "12001"); `vote_type "TOTAL"`; `contest_scope "statewide"`.
- Nothing corrected; every anomaly listed; a check that could not run is `None`.
- Don't touch `sources/`, `tools/`, `dnd_sim/`. No Co-Authored-By trailers.

## Review Focus

1. A `cafile` context that silently drops the default store (e.g. built with `create_default_context(cafile=...)`) → G2 missing, every other source would break if reused; test asserts G2 present and partial chain off (`test_cafile_context`).
2. Retention/amendment choices sharing ids `10`/`20` across races → each row named from its own race's `c` record, never another race's (test `test_yes_no_ids_per_race`).
3. A vote file that is an HTML error page → listed, no rows, checks `None` (test `test_unreadable_votes_not_checked`).
4. A tab file that is missing or unreadable → rows still emitted from the pipe files with party and contest_type empty, tab checks `None` (test `test_tab_missing_still_rows`).
5. Precincts reporting above the `p` count, or 0 → the first listed, the second counted (test `test_precincts_checks`).

---

### Task 1: TLS option and the cross-certificate

**Files:** Modify `pipeline/fetch.py` (`fetch(..., cafile=None)`, `_ssl_context(cafile) -> ssl.SSLContext`, `_urllib_opener(url, context=None)`); Create `pipeline/certs/godaddy-tls-root-r1-cross-g2.pem`, `pipeline/certs/README.md` (source URL `https://certs.godaddy.com/repository/gd_tls_root-r1-cross-g2.crt.pem`, date 2026-11-24, SHA-256, why, expiry 2037-12-31); Test `pipeline/tests/test_fetch.py`.

- [ ] Failing tests: `test_cross_cert_fingerprint` (SHA-256 of the DER of the PEM equals the constant); `test_cafile_context` (`_ssl_context(path)`: `verify_flags & VERIFY_X509_PARTIAL_CHAIN == 0`, `get_ca_certs()` contains a subject CN "GoDaddy TLS Root CA - R1" issued by "Go Daddy Root Certificate Authority - G2", and one CN "Go Daddy Root Certificate Authority - G2"); `test_fetch_passes_cafile` (an injected opener is unaffected; when `opener` is None and `cafile` given, `_urllib_opener` gets a context — tested by monkeypatching `_urllib_opener`).
- [ ] Copy the cross-certificate from the scratchpad (`gdcerts/gd_tls_root-r1-cross-g2.crt.pem`, downloaded from GoDaddy 2026-11-24) after re-checking its fingerprint; implement; suite green; commit `Let fetch add one CA file (partial chain off); add GoDaddy R1 cross-certificate`.

### Task 2: Sources, fetch pass, fixtures and reader

**Files:** Create `pipeline/sources_fl.toml`, `pipeline/run_fl.py` (`load_sources`, `fetch_pass`, `main` fetch|parse|fetch-parse), `pipeline/make_fl_fixture.py`, `pipeline/readers/fl.py`, fixtures `pipeline/tests/fixtures/fl_info.txt`, `fl_votes.txt`, `fl_tab.txt`, `fl_pass.json`; Test `pipeline/tests/test_run_fl.py`, `pipeline/tests/test_fl.py`.

**Interfaces:**
- `fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep, clock=time.time) -> record path`; kinds `info`, `votes`, `tab`.
- `parse_pass(record_path, base_dir=".") -> (rows, summary)`.
- Summary keys: `races`, `choices`, `counties`, `records` (ints), `status_counts` (dict), `zero_precincts_reporting` (int), lists `unknown_races`, `unknown_units`, `unknown_choices`, `duplicate_records`, `non_numeric`, `reporting_exceeds_precincts`, `missing_precinct_counts`, `unexpected_status`, `races_without_votes`, `pipe_vs_tab_differences`, `races_not_in_tab`, `candidates_with_several_parties`, `malformed_records`, `unreadable_files`, `missing_files`.

- [ ] Failing fetch tests: sources complete (URLs without `?v=`, `cafile = "pipeline/certs/godaddy-tls-root-r1-cross-g2.pem"`); pass URLs in order each ending `?v=1700000000` with a fake `clock`; gap `[10, 10]`; failure stops the pass; `cafile` passed to `fetch` (monkeypatched).
- [ ] Real fetch; `make_fl_fixture.py PASS OUT_DIR --races 120000,140020,140030,160000,500001,900001 --units 12001,12003,12005` keeps `u` records for the units, `r`/`c` for the races, `p` and `V` for both, tab rows for those race names (full or after-colon) and county names.
- [ ] Failing reader tests, real values: Alachua Senate Moody (`89119`) votes 34835, `choice "Ashley Moody"`, `party "REP"`, `contest_type "USS"`, `county_id "12001"`, `county_name "Alachua"`, `reporting_status "0/63 precincts, status I"`; Nixon `90009` 69813 `DEM`; Governor `choice` as published order ("first last" → "Donalds Avila"); amendment race `900001` choice id `10` named from its own race and `contest_type "AMD"`; retention race `500001` choice `10` too, separate rows; `status_counts {"I": ...}`; `pipe_vs_tab_differences == []`; `races_not_in_tab == []`.
- [ ] Failing synthetic tests: the Review Focus tests 2–5, plus `test_unknown_ids_listed`, `test_duplicate_record_listed`, `test_malformed_record_listed`, `test_pipe_vs_tab_difference_listed`.
- [ ] Run (fail), implement, suite green, commit `Add FL sources, fetch pass and reader with fixtures from the 2026 files`.

### Task 3: Real-file results and docs

- [ ] Parse the real pass with the CLI (test `test_parse_command` first); record in `docs/fl.md` URLs, the certificate path and fingerprints, bytes and SHA-256, rows, races, counties, every non-empty list, quirks (status I, zero reporting, Governor name order, Yes/No ids, no state rows).
- [ ] Update `CLAUDE.md`; commit `Add FL parse CLI; record 2026 results`.
