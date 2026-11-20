# Scenario model design (scenarios/)

Status: **approved by Steve 2026-11-20** ("go with recommendations": official state totals, TOML matchups file, positive swing = toward the Democrat). Full spec: `docs/queued/scenario-model-spec.md`.

## Intent

Game out hypothetical 2028 presidential matchups from Steve's fantasy-draft picks by applying hand-set swings to the 2024 result. **Scenario, not a forecast:** every input is an assumption Steve types in. Separate from the six-step results pipeline; nothing in `sources/` or `tools/` is imported or changed.

## Goals / non-goals / anti-goals

- Goals: reproduce 2024 exactly at zero settings; per-state winners, EV totals, tipping point, and the national swing needed to flip, for each matchup.
- Non-goals: county maps, turnout modeling, House or Senate.
- Anti-goals: any number about a candidate that Steve didn't set; polls, markets or "candidate strength"; silently clamping or estimating anything.

## Approaches considered

1. **Official state totals (chosen by Steve, 2026-11-20).** FEC official 2024 state results + ME/NE district totals from their Certificates of Ascertainment. Every input is official; no gaps. Exact for the spec's adjustments because they're linear: a uniform two-party margin shift applied per county sums to the same shift at state level, and third-party draws sum the same way. The one thing lost is detecting a county pushed past 0% or 100% by a huge swing.
2. County file (MIT county returns 2000–2024). Matches the spec's wording; needs Steve to download it through a Dataverse guestbook form; must pass an FEC check, with mismatching states listed as gaps. Kept as a later layer if county maps are wanted.
3. Precinct mapping for ME/NE. Rejected: more work, inherits MEDSL precinct errors.

## Data (committed, with provenance)

- `scenarios/data/baseline_2024_states.csv`: 51 rows (50 + DC): state, electoral_votes, R (Trump), D (Harris), other (all other candidates + write-ins), total, ev_awarded_R, ev_awarded_D. Built by `scenarios/build_baseline.py` from `data/raw/fec-2024/2024presgeresults.xlsx` (SHA-256 in `evidence/fetch-fec-2024presgeresults.csv`). The script has its own small xlsx reader; it does not import `tools/`.
- `scenarios/data/baseline_2024_districts.csv`: ME-1, ME-2, NE-1, NE-2, NE-3 with R, D, other, transcribed by hand from the certificates (hashes in `evidence/fetch-ascertainment-2024-me-ne.csv`). A test checks each state's district sums equal its FEC statewide totals.
- **Electoral units:** 49 winner-take-all states + DC; ME and NE each = an at-large unit worth 2 EVs (statewide vote) + one unit per district worth 1 EV. Total 538 is asserted.

## Swing arithmetic (all inputs in percentage points; default 0)

For each unit, with 2024 votes R, D, other, total T:

1. **Two-party margin swing.** m = (D − R)/(D + R). Shift s = `national_swing` + `regional_swing` for that state (or its region). New two-party votes: D′ = (D + R)(1 + m + s/100)/2, R′ = (D + R) − D′. **Sign: positive s moves toward the Democrat.** (Claude's call; Steve can flip it.)
2. **Minor-party draw.** Each third-party candidate has `share` (percent of T) and `from_r` + `from_d` = 1. Votes taken = share/100 × T, removed from R′ and D′ in that split, and added to that candidate. 2024 "other" votes stay as they are.
3. **No clamping.** If any unit's R or D would go below 0, the run stops and names the unit and inputs.
4. Winner = most votes in the unit (plurality). An exact tie is reported as a tie, not broken.
5. Regional swing for a district unit uses its state's value.

## Outputs (`scenarios/out/<matchup>.md` and `.csv`)

Every output starts with: **"Scenario, not a forecast: inputs are hand-set assumptions."**

- Per-unit table: projected R/D/third-party votes and shares, margin, winner, EVs.
- EV totals, and a flag for 269–269 (reported as "no majority; House decides"; not resolved).
- **Tipping point:** sort units by the winner's margin, largest first; the unit whose EVs carry the winner to 270.
- **Sensitivity:** EV totals at national swings from −10 to +10 in 0.5-point steps with all other inputs held, plus the exact national swing at which the winner changes (found by computing where each unit's margin crosses zero; no iteration).

## Matchups file

Spec says `scenarios/matchups.yaml`. PyYAML isn't installed, and Homebrew's Python needs a virtual environment to add it. **Decided (Steve, 2026-11-20): `scenarios/matchups.toml`**, read with Python's built-in `tomllib`; no dependencies. (Rejected: YAML via a `.venv` with PyYAML.) Contents either way: one entry per matchup with the R/D nominees (from the draft), national_swing, optional regional_swing per state, and third-party candidates with share/from_r/from_d, all 0 by default.

## Tests (stdlib `unittest`, run first, in this order)

1. Zero settings reproduce every 2024 unit winner, 312–226, and the FEC's per-state EV awards.
2. EVs total 538 in every run.
3. ME and NE district sums equal their FEC statewide totals.
4. Swing arithmetic: hand-worked cases (margin shift moves the state margin by exactly s; third-party draw splits correctly; negative-vote input stops the run).

## Build order (small commits)

1. Baseline builder + data files + tests 1–3.
2. Swing engine + test 4.
3. Matchups file (all zeros, draft names).
4. Outputs: tables, tipping point, sensitivity.

## Left to the builder

File layout inside `scenarios/`, output formatting, CLI flags.
