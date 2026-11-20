#!/opt/homebrew/bin/python3
"""Sum MIT MEDSL precinct returns for one office up to county level.

    /opt/homebrew/bin/python3 tools/medsl_county.py ZIP_DIR OFFICE OUT_CSV
    e.g. ... data/raw/medsl-2024-precinct "US PRESIDENT" data/derived/president-2024-county.csv

Reads every *.zip in ZIP_DIR in place (nothing is extracted). Rules, all explicit:

- Rows are kept when `office` equals OFFICE exactly and `stage` is GEN.
- `votes == "*"` (suppressed for privacy in small CA/KS/NM/NV precincts) is not
  counted; the number of such rows is reported per county in `suppressed_rows`.
- Vote modes: within one (county, jurisdiction, precinct, candidate), if any row
  has mode TOTAL, only the TOTAL rows are used; otherwise every mode is summed.
  This avoids the double count MEDSL warns about when a state reports both.
- Rows whose candidate is a tally rather than a person (undervotes, overvotes,
  blank ballots, ballots cast, ...) are dropped; see NON_CANDIDATES.
- No other correction is made. Known MEDSL errors (e.g. a county total stored
  as a precinct) pass through unchanged; checks against official totals catch them.

Output: one row per (state, county_fips, county_name, candidate, party_simplified)
with votes and suppressed_rows. Standard library only.
"""
import collections
import csv
import glob
import io
import os
import sys
import zipfile

NON_CANDIDATES = {
    "UNDERVOTES", "UNDERVOTE", "UNDER VOTES", "UNDERVOTES-VOIDS",
    "OVERVOTES", "OVER VOTES",
    "BLANK BALLOTS", "BLANKS", "INVALID VOTES",
    "TOTAL VOTES CAST", "TOTAL BALLOTS CAST", "CONTEST TOTAL", "CAST VOTES",
}


def read_rows(zip_dir, office):
    for path in sorted(glob.glob(os.path.join(zip_dir, "*.zip"))):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with z.open(name) as f:
                    for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline="")):
                        if row["office"] == office and row["stage"] == "GEN":
                            yield row


def main(zip_dir, office, out_csv):
    by_precinct = collections.defaultdict(lambda: collections.defaultdict(int))
    suppressed = collections.Counter()
    dropped = collections.Counter()
    for r in read_rows(zip_dir, office):
        county = (r["state_po"], r["county_fips"], r["county_name"])
        if r["candidate"] in NON_CANDIDATES:
            dropped[r["candidate"]] += 1
            continue
        if r["votes"] == "*":
            suppressed[county] += 1
            continue
        key = county + (r["jurisdiction_fips"], r["precinct"], r["candidate"], r["party_simplified"])
        by_precinct[key][r["mode"]] += int(float(r["votes"]))

    county_votes = collections.Counter()
    for key, modes in by_precinct.items():
        votes = modes["TOTAL"] if "TOTAL" in modes else sum(modes.values())
        county_votes[key[:3] + key[5:]] += votes

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["state_po", "county_fips", "county_name", "candidate", "party_simplified",
                    "votes", "suppressed_rows"])
        for key in sorted(county_votes):
            w.writerow(list(key) + [county_votes[key], suppressed[key[:3]]])
    print(f"{len(county_votes)} county-candidate rows -> {out_csv}")
    print(f"dropped non-candidate rows: {dict(dropped)}")
    print(f"suppressed rows by state: {dict(collections.Counter(k[0] for k in suppressed.elements()))}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: medsl_county.py ZIP_DIR OFFICE OUT_CSV")
    main(*sys.argv[1:])
