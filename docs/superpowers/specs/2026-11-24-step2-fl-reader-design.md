# Step 2: Florida reader (Division of Elections results files, county level)

Status: **approved under Steve's standing approval for the remaining state readers.** Steve chose (2026-11-24) "Florida option A": trust the certificate path to Florida's file host only, fingerprint checked against GoDaddy's published copy. Calls made without asking are marked "(my call)".

## Why

Florida has a 2028 Senate race (Class 3) and 28 House seats. The Division of Elections' Florida Election Watch site links three results files with every race by county.

## What recon found (2026-11-24, built-in browser + one download of each file to the scratchpad)

- **Downloads page** `https://floridaelectionwatch.gov/Downloads` links files on `https://flelectionfiles.floridados.gov/enightfilespublic/` (with a `?v=` cache-buster):
  - `20261103_ElecResultsFL_PipeDlm_Info.txt` (68,873 B; Last-Modified Oct 26): records `[r|FLDOS|seq|race name|election type|race id]` (176), `[c|FLDOS|seq|race id|last|first|candidate id]` (406), `[p|FLDOS|seq|race id|unit id|precincts]` (1,137), `[u|FLDOS|seq|county name|unit id]` (67).
  - `20261103_ElecResultsFL_PipeDlm_Votes.txt` (141,307 B; Last-Modified Nov 16): `[V|FLDOS|seq|status|race id|unit id|precincts reporting|candidate id|votes]` (3,063).
  - `20261103_ElecResultsFL.txt` (365,374 B; tab-delimited, same snapshot): ElectionDate, PartyCode, PartyName, RaceCode, RaceName, CountyCode, CountyName, Juris1num, Juris2num, Precincts, PrecinctsReporting, CanNameLast, CanNameFirst, CanNameMiddle, CanVotes (3,063 rows). Has party; has no ids.
  - Layout: `ResultsFileLayoutPipeDelimited.pdf` (2020). Status letters: I (Incomplete), F (Finished). All files UTF-8.
- **Certificate:** the file host's chain is `*.floridados.gov` → GoDaddy TLS Intermediate CA DV - R1v1 → GoDaddy TLS Root CA - R1, and the server also sends R1 self-signed. R1 is not in the Mozilla, Homebrew or macOS stores, so curl and Python fail verification. GoDaddy's repository (`https://certs.godaddy.com/repository`) publishes R1 (SHA-256 `25:CF:3D:A8:E9:B9:7A:DD:BF:92:54:3C:2B:82:52:7C:8A:4E:2C:FF:20:62:A6:48:30:40:D4:B6:4A:CE:71:9F`, identical to the one the server sends) and **R1 cross-signed by Go Daddy Root Certificate Authority - G2** (`gd_tls_root-r1-cross-g2.crt.pem`, SHA-256 `7B:CB:0F:2F:2D:10:31:A6:AF:8D:61:BA:A8:35:D2:83:5A:3B:8B:CC:26:D9:4A:3B:04:8B:16:55:FB:81:29:8C`, valid 2025-09-24 to 2037-12-31). G2 is in the Mozilla store. With the cross-certificate loaded and partial-chain trust off, Python verifies the host and the chain ends at G2.
- **Coverage:** 176 races, all "General Election": US Senator, 28 US House, Governor and Lieutenant Governor, Attorney General, CFO, Commissioner of Agriculture, state senate and house, Supreme Court and District Court of Appeal retention questions, circuit judges, 3 amendments, 4 special districts. 67 counties; unit ids are `12` + county FIPS (12001 Alachua).
- **US Senate county sums** equal the statewide totals on the race page (Moody REP 4,211,733; Nixon DEM 3,975,375; Gillespie NPA 94,681; total 8,281,789). Neither file has statewide rows.
- **Pipe vs tab:** 2,025 of 3,063 vote records join to the tab file on (race name, county name, last name, first name), all with equal votes and one party per candidate. The other 1,038 are the retention questions and amendments, whose race names differ between the files (nonpartisan, party NOP).
- **Status and precincts:** every V record has status `I` though the site says "Official Election Results"; 91 records report 0 precincts reporting.
- Governor tickets put the governor's surname in "first name" and the running mate's in "last name" (e.g. last Avila, first Donalds), as published.

