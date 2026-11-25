# Step 2: New Jersey Clarity counties (design)

Date: 2026-11-25. Steve: "Go for it" (survey and build HI, WY, MS, MA, IL, NJ where workable, 2026-11-24),
under the standing approval for the remaining state readers (2026-11-24).

## Intent

New Jersey has no statewide results feed: the Division of Elections links each county's own site
(`https://nj.gov/state/elections/election-night-results.shtml`). 15 of the 21 counties use Clarity
(Scytl), which the project already reads at state level (CO, SC, WV). Read those 15 counties'
election-night files at precinct level with vote types, live as counts come in. The other six
(Bergen, Camden, Hunterdon, Salem, Sussex, Warren) run their own sites: a separate job.

## Source (seen 2026-11-24/25, script download works with the project fetcher; Clarity's CDN
refuses curl's default client)

- Per county: `https://results.enr.clarityelections.com/NJ/<County>/<election id>/`, as linked from
  the state page (13 counties) or from the county's Clarity election list (Passaic 127401, Somerset
  127569). A pass reads `current_ver.txt`, then `<version>/reports/detailxml.zip` (one `detail.xml`).
- County XML differs from the statewide files the Clarity reader handles: under each `VoteType` the
  units are `<Precinct name=… votes=…>` (not `<County>`); `Region` names the county;
  `VoterTurnout/Precincts/Precinct` gives per precinct totalVoters, ballotsCast and percentReporting;
  a contest carries contest-level `VoteType` elements (Atlantic: `regVotersCounty`, all 0) besides
  its `Choice` elements; vote types Election Day, Early Voting, Vote by Mail, Provisional.
- Contest names are each county's own (`House of Representatives 2nd Cong`, `United States
  Senate`), with keys (`0004`) local to the file. No ids shared across counties.
- 2026 Atlantic: 65 contests (federal, county, municipal, school boards), 145 precincts, timestamp
  11/19/2026.
- No statewide official results yet (the Division's 2026 page has audits and candidate lists).

## Approaches

1. **Extend the Clarity reader with a county-XML parser (chosen).** `parse_county_xml` beside
   `parse_xml`; config entries with `format = "county_xml"` and `county`; the existing runner and
   fetch flow (current_ver.txt, detailxml.zip). Two requests per county per pass.
2. A New Jersey reader of its own. Rejected: same platform, same fetch, same file family.
3. Wait for certified results. Rejected: Steve wants results as they come in (Maryland,
   2026-11-24).

## Design

- **Config** (`sources_clarity.toml`): one entry per county, `clarity-NJ-<County>-2026-general`,
  `state = "NJ"`, `county = "<name as on the state page>"`, `base`, `format = "county_xml"`,
  `min_interval_s = 120`. Fetch as today.
- **Rows** (`parse_county_xml(zip_path, state, county, source_id)`):
  - precinct rows: `level` "precinct", `county_name` = the config county, `precinct_id` =
    `precinct_name` = the Precinct name, one row per (VoteType, Precinct) as published;
  - county rows: `level` "county", TOTAL (`totalVotes`) plus one row per VoteType;
  - `contest_scope` "local" (the contest key only identifies a contest within one county's file;
    schema meaning), `contest_id` the key, `contest_name` the text, `vote_for`, `contest_type`
    "question" when `isQuestion="true"`; `reporting_status` on county rows
    "<precinctsReported>/<precinctsReporting> precincts" from the contest, on precinct rows the
    turnout table's percentReporting code as published.
- **Turnout:** one row per precinct (registered voters, ballots cast, percentReporting) plus the
  county total line.
- **Summary lists** (nothing corrected; a check that couldn't run is `None`):
  vote types that don't sum to a choice's total; precincts that don't sum to their vote type;
  `contest_vote_types` (contest-level VoteType names, listed, not rows); `region_mismatch` (the
  file's Region isn't the config county); unknown elements; `precincts_not_in_turnout` and
  `turnout_precincts_without_results`; duplicate precincts within a vote type (later dropped).
- **Cross-county:** none in this step: contest names differ by county, and there is no state total
  to compare against yet. A name map (county contest → statewide contest) is a follow-up once
  official state results exist.

## Left to the builder / not done

- The six non-Clarity counties.
- Statewide aggregation and the contest name map.
- Fixture: Atlantic's real `detailxml.zip`, unmodified.
