# Enhanced Voting platform: AZ, GA, UT, WA

Checked 2026-11-20 in the built-in browser (page source, network requests, page links) and with curl `HEAD` requests. No export file except Arizona's was downloaded.

## Evidence the states share the platform

| State | Results site | Evidence |
|---|---|---|
| AZ | `app.enhancedvoting.com/results/public/Arizona/...` (linked from azsos.gov/press) | Hosted on enhancedvoting.com itself. |
| GA | `results.sos.ga.gov/results/public/Georgia` | Page's Content-Security-Policy allows `app.enhancedvoting.com`; page calls `/results/public/api/jurisdictions/Georgia` and `/results/public/api/elections/...`; the GA export also exists on `app.enhancedvoting.com/cdn/...` with the **same ETag** as GA's own copy. |
| UT | `electionresults.utah.gov/results/public/Utah` | CSP allows `app.enhancedvoting.com`; same `/results/public/api/...` endpoints and page layout ("Download Reports", "Media Export"). |
| WA | `results.votewa.gov/results/public/washington` | Same as UT. |

The jurisdiction API (`/results/public/api/jurisdictions/<State>`) lists elections with a `publicElectionId` and has a `mediaExportPath` field, which is `null` for GA, UT and WA. The export links come from the election pages, not that field.

## Media export files (2026 general)

Each state's 2026 general-election page has a **"Media Export"** link. URL pattern: `<site>/cdn/results/<State>/export-<publicElectionId>.json`.

| State | Linked export URL | HEAD result (2026-11-20) |
|---|---|---|
| AZ | `https://app.enhancedvoting.com/cdn/results/Arizona/export-110326GeneralElection.json` (linked from azsos.gov/press) | downloaded: 72,662,370 bytes; see `docs/az-feed.md` |
| GA | `https://results.sos.ga.gov/cdn/results/Georgia/export-11032026GeneralAndSpecialElection.json` | 200, octet-stream, 47,465,091 bytes, Last-Modified 2026-11-20 15:51:31 GMT, ETag `0x8DF471E2580BDE8` |
| UT | `https://electionresults.utah.gov/cdn/results/Utah/export-General11032026.json` | 200, octet-stream, 518,303 bytes, Last-Modified 2026-11-20 16:28:06 GMT |
| WA | `https://results.votewa.gov/cdn/results/washington/export-20261103.json` | 200, octet-stream, 74,864,683 bytes, Last-Modified 2026-11-20 00:42:53 GMT |

## Added later on 2026-11-20: VA, RI, ID

Found while verifying the registry; each official state page links an Enhanced Voting site (CSP allows `app.enhancedvoting.com`) with a Media Export link. None of these exports has been downloaded.

| State | Results page | Linked export |
|---|---|---|
| VA | `https://enr.elections.virginia.gov/results/public/virginia/elections/2026-November-General` | `https://enr.elections.virginia.gov/cdn/results/virginia/export-2026-November-General.json` |
| RI | `https://electionresults.ri.gov/results/public/rhodeisland/elections/2026StatewideGeneralElection` | `https://electionresults.ri.gov/cdn/results/RhodeIsland/export-2026StatewideGeneralElection.json` |
| ID | `https://results.voteidaho.gov/results/public/id/elections/nov2026` | `https://results.voteidaho.gov/cdn/results/id/export-nov2026.json` |

That makes seven states on the platform: AZ, GA, UT, WA, VA, RI, ID.

## Parsed with `pipeline/readers/enhanced_voting.py` (2026-11-20)

One download per state through `pipeline/fetch.py` (hashes in `data/raw/manifest.csv`; AZ and UT were saved earlier). All seven parse.

| State | Bytes | Counties | Precincts | Vote types | Statewide ≠ county sum | Groups ≠ total |
|---|---|---|---|---|---|---|
| AZ | 72,662,370 | 15 | yes | yes | 0 | 0 |
| GA | 47,465,091 | 159 | yes | yes | **37** | **191** (county level) |
| UT | 518,303 | 29 | no | no | 0 | 0 |
| WA | 74,864,685 | 39 | yes | no | **21** | 0 |
| VA | 26,732,640 | 133 | yes | yes | 0 | 0 |
| RI | 11,104,413 | 40 | yes | yes | 0 | 0 |
| ID | 8,233,749 | 44 | yes | no | 0 | 0 |

- **GA's mismatches are in the file itself, not the reader:** e.g. State School Superintendent (`S7`) is in all 159 counties under the same id, yet Richard Woods' county totals sum to 1,072,774 against 1,891,982 statewide; US House 5 is 175,797 vs 274,922. Some county rows have a nonzero total but vote-type groups summing to 0. Cause unknown; step 3's checks must flag this rather than trust either number.
- **WA's are all write-in lines** (a few to a few hundred votes each).
- GA's vote-type groups: Election Day, Advance Voting, Absentee by Mail, Provisional. WA and ID publish none.

## Not yet known

- **Whether GA, UT and WA exports use the same JSON structure as AZ.** Not downloaded or opened.
- **Utah's export is 0.5 MB** against 47–75 MB for the others; it may lack precinct detail. Unconfirmed.
- **Rate limits for GA, UT and WA.** Only Arizona's (2 minutes) is documented; until each state's terms are known, use at least the same interval.
- `publicElectionId` formats differ by state (`110326GeneralElection`, `11032026GeneralAndSpecialElection`, `General11032026`, `20261103`), so a reader must read the ID from the jurisdiction API rather than build it.
