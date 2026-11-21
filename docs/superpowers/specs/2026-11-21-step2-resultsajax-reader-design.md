# Step 2: ResultsAjax reader (MT, NE, NM, OR, SD), county level

Status: **approved by Steve 2026-11-21** ("Go ahead" to the design as proposed in chat).

## Why

Step 2 of the pipeline needs one reader per results platform. Five states run the same results engine (ASP.NET pages backed by a `ResultsAjax.svc` JSON service): Montana, Nebraska, New Mexico, Oregon, South Dakota. Nebraska matters most for 2028: it splits electoral votes by congressional district.

## What recon found (2026-11-21, 2026 general, browser + single downloads)

| State | Site | Service root | Service | Page types in scope | Races |
|---|---|---|---|---|---|
| MT | `https://electionresults.mt.gov/` | `https://esersws.mt.gov/` | `ResultsAjax.svc` | FED | 3 |
| NE | `https://electionresults.nebraska.gov/` | `https://neresultswebservice.azurewebsites.us/` | `ResultsAjax.svc` | SW, CG | 6 + 3 |
| NM | `https://electionresults.sos.nm.gov/` | `https://nmresultswebservice.azurewebsites.us/` | `NMResultsAjax.svc` | FED, SW | 4 + 17 |
| OR | `https://results.oregonvotes.gov/` | `https://orresultswebservices.azureedge.us/` | `ResultsAjax.svc` | FED, SWPAR, SWNON | 7 + 1 + 10 |
| SD | `https://electionresults.sd.gov/` | `https://sdresws.azurewebsites.us/` | `ResultsAjax.svc` | SWR, BQ | 9 + 4 |

