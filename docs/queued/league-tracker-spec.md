# Queued: 2028 fantasy league tracker (league/)

Spec as given by Steve, 2026-11-20 (the second version; it replaces an earlier draft with a Shapiro-led roster). Not started. Queue order: source verification → scenario model → this.

NEW COMPONENT: 2028 fantasy league tracker, in league/
- Separate from the results pipeline (sources/, tools/) and the scenario model (scenarios/); don't touch either. Flag it if this starts growing.
- Purpose: track hypothetical 2028 presidential picks fantasy-football style. These are picks, not predictions.

1. ROSTER
Draft rule: "likely nominee" = polls plus prediction markets.
Starting roster, as of Nov 20, 2026:
- Republican: JD Vance (bench: Marco Rubio, Ron DeSantis)
- Democratic: Gavin Newsom (bench: Kamala Harris, Jon Ossoff, Alexandria Ocasio-Cortez)
- Libertarian: Thomas Massie (bench: Justin Amash). Low-confidence: thin market.
- Green: Butch Ware (bench: Dashaun "Daví" Davis). Low-confidence: thin market.
- Constitution: open slot
Each pick carries a draft_basis field (source + date) and, where it applies, a low_confidence flag.

2. ROSTER HISTORY AND UPDATES
- Snapshots go in league/rosters/roster-YYYY-MM-DD.yaml. Never overwrite one. league/roster.yaml points to the current approved snapshot.
- The draft rule lives in league/draft_rule.yaml and must be deterministic:
  - Per party, rank candidates by national primary polling average and, separately, by prediction-market nominee odds. Starter = best combined rank; bench = the next 2-3.
  - Record every input value with its source URL and the date observed.
  - Before using any data source, verify it exists and can be read. List the sources in draft_rule.yaml. Never invent or estimate a number; if a value can't be retrieved, mark it missing.
- Monthly job: pull the inputs, apply the rule, and write league/rosters/proposed-YYYY-MM-DD.yaml plus a diff against the current roster (who moved, why, with the numbers). It never approves anything; it becomes current only after I approve it.
- declared_only flag (default off): once a party has 2 or more FEC-declared candidates, only declared candidates are eligible for that party. Anyone who publicly rules out running is cut.

3. SCORING (league/scoring.yaml; starting values, I'll tune them; same rules for every party)
- Formal campaign launch (FEC Form 2 filed): +10
- Quarterly fundraising: +1 per $1M raised, taken from the FEC filing itself, never from news coverage of it
- Endorsement: sitting governor or senator +3, House member +1, national union +3
- National primary poll from a pollster on my approved list: 1st +5, 2nd +3, 3rd +1 (the list starts empty; I'll add pollsters)
- Qualifies for an official primary debate: +2
- 2028 primaries: +0.1 per delegate won
- Third parties: propose equivalents (convention ballots, the party's own debates) and show me before scoring any.
- Points rule (my default, changeable): points belong to the candidate, and a party's weekly total counts only its starter's points for that week. Bench points are tracked but don't count. A candidate keeps their points when moved to the bench.
- Divisions: major parties and minor parties in separate standings.

4. EVENT LOG (league/events.csv)
- Columns: date, candidate, event_type (must exist in scoring.yaml), detail, source_url, status (proposed/approved/rejected), approved_on.
- Only approved rows score. Points come from a lookup in scoring.yaml, with no judgment calls in the code.
- Every row needs a source_url. For fundraising, the source is the FEC filing.

5. WEEKLY NEWS SCAN (the only LLM step; keep it in league/scan/)
- Searches news for all roster and bench candidates and appends rows with status=proposed.
- Never approves rows, edits existing ones, or invents numbers. If an article gives a figure without a primary source, propose the event with a note saying where to verify it.

6. OUTPUTS
- Weekly standings per division, with week-over-week change
- A points history per candidate
- A roster history: who was the starter each week

7. TESTS
- Scoring arithmetic
- Proposed and rejected rows never score
- An unknown event_type is rejected
- Bench points don't count toward a party's total
- The draft rule, run on the Nov 20, 2026 inputs, reproduces the starting roster above

BUILD ORDER (small commits)
roster + snapshot format -> scoring.yaml + scorer + tests -> event log + approval step -> standings -> draft rule + reproduction test -> monthly roster job -> weekly news scan

## Notes to resolve when work starts (Claude, 2026-11-20)

- The reproduction test can pass only if the Nov 20, 2026 poll and market inputs, once retrieved, actually rank this roster first. If they don't, the test fails and the mismatch goes to Steve; neither the inputs nor the rule gets adjusted to force it.
- The scenario model's draft (Shapiro-led) differs from this roster (Newsom-led). They're separate components, so both stand unless Steve says otherwise.
