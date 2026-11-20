# Queued: 2028 "what-if" scenario model (scenarios/)

Spec as given by Steve, 2026-11-20. Not started. Queue order: source verification → this → league tracker.

New, separate component: a 2028 "what-if" scenario model. It is not part of the six-step results pipeline. Keep it in its own folder (scenarios/) and don't let it touch the results pipeline code. Flag it if it starts growing.

Purpose: game out hypothetical 2028 presidential matchups from my fantasy-draft picks. These are hypothetical picks, not predictions of who will run.

Fantasy draft (hypothetical):
- Republican: JD Vance (alt: Marco Rubio)
- Democratic: Josh Shapiro (alt: Alexandria Ocasio-Cortez or Ro Khanna)
- Libertarian: Thomas Massie (alt: Justin Amash)
- Green: Butch Ware (alt: Jill Stein)
- Constitution: no pick yet

How it works (deterministic, inspectable, no LLM logic):
1. Starting point: 2024 presidential results by county, from an official or established source. Record the exact source and the download date. Prefer official certified state results. A well-known historical dataset (for example, MIT Election Data and Science Lab county returns) is acceptable if you verify it actually exists and covers 2024. Do not fabricate or estimate missing counties; list them as gaps.
2. scenarios/matchups.yaml lists each candidate per party. Every number about a candidate is a parameter I set by hand, never one you invent or "estimate from what's known about them":
   - national_swing: two-party margin shift vs. 2024, in points
   - optional regional_swing: per state or region
   - third_party_share: vote share for each minor-party candidate, with how much of it comes from the R and D columns
   Default every parameter to 0, so the first run reproduces 2024.
3. Apply the swings to each county's 2024 result, then add up county -> state -> electoral votes.
   - Maine and Nebraska award electoral votes by congressional district. Handle that, or flag those states as not modeled.
4. Output for each matchup: projected winner of each state, the electoral vote total, and the tipping-point state. Also produce a sensitivity table showing how many points of national swing it takes to flip the result.

Tests:
- With all parameters at 0, the model must reproduce the actual 2024 state winners and electoral votes exactly. Make this test pass before anything else.
- Electoral votes always total 538.
- Unit tests for the swing arithmetic.

Rules:
- Every output carries the label "Scenario, not a forecast: inputs are hand-set assumptions."
- No polling data, prediction-market odds, or candidate-strength numbers unless I supply them and say where they came from.
- Small commits: data loader + 2024 check first, then the swing engine, then the matchup file, then the output.

## Notes to resolve when work starts (Claude, 2026-11-20)

- The MEDSL 2024 county sums have large errors in LA, NJ and IN (see CLAUDE.md, "2024 President check"). Those states can't be a reliable starting point as is; options are official county results for them, or a verified county-level dataset.
- Maine and Nebraska congressional districts can't be built from county totals alone (district lines split counties); they need precinct or town data, or get flagged as not modeled.
