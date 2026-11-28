# Step 4: expected vote

Design: `docs/superpowers/specs/2026-11-27-step4-expected-vote-design.md`. Plan:
`docs/superpowers/plans/2026-11-27-step4-expected-vote.md`. Code: `pipeline/expected/`.

## Inputs

- FEC federal-elections workbooks: 2018 sha256 `f2c42311…0e303`, 2022 sha256 `cdb258ea…50897` (data/raw/manifest.csv).
- MEDSL 2022 precinct: commit `a8126c5790b8`.
- MEDSL 2018 precinct: MEDSL/2018-elections-official commit `42055b11dcd5` (deprecated GitHub copy; Steve's
  call 2026-11-27). Harvard Dataverse (version 1.1) needs a guestbook response for every file, so it wasn't
  used. The copies differ: Dataverse MD5s don't match, and each Dataverse CSV is 4–24 MB larger (Senate
  131,870,353 vs 126,069,543 bytes, House 139,130,672 vs 134,835,502, State 1,942,565,019 vs 1,918,570,538);
  not line endings; cause unknown.

## FEC check (2026-11-27)

Per (state, office), US SENATE and US HOUSE, MEDSL county sums against the FEC. Steve's bar (2026-11-27,
option 1 of three offered): an office passes when every contest is equal, or when its **named candidates**
are equal and only write-ins differ. "Named" means every FEC named total appears among MEDSL's non-write-in
totals, and any MEDSL line left over ("ALL OTHERS", "SCATTERING", unflagged write-in names) is smaller than the
FEC's smallest named candidate; the leftovers and both write-in totals are recorded per contest
(`medsl_extra`, `data/expected/check-<year>.csv`). Baseline rows say which pass it was (`check` column).
Anything else fails, however small (kind B below).

| | 2018 | 2022 |
|---|---|---|
| Pass (of 85) | 56 (16 on named candidates) | 41 (8 on named candidates) |
| B. fail, candidates off by at most 1% (cause not investigated; a pre-certification count is likely, unverified) | 17: AL-H CT-S FL-H FL-S KS-H KY-H MO-H MO-S NC-H NV-H PA-S SD-H TX-S UT-S VT-S WA-H WA-S | 31: AR-S AZ-S CA-H CT-H CT-S FL-H FL-S KS-H KS-S KY-H KY-S ME-H MO-H MO-S NC-H NC-S NH-S NM-H NV-H NV-S NY-S OR-H OR-S PA-H PA-S SC-H SC-S UT-H UT-S VA-H WA-S |
| C/D. fail, larger or a contest missing | 12 | 13 |

VT-S 2018 is 7 votes short: the FEC counts the 7 write-ins cast for Sanders into his total, and the check
doesn't join names. NV 2022 also has suppressed (`*`) rows.

### Causes of the C/D failures

