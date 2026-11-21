# Step 2 design: raw-download store, common results format, Enhanced Voting reader

Status: **approved by Steve 2026-11-20**. Order decided by Steve: Enhanced Voting first, then Clarity.

## Intent

Turn each state's official election-night file into one common, inspectable table, with the raw file saved and hashed before any parsing (plan step 2). This first piece covers the seven Enhanced Voting (EV) states: AZ, GA, UT, WA, VA, RI, ID. Clarity follows with the same store and the same output format.

## Goals / non-goals / anti-goals

- Goals: polite fetching (hard minimum interval per source), raw file + manifest row before parsing, one long-format output any later step can read, real-data tests.
- Non-goals (later steps): the step 3 checks (totals never decrease, votes ≤ registered, counties sum to state), expected vote, projections, scheduling a loop on election night, vote-type normalization across states.
- Anti-goals: fixing or filling source data; guessing a field's meaning; hitting a site faster than its limit; any LLM logic.

## What the data looks like (checked 2026-11-20)

- AZ export: 72.7 MB, statewide + 15 counties, precinct results, five vote-type groups (`docs/az-feed.md`).
- UT export: 0.5 MB, **same structure**, statewide + 29 counties, but **no precinct results and no vote-type groups**.
- So the reader must accept missing `groupResults` and `precinctResults` and record what's absent rather than fail.
- Format reference: `docs/Arizona Media JSON Guide.pdf`. Statewide status and precinct-count fields are documented as unused at state level.

## Approaches considered

1. **Shared fetch/store + one EV parser + long-format CSV (recommended).** Small modules, each testable; Clarity later adds only a parser.
2. One script per state. Rejected: seven copies of the same parser.
3. Parse straight into a database. Rejected for now: CSV is inspectable and enough at this scale (proportionality); a database can come in step 4–6 if needed.

## Design

**Where it lives:** a new package `pipeline/` (the results pipeline proper). `tools/` stays for one-off scripts. Nothing in `scenarios/` is touched.

- `pipeline/fetch.py`: `fetch(source_id, url, min_interval_s)` → saved file path.
  - Refuses to fetch if the same `source_id` was fetched less than `min_interval_s` ago. The last-fetch time is kept in `data/raw/.last_fetch.json`, so separate runs also respect it.
  - Saves the body unchanged to `data/raw/<source_id>/<UTC timestamp>.<ext>` and appends a row (source_id, url, fetched_utc, http_status, bytes, sha256) to `data/raw/manifest.csv` **before** returning. Parsing happens only on saved files.
  - Standard library only; Homebrew Python (TLS 1.3).
- `pipeline/sources.toml`: one entry per EV state: source_id (e.g. `ev-AZ-2026-general`), export URL (the officially linked Media Export from the registry/docs), `min_interval_s = 120` for all EV states. AZ's limit is 2 minutes per the SOS; the others publish no limit, so they get the same.
- `pipeline/schema.py`: the common output columns (below) and a CSV writer.
- `pipeline/readers/enhanced_voting.py`: `parse(path)` → rows, plus a small summary (election name, createdAt, counties, whether precinct and vote-type detail were present).
- `pipeline/run_ev.py`: CLI. `fetch` (respecting the interval) and/or `parse` a saved file into `data/parsed/<source_id>/<timestamp>.csv`. `data/` stays gitignored.

**Common output (long format, one row per vote count):**

`state, source_id, source_sha256, source_created_at, election_name, election_date, level, county_id, county_name, precinct_id, precinct_name, precinct_is_virtual, contest_id, contest_scope, contest_name, contest_type, vote_for, choice, choice_id, party, vote_type, votes, reporting_status`

- `contest_scope` and `choice_id`: added 2026-11-20 after the build (Steve approved). `contest_scope` is `statewide` when the contest appears in the file's state-level results (so `contest_id` is unique across counties), else `local` (key is `county_id` + `contest_id`). `choice_id` is the source's option id. Names are not reliable keys.

- `level`: `state`, `county` or `precinct`.
- `vote_type`: `TOTAL` for the option's total, otherwise the state's own group name unchanged (AZ: "Election Day", "Early Voting", "Provisional", "Early A.R.S. 16-579", "Late Early*"). Mapping these to common categories is deferred to step 5 (not yet approved).
- `reporting_status`: precinct rows carry the precinct's status; county rows carry the county status for that vote type where given. Statewide status fields are skipped (documented as unused).
- Ranked-choice results: not present in any EV file seen; the reader stops with a clear error if it meets one, rather than half-parse it.

**Not fixed, only reported:** while parsing, the reader records (not repairs) two internal mismatches it can see for free: statewide total ≠ sum of counties for a contest/choice, and vote-type groups ≠ the option total. These go in the summary; step 3 will own real checks.

## Tests (stdlib `unittest`)

- **Fixtures from real files:** a script cuts small fixtures from the saved AZ and UT exports (one county, a few contests), recording the source file's SHA-256. The fixtures are committed so tests run offline. The full raw files stay gitignored.
- Parser tests: row counts and exact vote values for named contests in the fixtures (taken from the real file); missing groups/precincts (UT) handled; statewide = sum of counties on the fixture; a ranked-choice item raises.
- Fetch tests (local only, no network): the interval refusal, raw saved + manifest row before return, hash correct. They use a local file URL or an injected opener, not a live site.
- One integration test parses the full saved AZ file when present (skipped if absent) and checks statewide = sum of counties for all 415 pairs, as found earlier.

## Build order (small commits)

1. `fetch.py` + manifest + interval, with tests.
2. Schema + EV parser + fixtures + tests (AZ, UT).
3. `sources.toml` for the 7 states + CLI; fetch each remaining state's export once (GA, WA, VA, RI, ID) to confirm the parser handles them, saving raw files only.

## Left to the builder

Internal function names, CLI flags, fixture contents beyond what the tests pin.
