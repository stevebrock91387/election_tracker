# Step 4: expected vote — design

Status: drafted 2026-11-27 for Steve's approval; builder check done, Steve chose the check bar (C).

## Intent

For each county, before results arrive, an expected total vote with a low–high range. On election night it is the denominator behind "how much of the vote is in" (step 5 projects the vote still out from it; step 6 calls races on it). That is how a decision desk knows what's still out.

The first use is the dry run: compute the 2026 expectation from past elections only, then score it against the certified 2026 results that step 2 has already loaded. The real use is 2028.

## Decisions (Steve, 2026-11-27)

- **Baseline from the last comparable elections** (option A): midterms for a midterm, presidential years for a presidential year. For the 2026 dry run that's 2018 and 2022; for 2028 it's 2020 and 2024.
- **Data source** (option B): MIT MEDSL precinct returns summed to counties, each state checked against the FEC's official federal-elections compilation for that year. (Replacing MEDSL with official county files state by state was offered; not chosen now.)
- **Check bar** (option C): exact match with the FEC, and differences are investigated and fixed before the dry run is scored. A state-office that still doesn't match exactly isn't used.
- **Design as played back and approved ("Go ahead"):**
  - Quantity: a county's votes in its top race (the race with the most votes there), a turnout proxy, since MEDSL has no ballots-cast counts.
  - Point: the latest comparable election's turnout rate (top-race votes ÷ registered voters) × current registered voters.
  - Range: each of the two comparable elections' rates × current registration; low and high are the smaller and larger, and the point is the latest one.
  - Registration missing for any needed year: no adjustment. The point is the latest raw vote and the range is the two raw votes. It's marked, never filled in.
  - Output: one table per county (point, low, high, method and reason), read by steps 5 and 6.

## Goals

1. County baselines for 2018 and 2022 from MEDSL, with every row tagged with the year, top office, MEDSL commit, and whether its state passed the FEC check.
2. An expected-vote table for the 2026 general per county.
3. A dry-run score: for each county with a 2026 actual, whether the actual top-race vote fell inside the range, by how much it missed, and the share of counties hit, per state and nationally.
4. Everything deterministic and reproducible from pinned inputs; no estimation beyond the stated formula.

## Non-goals

- Presidential years (2020 and 2024 baselines for 2028): US PRESIDENT in the office list and an FEC presidential check are a follow-up before 2028 (my call). This build is midterms, for the 2026 dry run.