## Approaches considered

1. **Pipe files for ids and votes, tab file for party (chosen; my call).** Ids for races, candidates and counties (FIPS); party joined by name where the names match.
2. Tab file only: party, but no ids; joins downstream would be by name.
3. The HTML race pages: one page per race and another per county breakdown; more requests, fragile parsing.

## Scope

All 176 races in the files (my call, as for Ohio: the state file carries state-administered races plus four multi-county special districts). County level only; no state rows (the files have none).

## Design

- **TLS (Steve's option A, implemented narrowly; my call on the mechanism):** `pipeline/certs/godaddy-tls-root-r1-cross-g2.pem` (GoDaddy's published cross-certificate, fingerprint above, source URL and date in a comment file next to it). `pipeline/fetch.py` gains an optional `cafile`: when given, the request uses the default trust store plus that file, with `VERIFY_X509_PARTIAL_CHAIN` cleared so the extra certificate can't act as a trust anchor by itself; without it nothing changes. Only Florida's source passes it. No verification is disabled anywhere.
- **Config** `pipeline/sources_fl.toml` `[fl-2026-general]`: `state = "FL"`, `info_url`, `votes_url`, `tab_url` (without `?v=`), `cafile = "pipeline/certs/godaddy-tls-root-r1-cross-g2.pem"`, `min_interval_s = 120`, `request_gap_s = 10`.
- **Fetch pass** `pipeline/run_fl.py fetch SOURCE_ID`: info, votes, tab (source ids `<id>-info`, `-votes`, `-tab`, `ext="txt"`), 10 s apart; any failure stops the pass.
- **Reader** `pipeline/readers/fl.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary)`:
  - One row per V record: `level = "county"`, `county_id` = unit id minus the leading `12` (the county FIPS, as "12001"? see below), `county_name` = the `u` name; `contest_id` = race id; `contest_name` = race name; `contest_type` = the tab file's RaceCode for that race where the race name matches, else empty; `choice_id` = candidate id; `choice` = "first last" as published (blank parts dropped); `party` = the tab file's PartyCode for that candidate where it joins, else empty; `vote_type = "TOTAL"`; `reporting_status` = "`<reporting>/<p record precincts>` precincts, status `<letter>`"; `election_date` = the tab ElectionDate; `contest_scope = "statewide"`.
  - `county_id` = the full unit id ("12001"): it is already the 5-digit county FIPS (my call).
  - **Checks, listed, nothing corrected:** V records whose race, unit or candidate id isn't in the info file; candidates whose race differs from the V record's race; duplicate (race, unit, candidate); non-integer votes or precincts; precincts reporting > the `p` count or a missing `p` record; status letters other than I/F (and the count of each); races with a `c` record but no votes; pipe-vs-tab vote differences where they join; races whose name doesn't appear in the tab file (counted, listed once per race); candidates with more than one party across counties; malformed records (no brackets, wrong field count).
  - Unreadable or missing files: listed; checks needing them are `None`. Without the info file no row can be named: no rows.
- **CLI** `fetch | parse SOURCE_ID PASS_RECORD | fetch-parse`, output CSV.
- **Tests:** fixtures cut from the real files (US Senate, two US House districts, Governor, one amendment, one retention question; three counties), plus a test that the cross-certificate file's SHA-256 equals the fingerprint above and a unit test of the `cafile` context (partial chain off, extra certificate loaded). Synthetic variants for each listed anomaly.

## Left to the builder

Fixture counties, summary key names, test layout.

## Not done / later

- Statewide rows (none in the files; the race pages have them).
- Precinct results (county Supervisor of Elections sites).
- Why every record is status I, and the 91 zero-reporting records.
- The cross-certificate expires 2037-12-31; R1 may join the Mozilla store before then, which would make it unnecessary.
