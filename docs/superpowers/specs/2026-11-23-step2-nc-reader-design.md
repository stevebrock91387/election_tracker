# Step 2: North Carolina reader (precinct ZIP + dashboard check)

Status: **approved by Steve 2026-11-23** ("Yes, ZIP + check", approach 1 as proposed in chat).

## Why

North Carolina is a 2028 battleground with a Senate race and 14 House seats. It publishes one official statewide file with every contest by precinct and by vote method, which is the precinct level the House work needs, and the same file for every election back to 2000.

## What recon found (2026-11-23, browser + single downloads)

- **Precinct ZIP:** `https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_11_03/results_pct_20261103.zip` (2,240,941 bytes, Last-Modified 2026-11-14 00:05:43 GMT), one member `results_pct_20261103.txt` (16,985,532 bytes), tab-separated, layout documented at `https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/layout_results_pct.txt`. Columns: County, Election Date, Precinct, Contest Group ID, Contest Type (S or C), Contest Name, Choice, Choice Party, Vote For, Election Day, Early Voting, Absentee by Mail, Provisional, Total Votes, Real Precinct (Y/N). 155,661 rows, 100 counties; the four methods always sum to Total; all counts numeric; 15,423 rows are administrative precincts (Real Precinct N: early-voting sites, absentee, transfers). One choice in contest group 1 is a NUL character. **No choice ids.** Local contests share contest group id 1.
- **Dashboard statewide file:** `https://er.ncsbe.gov/enr/20261103/data/results_0.txt` (JSON list, 677 rows, Last-Modified 2026-11-24 01:00:40 GMT): per (contest group `gid`, choice name `bnm`): party `pty`, `vct` total, `evc` Election Day, `ovc` early voting, `avc` absentee by mail, `pvc` provisional (mapping inferred by matching sums to the ZIP's columns, not documented), precincts `prt`/`ptl`, office group `ogl` (FED, COS, JUD, NCS, NCH, CCL, ""). `county.txt` gives the update time ("imp"/"sub": November 23, 2026 7:35/7:36 pm). The state says the dashboard updates every 5–10 minutes on election night.
- **The two disagree today:** 85 of the dashboard's 677 rows differ from the ZIP's precinct sums, in both directions (US Senate: Cooper 2,480,648 vs 2,480,640; Whatley 1,648,865 vs 1,648,870). Every dashboard row's (contest, choice) exists in the ZIP. Cause not known.
- Not verified: whether the ZIP is refreshed during election night.

## Approaches considered

1. **Precinct ZIP as the data, dashboard statewide file as an independent check (chosen).** Two requests; precinct level and vote methods.
2. Dashboard per-county files: live, county level only, 101 requests a pass.
3. Both: later, if the ZIP lags on election night.

## Scope

Contest Type S (statewide and district contests, including US Senate, US House, NC Senate/House, judicial, referenda), precinct level. Contest Type C (county contests) not now.

## Design

- **Config** `pipeline/sources_nc.toml`: `zip_url`, `member`, `dashboard_url`, `min_interval_s = 120`, `request_gap_s = 10`, `state = "NC"`.
- **Fetch pass** (`pipeline/run_nc.py fetch SOURCE_ID`): ZIP (`<id>-zip`), then dashboard (`<id>-dashboard`), 10 s apart, through `pipeline/fetch.py`; any failure stops the pass; a pass record lists both paths.
- **Reader** `pipeline/readers/nc.py`, `parse_pass(record_path, base_dir=".") -> (rows, summary)`:
  - Precinct rows from the ZIP (type S only): `level = "precinct"`, `county_name` as published (no county id), `precinct_id` = Precinct, `precinct_is_virtual` = "Y" when Real Precinct is N else "N", `contest_id` = Contest Group ID, `contest_scope = "statewide"`, `contest_name`, `vote_for`, `choice` as published, `choice_id` empty, `party` = Choice Party, `election_date` from the file (as published). One row per method (vote_type the layout's column names: "Election Day", "Early Voting", "Absentee by Mail", "Provisional") plus `TOTAL`.
  - State rows from the dashboard: same five vote types (mapped evc/ovc/avc/pvc as above), `reporting_status` "`<prt>/<ptl> precincts`", `contest_name` from `cnm`, `source_created_at` empty (results_0 carries no update time).
  - Check: precinct sums per (contest group, choice, vote type) vs the dashboard's state rows, listed `(contest, choice, vote_type, dashboard, zip_sum)`; dashboard rows with no ZIP match and type-S ZIP contests the dashboard doesn't carry, listed.
  - Also listed: rows whose methods don't sum to Total, non-integer counts (row kept, votes ""), rows with the wrong field count, an unexpected header, choice names with control characters (e.g. NUL), duplicate (county, precinct, contest, choice) keys, a ZIP without the expected member, an unreadable dashboard file.
- **CLI** `fetch | parse SOURCE_ID PASS_RECORD | fetch-parse`, output CSV as for the other readers.
- **Tests** on fixtures cut from the real files (the ZIP cut to US Senate and one House district across a few counties, recompressed with the same member name; dashboard cut to those contests with its real values, so the real Senate mismatch is a test; a synthetic variant whose dashboard values equal the ZIP sums tests the clean case), plus synthetic variants for each listed anomaly.

## Left to the builder

Fixture cutting, summary key names, test layout.

## Not done / later

County contests (type C); historical ZIPs (2000–2024; same layout since July 2018, older layouts differ per the layout file); dashboard per-county files; county FIPS mapping; why the ZIP and dashboard differ.
