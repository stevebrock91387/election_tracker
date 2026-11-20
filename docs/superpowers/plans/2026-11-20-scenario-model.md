# Scenario Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `scenarios/` package that applies hand-set swings to official 2024 results and reports per-unit winners, EV totals, the tipping point and swing sensitivity for each matchup.

**Architecture:** Electoral *units* (50 winner-take-all states + DC, ME/NE at-large, ME/NE districts) built from committed CSVs; a pure function applies a scenario to units; a report layer computes totals, tipping point and sensitivity and renders Markdown/CSV. A CLI reads `scenarios/matchups.toml`.

**Tech Stack:** Python 3.14 (`/opt/homebrew/bin/python3`), standard library only (`csv`, `tomllib`, `dataclasses`, `zipfile`, `xml.etree`), `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-20-scenario-model-design.md` (and `docs/queued/scenario-model-spec.md`).

## Global Constraints

- Every output begins with exactly: `Scenario, not a forecast: inputs are hand-set assumptions.`
- Nothing under `sources/` or `tools/` is imported or modified.
- No number about a candidate is set by code; all scenario parameters come from `matchups.toml` and default to 0.
- Positive swing moves toward the Democrat; swings are in percentage points.
- No clamping: a negative R or D vote count raises `ScenarioError` naming the unit.
- EV total must be 538 in every run.
- Run tests with: `/opt/homebrew/bin/python3 -m unittest discover -s scenarios/tests -t .`

## Review Focus

1. 269–269 tie → totals report `tie=True` and the Markdown says "No majority: House decides"; no winner named. (Task 4 test.)
2. Swing large enough to push a unit's R or D below zero → `ScenarioError` with the unit id. (Task 2 test.)
3. Third-party `from_r + from_d != 1` → `ScenarioError` at load. (Task 3 test.)
4. `regional_swing` key that isn't a known state code → `ScenarioError` at load. (Task 3 test.)
5. A third-party candidate with enough share to win a unit → that candidate is the unit's winner and gets its EVs. (Task 2 test.)

---

### Task 1: Baseline data, units, and the 2024 check

**Files:**
- Create: `scenarios/__init__.py` (empty), `scenarios/build_baseline.py`, `scenarios/units.py`
- Create: `scenarios/data/baseline_2024_states.csv` (generated), `scenarios/data/baseline_2024_districts.csv` (hand transcription)
- Test: `scenarios/tests/__init__.py`, `scenarios/tests/test_baseline.py`

**Interfaces:**
- Produces: `build_states_csv(xlsx_path: str, out_csv: str) -> int` (rows written); columns `state,electoral_votes,r,d,other,total,ev_awarded_r,ev_awarded_d`. `r` = FEC column TRUMP, `d` = HARRIS, `other` = TOTAL VOTES − r − d. Columns found by header name, not letter.
- Produces: `@dataclass(frozen=True) Unit(id: str, state: str, ev: int, r: int, d: int, other: int)`; `load_units(states_csv: str, districts_csv: str) -> list[Unit]`. ids: state code (e.g. `PA`), `ME-AL`/`NE-AL` (ev 2, statewide votes), `ME-1`, `ME-2`, `NE-1`, `NE-2`, `NE-3` (ev 1). Plain `ME`/`NE` units are not emitted.
- Produces: `DEFAULT_STATES_CSV`, `DEFAULT_DISTRICTS_CSV` path constants in `units.py`.

District CSV (`id,state,r,d,other,source`), values from the Certificates of Ascertainment; `other` = sum of minor-party lines shown per district (write-ins are not split by district):

| id | r | d | other |
|---|---|---|---|
| ME-1 | 165214 | 258863 | 9279 |
| ME-2 | 212763 | 176789 | 7886 |
| NE-1 | 177666 | 136153 | 4485 |
| NE-2 | 148905 | 163541 | 4244 |
| NE-3 | 238245 | 70301 | 3619 |

`source` = the archives.gov PDF URL.

