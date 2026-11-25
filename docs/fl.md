# Florida: Division of Elections results files, county level

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_fl.py`) on 2026-11-25 at 00:14 UTC, then parsed with `pipeline/readers/fl.py`. Design: `docs/superpowers/specs/2026-11-24-step2-fl-reader-design.md`. **County level; all 176 races in the files.** No statewide rows (the files have none).

## Where the data is

Linked from the Downloads page of Florida Election Watch (`https://floridaelectionwatch.gov/Downloads`). A pass makes three requests, 10 s apart, each with `?v=<unix seconds>` as the site's own links do:

| Kind | URL | Bytes | SHA-256 (first 12) |
|---|---|---|---|
| info | `https://flelectionfiles.floridados.gov/enightfilespublic/20261103_ElecResultsFL_PipeDlm_Info.txt` | 68,873 | `7311ccd89e95` |
| votes | `…/20261103_ElecResultsFL_PipeDlm_Votes.txt` | 141,307 | `a8a8365475a4` |
| tab | `…/20261103_ElecResultsFL.txt` | 365,374 | `6da5bdddd2f6` |

The layout is in `…/ResultsFileLayoutPipeDelimited.pdf` (2020): record types r (race), c (candidate), p (precincts per county per race), u (county), V (votes). File names contain the election date.

## Certificate

`flelectionfiles.floridados.gov` chains to **GoDaddy TLS Root CA - R1**, which the Mozilla, Homebrew and macOS stores don't contain (2026-11-24), so curl and Python fail verification. The main site (`floridaelectionwatch.gov`) verifies normally.

Steve chose option A: trust R1 for that host, with the fingerprint checked against GoDaddy's published copy. The root the server sends matches GoDaddy's published R1 exactly (SHA-256 `25:CF:3D:A8:…:71:9F`). The project uses the narrower form: `pipeline/certs/godaddy-tls-root-r1-cross-g2.pem` is GoDaddy's published cross-certificate of R1, signed by Go Daddy Root G2. For Florida's source only, `fetch` adds it to the default store with partial-chain trust off, so the chain still has to end at G2, which the default store has. No root is added and nothing is disabled. Source, fingerprint and expiry (2037-12-31) are in `pipeline/certs/README.md`.

## Parsed (2026-11-25, pass started 00:14 UTC)

- **Output:** 3,063 rows (one per county vote record).
- **Coverage:** 176 races, 406 choices, 67 counties. Rows by race code: GOV 670, DCA 502, AMD 402, STR 283, USR 282, USS 201, AGR 201, ATG 134, CFO 134, SCJ 134, STS 94, CTJ 10, and 4 each for four special districts (ECW, PLB, SEB, TOL).
- **Clean:** no unknown ids, duplicates, non-integer counts, missing precinct counts, reporting above the precinct count, races without votes, missing (race, county, candidate) records or malformed lines. **The pipe and tab files agree on every vote record, in both directions**, and every candidate has one party.
- **Listed or counted:**
  - `status_counts`: all 3,063 records have status I ("Incomplete"), although the site header says "Official Election Results".
  - `zero_precincts_reporting`: 91 records report 0 precincts (e.g. every Alachua race: "0/63 precincts").
- **US Senate (county sums, which equal the race page's statewide totals):** Moody REP 4,211,733; Nixon DEM 3,975,375; Gillespie NPA 94,681; total 8,281,789.

## Quirks

- **County ids are FIPS:** unit id 12001 = Alachua; `county_id` is the unit id as published.
- **Candidate ids repeat across races:** every retention question and amendment uses 10 and 20. Join on (contest_id, choice_id), never choice_id alone. Their choice texts differ: retention "Yes"/"No", amendments "Yes for Approval"/"No for Rejection".
- **Governor tickets:** the pipe file puts the governor's surname in "first name" and the running mate's in "last name", so `choice` reads "Donalds Avila".
- **Party and race code come from the tab file,** which has no ids. They're joined on (race name, county name, last name, first name). For the 26 retention and amendment races, the tab's race name is the part of the pipe name after the first colon.
- **No version id** links the three files; a pass on election night could straddle a publish, and then the pipe-vs-tab check would list timing differences.
- No statewide rows; no vote types; no precincts.

## Not done

- Statewide rows (only on the HTML race pages).
- Precinct results (county Supervisor of Elections sites).
- Why every record is status I, and the 91 zero-reporting records.
