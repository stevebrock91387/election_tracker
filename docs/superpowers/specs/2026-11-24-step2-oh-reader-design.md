# Step 2: Ohio reader (live XML feed, county level)

Status: **ready for Steve's approval** (builder check done; its one open question answered 2026-11-24). Approach A chosen by Steve 2026-11-24 ("A"): the live XML feed now at county level; a precinct reader for the certified spreadsheets later, as a separate piece.

## Why

Ohio has a 2028 Senate race (Class 3) and 15 House seats. The live results site is what Ohio updates on election night. A script can download its XML, and the XML carries candidate ids and county-by-district parts for every congressional district.

## What recon found (2026-11-24, built-in browser + single downloads to the scratchpad)

- **Feed:** `https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob`. It answers 200 to a script with our User-Agent; the site sits behind Cloudflare. NIST SP 1500-100 / IEEE 1622.2 V1 `ElectionReport`, namespace `http://grouper.ieee.org/groups/1622/groups/2/V1/1622_2-election_results_reporting.xsd`. 1,234,749 bytes, SHA-256 `8ef7b9e193f3…`. The documentation PDF is at `https://liveresults.ohiosos.gov/Content/PDF/P1622Documentation.pdf` (not read).
- **Freshness:** `Last-Modified` equals the request time; the body is built on each request. The root says `GeneratedDate="2026-11-13T09:43:04Z"`, `Status="UnofficialComplete"`, `Format="SummaryContest"`, `VendorApplicationId="Ohio-ENR 1.0.02"`. The two downloads 3 hours apart gave the same content.
- **Election:** `Date="2026-11-03"`, `Type="General"`, name "November 3, 2026 General Unofficial Canvass".
- **GpUnits (all `ReportingUnit`; the kind is the `Type` attribute):**
  - 88 counties with results and turnout: named "Adams" etc., with `SubUnitsReported`/`TotalSubUnits` (precincts), `VotersRegistered`, `VotersParticipated`, codes `StateLevel` and `LocalLevel` (region), `SummaryCounts` and `CountStatus`.
  - 88 more `County` units named "Adams County" etc. with no attributes beyond the name. No vote count refers to them.
  - 1 `State` ("Statewide"), 15 `Congressional`, 17 `StateSenate`, 99 `StateHouse`, 12 `Judicial`.
  - No FIPS codes on counties (only the state's code `39` at the root).
- **Contests:** 162: 161 `CandidateContest`, 1 `BallotMeasureContest` (State Issue 3). Every `VoteCounts` is `Type="Total"`: no vote types. A contest's selections each carry one count for the contest's own district unit (the `State` unit or the district) and one per county in that district. For a district that splits a county, the county count covers only the part inside the district. **All 340 selections: county counts sum exactly to the district count.**
  - US Senator: 7 selections × (1 + 88). US House districts 1–15: 2–5 selections, 2–17 counties each.
  - `JurisdictionalScopeId` on each contest names its district unit; `OfficeId` points to an `Office` with a `Term` (start or end date).
- **Duplicate contest names:** "Justice of the Supreme Court" twice (terms starting 2027-01-01 and 2027-01-02) and several "Judge of the Court of Appeals – District nn" pairs. Their `ObjectId`s differ.
- **Selections:** `CandidateSelection` with one `CandidateId`, or two for Governor/Lieutenant Governor tickets. Candidate → `BallotName` and `PartyId`. 17 selections are write-ins (`IsWriteIn="true"`; party "Write-in", "Not Applicable - WI"). Parties have an `Abbreviation` (`DEM`, `REP`, `LIB`, `Indep`, `Nonprtycan`, `Other-part`, `Write-in`, `Non-partis`, and "None" for "Blank (General Election Only)").
- **Ballot measure selections have no text**: only ObjectIds `_YES…` and `_NO…`.
- **County turnout (`SummaryCounts`):**
  - `Total BallotsCast` equals `VotersParticipated` (Adams 9,169).
  - `Provisional BallotsOutstanding` matches the canvass spreadsheet's "Outstanding Provisionals"; statewide 98,369.
  - `Absentee BallotsOutstanding` matches the spreadsheet's "Outstanding UOCAVA Absentees" (military and overseas only); statewide 3,779.
  - **`Absentee BallotsCast` is larger than the county's total ballots in all 88 counties** (Adams 62,074 vs 9,169; statewide 29.7 million). Its meaning is unknown.
- **The canvass spreadsheet** (`…?filename=GeneralElectionXlsFile`, 260,932 bytes, also script-fetchable) has the same numbers in a wide layout (one column per candidate, names with party suffix). Its internal timestamps are 2026-11-13 too, so it comes from the same snapshot of the same system and is **not an independent check.**
- **Certified precinct spreadsheets** (data.ohiosos.gov → `publicfiles.ohiosos.gov/election-results/…`): 403 to scripts, and the 2026 general isn't posted yet. Out of scope here.

## Approaches considered

1. **Live XML now, county level (chosen).** One request per pass, candidate ids, district-by-county parts, county turnout; no precincts, no vote types.
2. Certified precinct spreadsheets, downloaded by hand: precinct level, but post-certification only and no election-night path. Later, as a separate reader.
3. XML plus the canvass spreadsheet as a cross-check: rejected for now because the spreadsheet is the same snapshot from the same system, so agreement would prove little; it would double the requests and add an XLSX parser.

## Scope

All 162 contests in the feed (federal, statewide, state legislative, appellate judicial, statewide issues). This is everything the feed carries; there are no county or local contests in it. County level plus the district/state totals.

## Design

- **Config** `pipeline/sources_oh.toml`: section `[oh-2026-general]` with `state = "OH"`, `xml_url`, `min_interval_s = 120`.
- **Fetch pass** (`pipeline/run_oh.py fetch SOURCE_ID`): one request through `pipeline/fetch.py` (source id `<id>-xml`). The pass record lists the file (kind `xml`) as in the other readers. `fetch.py` names the saved file from the URL path, which here ends in `download`; the builder makes sure the saved file name is sensible and stable.
- **Reader** `pipeline/readers/oh.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary)`:
  - **Rows:** `vote_type = "TOTAL"`. One row per (selection, GpUnit count):
    - The count for the contest's own unit (the `State` unit, or a Congressional, StateSenate, StateHouse or Judicial district): `level = "state"`, as the ResultsAjax and NC readers label district totals (Steve, 2026-11-24: "State"). `county_id` and `county_name` are empty; the district is identified by the contest. The shared schema is unchanged.
    - Each county count: `level = "county"`, `county_id` = the county GpUnit ObjectId, `county_name` as published ("Adams"). For a district contest this is the county's part of that district.
  - `contest_id` = Contest ObjectId; `contest_name` = Name; `contest_type` = the `ContestType` code value (e.g. "U.S. Senator", "Statewide Issues"); `vote_for` = `VotesAllowed`; `contest_scope = "statewide"` (every contest is in the state-level feed, as in the other readers).
  - `choice_id` = BallotSelection ObjectId. `choice` = the candidates' BallotNames joined with " and " for tickets (the spreadsheet's form). For ballot-measure selections, "Yes" or "No" from the ObjectId prefix (`_YES`/`_NO`); a different prefix leaves `choice` empty and is listed.
  - `party` = the first candidate's Party `Abbreviation` as published ("None" kept). Write-in status isn't in the common schema; it is listed in the summary (count and ids).
  - `source_created_at` = the root `GeneratedDate`; `election_name`, `election_date` from `Election`; `reporting_status` on county rows "`<SubUnitsReported>/<TotalSubUnits>` precincts", on state/district rows empty.
  - **County turnout file** (as the Clarity reader does; my call: `parse_pass` returns it as a third value, as Clarity's XML parse does): one row per county with registered voters, ballots cast, provisional outstanding, UOCAVA absentee outstanding, and the absentee ballots-cast value **as published under its own name**, not relabelled as turnout.
  - **Checks, listed, nothing corrected:**
    - county counts that don't sum to the contest's district/state count;
    - selections with no count for the contest's own unit, or more than one;
    - counts that point to an unknown GpUnit or to a GpUnit that is neither a county nor the contest's own unit;
    - non-integer counts (row kept, votes empty);
    - unknown candidate or party ids;
    - ballot-measure selections whose id has no `_YES`/`_NO` prefix;
    - duplicate (contest, selection, GpUnit) counts;
    - `VoteCounts` with a `Type` other than "Total";
    - counties whose `Absentee BallotsCast` exceeds their total ballots (expected: all 88 today);
    - county GpUnits referenced by no count (the 88 "… County" units today: one count, not 88 entries);
    - contests sharing a name (listed with their ids);
    - a root `Status` other than the one seen (`UnofficialComplete`) is not an anomaly; it's printed.
    - An unreadable or non-XML file is listed and the checks show "not checked".
- **CLI** `fetch | parse SOURCE_ID PASS_RECORD | fetch-parse`, output CSV as for the other readers.
- **Tests** on a fixture cut from the real file: US Senator, two House districts (one that splits counties), State Issue 3, the Governor ticket, and the two same-named Supreme Court contests, with their counties and the GpUnits, parties, candidates and offices they reference. Synthetic variants for each listed anomaly.

## Left to the builder

Fixture cutting, summary key names, test layout, the saved file's extension.

## Not done / later

- Certified precinct results (separate reader, downloads by hand, after certification).
- Vote types (not in the feed).
- County FIPS mapping.
- What `Absentee BallotsCast` means; reading the documentation PDF.
- Whether the feed's numbers move during election night (only a post-election snapshot has been seen).