- Race-specific drop-off (e.g. a down-ballot race's share of the top race). The expected vote is for the top race; per-race use is step 5's concern.
- Vote-type splits (mail / early / election day). Step 5 is where vote type matters.
- House-district expected vote. Districts that split counties need precinct work and redistricting maps; later.
- Collecting official county registration for all states. This build uses only registration already in the project; collecting the rest is a separate follow-up (see "Registration" below).
- Official county results replacing MEDSL (Steve chose not to now).

## Anti-goals

- A number that looks official but isn't: every value carries its source and check status.
- Silent fills: no imputed registration, no interpolated turnout, no clamping.
- Tuning the range until the dry run looks good. The formula is fixed before scoring; the score is reported as it comes out.

## Inputs

| Input | Use | State |
|---|---|---|
| MEDSL 2022 precinct (`data/raw/medsl-2022-precinct`, commit `a8126c5790b8`) | 2022 county top-race votes | downloaded 2026-11-20 |
| MEDSL 2018 precinct, Harvard Dataverse (CC0, public files): U.S. Senate `doi:10.7910/DVN/DGNAFS`, U.S. House `doi:10.7910/DVN/IVIXLK`, State `doi:10.7910/DVN/ZFXEJU` (governor) | 2018 county top-race votes | to download (the GitHub repo is deprecated per its README); pinned by dataset version and file SHA-256 (my call) |
| FEC Federal Elections 2018 and 2022 (`fec.gov/introduction-campaign-finance/election-results-and-voting-information/federal-elections-2018/`, `-2022/`) | official state totals for the check | to download; the file format (xlsx/pdf) is to be confirmed |
| Registered voters, 2026 | current registration | readers' `-turnout.csv` tables (about half the states; at precinct or county level) |
| Registered voters, 2018 and 2022 | turnout rates | not in the project; see "Registration" |
| 2026 actuals | dry-run scoring | `data/results.sqlite` (step 3), county rows or precinct rows summed |

## How it's built

### 1. County baselines (`pipeline/expected/baseline.py`)

- **Reading.** Sum MEDSL precincts to counties with the same rules as `tools/medsl_county.py`: TOTAL preferred within a precinct-candidate, `*` not counted (and counted per county), tally rows dropped, no corrections. The tool is reused by import where the columns allow. If the 2018 Dataverse files' columns differ, the same rules are rewritten with a column mapping in the new module. `tools/` stays untouched.
- **Offices considered for the top race:** US SENATE, GOVERNOR, and US HOUSE. House is summed across every district in the county. Per county, the top race is the one with the most votes; ties go in that order.
- **FEC check, per state, year and office** (per office is my call: a bad House file shouldn't sink a state's clean Senate rows). MEDSL's statewide US SENATE and US HOUSE candidate totals are compared with the FEC's.
  - An office passes when every candidate matches exactly.
  - How candidates are joined to the FEC's (names, party lines, write-ins) is written down, and anything that can't be joined is listed.
  - Counties use only offices that passed.
  - A county whose top race is GOVERNOR is used only if both federal offices in its state passed (the governor rows come from the same per-state MEDSL file but aren't checked directly; tagged `checked_via = "federal rows"`).
- **Fixing differences (Steve's option C).** Each failing state-office is investigated before the dry run is scored. A fix goes in `pipeline/expected/medsl_fixes.toml`, one entry each, applied visibly, never silently:
  - state, year, office;
  - what it changes (e.g. drop a row MEDSL stored as a county total under a precinct name);
  - the evidence (the official figure it restores and where it's published);
  - the before and after differences.
  A fix must make the office match the FEC exactly. Otherwise the office stays failed, with its differences listed. No fix is made to reach a match without an identified cause.
- **Two Senate contests in one year** (MN and MS 2018, OK 2022), runoffs (the stage filter keeps the general only), and similar cases are the builder's to settle and write down.
- **Unopposed races.** Uncontested House races with no votes counted (e.g. Florida) simply lose the top-race contest to Senate or Governor. A county where every candidate office was uncontested has no baseline, and that's listed.
- **Output.** `data/expected/baseline-<year>.csv` with:
  - state, county_fips, county_name, year, top_office, votes, suppressed_rows;
  - check (passed / failed / not checked), checked_via;
  - medsl_commit, fec_file_sha256.

### 2. Registration (`pipeline/expected/registration.py`)

- **2026:** registered voters from the readers' turnout tables, summed to county where they're precinct-level and the reader's doc says the units add up. Sources with no turnout table, or units that can't be joined to counties, give no registration.
- **2018 and 2022:** none in the project. This build ships with them missing, so every county is unadjusted (point = 2022 votes, range = the 2018 and 2022 votes) until registration is collected.
- **Collection (follow-up, its own design).** Official county registration by state and year, one small reader per state report. Steve picks the states and order.
- **Output.** `data/expected/registration.csv`: state, county_fips, county_name, year, registered, source_id, source_sha256.

### 3. Expected vote (`pipeline/expected/compute.py`)

For each county and a target election (target year plus the two comparable years):
- **With registration for all three years:**
  - rate_y = votes_y ÷ registered_y for each comparable year;
  - point = rate_latest × registered_target;
  - low and high = min and max of rate_y × registered_target over both years;
  - method "rate × registration".
- **Otherwise:** point = votes_latest, low and high = min and max of the two years' votes, method "raw". The reason names the missing years.
- **One comparable year missing** (e.g. the state failed the check that year): point and low = high = that year's value, method "one year". A wider range would need a rule; this design doesn't invent one.
- **Both missing:** no row; the county is listed with the reason.
- **Output.** `data/expected/expected-<target>.csv`: state, county_fips, county_name, target, point, low, high, method, reason, years used, input file hashes.

### 4. Dry-run score (`pipeline/expected/score.py`)

- **Actuals.** Each county's 2026 top-race votes from the step-3 database: the same office rule, from county rows or precinct rows summed.
- **Joining counties.** Join on county FIPS where a reader carries it (TX, AR, ND, FL); otherwise on normalized county name within the state. Unmatched counties are listed, never guessed. New England towns (CT, VT, MA) and Alaska districts don't match MEDSL counties; they're listed as not scored.
- **Per county:** actual, point, low, high, inside (yes/no), miss = actual − nearest bound (0 if inside), and miss % of point.
- **Summary per state and overall:** counties scored, share inside, median and 90th-percentile absolute miss %, and the not-scored list with reasons.
- **Output.** `data/expected/score-2026.csv` and a text summary.

CLI: `python3 -m pipeline.expected.run baseline YEAR | registration | compute TARGET | score TARGET`. Stdlib only; tests in `pipeline/tests/`.

## What's left to the builder

- FEC file layout and parsing: confirm the file before writing the check, and note it in the doc.
- Normalizing county names for the join: suffixes like "County" and "Parish", "St." vs "Saint", case. Every rule written down; ambiguous matches are listed, not resolved.
- Which turnout tables can be summed to counties (each reader's doc says what its units are).
- Doc: `docs/expected.md`, with the 2026 dry-run results and what's unverified.

## Known limits (stated, not solved)

- Midterm-to-midterm swings in turnout (2018 was unusually high) make a two-year range narrow or skewed; the score will show how often that matters.
- Counties change rarely, but any FIPS changes between 2018 and 2026 (e.g. Connecticut's planning regions replacing counties in 2022) break the join and are listed.
- Without registration, the 2026 expectation ignores population and registration change entirely.
