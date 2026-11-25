# Alaska: Division of Elections precinct CSV (first-choice results)

Seen 2026-11-24 in the built-in browser and with a single recon download. Downloaded through `pipeline/fetch.py` (`pipeline/run_ak.py`) on 2026-11-24 at 17:35 Pacific (01:35 UTC 11-25), then parsed with `pipeline/readers/ak.py`. Design: `docs/superpowers/specs/2026-11-24-step2-ak-reader-design.md`. **Precinct level, total plus five vote types, every contest in the file. These are first choices (round 1): Alaska's general uses ranked-choice voting, and the final rounds are a separate tabulation not read here.**

## Where the data is

`https://www.elections.alaska.gov/enr/26GENR/results/GA_ENR_Precinct_State_of_Alaska.csv`, linked as "Summary (csv)" from the election page `https://www.elections.alaska.gov/election-results/e/?id=26genr` ("Results Status: Official", last updated November 23, 2026). One request per pass. The same page links a summary PDF, per-house-district PDFs and the cast vote record (JSON in a ZIP).

| File | Bytes | SHA-256 (first 12) |
|---|---|---|
| CSV | 3,335,767 | `448d82a6beba` |

## Parsed (2026-11-24)

- **Output:** 120,276 rows (20,046 lines × TOTAL plus five vote types); 523 turnout rows.
- **Coverage:** 76 contests; 523 units: 402 real precincts and 121 counting units (Absentee, Early Voting and Question per house district, and HD99 Fed Overseas Absentee).
- **Clean:** every line's vote types sum to its totals (ballots, votes, under, over); candidate lines of each (unit, contest) agree on ballots, under and over; no negative ballot gaps; no duplicates, unit-id conflicts, non-integer counts or malformed lines; every unit has a U.S. Senator line.
- **Listed:** 12 counting units whose ballots differ between contests (the Absentee, Early Voting and Question units of districts 30, 36, 37 and 39; their ballots split by judicial district, e.g. District 30 Absentee 2,171 + 310 = 2,481, so these units most likely span two judicial districts, an inference).
- **Write-in gap (informational):** per contest, ballots − votes − under − over summed over units; e.g. U.S. Senator 886, U.S. Representative 439, Governor 828. It is exactly 0 for the two ballot measures and the Supreme Court retention, which have no write-ins: the gap is most likely write-in votes, which the file doesn't list (unverified).
- **Example, U.S. Senator (first choices):** Peltola (DEM) 144,583; Sullivan, Dan S. (REP) 132,022; Heikes (REP) 6,107; Sullivan, Daniel J. Jr. (no party code) 4,767.

## Quirks

- **Counting units** are rows with `precinct_is_virtual` "Y"; the 80 Early Voting and Question units have no Pct_Id, so their `precinct_id` is the unit name. Real precincts carry only Election Day votes; absentee, early, question and remote votes come only from the counting units.
- **Turnout** uses each unit's U.S. Senator ballots and the published registered voters (0 for counting units except HD99, 822).
- `Reporting_flag` is 0 on every line (meaning unknown); counted in the summary.
- `contest_type` is "first choice" on every row.

## Not done

- Ranked-choice final rounds (tabulation reports or the cast vote record).
- Statewide rows (only in the PDF), write-in names.
- Election-night behaviour of the CSV (only the official, post-certification file was seen).