- [ ] **Step 1: Write failing tests** in `test_baseline.py`:
  - `test_ev_total_538`: `sum(u.ev for u in load_units(...)) == 538`
  - `test_unit_count`: 48 states (all but ME, NE) + DC + 2 at-large + 5 districts = 56 units
  - `test_district_sums_match_state`: for ME and NE, sum of district r and d equals the states CSV r and d
  - `test_2024_winners_match_fec_awards`: for each state, EVs won by R and D across its units equal `ev_awarded_r`/`ev_awarded_d`; national totals `r == 312`, `d == 226`
- [ ] **Step 2:** Run tests; expect import errors.
- [ ] **Step 3:** Implement `build_states_csv` (own xlsx reader: shared strings + sheet1, header row → column letter map, keep rows whose STATE is two letters) and run it once to write `baseline_2024_states.csv`; hand-write the districts CSV; implement `load_units`.
- [ ] **Step 4:** Run tests; expect PASS.
- [ ] **Step 5:** Commit `scenarios/` files: "Add scenario baseline units from official 2024 totals".

### Task 2: Swing engine

**Files:** Create `scenarios/engine.py`; Test `scenarios/tests/test_engine.py`

**Interfaces:**
- Consumes: `Unit` (Task 1).
- Produces: `class ScenarioError(ValueError)`; `@dataclass(frozen=True) ThirdParty(name: str, share: float, from_r: float, from_d: float)`; `@dataclass(frozen=True) Scenario(name: str, r_name: str, d_name: str, national_swing: float = 0.0, regional_swing: dict[str, float] = {}, third_party: tuple[ThirdParty, ...] = ())` (use `field(default_factory=dict)`); `@dataclass(frozen=True) UnitResult(id, state, ev, r: float, d: float, third: dict[str, float], other: int, winner: str)` where winner is `"R"`, `"D"`, a third-party name, or `"TIE"`; `apply(units: list[Unit], s: Scenario) -> list[UnitResult]`.

Arithmetic per unit (design §Swing arithmetic): `two = r + d`; `m = (d - r) / two`; `shift = national_swing + regional_swing.get(state, 0)`; `d1 = two * (1 + m + shift/100) / 2`; `r1 = two - d1`; for each third party `take = share/100 * (r + d + other)`, `r1 -= take*from_r`, `d1 -= take*from_d`. Negative `r1` or `d1` → `ScenarioError(f"{unit.id}: ...")`. Winner = max of R, D, third parties; exact tie at the top → `"TIE"`. District units use their state's regional swing.

- [ ] **Step 1: Write failing tests:**
  - `test_zero_scenario_returns_2024_votes`: every result's r/d equal the unit's (within 1e-6)
  - `test_margin_moves_by_swing`: on a unit r=600,d=400, swing +5 → `(d1-r1)/(r1+d1) == -0.2 + 0.05`
  - `test_regional_swing_adds_to_national`: PA regional +2, national +1 → PA margin moves 3 points, OH moves 1
  - `test_third_party_draw_split`: r=500,d=500,other=0, share 10, from_r .7, from_d .3 → r1=430, d1=470, third=100
  - `test_negative_votes_raise` (Review Focus 2): unit r=990,d=10, swing −5 → `ScenarioError` mentioning the unit id
  - `test_third_party_can_win_unit` (Review Focus 5): r=400,d=400,other=200, share 45 split .5/.5 → winner is the third-party name
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `engine.py`.
- [ ] **Step 4:** Run all tests; PASS.
- [ ] **Step 5:** Commit "Add scenario swing engine".

### Task 3: Matchups file and loader

**Files:** Create `scenarios/matchups.toml`, `scenarios/matchups.py`; Test `scenarios/tests/test_matchups.py`

**Interfaces:**
- Consumes: `Scenario`, `ThirdParty`, `ScenarioError` (Task 2); unit states from `load_units` (Task 1).
- Produces: `load_matchups(path: str, known_states: set[str]) -> list[Scenario]`.

