# Clarity (Scytl) platform: CO, IA, SC, WV

Seen 2026-11-20 in the built-in browser (page network requests) and with one recon download per state; then downloaded through `pipeline/fetch.py` and parsed with `pipeline/readers/clarity.py`. Design: `docs/superpowers/specs/2026-11-20-step2-clarity-reader-design.md`. **County level only**; precinct results are on each county's own Clarity site (not read yet).

## Where the files are

Each election has a base URL; `<base>/current_ver.txt` holds the current version number, and every file lives under `<base>/<version>/`. A fetch pass reads the version first, then builds the data URLs from it.

| State | Base (2026 general) | Data file(s) | Version fetched |
|---|---|---|---|
| CO | `https://results.enr.clarityelections.com/CO/127407` | `reports/detailxml.zip` | 387376 |
| SC | `https://www.enr-scvotes.org/SC/127300` | `reports/detailxml.zip` | 386661 |
| WV | `https://results.enr.clarityelections.com/WV/127496` | `reports/detailxml.zip` | 387101 |
| IA | `https://electionresults.iowa.gov/IA/127077` | `json/sum.json` + `json/ALL.json` (no XML: 404) | 387368 |

The election id (127407 etc.) changes per election; a new election means a new base in `pipeline/sources_clarity.toml`.

## Formats

- **Detail XML** (`detail.xml` in the zip): contest (`key`) → choice (`key`, `text`, `party`, `totalVotes`) → vote type (`name`, `votes`) → county (`name`, `votes`). Also per-county registered voters, ballots cast and precincts (`ElectionVoterTurnout`), and per contest per county precincts reported (`ParticipatingCounties`).
- **Iowa JSON**: `sum.json` has each contest's key `K`, choice names `CH`, choice ids `CHAggId`, parties `P`, statewide votes `V`. `ALL.json` has, per area `A`, contest keys `C` and vote arrays `V` in `sum.json`'s choice order. The area named `-1` is the statewide total.
- **Iowa's server gzips its JSON even when not asked** (`Content-Encoding: gzip`). Raw files are saved as received; the reader un-gzips them.
- The JSON on every Clarity site has no vote types (`vt.json` is empty in all four); Iowa's Election Day / Absentee split exists only in `reports/detailtxt.zip`, a fixed-width text file without ids (not read).

## Parsed (2026-11-20, files fetched 2026-11-21T01:53:06Z)

| State | Bytes | Contests | Counties | Rows | Vote types | Mismatches |
|---|---|---|---|---|---|---|
| CO | 62,049 | 302 | 64 | 7,084 | Total Votes | 0 |
| SC | 78,008 | 171 | 46 | 19,671 | Election Day, Early Voting, Absentee By Mail, Failsafe, Failsafe Provisional, Provisional, "Provionsal" | 0 |
| WV | 16,804 | 126 | 55 | 1,355 | Election Day (only) | 0 |
| IA | 26,354 + 27,284 (gzip) | 274 | 99 | 6,014 | none (totals only) | 0 |

"Mismatches": XML vote types vs choice total and counties vs vote type; IA counties vs statewide and the `-1` area vs statewide.

- **SC** spells "Provisional" as **"Provionsal"** on 33 choice lines; kept as published.
- **WV** labels every vote "Election Day", though the state also has early and absentee voting; kept as published.
- **SC's statewide file carries local contests** (e.g. 40111, a school-district referendum in 2 counties). They are `contest_scope = statewide` because their key is unique across the file.
- No county `TOTAL` row is made for XML states (none is published); sum the vote types.
- `county_id` is empty: Clarity names counties but gives no code.
- WV's file was last updated 2026-11-16, SC's 2026-11-10 ("Official Results" per the earlier browser check), CO's and IA's 2026-11-20.

## Not yet known / not done

- Rate limits: none published; 2 minutes per file is applied.
- Precinct results (264 county sites; CO's Adams County site has precinct JSON and no XML).
- Mapping county names to FIPS codes.
