# Hawaii: Office of Elections text files (precinct level)

Seen 2026-11-24 in the built-in browser and with a recon download. Downloaded through `pipeline/fetch.py` (`pipeline/run_hi.py`) on 2026-11-24 at 23:32 Pacific (07:32 UTC 11-25), then parsed with `pipeline/readers/hi.py`. Design: `docs/superpowers/specs/2026-11-24-step2-hi-reader-design.md`. **Precinct level with mail and in-person votes, every contest, the statewide file as a check.**

## Where the data is

Linked as "Certified Text Files" in the 2026 tab of `https://elections.hawaii.gov/election-results/` ("Last Updated: November 24, 2026 7:37 am"). Two requests per pass:

| File | Link text | Bytes | SHA-256 (first 12) |
|---|---|---|---|
| `…/wp-content/results/2026%20General/summary.txt` | Statewide Summary | 22,026 | `b262fa9df3b4` |
| `…/wp-content/results/2026%20General/media.txt` | Statewide Precinct Detail | 1,885,088 | `c8cc8576e80b` |

The same tab links PDFs (statewide and county summaries, precinct detail, statement of vote).

## Parsed (2026-11-24)

- **Output:** 78,732 rows: 77,298 precinct rows (25,766 lines × TOTAL, mail, in-person) and 1,434 state rows (202 lines × 3, plus Blank, Over and Invalid Votes × 3 for 92 contests); 496 turnout rows.
- **Coverage:** 92 contests (U.S. House, Governor, legislature, OHA trustees, county offices, statewide and county charter questions); 496 units: 249 plain (247 precincts `01-01` … `51-05`, plus `OS I`, `OS II`) and 247 `VSC` units.
- **Clean:** every check. Summed to the state, the precinct mail and in-person votes equal the summary for all 202 lines; every Total equals mail + in-person; registered voters (853,399) equal the sum over units; Total/Counted Precincts equal the units with lines and the units with Reporting 1; titles and candidate names agree between files; no conflicts, duplicates, non-numeric cells or malformed lines; nothing in the `*_not_checked` lists.
- **Example (state rows):** Governor: Green (D) 279,445, Cordery (R) 105,258. U.S. House 1: Case (D) 126,337, Lam (R) 40,308, Conley (G) 7,011, Berning (N) 2,348. U.S. House 2: Tokuda (D) 129,931, Awa (R) 65,441.

## Quirks

- **Two units per precinct.** The plain unit carries registered voters, Reporting 1 and the mail votes (in-person 0); the `VSC` (Voter Service Center) unit carries 0 registered voters, Reporting 0 and the in-person votes (mail 0). Units are keyed by `precinct_splitId` (`precinct_id`); VSC units are `precinct_is_virtual` "Y" and named `01-01 VSC`. To get a precinct's full vote, add its two units.
- **Party** comes from a name prefix (`(D) TOKUDA, Jill N.`); the party columns are empty. Nonpartisan contests have no prefix and an empty party.
- **Multi-line names:** the Governor and Lieutenant Governor ticket is one quoted field over four lines; whitespace runs are collapsed to one space (`(D) GREEN, Josh For GOVERNOR KAWAKAMI, Derek S.K. For LIEUTENANT GOVERNOR`).
- **`OS I`, `OS II`:** 0 registered and 0 ballots in 2026, no VSC unit; meaning unverified (kept, virtual).
- No county anywhere: precinct ids begin with the state house district, not the county.
- Blank, over and invalid votes are state-level only.

## Not done

- Precinct → county mapping.
- `sources/registry.csv` still describes Hawaii as "PDF summary reports" (as of 2026-11-20); the text files above are the source this reader uses.
- Election-night behaviour: these are the certified files. The 2024 election published numbered printouts on election night (registry); whether 2028's use the same files and paths is unverified.
