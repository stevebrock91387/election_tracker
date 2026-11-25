# Step 2: Wyoming reader (design)

Date: 2026-11-24. Steve: "Go for it" (survey and build HI, WY, MS, MA, IL, NJ where workable), under
the standing approval for the remaining state readers (2026-11-24).

## Intent

Load Wyoming's official 2026 general results at precinct level from the Secretary of State's own
workbook, with the SOS's county-level summary workbook as an independent check. Wyoming has no
election-night feed on the SOS site (registry), so this is the certified load.

## Source (seen 2026-11-24, script download works)

`https://sos.wyo.gov/Elections/Docs/2026/Results/General/2026_Wyoming_General_Results.zip`, linked as
"Wyoming General Election Results" on `https://sos.wyo.gov/Elections/Docs/2026/2026GeneralResults.aspx`
(647,239 B). Three `.xlsx` members (Office Open XML: a ZIP of XML parts, readable with the stdlib):

- `2026 County General PbP - OFFICIAL.xlsx`: one sheet per county (23, Albany … Weston). Row 1 a
  title repeated at each block's first column; row 3 the contest name at each block's first column
  (`United States Senator`, `House District 13`, `Supreme Court Justice, Wyoming Supreme Court …`);
  row 4 `Precinct` then one header per column (`Harriet\nHageman (R)`, `Write-Ins`, `Overvotes`,
  `Undervotes`; retention and propositions `For`/`Against` or similar); then one row per precinct
  (`13-1`, 436 in all) and a `Total` row. Counts are stored as text.
- `2026 County General PbP TBC - OFFICIAL.xlsx`: one sheet per county, `Precinct`, `Total Ballots
  Cast` per precinct (the turnout table).
- `2026 General Results Summaries - OFFICIAL.xlsx`: sheets Statewide Total Ballots Cast, Statewide
  Candidates, Statewide Senate Odd, Statewide House, Statewide Judicial, Statewide Ballot Issue; the
  same block layout with one row per county and a `Total` row. A county where a contest isn't on the
  ballot shows `-`.
- No ids anywhere (contest, choice, precinct). No vote types. No registered voters.
- Found while building: in Carbon, Converse and Crook the PbP precinct cells are numbers with a
  date number format (`mm\-dd`): 44562 displays as `01-01`, the TBC workbook's text name for the
  same precinct. Campbell, Laramie, Natrona and Sweetwater have a `Precincts Continue\non Next Page`
  row with no values (a print page break). Teton's `1-12` has one empty cell beside `-` cells.

## Approaches

1. **The ZIP's workbooks, stdlib XML (chosen).** Precinct rows from PbP, county check from the
   summaries, ballots cast from TBC. One request.
2. The per-county PDFs. Rejected: same numbers, PDF parsing.
3. xlrd/openpyxl. Rejected: `.xlsx` is ZIP + XML; the stdlib reads it, and the project keeps
   dependencies to the one Steve allowed (xlrd, for legacy `.xls` only).

## Design

- **Fetch.** `sources_wy.toml` (`wy-2026-general`): `zip_url`, `min_interval_s` 120. One request,
  `ext="zip"`. Pass record: one file of kind `zip`.
- **Workbook reader** (`read_xlsx(data) -> [(sheet name, grid)]`): workbook.xml for sheet names and
  order, its rels for each sheet's part, sharedStrings, inline strings; a grid is a list of rows
  (by row number, gaps kept as empty rows) of cells (by column letter, gaps `None`); values are
  strings as stored (numbers too). Members read in memory; a member over 50 MB is refused; XML
  parsed with `xml.etree.ElementTree` (no external entities are resolved by it). A numeric cell whose style
  has a date number format made only of `m`/`mm`/`d`/`dd`/`yy`/`yyyy` tokens and literal separators is
  rendered as that format displays it (1900 date system; the workbook's `date1904` flag honoured);
  each such cell is listed in `date_formatted_cells` (informational, with raw and shown value), and a
  date-styled cell whose format isn't of that kind keeps its raw value and is listed in
  `unrendered_formats`.
- **Block parser** (`parse_blocks(grid) -> contests`), shared by PbP and summaries: row 3 gives each
  block's start column and contest name; the block runs to the next start (or the last non-empty
  header in row 4); row 4 gives each column's choice header; data rows run from row 5 to the `Total`
  row. Unit name in column A.
- **Rows.** PbP → `level` "precinct", `county_id` = `county_name` = sheet name, `precinct_id` =
  `precinct_name` = column A as published. Summaries → `level` "county" (county from column A)
  and `level` "state" from the `Total` row. `contest_id` = `contest_name` = the row-3 text, whitespace
  collapsed; `contest_scope` "statewide"; `contest_type` "candidate", or "measure" for the ballot
  issue sheet, "retention" for judicial contests whose choices are For/Against-style (yes/no words),
  else "candidate". `choice` = header with whitespace collapsed (`Harriet Hageman`) and the trailing
  `(X)` moved to `party`; Write-Ins, Overvotes, Undervotes are choices with party "". `choice_id`
  "". `vote_type` "TOTAL". A `-` cell gives no row (contest not on that unit's ballot).
- **Turnout table:** state, source_id, source_sha256, county, precinct, ballots_cast (TBC).
- **Summary lists** (nothing corrected; a check that couldn't run is `None`):
  - `total_row_mismatches`: (sheet, contest, choice, Total row, sum of units) per PbP sheet and per
    summaries sheet.
  - `county_mismatches`: (county, contest, choice, summaries value, PbP Total row) both directions
    (a contest/choice on one side only listed with `None`).
  - `ballots_mismatches`: (county, PbP TBC sum, summaries Total Ballots Cast).
  - `precincts_over_ballots`: (county, precinct, contest, lines sum, ballots cast) where a contest's
    lines (choices + write-ins + over + under) don't equal the precinct's ballots cast (informational:
    vote-for-more contests mismatch by design).
  - `empty_unit_rows`: (sheet, row, text) unit rows with no value in any block (page-break rows);
    skipped. `empty_cells`: (sheet, unit, contest, choice) an empty cell in a unit that has other
    values; no row. A `-` cell gives no row and is counted in `not_on_ballot_cells`.
  - Comparisons that can't be made (a non-numeric side) go to `total_row_not_checked` /
    `county_not_checked`, never into a mismatch list.
  - `non_numeric` (cell neither digits nor `-`), `duplicate_units`, `duplicate_choices`,
    `blank_headers`, `unmatched_tbc_precincts` (in one workbook only), `sheet_mismatches` (county
    sheets in one PbP workbook only), `out_of_place_cells` (values outside any block).
  - `unreadable_files` / `missing_files` / `unreadable_members` / `missing_members`; every check
    `None` when the PbP workbook can't be read.

## Left to the builder / not done

- Live results: none on the SOS site; counties may publish their own (not surveyed).
- Contest names are not normalised across sheets beyond whitespace; a mismatch shows up in
  `county_mismatches` one-sided.
- Fixture: the real ZIP, unmodified (647 KB; the repo already holds a 1 MB fixture). Cutting
  counties out would break the summaries' Total rows; the whole file lets every check run on real
  values. Synthetic tests build small grids directly (the block parser takes a grid).