TOML shape (one table per matchup; all numbers 0):
```toml
[[matchup]]
name = "vance-vs-shapiro"
r_name = "JD Vance"
d_name = "Josh Shapiro"
national_swing = 0.0
[matchup.regional_swing]   # state code -> points, optional
[[matchup.third_party]]
name = "Thomas Massie (L)"
share = 0.0
from_r = 0.5
from_d = 0.5
```
Ship matchups for the draft starters (Vance vs Shapiro) and the listed alternates as separate entries: Rubio vs Shapiro, Vance vs Ocasio-Cortez, Vance vs Khanna. Third parties in each: Massie (L), Ware (G), all share 0, split 0.5/0.5. No Constitution entry (no pick). Comment at top: names are hypothetical draft picks, every number is hand-set by Steve.

- [ ] **Step 1: Write failing tests:**
  - `test_loads_shipped_file`: 4 scenarios, all swings and shares 0
  - `test_bad_split_rejected` (Review Focus 3): from_r .6 + from_d .6 → `ScenarioError`
  - `test_unknown_region_rejected` (Review Focus 4): `regional_swing = {XX = 1}` → `ScenarioError`
  - `test_shipped_matchups_reproduce_2024`: every shipped scenario applied to units yields 312 R / 226 D
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit "Add matchups.toml and loader".

### Task 4: Report: totals, tipping point, sensitivity, output files

**Files:** Create `scenarios/report.py`, `scenarios/run.py`; Test `scenarios/tests/test_report.py`

**Interfaces:**
- Consumes: `apply`, `Scenario`, `UnitResult` (Task 2); `load_units` (Task 1); `load_matchups` (Task 3).
- Produces: `LABEL = "Scenario, not a forecast: inputs are hand-set assumptions."`; `ev_totals(results) -> dict` with keys per winner plus `tie: bool` (True when no candidate reaches 270 and the top two are 269–269) and `winner: str | None`; `tipping_point(results) -> str` (unit id: sort units won by the overall winner by that winner's margin in that unit, descending; the first unit at which their cumulative EV reaches 270); `flip_swing(units, s) -> float | None` (smallest-magnitude change to `national_swing` at which the overall winner changes; compute each unit's crossing shift `-(margin after other inputs)` in points, walk crossings in order of distance, re-tally EVs at each; None if no flip within ±100); `sensitivity(units, s) -> list[tuple[float, int, int]]` for national swing −10.0 to +10.0 step 0.5 (41 rows: swing, R EV, D EV); `render_markdown(s, results, totals, tp, flip, sens) -> str` (first line is `LABEL`); `run.py` CLI: `python3 -m scenarios.run [--matchups PATH] [--out DIR]` writes `scenarios/out/<name>.md` and `<name>.csv` (CSV first line is `# ` + LABEL).
- Add `scenarios/out/` to `.gitignore`.

- [ ] **Step 1: Write failing tests:**
  - `test_label_first_line`: rendered Markdown and CSV both start with LABEL
  - `test_2024_totals_and_tipping_point`: zero Vance–Shapiro scenario → R 312, D 226, winner R, tipping point is a unit won by R (assert it's in the set of R-won units and cumulative EV logic holds)
  - `test_flip_swing_flips`: applying `national_swing = flip_swing(...)` + 0.01 in the flip direction changes the winner; applying flip − 0.01 does not
  - `test_sensitivity_shape`: 41 rows, first swing −10.0, last +10.0, R+D EVs ≤ 538 each row
  - `test_tie_reported` (Review Focus 1): synthetic units summing to 538 split 269/269 → `tie is True`, `winner is None`, Markdown contains "No majority: House decides"
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run all tests; PASS; run `python3 -m scenarios.run` and confirm four `.md` files exist, each starting with LABEL and showing 312–226.
- [ ] **Step 5:** Commit "Add scenario reports: totals, tipping point, sensitivity".