| Office | Cause | Fixable by a recorded fix? |
|---|---|---|
| DC-H 2018, 2022; DC-S 2018 | MEDSL's US HOUSE / US SENATE rows are DC's shadow representative and shadow senators; the delegate race is missing | no |
| IN-H, IN-S 2018 | contests missing in MEDSL (House 01; Senate) | no |
| IN-S, IN-H 2022 | MEDSL has 39 of 92 counties for Senate; House misses Monroe County and district 07 | no |
| ME-H 2018 | district 02 (ranked-choice) missing in MEDSL | no |
| PA-H 2018 | districts 07 and 15 missing in MEDSL | no |
| NY-H 2018, NY-S 2018 | counties missing in MEDSL (House 12, e.g. Albany, Saratoga; Senate Jefferson, Niagara, Ulster); House districts 18, 20, 21 absent | no |
| CA-S 2022 | no Senate rows in MEDSL | no |
| ID-H, ID-S 2022 | a "COUNTY TOTAL" row per county doubles the count; dropping it leaves Power County, which has no Senate or House rows (it has Governor rows) | no (a fix must make the office pass) |
| MS-H 2022 | Yazoo County's "TOTAL" row repeats its precincts (MS-02 +5,171); without it MS-01 is still 1 vote off | no |
| AZ-H, WA-H 2022 | one county's House rows have a blank district (Santa Cruz, AZ-07; Snohomish, WA-08), and other districts differ slightly | no (would need a district assigned, not a drop) |
| MI-H 2022 | "TOTALS" rows (Keweenaw, Mackinac), candidates split across spellings (MI-09 "BRIAN STEVEN JAYE" + "BRIAN JAYE" = the FEC's Jaye), MI-08 10.8% short | no |
| UT-H 2018 | candidates split across spellings (UT-04 "MIA B LOVE" + "MIA LOVE" = the FEC's Love) plus other differences (UT-03) | no |
| NJ-H, NJ-S 2018 | every county present, counts short (NJ-06, NJ-12 by 8–11%); cause not found | no |
| NY-H 2022 | districts 19 and 21 off by thousands in opposite directions; not investigated further | no |
| TX-H 2018, 2022; AR-H 2022 | small differences spread over many districts plus one larger (TX-18 −1.7%, TX-14 +2.3%, AR-01 −2%); not investigated further | no |

### Fixes made (`pipeline/expected/medsl_fixes.toml`)

Each one makes its office pass; the run prints how many rows each matched.

- **NJ-2022-1, NJ-2022-2** (House, 215 + 44 rows): drop the county and district "Totals" lines MEDSL stores as
  precincts (NJ was 3× the FEC); in Mercer keep "Mercer Totals" and drop the town rows, which lack votes the
  total has (NJ-03 Kim 31,845 by town vs 31,901). After both, every district equals the FEC exactly.
- **VT-2022-1** (House, 245 rows): Ericka Redic (LIB, on the ballot) is flagged as a write-in; flag cleared.
- **MI-2018-1** (House, 3,627 rows): three no-party candidates (Peruski, Nye, Niemuth) flagged as write-ins.
- **OR-2018-1, OR-2018-2** (House 7 rows, Governor 9): Tillamook's "TOTAL" precinct repeats the county. The
  Governor fix has no FEC figure behind it; it's made because the row equals the precinct sum line by line and
  OR Governor is eligible as a top race (OR had no 2018 Senate race).

Rules changed in the readers along the way (each with a test that failed first):
- NYC's ballot-count lines (PUBLIC COUNTER, ABSENTEE / MILITARY, AFFIDAVIT, FEDERAL, MANUALLY COUNTED
  EMERGENCY; the five NYC counties only, both years) are tallies, not candidates.
- A name with both named and write-in rows in a county gives two county rows (it used to turn the county's
  whole total into write-ins: VT 2018 Sanders).
- FEC party labels ending "/W" ("W(D)/W") are general-election write-ins ("primary/general" reading inferred
  from the labels; the FEC's legend not read).

Not checked against anything: GOVERNOR. A scan of every county where Governor is eligible found none whose
Governor votes exceed 1.28× its federal votes (the highest are GA 2018 counties with uncontested House races).

## Baselines

- 2018: 1,909 counties (Governor 853, Senate 532, House 524); 1,114 listed with no eligible office.
- 2022: 1,416 counties (Governor 814, House 347, Senate 255); 1,644 listed.

## Registration

2026 only: 715 counties in 9 states (AL CO IN LA NJ OH SC TX WV), from the step-3 database's turnout tables;
62 listed (`registration-2026-listed.csv`). None for 2018 or 2022, so no county uses "rate × registration":
every expectation is "raw" (the 2022 votes, range the 2018 and 2022 votes) or "one year" (low = high).

## 2026 dry run (`python3 -m pipeline.expected.run all 2026`, 2026-11-27)

Expected rows for 2,064 counties in 38 states (raw 1,261, one year 803); 1,198 listed with no baseline.
Scored 1,133 counties in 18 states; 558 not scored (554 with no expected row, 4 with no 2026 actual); 8
sources not scored at all (towns: CT MA RI VT; no county names: AK HI MN; NJ Bergen's two sources differ,
317,443 vs 317,126).

Overall: **202 of 1,133 inside the range (17.8%)**; median miss 4.9% of the point, 90th percentile 16.4%;
median |actual − point| 7.1%. By method: raw 202 of 661 inside (30.6%); one year 0 of 472 (its range has no
width). The `*_pct` columns in the score files are fractions (0.049 = 4.9%).

| State | Scored | Inside | Median miss | P90 miss | Median error |
|---|---|---|---|---|---|
| AL | 67 | 0.0% | 12.1% | 29.0% | 12.1% |
| AR | 75 | 0.0% | 9.8% | 21.0% | 9.8% |
| DE | 3 | 33.3% | 6.9% | 18.3% | 17.9% |
| GA | 159 | 20.8% | 3.3% | 8.6% | 3.9% |
| IA | 99 | 49.5% | 0.1% | 7.5% | 5.8% |
| ID | 44 | 0.0% | 11.1% | 27.3% | 11.1% |
| LA | 63 | 33.3% | 2.9% | 7.6% | 5.3% |
| MD | 24 | 37.5% | 1.5% | 7.7% | 7.9% |
| MT | 56 | 37.5% | 1.0% | 10.3% | 4.4% |
| ND | 53 | 17.0% | 7.1% | 12.5% | 7.2% |
| NE | 93 | 31.2% | 3.0% | 11.7% | 7.8% |
| NJ | 18 | 0.0% | 15.1% | 29.6% | 15.1% |
| NM | 33 | 0.0% | 5.1% | 11.9% | 5.1% |
| OH | 88 | 26.1% | 2.7% | 11.4% | 6.1% |
| OR | 36 | 0.0% | 6.1% | 15.3% | 6.1% |
| SD | 66 | 0.0% | 14.6% | 19.4% | 14.6% |
| VA | 133 | 0.0% | 8.2% | 19.5% | 8.2% |
| WY | 23 | 30.4% | 3.8% | 9.8% | 5.6% |
| ALL | 1133 | 17.8% | 4.9% | 16.4% | 7.1% |

The formula was fixed before scoring and isn't tuned to these numbers (spec anti-goal).

## Known limits

- Without 2018/2022 registration the expectation ignores population and registration change entirely.
- Two midterms make a narrow or skewed range (2018 turnout was unusually high); "one year" counties have none.
- 2026 is scored only where a state's offices passed in 2018 and/or 2022 and a reader gives county totals.
- Counties that change (CT's 2022 planning regions) don't join and are listed.

## Unverified

- Kind B causes (pre-certification counts are a guess).
- The FEC "/W" label reading.
- The 2018 GitHub copy against Harvard Dataverse (they differ; cause unknown).
