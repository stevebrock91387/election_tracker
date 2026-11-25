# Step 2: Massachusetts reader (design)

Date: 2026-11-24. Steve: "Go for it" (survey and build HI, WY, MS, MA, IL, NJ where workable), under
the standing approval for the remaining state readers (2026-11-24).

## Intent

Load Massachusetts' official 2026 general results at precinct level from the Secretary of the
Commonwealth's results archive (PD43+, `electionstats.state.ma.us`). Massachusetts has no statewide
election-night feed (registry), so this is the certified load.

## Source (seen 2026-11-24, script download works under TLS 1.3)

- Contest list: `https://electionstats.state.ma.us/elections/search/year_from:2026/year_to:2026/stage:General`
  (HTML, 969 KB, 274 contests). Each row `<tr id="election-id-<id>">` gives year, office, district,
  stage, and a candidates table with each candidate's name, party label and statewide vote count,
  plus All Others, Blanks and Total Votes Cast.
- Questions list: `https://electionstats.state.ma.us/ballot_questions/search/year_from:2026/year_to:2026`
  (`<tr id="bq-id-<id>">`: number, type, location; 39 questions, 9 of them Statewide: ids 11789–11797).
- Per contest: `/elections/download/<id>/precincts_include:1/`; per question:
  `/ballot_questions/download/<id>/precincts_include:1/`. CSV (UTF-8, quoted, thousands
  separators). Contests: header `City/Town, Ward, Pct, <candidate names…>, All Others, Blanks,
  Total Votes Cast`, then a second header row with each candidate's party (`Democratic`,
  `Unenrolled`, blank for All Others/Blanks); questions: `Locality, Ward, Pct, Yes, No, Blanks,
  Total Votes Cast`, no party row. One line per precinct (Ward `-` in towns), then `TOTALS`.
- Party labels differ between the list and the CSV: the list says `Independent` and `Socialism and
  Liberation` where the CSV says `Unenrolled` (registration vs ballot designation; both kept).
- No ids for candidates or precincts; no vote types; no registered voters.

## Approaches

1. **List pages + one CSV per in-scope contest (chosen).** A pass reads both list pages (saved
   raw), takes the contest ids whose office is in scope and the statewide questions, then fetches
   each CSV. 2026 scope: U.S. Senate, Governor, Attorney General, Secretary, Treasurer, Auditor, U.S.
   House (9), Governor's Council (8), State Senate (41), State Representative (161), questions 1–9:
   236 requests, 5 s apart, about 20 minutes. The list's candidate totals are an independent check
   of each CSV.
2. Hard-code the 234 ids in config. Rejected: a pass reads the list anyway for the check, and
   ids found from the list follow a republished archive.
3. Municipality-level CSVs. Rejected: the House needs precincts.

## Design

- **Fetch.** `sources_ma.toml` (`ma-2026-general`): `base_url`, `search_path`, `questions_path`,
  `offices` (the in-scope office labels), `question_locations` (`["Statewide"]`), `min_interval_s`
  120, `request_gap_s` 5. Source ids `<id>-search`, `<id>-questions`, `<id>-c<election id>`,
  `<id>-q<question id>`. A failure stops the pass. The pass record lists every file with kind
  (`search`, `questions`, `contest`, `question`), the id, office and district from the list.
- **List parser** (`parse_search(html)`, `parse_questions(html)`): stdlib `html.parser`; returns
  per id: office, district, stage, and the candidates table (name, party label, votes; All Others,
  Blanks, Total Votes Cast). Questions: number, type, location, Yes/No/Blanks/Total.
- **CSV parser** (`parse_csv(text, kind)`): header and (contests) party row; precinct lines;
  TOTALS. Thousands separators removed only for digit groups (`1,401` → 1401); anything else is
  non-numeric.
- **Rows.** Precinct lines → `level` "precinct", `county_id` = `county_name` = City/Town (a town,
  as Connecticut), `precinct_id` = `<Ward>/<Pct>` as published (`-/1`, `10/4A`), `precinct_name` =
  "<Town> Ward <w> Precinct <p>" or "<Town> Precinct <p>"; TOTALS → `level` "state".
  `contest_id` = `contest_name` = "<office> <district>" for districts, the office for Statewide
  (`U.S. House 1st Congressional`, `Governor`); questions "Question <n>". `contest_type`
  "candidate" / "measure". `choice` = column name; `party` = the CSV party row (questions "");
  All Others and Blanks are choices; Total Votes Cast is not a row. `choice_id` "". `vote_type`
  "TOTAL".
- **Summary lists** (nothing corrected; a check that couldn't run is `None`; a value that can't be
  compared goes to a `*_not_checked` list, never a mismatch):
  - `totals_row_mismatches`: (contest, choice, TOTALS, sum of precincts).
  - `list_mismatches`: (contest, choice, list value, CSV TOTALS) both directions (a choice on one
    side only: `None` on the other).
  - `total_votes_mismatches`: (contest, precinct, Total Votes Cast, sum of choices) per line.
  - `party_label_differences` (informational): (contest, choice, CSV party, list party).
  - `non_numeric`, `malformed_lines`, `duplicate_precincts`, `duplicate_choices`,
    `contests_without_file`, `out_of_scope_offices` (distinct office labels not read, counted),
    `unexpected_headers`.
  - `unreadable_files` / `missing_files` per file; a contest whose CSV can't be read is listed and
    its checks don't run.

## Left to the builder / not done

- Local questions, county offices: out of scope (listed by office).
- Fixture: the two list pages trimmed to a few contests (rows kept as published) and those
  contests' CSVs as published.
