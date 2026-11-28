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

## FEC check, first pass (2026-11-27)

Exact match per (state, office), after two reader fixes (FEC footnote markers `*`/`#` and non-breaking
spaces in names; MEDSL's blank at-large House district in 2022 AK and DC):

- 2022: 31 of 85 state-offices pass. 2018: 37 of 85 pass.

Failing offices by their worst contest (S = Senate, H = House):

| Kind | 2018 | 2022 |
|---|---|---|
| A. Named candidates equal; only write-in accounting differs (MEDSL counts more write-ins, lists write-ins or "ALL OTHERS" as candidates, or has extra zero-vote lines) | 19: AZ-H AZ-S CT-H GA-H IL-H NE-S OH-H OH-S VA-H WI-H WI-S MA-H MA-S ME-S MI-H MI-S MS-H NV-H VT-S | 9: DE-H IL-S WV-H CO-H CO-S NH-S WI-H IL-H VT-S |
| B. Candidate votes off by at most 1% (likely a pre-certification count; unverified) | 17: AL-H FL-H KY-H NC-H TX-H VT-H CT-S FL-S KS-H MO-H MO-S PA-S SD-H TX-S UT-S WA-H WA-S | 30: CA-H CT-H CT-S KS-S KY-H NC-H UT-H VT-H AR-S AZ-S FL-H FL-S KS-H KY-S ME-H MO-H MO-S NC-S NM-H NV-H NV-S OR-H OR-S PA-H PA-S SC-H SC-S UT-S VA-H WA-S |
| C. Off by more than 1% | 6: DC-H NJ-H NJ-S NY-S OR-H UT-H | 11: AR-H DC-H ID-H ID-S IN-S MI-H MS-H NJ-H NY-H NY-S TX-H |
| D. A whole contest missing on one side | 6: DC-S (MEDSL files DC's shadow senator as US SENATE), IN-H IN-S ME-H NY-H PA-H | 4: AZ-H WA-H (MEDSL rows with a blank district), CA-S, IN-H |

Not yet investigated contest by contest; the plan's stop condition (more than 10 unexplained) applies.
Per-contest differences are in `data/expected/check-<year>.csv`.
