# North Carolina: precinct ZIP + dashboard check

Seen 2026-11-23 in the built-in browser and with single recon downloads. Downloaded through `pipeline/fetch.py` (`pipeline/run_nc.py`) on 2026-11-24 at 15:02 UTC, then parsed with `pipeline/readers/nc.py`. Design: `docs/superpowers/specs/2026-11-23-step2-nc-reader-design.md`. **Precinct level; contest type S only** (statewide and district contests: US Senate, US House, NC Senate and House, judges, referenda).

## Where the data is

A pass makes two requests, 10 s apart:

| Kind | URL (2026 general) | What it is |
|---|---|---|
| `zip` | `https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_11_03/results_pct_20261103.zip` | Every contest by precinct and vote method. One tab-separated member, `results_pct_20261103.txt`, with CRLF line endings. The layout is at `https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/layout_results_pct.txt`. |
| `dashboard` | `https://er.ncsbe.gov/enr/20261103/data/results_0.txt` | The results dashboard's statewide file: a JSON list with one object per (contest, choice). |

Both URLs, and the member name, contain the election date.

The ZIP columns are: County, Election Date, Precinct, Contest Group ID, Contest Type, Contest Name, Choice, Choice Party, Vote For, Election Day, Early Voting, Absentee by Mail, Provisional, Total Votes, Real Precinct.

The dashboard keys are:
- `gid`: contest group, the same id as the ZIP's.
- `cnm`: contest name, with "(VOTE FOR n)" appended.
- `bnm`: choice name.
- `pty`: party.
- `vct`: total.
- `evc`, `ovc`, `avc`, `pvc`: by method, in that order Election Day, Early Voting, Absentee by Mail, Provisional. This mapping is **inferred from sums** and the state doesn't document it.
- `prt` / `ptl`: precincts reporting / total.
- `ogl`: office group (FED, COS, JUD, NCS, NCH, CCL, or blank).

## Parsed (2026-11-24, pass started 15:02 UTC)

| File | Bytes | SHA-256 (first 12) | Notes |
|---|---|---|---|
| ZIP | 2,240,941 | `4fcc5999bbaf` | Member timestamp 2026-11-13 19:05:40 (time zone not stored); 155,661 lines, 100 counties |
| Dashboard | 197,630 | `eed543187682` | 677 rows |

- **Output:** 439,030 rows.
  - 436,025 precinct rows: 87,205 type-S lines × 5 vote types.
  - 3,005 state rows: 601 dashboard rows × 5.
- **Coverage:** 395 contests, 601 choices, 100 counties, 2,842 precincts (county + precinct name pairs; administrative precincts included).
- **Out of scope:** 76 dashboard rows are skipped because the ZIP marks their contests as type C. These are municipal contests with their own group ids (office group CCL).
- **Clean checks:** no bad method sums, non-numeric counts, wrong field counts, header changes, duplicate keys or orphans in either direction. The NUL choice seen in recon is in a type-C contest (Hyde County commissioners), so it is out of scope here.

### The dashboard and the ZIP disagree

252 differences across 89 (contest, choice) pairs in 60 contests.

- **By vote type:**
  - TOTAL 85
  - Provisional 60
  - Election Day 52
  - Early Voting 29
  - Absentee by Mail 26
- **Size:** TOTAL differences are at most 13 votes. The dashboard is higher in 51 and lower in 34; net +12 across all TOTALs. The largest single difference is Cooper's provisional count: 12,782 on the dashboard vs 12,767 in the ZIP.
- **Federal contests:**
  - US Senate: Cooper 2,480,648 vs 2,480,640; Whatley 1,648,865 vs 1,648,870; Bray +1; Dublin +3.
  - US House: 15 choices across districts 1, 5, 7, 8, 9, 10, 11 and 13 differ by 1–12. The two largest:
    - NC-08: Harris +4, Watson +12. Harris's margin is 5,016 on the dashboard vs 5,024 in the ZIP.
    - NC-10: Harrigan −1, Bell −8. Harrigan's margin is 2,516 vs 2,509.

The cause is unknown. The ZIP's member is dated 2026-11-13, but the dashboard file was last modified 2026-11-24 (per recon). That fits a ZIP that hasn't been refreshed since later count changes, but this has **not been verified**. The reader lists every difference and doesn't choose between the two.

## Quirks

- **No choice ids** in either file. The check joins on (contest group id, choice name as published); all 601 dashboard names match the ZIP exactly today. A spelling change in either file shows up as orphans.
- **No county codes:** `county_id` is empty and `county_name` is as published (upper case). No FIPS mapping yet.
- **Administrative precincts** (Real Precinct = N, `precinct_is_virtual` = "Y"): absentee, early-voting sites (e.g. "EV CRC") and transfers. 15,423 of 155,661 lines. Their votes are part of the county totals.
- **Party** is blank (a single space in the ZIP) for nonpartisan choices; the reader stores it as "".
- **Election Date** is stored as published ("11/03/2026"). Neither file carries an election name.
- **Local contests** in the ZIP all share contest group id `1` (type C). The dashboard gives municipal contests their own ids. Both are out of scope.

## Not done

- County contests (type C).
- Historical ZIPs, 2000–2024: the same layout since July 2018; older layouts differ per the layout file.
- The dashboard's per-county files.
- County FIPS mapping.
- Why the two files differ.
- Whether the ZIP is refreshed during election night (if it isn't, election night needs the dashboard's county files).
