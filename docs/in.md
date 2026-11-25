# Indiana: Indiana ENR (category JSON + precinct CSV)

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_in.py`) on 2026-11-24 at 16:40 Pacific (00:40 UTC 11-25), then parsed with `pipeline/readers/in_.py`. Design: `docs/superpowers/specs/2026-11-24-step2-in-reader-design.md`. **Precinct, county and state level; six office categories:** US Representative, Secretary of State, State Comptroller, Treasurer of State, State Senator, State Representative.

## Where the data is

Base `https://enr.indianavoters.in.gov/site/`. A pass reads `data/settings.json` for the version letter (data files end `_A` or `_B`; they alternate), then nine files 10 s apart:

| Kind | File | Bytes | SHA-256 (first 12) |
|---|---|---|---|
| settings | `data/settings.json` | 3,578 | `4d25adbba15c` |
| elections | `data/statewideElectionsC_B.json` | 21,591 | `0e320e693793` |
| offcat-1005 | `data/OffCatC_1005_B.json` (US Representative) | 116,491 | `d64516c03966` |
| offcat-1041 | `…_1041_B` (Secretary of State) | 265,862 | `11daf038a5f4` |
| offcat-1047 | `…_1047_B` (State Comptroller) | 198,122 | `3a7bf0a4efc9` |
| offcat-1037 | `…_1037_B` (Treasurer of State) | 153,949 | `9a43376fc196` |
| offcat-1018 | `…_1018_B` (State Senator) | 92,174 | `dfde4f4a2d2e` |
| offcat-1040 | `…_1040_B` (State Representative) | 301,937 | `d32e18f80689` |
| turnout | `data/statewideTurnout_B.json` | 13,704 | `5d64bdba4322` |
| csv | `download/AllOfficeResults.csv` (every office, by precinct; not versioned) | 35,190,191 | `fe537e140c7a` |

Settings: `VersionCode` 20261119_100058, `Certified` F (not certified). The site also offers the same precinct data as JSON (76 MB) and XML (150 MB), and referendums (`AllRefResults`).

## Parsed (2026-11-24)

- **Output:** 82,906 rows: 271 state, 1,791 county, 80,844 precinct. 92 turnout rows.
- **Coverage:** 137 offices, 92 counties (FIPS), 5,123 precinct units in the CSV (county + precinct name; the category index says 5,061 of 5,067 precincts reporting).
- **Every check is clean:** precinct sums equal county totals for every candidate line, every in-scope precinct row joins to its ids, county sums equal statewide totals and every county line has a statewide line (both directions), every statewide candidate has an id, no party differences beyond case, no duplicates, no non-integer counts, every county has FIPS, the turnout Total equals the county sums, and no Federal/State category is uncovered.
- **Not listed by design:** a county line with zero votes and no precinct rows.
- **Counted:** 26 precinct units whose name ends "Nv"; 60 units with zero votes in every in-scope line.
- **Example, Secretary of State (unofficial):** Bayh D 1,007,815; Engling R 829,083; Ballard Lp 70,068; Shillings L 38,663; Delano (W/I) Nsaw 136.

## Quirks

- **The precinct CSV has no ids.** Rows get office, candidate and county ids by joining on (office title, county, name on ballot) to the category JSON, compared case-insensitively. The files spell names in different case: "Secretary Of State" vs "Secretary of State"; "Laporte"/"Dekalb"/"Lagrange" vs "LaPorte"/"DeKalb"/"LaGrange".
- **Party spellings differ by level, kept as published:** statewide summaries and county lines both carry codes like "Lp", "Nsaw", "L", "SPI" (settings list "LP", "NSAW"); the CSV has the full party name. The two Libertarian candidates appear as "Lp" and "L".
- **No reporting flag:** an unreported precinct can't be told from one with zero votes, so `reporting_status` is empty everywhere. Step 4 (expected vote) has to treat zero-vote precincts as unknown.
- **The CSV isn't versioned** with the JSON. A pass during an update could mix two moments; the precinct-vs-county check would then list differences.
- A single item in the JSON may be an object instead of a one-element list.

## Not done

- Judges, prosecutors, local offices, referendums.
- Vote types (the CSV has totals only).
- What "Nv" precinct names mean; the 56-unit gap between the CSV's 5,123 units and the index's 5,067 precincts.
- 2028 adds US Senator and Governor categories; their ids go into `pipeline/sources_in.toml` (the reader lists uncovered Federal/State categories).
