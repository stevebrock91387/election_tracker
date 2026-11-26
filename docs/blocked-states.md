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
