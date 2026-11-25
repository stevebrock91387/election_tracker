# Delaware: Department of Elections ENR JSON, election-district level

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_de.py`) on 2026-11-24 at 17:25 Pacific (01:25 UTC 11-25), then parsed with `pipeline/readers/de.py`. Design: `docs/superpowers/specs/2026-11-24-step2-de-reader-design.md`. **Election-district (precinct) level, with machine, absentee and early votes; federal, statewide and legislative contests.** County offices are out. Delaware has one House seat and 3 electoral votes in 2028 (no Senate race until 2030).

## Where the data is

`https://elections.delaware.gov/results/enr/`, each file with `?t=<unix ms>` as the results page (`GE2026.html`) requests them:

| Kind | File | Bytes | SHA-256 (first 12) |
|---|---|---|---|
| statewide | `Election_StatewideResults_ID_GE2026.json` | 65,002 | `367f31e3cefd` |
| district | `Election_ByElectionDistrict_ID_GE2026.json` | 3,750,122 | `767ec0788141` |
| county | `Election_ByCountyWithWilmington_ID_GE2026.json` | 45,166 | `0cb6da959b70` |
| turnout | `Election_VoterTurnout_ID_GE2026.json` | 8,166 | `1d21e5411017` |

Only the statewide file has candidate ids, election date, report time and precinct counts; the others join on (contest title, candidate name).

## Parsed (2026-11-24; "OFFICIAL RESULTS", data as of 2026-11-10)

- **Output:** 29,261 rows (state, county and election-district rows; four vote types on state and district rows). 41 turnout rows.
- **Coverage:** 57 contests (U.S. Senator, Representative in Congress, Attorney General, Auditor, Treasurer, state senate and house districts), 530 election districts.
- **Every check is clean:** election-district sums equal the statewide values for all four vote types, and every line is in both files; county columns equal the statewide totals and their parts add up; each contest's districts with lines equal its precinct count; the turnout ALL row equals the district sums.
- **Example, U.S. Senator:** Coons (Democratic Party) 240,587 (machine 140,838, absentee 15,885, early 83,864); Katz 137,837.

## Quirks

- **Counts are strings with thousands separators** ("140,838") except in the county file; the reader removes the separators (a format, not a correction).
- **Per-contest precinct counts:** Attorney General, Auditor and Treasurer cover 527 of 530 districts (02-27, 31-16 and 41-16 have no lines for them).
- **County rows** are New Castle (10003), Kent (10001) and Sussex (10005), for statewide contests only; Wilmington and the rest of New Castle are checked, not rows.
- `contest_id` is the Contest Sorting Order (the only contest key; checked unique per title).
- Election-district rows carry no reporting status or timestamp (not published per district).

## Not done

- County offices; representative-district results; write-ins (a PDF).
- Election-night behaviour (only the post-election state was seen).
