# Blocked states: official sources on other hosts

Research 2026-11-25 (Steve chose option A: look for sanctioned bulk files before anything else). A
read-only research agent, web search and WebFetch only; nothing downloaded through `pipeline/fetch.py`.
A WebFetch 200 is that tool's client, not ours, so every lead still needs a project-fetcher try and a
look in the built-in browser before it counts as verified. No page found permits or forbids automated
access explicitly.

| State | Lead | Level | When | Verdict |
|---|---|---|---|---|
| MN | `electionresultsfiles.sos.mn.gov/20261103/allracesbycounty.txt` (semicolon-delimited, no header; same pattern for 2022 and the 2026 primary) | county | 2026 file exists; live updates unverified | promising |
| CA | SOS Election Night Data Feed for media that sign up (pipe-delimited files and a JSON API, about every 5 min after 8 pm PT); `sos.ca.gov/media`, media guide v20 | unverified | live | promising, on request |
| PA | pa.gov election-data page: precinct `.txt` bulk files (2026 primary posted, general not yet) | precinct | after certification | post-cert |
| KS | `kssos.org/elections/election-results.html`: precinct XLSX per office (2022, 2024); also by email request | precinct | after the election | post-cert |
| ME | Legislature law library open directory `lldc.mainelegislature.org/Open/Elections/Returns/<year>/` (xlsx, pdf; no 2026 folder yet) | town (unverified) | after certification | post-cert |
| NV | SOS precinct page "Excel or CSV" (seen only in a staging-site snippet); Clark County CVR ZIPs (marked "Confidential", not opened) | precinct | after the election | post-cert, unverified |
| NY | NYC Board of Elections election-district CSVs (5 of 62 counties) | election district | after the election | post-cert, partial |
| MO | PDFs only; precinct files sold on request | | | post-cert, paid |
| TN NH MI WI | statewide files are on the blocked hosts; MI/WI counties mostly PDFs (Kent County MI has an ElectionStats archive, unverified) | | | none found |
| OK | only the OKER app's export tab (password-gated API) | | | none found |
| KY | per-county PDF recaps; a precinct file reportedly on the blocked host | | | none found |

Third-party fallbacks (not sources): VEST / UF Election Lab, Redistricting Data Hub (2024 precincts for
KS MO TN NV MI OK).

Requests to a state (CA media feed, KS email, MO purchase, PA Right-to-Know) would go out from Steve;
none has been sent.

## Post-certification check (2026-11-27)

Looked again at the post-cert leads; none has a 2026 general file yet:
- **PA:** `pa.gov/agencies/dos/.../election-data` lists 2026 general voter registration only; election returns are posted for the 2026 primary. The 2024 general returns went up 2025-01-29 (`erstat_2024_g_268768_20250129.txt`), so expect late January.
- **NY:** `vote.nyc/page/election-results-summary` has 2026 special and primary files (per-contest Recap/EDLevel CSV and PDF, a CVR ZIP for the primary) and nothing for the general.
- **KS:** `sos.ks.gov/elections/election-results.html` lists the 2026 primary official totals PDF only.
- **ME:** `lldc.mainelegislature.org/Open/Elections/Returns/2026/` has two primary folders (`20260224`, `20260609`).
- **NV:** `nvsos.gov/.../precinct-level-results` answers the project fetcher with an Incapsula bot-check page: blocked like the results site.

## Minnesota follow-up (2026-11-26)

- Project fetcher, one request: `electionresultsfiles.sos.mn.gov/20261103/allracesbycounty.txt` returned
  200, 714,945 bytes (sha256 `ba71d3fa…`, `data/raw/mn-2026-general/20261126T223911Z.txt`): ISO-8859
  text, CRLF, 8,285 lines, 16 semicolon-separated fields, no header; 87 counties (U.S. Senator has 435
  lines = 87 × 5 choices). Offices include U.S. Senator, U.S. Representative, Governor, constitutional
  officers, amendment, judges, and county and soil-and-water offices. Field meanings are not verified
  (no spec read yet); the rows look like state; county id; precinct (empty); office id; office name;
  district; choice id; choice name; …; party; precincts reporting; precincts total; votes; percent;
  office total.
- Built-in browser: `electionresults.sos.mn.gov/20261103` (the official results site) loads and links
  "Downloadable Text Results" (`/Select/MediaFiles/Index?ersElectionId=201`), but that page, and the SOS
  2026 general results page on sos.mn.gov, went to a Radware CAPTCHA page ("validate.perfdrive.com").
  Not solved; not retried. The file host's directory listing is 403 (listing off).
- So the file itself answers scripts, but the page that lists the files and (likely) describes their
  format sits behind a bot check. Steve approved reading the file host directly (2026-11-26): reader in
  `docs/mn.md`.

