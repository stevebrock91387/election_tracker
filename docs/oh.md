# Ohio: live XML feed, county level

Seen 2026-11-24 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_oh.py`) on 2026-11-24 at 23:18 UTC, then parsed with `pipeline/readers/oh.py`. Design: `docs/superpowers/specs/2026-11-24-step2-oh-reader-design.md`. **County level; every contest in the feed** (federal, statewide, state legislative, appellate judicial, statewide issues). Certified precinct results are a separate, later reader.

## Where the data is

One request per pass:

| Kind | URL | What it is |
|---|---|---|
| `xml` | `https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob` | NIST SP 1500-100 / IEEE 1622.2 V1 `ElectionReport`. The server builds the body on each request (`Last-Modified` = request time). |

The URL path ends in `download`, so `run_oh` passes `ext="xml"` to `fetch` and the file is saved as `.xml`. The URL has no election in it; which election the feed carries is read from the file (`Election` name and date). The state's documentation is at `https://liveresults.ohiosos.gov/Content/PDF/P1622Documentation.pdf` (not read).

## Parsed (2026-11-24, pass started 23:18 UTC)

| File | Bytes | SHA-256 (first 12) | Notes |
|---|---|---|---|
| XML | 1,234,749 | `8ef7b9e193f3` | `GeneratedDate` 2026-11-13T09:43:04Z, `Status` UnofficialComplete; byte-identical to the recon copy downloaded earlier the same day |

- **Output:** 3,700 rows: 340 state rows (one per selection, for the contest's own unit: the State unit or a district) and 3,360 county rows. 88 turnout rows.
- **Coverage:** 162 contests, 340 selections, 88 counties. State rows by contest type: State Representative 208, Representative to Congress 41, State Senator 35, Judge of the Court of Appeals 28, U.S. Senator 7, Governor and Lieutenant Governor 6, Justice of the Supreme Court 4, Secretary of State 3, Attorney General 2, Auditor of State 2, Treasurer of State 2, Statewide Issues 2.
- **Clean checks:** none of the following occur: county counts not summing to the own-unit count (all 340 selections sum exactly), missing or repeated own-unit counts, unknown GpUnits, counts outside the contest's own unit and counties, non-integer counts, unknown candidates or parties, ballot-measure ids without `_YES`/`_NO`, duplicate counts, count types other than Total, unexpected namespace.
- **Listed, expected:**
  - `absentee_exceeds_total`: 88 (every county; see quirks).
  - `unreferenced_county_units`: 88.
  - `same_named_contests`: 8 names, e.g. "Justice of the Supreme Court" (two contests) and "Judge of the Court of Appeals - District 08" (five). Their ids differ; join on ids.
  - `write_ins`: 17 selections.
- **Turnout, statewide sums of the county rows:** registered 8,018,054; ballots cast 4,658,250; provisional outstanding 98,369; UOCAVA absentee outstanding 3,779; precincts 8,834 of 8,834.
- **Example, US Senate:** Brown (DEM) 2,301,042; Husted (REP) 2,077,748; Redpath (LIB) 128,272; Levy (Other-part) 94,509; three write-ins 291, 36, 27. Unofficial canvass figures from the feed, not certified.

## Quirks

- **District totals are level "state"**, as in the ResultsAjax and NC readers (Steve, 2026-11-24). The contest identifies the district; county rows of a district contest are that county's part of the district.
- **Two County units per county:** "Adams" carries the results, precinct counts and turnout; "Adams County" carries only a name and no count refers to it.
- **`Absentee BallotsCast` exceeds total ballots in every county** (Adams 62,074 vs 9,169; statewide 29,688,375). Its meaning is unknown; the turnout table keeps it as `absentee_ballots_cast_as_published` and doesn't use it as turnout. `Absentee BallotsOutstanding` matches the canvass spreadsheet's "Outstanding UOCAVA Absentees" (recon).
- **Ballot measures have no choice text:** "Yes"/"No" come from the selection ids' `_YES`/`_NO` prefixes. `vote_for` is empty for them (no `VotesAllowed`).
- **Tickets:** Governor/Lieutenant Governor selections name two candidates, joined with " and "; `party` is the first candidate's.
- **Party** is the abbreviation as published. The feed's party list has `DEM`, `REP`, `LIB`, `Indep`, `Nonprtycan`, `Other-part`, `Write-in`, `Non-partis` and `None` ("Blank (General Election Only)"); `None` appears on no 2026 row.
- **No vote types** (every count is Total) and **no county FIPS codes**; `county_id` is the GpUnit ObjectId.

## Not done

- Certified precinct results (separate reader; the files on publicfiles.ohiosos.gov return 403 to scripts, so they'd be downloaded by hand after certification).
- Vote types, county FIPS mapping, the documentation PDF, the meaning of absentee `BallotsCast`.
- Whether the feed's numbers move on election night: only this post-election snapshot has been seen (`GeneratedDate` 2026-11-13).
