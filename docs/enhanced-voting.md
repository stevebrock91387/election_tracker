# Enhanced Voting platform: AZ, GA, UT, WA, VA, RI, ID

Platform evidence checked 2026-11-20 in the built-in browser (page source, network requests, page links) and with curl `HEAD` requests. All seven exports were later downloaded once and parsed (see "Parsed with" below).

## Evidence the states share the platform

| State | Results site | Evidence |
|---|---|---|
| AZ | `app.enhancedvoting.com/results/public/Arizona/...` (linked from azsos.gov/press) | Hosted on enhancedvoting.com itself. |
| GA | `results.sos.ga.gov/results/public/Georgia` | Page's Content-Security-Policy allows `app.enhancedvoting.com`; page calls `/results/public/api/jurisdictions/Georgia` and `/results/public/api/elections/...`; the GA export also exists on `app.enhancedvoting.com/cdn/...` with the **same ETag** as GA's own copy. |
| UT | `electionresults.utah.gov/results/public/Utah` | CSP allows `app.enhancedvoting.com`; same `/results/public/api/...` endpoints and page layout ("Download Reports", "Media Export"). |
| WA | `results.votewa.gov/results/public/washington` | Same as UT. |

The jurisdiction API (`/results/public/api/jurisdictions/<State>`) lists elections with a `publicElectionId` and has a `mediaExportPath` field, which is `null` for GA, UT and WA. The export links come from the election pages, not that field.

## Media export files (2026 general; HEAD checks before download)

Each state's 2026 general-election page has a **"Media Export"** link. URL pattern: `<site>/cdn/results/<State>/export-<publicElectionId>.json`.

| State | Linked export URL | HEAD result (2026-11-20) |
|---|---|---|
| AZ | `https://app.enhancedvoting.com/cdn/results/Arizona/export-110326GeneralElection.json` (linked from azsos.gov/press) | downloaded: 72,662,370 bytes; see `docs/az-feed.md` |
| GA | `https://results.sos.ga.gov/cdn/results/Georgia/export-11032026GeneralAndSpecialElection.json` | 200, octet-stream, 47,465,091 bytes, Last-Modified 2026-11-20 15:51:31 GMT, ETag `0x8DF471E2580BDE8` |
| UT | `https://electionresults.utah.gov/cdn/results/Utah/export-General11032026.json` | 200, octet-stream, 518,303 bytes, Last-Modified 2026-11-20 16:28:06 GMT |
| WA | `https://results.votewa.gov/cdn/results/washington/export-20261103.json` | 200, octet-stream, 74,864,683 bytes, Last-Modified 2026-11-20 00:42:53 GMT |

## Added later on 2026-11-20: VA, RI, ID

Found while verifying the registry; each official state page links an Enhanced Voting site (CSP allows `app.enhancedvoting.com`) with a Media Export link. Downloaded and parsed later the same day (below).

| State | Results page | Linked export |
|---|---|---|
| VA | `https://enr.elections.virginia.gov/results/public/virginia/elections/2026-November-General` | `https://enr.elections.virginia.gov/cdn/results/virginia/export-2026-November-General.json` |
| RI | `https://electionresults.ri.gov/results/public/rhodeisland/elections/2026StatewideGeneralElection` | `https://electionresults.ri.gov/cdn/results/RhodeIsland/export-2026StatewideGeneralElection.json` |
| ID | `https://results.voteidaho.gov/results/public/id/elections/nov2026` | `https://results.voteidaho.gov/cdn/results/id/export-nov2026.json` |

That makes seven states on the platform: AZ, GA, UT, WA, VA, RI, ID.

## Parsed with `pipeline/readers/enhanced_voting.py` (2026-11-20)

One download per state through `pipeline/fetch.py` (hashes in `data/raw/manifest.csv`; AZ and UT were saved earlier under `data/raw/az-2026/` and `data/raw/ev-2026/`, outside the manifest). All seven parse. Statewide vs county totals are matched by **(contest id, option id)**, the guide's option key.

| State | Bytes | Counties | Precincts | Vote types | Pairs compared | Statewide ≠ county sum | Null vote-type counts |
|---|---|---|---|---|---|---|---|
| AZ | 72,662,370 | 15 | yes | yes | 415 | 0 | 0 |
| GA | 47,465,091 | 159 | yes | yes | 457 | 0 | 192 county + 37,087 precinct option lines |
| UT | 518,303 | 29 | no | no | 290 | 0 | 0 |
| WA | 74,864,685 | 39 | yes | no | 468 | 0 | 0 |
| VA | 26,732,640 | 133 | yes | yes | 115 | 0 | 0 |
| RI | 11,104,413 | 40 | yes | yes | 1,277 | 0 | 0 |
| ID | 8,233,749 | 44 | yes | no | 292 | 0 | 0 |

No numeric vote-type mismatches at any level in any state.

- **Correction (2026-11-20):** an earlier version of this section said GA had 37 and WA 21 statewide-vs-county mismatches "in the file itself". That was wrong: the first reader matched options by **name**, and some counties spell the same option differently under the same option id (GA `Richard Woods (I) (Rep)` vs `Richard Woods (I)(Rep)`; WA `Write-in` vs `Write-In`, `Levy  Yes` vs `Levy Yes`). Matched by id, there are none. Found by the final code review.
- **GA publishes some vote-type counts as null** (not 0): those option lines are listed as "not published", not as mismatches.
- **UT:** one county write-in line (contest 636107031, option 191, 78 votes) has no statewide match.
- **VA:** one ranked-choice contest (Arlington County Board, `cc381`, typed `RankChoice`, no round results in the file) is skipped and listed, not parsed.
- **Names are not keys:** option names vary in spelling across counties, local contest ids repeat across counties (GA, UT, ID), and WA King County reuses precinct ids. The common output has no option-id column yet (see the step 2 design's open question).
- WA's file was regenerated between the HEAD check (74,864,683 bytes) and the download (74,864,685).
- GA's vote-type groups: Election Day, Advance Voting, Absentee by Mail, Provisional. WA and ID publish none.

## Not yet known

- **Rate limits** for every state but AZ. Only Arizona's (2 minutes) is documented; the same is applied to all.
- `publicElectionId` formats differ by state (`110326GeneralElection`, `11032026GeneralAndSpecialElection`, `General11032026`, `20261103`), so a reader must read the ID from the jurisdiction API rather than build it.