- **Race list:** each results page `<site>ResultsSW.aspx?type=<TYPE>&map=CTY` contains one `BuildCounty('<TYPE>', '<raceID>', '<osn>', '<party>')` call per race.
- **County results:** `<service root><service>/GetMapData?type=<TYPE>&category=CTY&raceID=<raceID>&osn=<osn>&county=0&party=<party or 0>` returns one record per (county, candidate): `RaceID`, `RaceName`, `VoteFor`, `CandidateID`, `calcCandidate`, `PartyCode`, `PartyName`, `CountyID`, `CountyName`, `calcCandidateVotes`, `PrecinctsReporting`, `TotalPrecincts`, `PrecinctsPartial`, `IsReported`, `Winner`, and more. US Senate checked in all five: MT 56 counties × 4, NE 93 × 5, NM 33 × 2, OR 36 × 5, SD 66 × 2. MT Beaverhead (Alme 2,805) matches MT's own Excel export.
- **Per-state quirks:**
  - MT returns `{"d": null}` unless `party=0` is sent (the site's own JS sends 0 for an empty party).
  - NM: the service is named `NMResultsAjax.svc`; it returns a bare list (no `"d"` wrapper); `calcCandidateVotes` and `RecountVotes` are strings; `CountyID` is padded (`"01 "`).
  - OR: `PartyCode` "NON" with `PartyName` "Republican" for a Republican; counties with votes show `PrecinctsReporting` 0 (all-mail state).
  - MT and OR: `IsReported` false even at full precincts.
- **Statewide totals from the state itself (independent check):** SD, NE, NM publish a media CSV, `<site>resultsCSV.aspx?text=All&type=<TYPE>&map=CTY`, one row per (race, candidate) with `RaceID`, `CandidateID`, `CandidateVotes`, `PrecinctsReporting` (SD/NE write it as `="671/671"`). NE's `type=All` covers every race; SD needs SWR and BQ; NM needs FED and SW. NM's CSV has different columns (no `OfficeSeqNo`/`AreaType`; adds absentee/election-day/early columns, empty in 2026). MT's statewide export is an Excel file reached by a form post (one sheet per contest, a TOTALS row, no candidate ids); OR's export was not opened.
- No vote-type split anywhere in the JSON.

## Approaches considered

1. **Race list from the results pages + per-race county JSON + the state's media CSV as a statewide check (chosen).** IDs everywhere, one parser for all five, an independent total where the state publishes one.
2. Exports only: no county data for SD, NE, NM. Rejected.
3. Scraping HTML results pages: fragile, no ids. Rejected.

## Scope

- Federal and statewide races only, county level (the page types in the table). Legislative, county, local races: not now.
- Nebraska's CG page (3 House races) is in scope: congressional-district results.
- Statewide check: SD, NE, NM via media CSV. **MT and OR: no statewide check in this build** (MT needs a form post and an Excel parser; OR's export is unexamined). The summary says so per state rather than reporting "0 mismatches".

## Design

- **Config** `pipeline/sources_resultsajax.toml`, one entry per state: `state`, `site`, `service_root`, `service`, `page_types`, `media_types` (empty for MT, OR), `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** (`pipeline/run_resultsajax.py fetch SOURCE_ID`):
  1. Fetch each results page (source id `<id>-page-<TYPE>`), each media CSV (`<id>-media-<TYPE>`), then each race's JSON (`<id>-race-<raceID>`), all through `pipeline/fetch.py` (raw body + manifest row before parsing; 120 s minimum per source id).
  2. Wait `request_gap_s` (10 s) between consecutive requests in a pass (injectable sleep for tests). Pass runtime ≈ requests × 10 s (OR ≈ 21 requests, 3.5 min).
  3. A page or media CSV that fails stops the pass (FetchError/FetchTooSoon propagate). A single race that fails is listed in the pass record and the pass continues, so one bad race doesn't lose the rest on election night.
  4. Writes a pass record `data/raw/<id>/pass-<UTC ts>.json`: version-free list of `{kind, type, race_id, osn, party, path}` plus failures. Parse reads this record.
- **Reader** `pipeline/readers/resultsajax.py`:
  - `parse_page(html) -> [(type, race_id, osn, party)]` from the `BuildCounty(...)` calls; duplicates collapsed, order kept.
  - `parse_race(body_bytes) -> list of records`: accepts `{"d": [...]}` or a bare list; `{"d": null}`/empty → listed as "no data", no rows.
  - `parse_media_csv(text) -> {(race_id, candidate_id): votes}`; strips the `="…"` wrapper; tolerates NM's columns and trailing commas.
  - `parse_pass(pass_record, state, source_id) -> (rows, summary)`.
- **Rows** (common columns, `pipeline/schema.py`): county rows only, `vote_type = "TOTAL"`, `contest_scope = "statewide"`, `contest_id = RaceID`, `choice_id = CandidateID`, `choice = calcCandidate` (as published, whitespace kept), `party = PartyCode`, `county_id = CountyID` with surrounding whitespace stripped (NM pads it; recorded here as the one normalisation), `county_name` as published, `vote_for`, `votes` as int, `reporting_status = "<PrecinctsReporting>/<TotalPrecincts> precincts"` as published (OR's 0/17 kept), `contest_type` empty, `source_sha256` of that race's JSON file, `election_name`/`election_date`/`source_created_at` empty. No state rows are made up: for SD/NE/NM, state rows come from the media CSV (`level = "state"`, `vote_type = "TOTAL"`, `source_sha256` of the CSV); for MT/OR there are none.
- **Summary** (nothing corrected, everything listed): races on pages, races parsed, races with no data, failed races (from the pass record), counties per race, duplicate (race, county, candidate) keys, mismatches county-sum vs media CSV `(race, candidate, csv, sum)`, media rows for races not on the pages, races not in the media CSV, `statewide_check` = "media CSV" or "not available".
- **CLI** like `run_clarity`: `fetch | parse PASS_RECORD | fetch-parse`, output `data/parsed/<id>/<UTC ts>.csv`.
- **Tests** on fixtures cut from real 2026 downloads (one race per state at least, plus SD/NE/NM media CSV rows for those races and one results page per state cut to the `BuildCounty` lines), plus synthetic variants for: `{"d": null}`, NM bare list with string votes, a county-sum mismatch, a duplicate key, a failed race in the pass record, a missing media row.

## Left to the builder

Fixture cutting tool, exact summary key names, test layout (mirror the Clarity tests).

## Not done / later

Legislative and local races; precinct level (`category=PREC` exists, not examined); MT Excel and OR export statewide checks; county FIPS mapping; NE presidential-by-district for 2028 (same CG page type, appears only in presidential years).
