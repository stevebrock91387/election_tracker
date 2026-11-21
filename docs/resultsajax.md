# ResultsAjax engine: MT, NE, NM, OR, SD

Seen 2026-11-21 in the built-in browser and with single recon downloads; then downloaded through `pipeline/fetch.py` (`pipeline/run_resultsajax.py`) and parsed with `pipeline/readers/resultsajax.py`. Design: `docs/superpowers/specs/2026-11-21-step2-resultsajax-reader-design.md`. **County level, federal and statewide page types only.**

## Where the data is

| State | Results pages read | Media CSVs (statewide totals) | County JSON service |
|---|---|---|---|
| MT | FED | none published | `https://esersws.mt.gov/ResultsAjax.svc` |
| NE | SW, CG | SW, CG | `https://neresultswebservice.azurewebsites.us/ResultsAjax.svc` |
| NM | FED, SW | FED, SW | `https://nmresultswebservice.azurewebsites.us/NMResultsAjax.svc` |
| OR | FED, SWPAR, SWNON | none published | `https://orresultswebservices.azureedge.us/ResultsAjax.svc` |
| SD | SWR, BQ | SWR, BQ | `https://sdresws.azurewebsites.us/ResultsAjax.svc` |

- Page: `<site>ResultsSW.aspx?type=<T>&map=CTY`; each race appears as `BuildCounty('<T>', '<raceID>', '<osn>', '<party>')`.
- Media CSV: `<site>resultsCSV.aspx?text=All&type=<T>&map=CTY`. NE also has `type=All` (every race, legislative and local included); the reader uses SW and CG so the check matches the pages.
- County JSON: `GetMapData?type=<T>&category=CTY&raceID=<id>&osn=<osn>&county=0&party=0`. MT returns `{"d": null}` without `party=0`.
- MT's statewide Excel export (form post, one sheet per contest, a TOTALS row, no candidate ids) and OR's export are not read: **MT and OR have no statewide check** (`statewide_check = "not available"`).

## Parsed (2026-11-21, passes started 19:55–20:08 UTC)

| State | Files | Bytes | Races | Counties per race | Rows (county + state) | Statewide check | Anomalies |
|---|---|---|---|---|---|---|---|
| MT | 4 | 325,624 | 3 (Senate, House 1–2) | 16–56 | 436 + 0 | not available | none |
| NE | 13 | 1,482,476 | 9 (Senate, Governor, 4 statewide, House 1–3) | 3–93 | 2,224 + 31 | media CSV, 0 mismatches | none |
| NM | 25 | 1,217,952 | 21 (Senate, House 1–3, statewide offices, judicial, 4 amendments, 3 bonds) | 10–33 | 1,241 + 41 | media CSV, 1 mismatch | 1 non-numeric vote |
| OR | 21 | 589,468 | 18 (Senate, House 1–6, Governor, 7 circuit judges, 3 district attorneys) | 1–36 | 507 + 0 | not available | none |
| SD | 17 | 1,227,723 | 13 (Senate, House, 7 statewide offices, 4 amendments) | 66 | 1,716 + 26 | media CSV, 0 mismatches | none |

- **NM CD2, Chaves County:** Gabriel Vasquez's county votes are published as `"*"` (the site still shows 4.4% for him there). The row keeps `votes` empty and is listed under `non_numeric_votes`; the county sum is 123,754 against the state's CSV total of 123,757, so the hidden cell holds 3 votes. Not estimated.
- **OR** `PartyCode` "NON" with `PartyName` "Republican" for the Senate Republican; counties with votes show `PrecinctsReporting` 0 (e.g. Baker 0/17); kept as published.
- **NM** pads `CountyID` (`"01 "`; stripped, the one normalisation), sends votes as strings, and returns a bare JSON list.
- MT and OR mark counties `IsReported: false` even at full precincts (not used).
- OR's SWNON page includes single-county races (circuit judges, district attorneys); they keep `contest_scope = "statewide"` like every race from these pages.
- A race body that isn't the expected JSON (an HTML error or bot-check page, an empty body) is listed under `races_unreadable` and skipped; a race fetch that fails (HTTP error, timeout, too soon) is listed under `failed_races` and the pass goes on. Unreadable media CSV rows (non-integer votes, extra fields, missing ids, repeated keys) go to `media_problems`. Where no media CSV exists, the check results print as "not checked", never 0.
- No vote types (election day / mail) are published in the county JSON; every row is `TOTAL`. NM's media CSV has empty absentee / election-day / early columns.

## Running

```
/opt/homebrew/bin/python3 -m pipeline.run_resultsajax fetch-parse resultsajax-NE-2026-general
```

A pass makes one request per page, media CSV and race, 10 s apart (NM ≈ 25 requests, about 4 minutes). Five passes run in parallel on 2026-11-21 corrupted `data/raw/.last_fetch.json` (repaired by hand, backup kept outside the repo); `pipeline/fetch.py` has since been made safe for concurrent runs (an exclusive lock on `data/raw/.fetch.lock` around the timing check and the manifest append, and an atomic replace of the timing file).

## Not yet known / not done

- Legislative and local races; precinct level (`category=PREC` exists, not examined).
- Statewide checks for MT (Excel export) and OR (export not opened).
- County FIPS mapping (these sites give their own county ids: MT `01`…, NE `14`…, SD `10`…, OR `20`…).
- NE presidential-by-district results for 2028: expected on the same CG page type; appears only in presidential years.
