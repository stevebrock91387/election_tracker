# Step 2: Clarity reader (CO, IA, SC, WV), county level — design

Status: draft, awaiting Steve's approval. Short design (the reader reuses the Enhanced Voting reader's fetch, schema and CLI pattern).

## Intent

Read the 2026 general-election results of the four states on Clarity (Scytl) from their official statewide sites into the common output, so steps 3–4 can use them. Steve chose **county level now; precincts later** (2026-11-20). Precinct results live on each county's own Clarity site (264 sites across the four states) and are a separate, later task.

## What the states publish (seen 2026-11-20, browser + one recon download each)

Every Clarity election has `<base>/current_ver.txt` (the current version number); files live under `<base>/<version>/`. Bases:

| State | Base | Statewide detail XML | Notes |
|---|---|---|---|
| CO | `https://results.enr.clarityelections.com/CO/127407` | yes (62 KB zip, 302 contests) | one vote type, "Total Votes" |
| SC | `https://www.enr-scvotes.org/SC/127300` | yes (78 KB zip, 171 contests) | Election Day, Early Voting, Absentee By Mail, Failsafe, Failsafe Provisional, Provisional (33 lines spelled "Provionsal") |
| WV | `https://results.enr.clarityelections.com/WV/127496` | yes (17 KB zip, 126 contests) | one vote type, labelled "Election Day" |
| IA | `https://electionresults.iowa.gov/IA/127077` | **no** (404) | JSON: `json/sum.json` (contest key `K`, choice names `CH`, choice ids `CHAggId`, party `P`, statewide votes `V`) and `json/ALL.json` (per county `A`: contest keys `C`, votes `V` in the same choice order, totals `T`; one extra area named `-1`). A fixed-width `reports/detailtxt.zip` has vote types but no ids. |

The XML (`detail.xml` inside `reports/detailxml.zip`): `ElectionResult` → `Timestamp`, `ElectionName`, `ElectionDate`, `Region`, `ElectionVoterTurnout` (per county: `totalVoters` (registered), `ballotsCast`, precincts participating/reported) and `Contest` (`key`, `text`, `voteFor`, `isQuestion`; children `ParticipatingCounties` with per-county precincts participating/reported, and `Choice` (`key`, `text`, `party`, `totalVotes`) → `VoteType` (`name`, `votes`) → `County` (`name`, `votes`)). On all three files, vote types sum to each choice total and counties sum to each vote type (1,431 choices, 0 differences).

## Approaches

1. **XML for CO/SC/WV, JSON for IA** (chosen). IDs everywhere, vote types and registered voters where the state publishes them. Iowa has no vote-type split this way.
2. XML for CO/SC/WV, Iowa's fixed-width TXT. Gets Iowa's Election Day / Absentee split, but the TXT has no ids (names aren't keys) and fixed-width layouts break silently.
3. JSON for all four. One parser, but drops South Carolina's five-way vote-type split and the XML's registered-voter figures.

Iowa's vote-type split can be added later from the TXT, matched to JSON by column position, if step 5 needs it.

## Design

- **Sources** (`pipeline/sources.toml`): one entry per state with `platform = "clarity"`, `base`, `format = "xml"` or `"json"`, `min_interval_s = 120`. The existing EV entries are unchanged.
- **Fetch** (`pipeline/fetch.py`, unchanged): one pass reads `current_ver.txt` (source id `<id>-ver`), then the data file(s) built from that one version: `reports/detailxml.zip` (XML states) or `json/sum.json` + `json/ALL.json` (IA, source ids `<id>-sum`, `<id>-all`). Each source id keeps its own 120 s minimum, so a pass is 2 requests (3 for IA). Raw bodies and manifest rows are saved before parsing, as now. The version is recorded in the summary.
- **Reader** `pipeline/readers/clarity.py`:
  - `parse_xml(zip_path, state, source_id) -> (rows, summary, turnout)` reads `detail.xml` from the zip with `zipfile` (no extraction to disk).
  - `parse_json(sum_path, all_path, state, source_id) -> (rows, summary)`.
- **Rows** (common columns, no schema change): `contest_id` = contest key, `choice_id` = choice key (XML) / `CHAggId` (JSON), `contest_scope = "statewide"` (these are statewide files), `county_id` empty (Clarity gives names only), precinct columns empty.
  - State level: `TOTAL` = the choice's published total; XML also one row per vote type as published.
  - County level: **vote types exactly as published** (CO "Total Votes", WV "Election Day", SC's five). No county `TOTAL` row is made up by summing, since none is published. Iowa's county values are totals and get `TOTAL`.
  - `reporting_status` for XML county rows: `"<reported>/<participating> precincts"` from that contest's `ParticipatingCounties`. Empty elsewhere.
- **Turnout** (XML only): a second CSV per parse with state, source_id, source_sha256, county_name, registered_voters, ballots_cast, precincts_participating, precincts_reported. Registered voters feed step 3's "votes never exceed registered voters" check.
- **Reported, not fixed** (summary, like the EV reader): vote types ≠ choice total; counties ≠ vote type (XML) or ≠ statewide (IA, by contest key and choice position); IA areas not matching a county (`-1`) listed and not emitted as county rows; unknown child elements of `Contest`/`Choice` listed and not parsed; IA contests or choice arrays whose lengths disagree, listed and skipped.
- **CLI** `python3 -m pipeline.run_clarity fetch|parse|fetch-parse SOURCE_ID`, writing `data/parsed/<source_id>/<timestamp>.csv` (+ `-turnout.csv`).
- **Tests**: fixtures cut from the real files (a few contests and counties each, with the source hash recorded), committed; exact values from the files; the checks; fetch order (version first, data URL built from it) with an injected opener. Integration test on the full saved files when present.

## Non-goals

Precinct results and the 264 county sites; mapping county names to FIPS; Iowa vote types; ranked-choice parsing (none seen); any correction of source data.

## Calls I made (check these)

- One shared module for XML and JSON, since they share the version step and the output rules.
- County rows keep published vote types only; no summed county `TOTAL`.
- `reporting_status` text format for Clarity county rows.
- Turnout as a separate CSV rather than new columns.
