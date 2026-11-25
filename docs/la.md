# Louisiana: SOS live-results blobs, parish level

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_la.py`) on 2026-11-24 from 16:52 Pacific (00:52 UTC 11-25; 44 files, about 7⅓ minutes), then parsed with `pipeline/readers/la.py`. Design: `docs/superpowers/specs/2026-11-24-step2-la-reader-design.md`. **Parish level, total and early votes; 21 races:** US Senator, US Representative 1–6, Public Service Commission districts 1 and 5, BESE district 1, State Representative district 92, and Constitutional Amendments 1–10.

## Where the data is

`https://voterportal.sos.la.gov/ElectionResults/ElectionResults/Data?blob=<path>` (JSON). For 11/03/2026 (`<date>` = `20261103`):

| Kind | Path | Notes |
|---|---|---|
| races | `<date>/RacesCandidates_Multiparish.htm` | race and choice ids, titles, choice labels ("Julia Letlow (REP)"); `WriteTime` |
| votes | `<date>/Votes_Multiparish.htm` | statewide or district totals, precincts, absentee, qualified and voted counts, outcomes |
| parish-<race> | `<date>/VotesRaceByParish/Votes_<race>.htm` | the same by parish (only the race's parishes) |
| early-<race> | `<date>/VotesEarly/Votes_<race>.htm` | early votes by parish |

`ElectionDates.htm` lists 320 elections back to 1982 (11/03/2026 is official; the 12/12/2026 runoff is the default). Parish names come from the site's JavaScript (`parishList`), copied into `pipeline/sources_la.toml` with codes "01" (Acadia) to "64" (Winn).

## Parsed (2026-11-24, pass started 00:52 UTC)

- **Output:** 4,163 rows (state totals, parish totals and parish early votes); 822 turnout rows (one per race and parish).
- **Coverage:** 21 races, 64 parishes.
- **Every check is clean:** parish sums equal the state value for every choice and for qualified, voted, precinct and absentee counts; early votes never exceed totals; every parish reported early votes; no unknown parishes, duplicates, non-integer counts or malformed entries.
- **Runoffs:** House 5 and House 6 have `Runoff` outcomes (the 12/12/2026 runoff is a separate election date).
- **Example, US Senator (official):** Letlow (REP) 746,466 Elected; "Jamie" Davis (DEM) 720,516; 3,722 precincts; 2,975,700 qualified, 1,493,171 voted.

## Quirks

- **Choice ids repeat across races:** every amendment uses 3 (YES) and 4 (NO). Join on (contest_id, choice_id).
- **Party** is taken from the trailing code in the choice label ("(REP)"); amendment choices have none.
- **Outcomes** (Elected, Runoff, Approved, Defeated) have no schema column; the summary lists them per race.
- **Early votes** are vote type "EarlyVoting" (the file's key); whether they include mail absentee isn't stated.
- **Turnout counts are per race:** each race has its own qualified and voted counts per parish.
- **Parish ids are the site's codes** ("01".."64"), not FIPS.
- **No election name** in any blob. Before election day the site warns it "may contain test data"; nothing in the blobs marks test data.

## Not done

- Precinct results (one file per race per parish).
- The 12/12/2026 runoff and other dates (add a config entry per date).
- Judges, district attorneys, municipal races, local propositions.
