# Wyoming: Secretary of State official results ZIP (precinct level)

Seen 2026-11-24 in the built-in browser and with a recon download. Downloaded through `pipeline/fetch.py` (`pipeline/run_wy.py`) on 2026-11-24 at 23:42 Pacific (07:42 UTC 11-25), then parsed with `pipeline/readers/wy.py`. Design: `docs/superpowers/specs/2026-11-24-step2-wy-reader-design.md`. **Precinct level, every contest on the official workbooks, with the SOS's county summaries as a check. Certified results; Wyoming's SOS publishes no election-night feed.**

## Where the data is

`https://sos.wyo.gov/Elections/Docs/2026/Results/General/2026_Wyoming_General_Results.zip`, linked as "Wyoming General Election Results" on `https://sos.wyo.gov/Elections/Docs/2026/2026GeneralResults.aspx`. One request per pass. The same page links PDFs (statewide summaries, per-county precinct results and ballots cast, canvassing board minutes).

| File | Bytes | SHA-256 (first 12) |
|---|---|---|
| ZIP | 647,239 | `c378306bd8df` |

Members: `2026 County General PbP - OFFICIAL.xlsx` (precinct results, one sheet per county), `2026 County General PbP TBC - OFFICIAL.xlsx` (total ballots cast per precinct), `2026 General Results Summaries - OFFICIAL.xlsx` (six statewide sheets, one row per county). Read with the stdlib (an `.xlsx` is a ZIP of XML parts). The test fixture is this ZIP, unmodified.

## Parsed (2026-11-24)

- **Output:** 31,832 rows: 29,514 precinct, 1,842 county, 476 state; 432 turnout rows.
- **Coverage:** 23 counties, 432 precincts, 108 contests (federal, statewide, state senate odd districts, state house, 21 judicial retentions, one initiative).
- **Clean:** every Total row equals the sum of its units (precinct sheets, summaries, ballots-cast sheets); county ballots cast equal the summaries; every precinct is in both precinct workbooks; no duplicates, non-numeric cells, layout problems or precincts with `-` in every contest; nothing in the `*_not_checked` lists.
- **Listed:**
  - **Teton, House District 22:** the summaries say "Andrew Byron", the precinct workbook "Andrew P Byron" (1,399 votes on both). Both spellings are kept; the county check lists each one-sided.
  - **Teton `1-12`, Senate District 17:** one empty cell (Mike Gierau) beside `-` cells; no row for it.
  - **Ballot balance (informational), 93:** a contest's lines (choices + write-ins + over + under) differ from the precinct's ballots cast. 58 are precincts split between districts of one office, whose parts add to the ballots (Big Horn `01-01`: House 27 286 + House 28 350 = 636). 11 are precincts where only one of their Senate districts was elected in 2026 (odd districts only), so its lines are a part of the ballots. The other 24 are unexplained and not corrected: off by 1 or 2 votes (the initiative in 15 Natrona precincts, e.g. `2-10` 734 lines vs 733 ballots; Secretary of State in Sheridan `12-1` and `13-1`; the Jarosh retention in Sweetwater `04-1` and `04-4`), and five contest blocks whose lines are all 0 against the precinct's ballots (Natrona `2-9` House 37 and Senate 29, Natrona `8-1` House 58, Sheridan `01-01` House 30, Sweetwater `04-5` House 17; possibly precincts outside the district shown as 0 instead of `-`, unverified).
- **Example (state rows):** U.S. Senator: Hageman (R) 122,174, Byrd (D) 65,105. U.S. Representative: Gray (R) 99,906, Kinney (D) 61,689, Johnson (L) 13,667, Haggit (C) 7,961. Governor: Barlow (R) 128,496, Bextel (C) 31,444, Casner (D) 27,472.

## Quirks

- **Date-formatted precinct names.** In Carbon, Converse and Crook the precinct cells are numbers with the format `mm\-dd` (Excel turned `01-01` into a date). The reader renders them as the sheet displays them (44562 → `01-01`), which equals the ballots-cast workbook's text names; all 35 cells are listed in `date_formatted_cells`.
- **Page-break rows.** Campbell, Laramie, Natrona and Sweetwater have a "Precincts Continue on Next Page" row with no values: skipped and listed.
- `-` means the contest isn't on that unit's ballot: no row (18,234 cells).
- Counts are numeric cells in the precinct and ballots-cast workbooks; the summaries workbook is a Google Sheets export holding cached formula values. Names and `-` are strings. No ids, vote types or registered voters.
- Only unit names (column A) are rendered through a date format; a date-styled cell elsewhere keeps its raw value and is listed in `unrendered_formats`. Month-name formats (`mmm`) aren't rendered.
- `contest_type` is inferred from the choices: For/Against → measure, Yes/No → retention, else candidate. Write-Ins, Overvotes and Undervotes are choices with no party.
- The precinct workbook's own Total rows are used only for checks; county rows come from the summaries workbook.

## Not done

- Live results: none on the SOS site; county sites not surveyed.
- `sources/registry.csv` still describes Wyoming's results as PDF summaries (as of 2026-11-20).
