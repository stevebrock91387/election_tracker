# Step 3: checks on a results database (design)

Date: 2026-11-25. Steve chose step 3 next (after the state readers) and, of three ways to build it,
"C": load every reader's output into one database and write the checks as queries. Not covered by the
standing approval for state readers. **Approved by Steve 2026-11-25** with retention option A.

## Intent

Catch bad numbers before anything is projected from them (steps 4–6). CLAUDE.md names the checks:
totals never decrease, votes never exceed registered voters, counties add up to the state total. AP
numbers are a cross-check only, never a source (not built here). The database is also meant to serve
step 4 (expected vote), which joins this year's counts with past turnout.

## Goals, non-goals, anti-goals

- **Goals:** one SQLite file holding every parsed snapshot from every reader; three checks that run on
  it and list every exception; runs on election night after each poll.
- **Non-goals:** fixing, choosing between or estimating values; the AP cross-check; mapping contests
  across counties or states (NJ contest name map, FIPS); step 4.
- **Anti-goals:** a check that blocks or edits data (new checks start in observe mode: they report
  only); a silent "clean" when a check couldn't run; numbers in the database that differ from the
  reader's CSV.

## Constraints

- stdlib only (`sqlite3`; the installed SQLite is 3.53.4). Run under `/opt/homebrew/bin/python3` or
  `.venv/bin/python`.
- Inputs are the readers' outputs as they are today: `data/parsed/<source_id>/<UTC>.csv` (the common
  columns in `pipeline/schema.py`) and, for 14 readers, `<UTC>-turnout.csv` with reader-specific
  columns. Readers are not changed.
- The database lives in `data/` (gitignored): `data/results.sqlite`. Reports go to
  `data/reports/<UTC>/`.
- Don't name anything `checks/`: `.gitignore` ignores every directory with that name (it holds the
  old URL-checker output).
- Size today: 49 sources, 8.4M result rows in 2.4 GB of CSV.

## What the data looks like (recon 2026-11-25)

- 22 sources have more than one parsed CSV. For 20 of them every CSV comes from the same downloaded
  files (same `source_sha256` values): re-parses after reader fixes, not new data. MA and NC have
  two different downloads each (NC: the dashboard changed, the ZIP didn't).
- A row's `source_sha256` is the hash of the downloaded file it came from; multi-file passes (NC,
  NJ county JSON, MD pages) carry several. `data/raw/manifest.csv` maps every hash to its
  `fetched_utc`.
- Turnout tables differ by reader: registered voters are `registered_voters` or `voters_qualified`
  (LA); ballots are `ballots_cast`, `ballots`, `voters_voting` (IN), `voters_voted` (LA) or absent
  (WY has no registered voters); TX's `voters` may not be ballots cast (`docs/tx.md`). Units are
  counties, towns, precincts, election districts (DE) or per contest (LA).

## Approaches (Steve picked C)

- A. A Python checker reading the CSVs directly. Simpler, but every later step re-reads the CSVs.
- B. Checks inside each reader. About 20 copies, and no reader sees the previous poll.
- **C. Load into SQLite, checks as SQL (chosen).** One loading step, checks are short readable
  queries, and step 4 can join against the same tables. Costs a load step and a second copy of the
  data (a few GB).

## Design

### Tables

- `snapshot`: one row per distinct downloaded state of a source. Its time is **when that content
  first existed**: for each `source_sha256` in the CSV take its earliest `fetched_utc` in the manifest,
  then the latest of those. (A file unchanged across passes, like NC's ZIP, keeps its first fetch
  time, so the pass whose dashboard changed gets the later time.) Identity = (`source_id`, that time):
  two parses with the same time are the same snapshot even when a reader fix reads one more or one
  fewer file of the pass. A hash missing from the manifest is listed and the CSV isn't loaded.
  Columns: `snapshot_id`, `source_id`, `state`, `first_seen_utc`, `csv_path`, `csv_sha256`,
  `turnout_path`, `loaded_utc`.
- `result`: the common columns, plus `snapshot_id`; `votes` stored as INTEGER, "" stored as NULL.
  No other change to any value.
- `turnout`: one row per turnout-table row: `snapshot_id`, the unit (`level`, `county_id`,
  `county_name`, `precinct_id`, `precinct_name`, `contest_id` for LA), `registered_voters`,
  `ballots_cast` (NULL where the reader has none or the map says it isn't ballots), and `raw` (the
  whole row as JSON, so nothing is lost).
- `load_note`: anything the loader couldn't place (unknown turnout columns, hash not in manifest,
  superseded parses).

### Loading (`python3 -m pipeline.db load`)

- Walks `data/parsed/`, skips CSVs already loaded (by `csv_sha256`).
- **Re-parses of the same snapshot:** the newest parse (by its file name) is the snapshot's data; an
  older one already loaded is replaced and a `load_note` says so. Reader fixes therefore win.
