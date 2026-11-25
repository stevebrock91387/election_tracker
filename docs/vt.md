# Vermont: SOS static JSON, town level

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_vt.py`) on 2026-11-24 at 16:26 Pacific (00:26 UTC 11-25), then parsed with `pipeline/readers/vt.py`. Design: `docs/superpowers/specs/2026-11-24-step2-vt-reader-design.md`. **Town level (by town part); federal, statewide, state senate and state house offices.** County and town offices are out.

## Where the data is

The site `https://electionresults.vermont.gov/` reads static files under `https://static.electionresults.vermont.gov/elections/`. `elections.json` lists elections; the 2026 general is guid `68d61e96-1d28-4210-8c1d-8e90512ae105`. A pass reads `<guid>.json`, which names one timestamped file per tab, then five of them, 10 s apart:

| Kind | File (snapshot 20261117185828) | Bytes | SHA-256 (first 12) |
|---|---|---|---|
| election | `<guid>.json` | 119,967 | `f4f6a07a93c0` |
| federal | `<guid>-f-<snapshot>.json` | 324,255 | `144361738949` |
| stateWide | `<guid>-s-<snapshot>.json` | 1,329,283 | `bb5c5ba6fe6b` |
| senate | `<guid>-sn-<snapshot>.json` | 356,624 | `ac6f21da316a` |
| house | `<guid>-h-<snapshot>.json` | 454,737 | `9004bebdceed` |
| turnOut | `<guid>-turnout-<snapshot>.json` | 3,560,436 | `2e3f638ef9e8` |

## Parsed (snapshot 20261117185828; site: "OFFICIAL", 247 of 247 towns, last updated 11/17/2026 06:58 PM)

- **Output:** 20,468 rows: 2,548 total rows (statewide and district totals) and 17,920 town-part rows; 247 turnout rows.
- **Coverage:** 132 offices (Congress, 6 statewide, 16 senate districts, 109 house districts), 247 towns in 283 town parts.
- **Every check is clean:** town-part sums equal the total entry for every choice (blank and over votes included), and no choice is in one but not the other; every entry's vote slots equal votes + blank + over; each town's Congress ballots (summed over its parts) equal its turnout ballots, and the Congress total equals the turnout sum; no unknown towns, duplicates, non-integer counts or stray choices.
- **Turnout sums:** registered 506,830; ballots 311,510 (= the Congress total); absentee 193,189.
- **Example, Congress:** Balint DEMOCRATIC 198,758; Malloy REPUBLICAN 94,078; four independents; blank 6,241, overvotes 594.

## Quirks

- **Split towns:** a town split by legislative districts has one entry per (house district, senate district) part: 24 towns, e.g. Burlington 6 parts and Brattleboro 3 for Congress. Rows keep the part in `precinct_id` as "house district|senate district"; sum the parts for a town total.
- **District contests** share an office id (12 for every senate district, 11 for every house district), so `contest_id` is "oid:district code" ("12:CHI CT 1"). `vote_for` is 1–3 for senate and 1–2 for house districts.
- **`sc` is vote slots,** not ballots, where more than one seat is elected.
- **Fusion** appears as one line with a combined party name (DEM/PROG, REP/DEM, PROG/DEM).
- **Blank votes and overvotes** are rows with an empty `choice_id` ("Blank Votes", "Overvotes"), as the site shows them.
- **Reporting fields** differ by file: federal and statewide totals say "0/0" (`distReported`), district entries "25/25" (`townsReported`); kept as published.
- **Write-in names** list everyone who got a write-in vote, many apparently private individuals. They're in the raw and parsed data (gitignored); the committed test fixture replaces them with "WRITE-IN <id>".
- Senate district names end in an underscore ("ADDISON_"), kept as published. No FIPS codes; no vote types.

## Not done

- County and town offices; unorganized gores (no results entries).
- Whether the files change after this snapshot.
