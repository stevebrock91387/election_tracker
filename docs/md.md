# Maryland: State Board of Elections live results pages (HTML)

Seen 2026-11-24 in the built-in browser and by script. Downloaded through `pipeline/fetch.py` (`pipeline/run_md.py`) on 2026-11-24 at 21:29–21:32 Pacific (05:29–05:32 UTC 11-25), then parsed with `pipeline/readers/md.py`. Design: `docs/superpowers/specs/2026-11-24-step2-md-reader-design.md`. **County level, four vote types, live: the reader works on the election-night pages, which keep the same URLs as counting goes on** (Steve, 2026-11-24: "I want the results as they come in, not when they're done"). Stdlib only.

## Where the data is

Base `https://elections.maryland.gov/elections/2026/general_results/` (linked as "Unofficial General Results" from the 2026 elections page). A pass is 36 requests, 5 s apart (about 3 minutes):

- 24 county pages `gen_results_2026_by_county_<n>.html` (every contest on that county's ballot, statewide questions included): **the data**.
- 9 office pages `gen_results_2026_<n>.html` (every district of one office) and 3 question pages `gen_qresults_2026_<n>.html`: **the check**.

The question-only county pages (`gen_qresults_2026_by_county_<n>`) repeat the county pages' statewide questions (Montgomery Question 1 identical cell for cell) and aren't read. All 36 pages said "Last refreshed: 11/23/2026 07:40:42 PM". Montgomery's page: 99,993 bytes, SHA-256 `5694d0bd1301…`.

## Parsed (2026-11-24)

- **Output:** 8,470 rows (5,950 county, 2,520 state); vote types Early Voting, Election Day, Mail-In Ballot, Provisional, and TOTAL.
- **Coverage:** 145 contests: Governor, Comptroller, Attorney General, 8 Congress, 47 State Senate, 71 House of Delegates, 11 circuit-judge (county) contests, Supreme Court Circuit 4 and Appellate Court at-large retention, and 3 statewide questions. 44 county/local titles out of scope (county offices, boards of education, lettered local questions).
- **Provenance:** every row carries its page's SHA-256 (`source_sha256`) and "Last refreshed" time as published (`source_created_at`), so rows from a pass that straddles a site rebuild can be told apart.
- **Clean:** all 145 contests checked (`contests_checked` 145): county sums equal the office/question pages for every choice and vote type; counties' precinct counts add up to the state's; vote types sum to Total and choices to the Totals row everywhere (no table where that check couldn't run); no title mismatches, non-numeric or NR cells, duplicates, empty contests, unexpected columns, page problems, mixed or missing refresh times, or configured offices not found.
- **Example, Governor (state page):** Moore/Miller (Democratic) 1,472,845; Cox/Krop (Republican) 683,775; Ellis/Silverman Andrews (Green) 48,649; White/Permut (Working Class Party) 43,760; other write-ins 5,958. Unofficial (the page says so); not checked against certified results.

## Quirks

- **No ids.** contest_id is the office plus its headings ("Representative in Congress District 4", "House of Delegates District 9A", "Judge, Appellate Court of Maryland At Large Dan Friedman", "Justice, Supreme Court of Maryland Circuit 4 Peter Killough"); choices are joined by name.
- **Headings nest:** h2 office, then h3/h4 qualifiers (district; circuit then county; or a retention judge, "Name / Vote Yes or No / For continuance in office"); "Vote for 1" / "Vote for up to 3 - …" (h3, h4 or, on the circuit-judge office page, h5) set vote_for.
- **Circuit judges** are elected county by county: the office page heads them "Circuit 2" / "Cecil County", a county page only "Circuit 2". County pages add the county name for offices in `per_county_offices`.
- **Question tables** put the choice in a `<th>` inside the body; header rows are told apart by `<thead>`.
- `reporting_status` is the page's phrase, e.g. "257 of 257 election day precincts reported": election-day precincts only, so it says nothing about mail-in ballots still to count.
- Write-in candidates who filed appear by name with "(Write-In)"; the rest are "Other Write-Ins".
- No turnout (no registered voters or ballots cast on these pages), so no turnout file.

## Summary lists beyond the design

- `totals_row_not_checked`: tables whose Totals check couldn't run (no Totals row, a short one, a non-numeric Totals cell, or NR cells in a column), so an unrun check never reads clean.
- `empty_contests`, `offices_not_found` (configured offices or questions with no contest on any page read: a retitled office shows here instead of vanishing), `pages_without_refresh`, `contests_checked`.
- The design's `counties_missing` isn't a separate list: an unreadable county page is in `unreadable_files`, and every contest it touches lands in `contests_not_checked` through the precinct-count gate.

## Not done

- Tested only on final pages: NR cells and partial reporting are covered by synthetic tests, not seen live. Whether the pages are rebuilt in place during the count (and how often) is unverified.
- A failed page stops the pass, like the other readers (Steve's call, 2026-11-24: "Maryland works like the other readers"). Skipping and listing a failed page was considered and declined.
- Certified precinct CSVs (after certification) as a separate reader; 2028 needs new page names in the config.
