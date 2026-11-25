# Step 2: Maryland reader (design)

Date: 2026-11-24. Steve: "on Maryland, we should build a reader for the HTML. I want the results as
they come in, not when they're done." Standing approval for the remaining state readers
(2026-11-24) covers this design.

## Intent

Read Maryland's live election-night results pages (State Board of Elections, static HTML) at county
level, with vote types and per-county reporting, so a pass during the count gives a usable snapshot.
The certified CSVs come weeks later and are a separate job.

## Source (seen 2026-11-24, script download works)

Base `https://elections.maryland.gov/elections/2026/general_results/`. Pages say "Unofficial 2026
Gubernatorial General Election Results" and "Last refreshed: 11/23/2026 07:40:42 PM".

- `gen_results_2026_by_county_<1..24>.html`: one page per county (Allegany 1 … Worcester 24, as
  linked from `index.html`), every contest on that county's ballot, the statewide questions included.
- `gen_qresults_2026_by_county_<1..24>.html`: questions only; Montgomery's Question 1 matches its
  candidate page cell for cell, so these pages aren't read.
- `gen_results_2026_<1..9>.html`: one page per office with every district (1 Governor / Lt.
  Governor, 2 Comptroller, 3 Attorney General, 4 Representative in Congress, 5 State Senator, 6 House
  of Delegates, 7 Judge of the Circuit Court, 8 Justice, Supreme Court of Maryland, 9 Judge, Appellate
  Court of Maryland At Large). `gen_qresults_2026_<1..3>.html`: statewide questions.
- Layout: `h1` "… Results for Montgomery County"; per contest an `h2` office, then either `h3` "Vote
  for 1" or `h3` "District 4" + `h4` "Vote for up to 3"; a text node "(257 of 257 election day
  precincts reported)" (office pages prefix it with a "County Break Down" link); then a table:
  `Name`, `Party`, Early Voting, Election Day, Mail-In Ballot, Provisional, `Total`, `Percentage`;
  the last body row is `Totals`. Retention contests (Appellate Court, Supreme Court) put one `h3`
  per judge: "Dan Friedman<br>Vote Yes or No<br>For continuance in office"; their table's first
  header is the judge's name, with no Party column, and the choices are Yes/No. Question tables have no Party column and the first header is
  "Question 1". Counts carry thousands separators. Winners carry an image (`alt="Winner Selected"`).
  "NR: not reported" is in the legend (no NR cell seen on the final pages).
- No ids anywhere. No registered voters or ballots cast.

## Approaches

1. **County pages + office pages (chosen).** 24 county pages are the data (county × contest ×
   vote type, with each county's precinct reporting); the 9 office pages and 3 question pages are an
   independent check. 36 requests per pass, about 3 minutes.
2. Per-contest county breakdown pages (`gen_detail_results_*`): about 160 requests for the same
   numbers. Rejected: three times the requests, slower passes on election night.
3. Wait for the certified CSVs. Rejected by Steve (wants results as they come in).

## Design

- **Fetch.** `sources_md.toml`: `base_url`, `counties` (number → name, from the index),
  `office_pages` (1–9), `question_pages` (1–3), `offices` (in-scope `h2` titles: the nine offices
  above), `min_interval_s` 120 per file, `request_gap_s` 5 between requests (my call: a pass takes
  about 5 minutes, half the LA/ResultsAjax gap of 10 s, for fresher snapshots; static pages). Each
  page is its own fetch source id (`<id>-county-16`, `<id>-office-4`,
  `<id>-question-1`); a failure stops the pass. The pass record lists every file with its kind and
  number.
- **Page parser** (stdlib `html.parser`): `parse_page(text) -> {"title", "refreshed", "contests":
  [{"office", "district", "vote_for", "reporting", "columns", "rows", "totals"}], "problems"}`.
  Contest heading state: `h2` sets the office and clears the district; `h3`/`h4` starting "Vote for"
  set vote_for, any other `h3` sets the district; an `h3` whose second line is "Vote Yes or No" is a
  retention contest: the district is the judge's name and vote_for is 1. The reporting phrase is the text matching
  `\((\d+) of (\d+) election day precincts reported\)`. Cell text is whitespace-collapsed; images
  are ignored.
- **Scope.** Candidate contests whose office is in `offices`; question contests whose title is on a
  statewide question page (`Question 1: Constitutional Amendment` …). Everything else (county
  executive, council, sheriff, board of education, local questions) is out; the distinct titles are
  listed.
- **Rows.** County pages → `level` "county", `county_id` the page number, `county_name` from config;
  office and question pages → `level` "state". `contest_id` = `contest_name` = office plus district
  ("Representative in Congress District 4"; retention: "Judge, Appellate Court of Maryland At Large
  Dan Friedman"; no district: the office). `contest_type` "question", "retention" or "candidate"; `vote_for` the number from "Vote for 1" / "Vote for up to 3". `choice` and `party` as
  published (questions: party ""), `choice_id` "". One row per vote-type column (name as published)
  and `TOTAL` from the Total column. `reporting_status` = "257 of 257 election day precincts
  reported" as published (county rows: that county's; state rows: the contest's). The Totals row
  isn't a row; Percentage is dropped. No turnout table (the pages carry none).
- **Summary lists** (nothing corrected; a check that couldn't run is `None`):
  - `vote_type_sum_mismatches`: (level, county, contest, choice, total, sum of types).
  - `totals_row_mismatches`: (level, county, contest, column, Totals row, sum of choices).
  - `county_state_mismatches`: (contest, choice, vote type, state value, county sum), both
    directions (a choice or contest on one side only is listed with `None` on the other). Joined on
    names (no ids). `None` when any office or question page is unreadable for that contest's office.
  - `reporting_mismatches`: (contest, state "N of M", summed county "n of m") where the counties'
    precinct counts don't add to the state's.
  - `refresh_times`: the distinct "Last refreshed" values with their page counts; a pass whose pages
    differ is listed in `mixed_refresh`.
  - `county_title_mismatches`: county pages whose `h1` doesn't name the configured county.
  - `non_numeric` (page, contest, choice, column, text); `not_reported` count for "NR" cells (votes
    ""); `duplicate_choices`; `unexpected_columns` (tables whose headers don't start Name/Party or
    Question N, or don't end Total, Percentage); `contests_without_reporting`.
  - `out_of_scope_titles`: sorted distinct `h2` titles not read.
  - `unreadable_files` / `missing_files`: per page; a county page that can't be read is listed and the
    county is missing from the cross-check (listed in `counties_missing`).

## Left to the builder / not done

- Certified precinct CSVs (post-certification) as a later reader.
- Whether the pages change URL scheme for 2028 (`2028`, `pres` instead of `gen`): config per election.
- Write-in candidates appear as named choices with "(Write-In)" in the name plus "Other Write-Ins".
- Fixture: Montgomery and Kent county pages, office pages 1, 4, 5 and 9 and question page 1, saved
  as published (office 5 lets Montgomery's eight own Senate districts be checked against real data).