- Turnout columns come from a small map, `pipeline/turnout_map.toml`, one entry per turnout layout
  (14 reader prefixes; Clarity has two layouts, statewide and county): unit level, which columns are
  the unit key, which column is registered voters, which is ballots cast, which vote type is a unit's
  total (default `TOTAL`; WV's county rows are all "Election Day", which `docs/clarity.md` says holds
  every vote), and an optional roll-up of result units into turnout units, **only where the reader's
  own doc defines it** (HI: a precinct's plain and `VSC` units are added; VT: town parts are added to
  the town). A turnout CSV with no entry, or with columns the entry doesn't name, is loaded with only
  `raw` filled and listed.
- One transaction per CSV. Indexes on the keys the checks use.

### Checks (`python3 -m pipeline.db check [--source ID]`)

Each is a SQL query in `pipeline/db_checks/*.sql` with a name and a one-line meaning. A run writes one
CSV per check (every exception, with both values) to `data/reports/<UTC>/` and prints the counts,
including **not checked** with the reason when a check can't run for a source. Nothing is ever
blocked or changed.

1. **Never decrease:** for each source, each snapshot against the one before it (by
   `first_seen_utc`), same key: `level`; `county_id`, or `county_name` where the id is empty;
   `precinct_id`, or `precinct_name` where empty; `contest_id`; `choice_id`, or `choice` where empty;
   `party`; `vote_type`. Every lower count, and every key that disappeared (in name-keyed readers a
   spelling change shows as a disappearance plus a new key: listed, which is wanted). Not checked for a source with one
   snapshot. Every decrease is listed, no tolerance: recounts and rejected provisionals lower counts
   for real, and the list shows them. A reader fix between two parses of different downloads can show
   up here too (MA in 2026).
2. **Not over registered voters:** at each turnout unit with registered voters > 0: ballots cast >
   registered; and for each contest, the sum of its choices' TOTAL votes > registered × `vote_for`
   (a blank `vote_for` counts as 1, listed). The sum includes every choice row as published,
   including blank, over and under votes and "All Others": with them it is still a valid ceiling, and
   no column marks them. Units with 0 registered voters are listed apart, not compared (AL publishes 0
   for 31 counties; NJ has 73 such units). Results join turnout on the unit key the map gives, after
   any roll-up the map names; result and turnout units that don't meet are counted and listed, and a
   source whose units don't meet at all (DE: turnout per representative district, results per
   election district) is "not checked" with that reason. A source with registered voters but no
   usable ballots column (TX) still gets the contest half of the check; WY publishes no registered
   voters, so check 2 is "not checked" for WY.
3. **Parts add up:** within each snapshot, for each contest, choice and vote type: precinct sum vs the
   county row, and county (or town) sum vs the state row, where both levels exist. A source missing a
   level is "not checked" for that pair (AK FL HI and the NJ counties have no state rows). Rows with
   an empty count make that sum "not checked", not a mismatch. Key: `contest_scope` "statewide" joins
   on `contest_id`; "local" on (`county_name`, `contest_id`); plus choice (id, else name), `party`
   (CT and DC publish one row per party line) and vote type. Precinct rows with no county (DE) make
   the precinct-to-county pair "not checked"; no keys are derived. Units that aren't a clean partition
   (AL columns holding two districts) show as mismatches, which the AL reader already explains.

### Snapshot retention (Steve chose A, 2026-11-25)

Every new version is a full copy (Burlington about 1.29M rows, NC about 439k). Check 1 needs only the
latest two snapshots per source; every download stays in `data/raw/` regardless and can be re-parsed
and reloaded. **The database keeps the result and turnout rows of the latest two snapshots per source**
(by `first_seen_utc`); older snapshots keep their `snapshot` row, marked pruned. A CSV older than both
kept snapshots isn't loaded (noted). Rejected: every snapshot (possibly hundreds of GB a night); every
snapshot as changed rows only (compact, more complex queries).

### Election night

`fetch-parse`, then `db load`, then `db check --source ID`. Loading is incremental; a check run can be
limited to one source.

## Left to the builder

Index choice, SQL style, report column order, how `load` reports progress, test fixtures (small
synthetic CSVs plus one real reader fixture).

## Calls I made (Steve to check)

- Database file in `data/` (not committed); one database for all states and snapshots.
- Re-parses: newest parse wins, older ones replaced and noted.
- Snapshot time = when its content first existed, from the manifest, not the publisher's own
  timestamp (not every source has one); same time = same snapshot (newest parse wins).
- Unit roll-ups only where a reader's doc defines them (HI, VT); otherwise unmatched units are listed
  or the source is "not checked". No derived keys.
- Check 2 sums every choice row, blanks and over/under votes included.
- WV's total vote type is "Election Day" (configured, per `docs/clarity.md`).
- Check 1 and 3 keys use ids where present, names where not; `party` is part of the key.
- 0 registered voters: listed apart, not compared.
- Blank `vote_for` treated as 1 in check 2 (and listed).
- TX `voters` not used as ballots cast until its meaning is known.

## Not done

AP cross-check; contest/county name maps; any step-4 tables; checks across sources (e.g. NJ counties
against a future state total).
