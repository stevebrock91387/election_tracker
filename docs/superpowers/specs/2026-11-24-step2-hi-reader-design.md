# Step 2: Hawaii reader (design)

Date: 2026-11-24. Steve: "Go for it" (survey and build HI, WY, MS, MA, IL, NJ where workable), under
the standing approval for the remaining state readers (2026-11-24).

## Intent

Read Hawaii's results at precinct level, with mail and in-person votes, from the Office of Elections'
own text files, with the statewide file as a check.

## Source (seen 2026-11-24, script download works)

Linked as "Certified Text Files" on `https://elections.hawaii.gov/election-results/` (2026 tab, "Last
Updated: November 24, 2026 7:37 am"):

- `https://elections.hawaii.gov/wp-content/results/2026%20General/summary.txt` ("Statewide Summary",
  22 KB) and `…/media.txt` ("Statewide Precinct Detail", 1.9 MB). Tab-separated UTF-8; quoted fields
  may hold newlines (Governor/Lt. Governor candidate names span four lines).
- `summary.txt`: line 1 `#FormatVersion 1`, line 2 the header (`#Contest ID`, Contest Title, Contest
  Seq Nbr, Contest Type `OF`/`MS`, Contest Party, Mail/In-Person Blank, Over and Invalid Votes,
  Registered Voters, Total Precincts, Counted Precincts, Candidate ID, Candidate Name, Candidate Seq
  Nbr, Candidate Party, Mail Votes, In-Person Votes, Total Votes); one line per (contest, candidate).
- `media.txt`: line 1 `Column1 … Column16`, line 2 `#FormatVersion 1`, line 3 the header
  (`#"Precinct_Name"`, Split_Name, precinct_splitId, Reg_voters, Ballots, Reporting, Contest_id,
  Contest_title, Contest_party, Choice_id, Candidate_name, Choice_party, Candidate_Type, Mail votes,
  In-Person votes, and an empty 16th field); one line per (unit, contest, candidate).
- 2026: 92 contests (federal, state, OHA trustees, county offices and charter questions), 202
  candidate lines, 496 units. Every precinct (`01-01` … `51-05`, plus `OS I`, `OS II`) appears twice:
  a plain unit (Split_Name empty: registered voters, Reporting 1, mail votes, in-person 0) and a
  `VSC` unit (Voter Service Center: registered voters 0, Reporting 0, mail 0, in-person votes).
  `Total Precincts` counts both units; `Counted Precincts` equals the plain units. Summed to the state,
  the precinct lines equal the summary for all 202 lines (mail and in-person). Party is not in the
  party columns (empty) but as a name prefix: `(D) TOKUDA, Jill N.`.
- No county anywhere; no blank/over votes per precinct (state only).
- Election night: the 2024 election published numbered printouts (registry). Whether 2028's
  printouts use these same files and paths is unverified; the URLs are config.

## Approaches

1. **Both text files (chosen).** Precinct rows from `media.txt`, state rows and the check from
   `summary.txt`. Two requests per pass.
2. The PDFs (summary, precinct detail, statement of vote). Rejected: same numbers, PDF parsing.
3. `media.txt` only. Rejected: loses the independent state check and blank/over votes.

## Design

- **Fetch.** `sources_hi.toml` (`hi-2026-general`): `summary_url`, `media_url`, `min_interval_s`
  120. Source ids `<id>-summary`, `<id>-media`, ext `txt`. A failure stops the pass (as every
  reader). Pass record files: kinds `summary`, `media`.
- **Reading.** Decode UTF-8 (BOM tolerated), `csv.reader(delimiter="\t")`. Each file's header must
  appear exactly as above within its first five lines; the lines before it are recorded as
  `preamble` per file. A changed header or no data lines: that file is unreadable.
- **Scope.** All 92 contests (Hawaii's file is small, and the county offices are in the
  statewide file). `contest_scope` "statewide" (the schema's meaning: in the state-level file).
  `contest_type` "candidate" for `OF`, "measure" for `MS`, else the code as published.
- **Precinct rows** (`level` "precinct"): `precinct_id` = precinct_splitId, `precinct_name` =
  Precinct_Name plus " " + Split_Name when present (`01-01 VSC`), `precinct_is_virtual` "Y" when
  Split_Name is non-empty or the name isn't `NN-NN`, else "N". `choice` = Candidate_name with
  whitespace runs collapsed to one space; `party` = the leading `(X)` letter(s) when present, else
  the Choice_party column; `choice_id` = Choice_id. Vote types `TOTAL` (mail + in-person),
  `Mail votes`, `In-Person votes`. `reporting_status` = "Reporting " + the unit's flag.
- **State rows** (`level` "state") from `summary.txt`, same choice/party rules, vote types `TOTAL`
  (the Total Votes column), `Mail Votes`, `In-Person Votes`; plus per contest three choices `Blank
  Votes`, `Over Votes`, `Invalid Votes` (choice_id "", party "") with mail, in-person and TOTAL
  (their sum). `reporting_status` = "<Counted> of <Total> precincts counted".
- **Turnout table** (one row per unit): state, source_id, source_sha256, precinct_id,
  precinct_name, registered_voters, ballots, reporting.
- **Summary lists** (nothing corrected; a check that couldn't run is `None`):
  - `state_precinct_mismatches`: (contest, choice_id, vote type, state, precinct sum), both
    directions (`None` on the missing side).
  - `total_mismatches`: summary lines whose Total ≠ Mail + In-Person.
  - `registered_mismatches`: contests whose summary Registered Voters ≠ the sum over all units.
  - `precinct_count_mismatches`: (contest, Total/Counted as published, units with lines, units with
    Reporting 1 among them).
  - `title_mismatches` / `choice_name_mismatches`: an id whose title or name differs between files.
  - `unit_conflicts`: a unit whose name, Split_Name, registered, ballots or Reporting varies across
    its lines.
  - `duplicate_lines`: (file, contest, choice, unit) repeated; the later line is dropped.
  - `non_numeric`, `malformed_lines` (wrong field count), `inconsistent_contest_fields` (a contest
    whose title, type, blank/over/invalid, registered or precinct counts vary across its summary
    lines).
  - Counts: contests, units, plain units, VSC units, lines per file, `parties_from_prefix`.
  - `unreadable_files` / `missing_files`; a missing summary makes the cross-checks `None`; a
    missing media file makes them and the precinct checks `None`.

## Left to the builder / not done

- County: precinct ids carry the state house district (`01-01`), not the county. A precinct →
  county map (or a later file that carries it) is a separate job.
- `OS I` / `OS II` (0 registered, 0 ballots in 2026) are kept as published; meaning unverified.
- Fixture: the real files filtered to a few small contests (lines kept byte for byte, preambles and
  headers included).
