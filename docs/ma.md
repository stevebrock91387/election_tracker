# Massachusetts: PD43+ results archive (precinct level)

Seen 2026-11-24 in the built-in browser and with recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_ma.py`) on 2026-11-25 from 00:20 to 00:40 Pacific (08:20–08:40 UTC), then parsed with `pipeline/readers/ma.py`. Design: `docs/superpowers/specs/2026-11-24-step2-ma-reader-design.md`. **Precinct level, the federal, statewide and legislative contests plus the nine statewide questions, each checked against the archive's own list page. Certified results; Massachusetts has no statewide election-night feed.**

## Where the data is

The Secretary of the Commonwealth's archive `https://electionstats.state.ma.us` (needs TLS 1.3: run with Homebrew Python). A pass makes 234 requests, 5 s apart (about 20 minutes):

- the 2026 general contest list `/elections/search/year_from:2026/year_to:2026/stage:General` (274 contests, 2 of them special elections; 969,080 B, SHA-256 `321159c0e502…` on this run) and the 2026 question list `/ballot_questions/search/year_from:2026/year_to:2026` (39 questions);
- one precinct CSV per in-scope contest, `/elections/download/<id>/precincts_include:1/` (223), and per statewide question, `/ballot_questions/download/<id>/precincts_include:1/` (9).

Every file's hash is in `data/raw/manifest.csv` and the pass record.

## Parsed (2026-11-25)

- **Output:** 163,020 rows: 162,241 precinct, 779 state (from each CSV's TOTALS row). No turnout file (the source has none).
- **Coverage:** 223 contests (U.S. Senate, Governor, Attorney General, Secretary, Treasurer, Auditor, U.S. House 1–9, Governor's Council 1–8, State Senate 40, State Representative 160) and Questions 1–9; 2,393 precincts in 351 cities and towns.
- **Out of scope (counted):** county offices (District Attorney 11, Register of Probate 14, County Charter Commission 15, County Commissioner 4, County Treasurer 3, Sheriff 1, Council of Governments 1) and 30 local or district questions. Two **special general elections** in the same list (State Senate 1st Middlesex, id 171923; State Representative 5th Essex, id 171924) are a different election and are filtered out by stage (`stages` in the config), counted in `out_of_scope_stages`. An earlier run (fixed after review) had merged each into the November contest of the same name.
- **Clean:** every TOTALS row equals the sum of its precincts; every line's Total Votes Cast equals its choices plus All Others and Blanks; every CSV total equals the list page's figure; no non-numeric cells, malformed lines, duplicates or missing files.
- **Listed:** State Representative 11th Plymouth: the CSV has an All Others column (0 votes) that the list page doesn't show. 16 party-label differences (below).
- **Example (state rows):** U.S. Senate: Markey 1,718,276, Deaton 855,969, Ayyadurai 61,085, Tache 59,097. Governor: Healey and Driscoll 1,691,156, Minogue and Oliver 930,508, James and Kittredge 89,951. Question 1: Yes 2,272,519, No 373,273, Blanks 103,817.

## Quirks

- **Two party labels.** The CSV's second header row gives each candidate's party as registered (`Unenrolled`); the list page gives the ballot designation (`Independent`, `Socialism and Liberation`, `Gulf War Veteran`). `party` is the CSV's; the 16 differences are listed in `party_label_differences`.
- **Precincts:** `precinct_id` is `<Ward>/<Pct>` as published (`-/1` in towns without wards, `10/4A`); the city or town is in `county_id`/`county_name`, as for Connecticut. Some precincts are sub-precincts with 0 votes (`Worcester 10/4A`).
- All Others and Blanks are choices; Total Votes Cast is a check, not a row.
- No ids for candidates or precincts; contest ids are built from the list page's office and district (`U.S. House 2nd Congressional`, `State Representative 1st Barnstable`, `Question 1`).

## Not done

- Local questions and county offices.
- `sources/registry.csv` still lists Massachusetts as partial (2026 general not seen on 2026-11-20).
