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

## Not yet known

- **Whether GA, UT and WA exports use the same JSON structure as AZ.** Not downloaded or opened.
- **Utah's export is 0.5 MB** against 47–75 MB for the others; it may lack precinct detail. Unconfirmed.
- **Rate limits for GA, UT and WA.** Only Arizona's (2 minutes) is documented; until each state's terms are known, use at least the same interval.
- `publicElectionId` formats differ by state (`110326GeneralElection`, `11032026GeneralAndSpecialElection`, `General11032026`, `20261103`), so a reader must read the ID from the jurisdiction API rather than build it.
