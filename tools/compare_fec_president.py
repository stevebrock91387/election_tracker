#!/opt/homebrew/bin/python3
"""Compare county-summed presidential votes with the FEC's official state totals.

    /opt/homebrew/bin/python3 tools/compare_fec_president.py COUNTY_CSV FEC_XLSX OUT_CSV

COUNTY_CSV is the output of tools/medsl_county.py for "US PRESIDENT". FEC_XLSX is
the FEC's "Official 2024 Presidential General Election Results" workbook (state
totals compiled from state election offices). The xlsx is read with the standard
library (it is a zip of XML); no spreadsheet package is needed.

Compares Trump and Harris only, matched by name: the FEC sheet has one column per
candidate surname; MEDSL candidate strings are matched by CANDIDATES below.
Writes one row per state with both sources and the differences, and status
`match` (both differences zero) or `mismatch`.
"""
import collections
import csv
import sys
import xml.etree.ElementTree as ET
import zipfile

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
CANDIDATES = {"TRUMP": "DONALD J TRUMP", "HARRIS": "KAMALA D HARRIS"}


def read_fec(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(t.text or "" for t in si.iter(M + "t"))
                      for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iter(M + "row"):
        cells = {}
        for c in row:
            v = c.find(M + "v")
            x = v.text if v is not None else ""
            if c.get("t") == "s":
                x = shared[int(x)]
            cells["".join(ch for ch in c.get("r") if ch.isalpha())] = x
        rows.append(cells)
    header = {v: k for k, v in rows[0].items()}
    totals = {}
    for r in rows[1:]:
        st = r.get("A", "")
        if len(st) == 2 and st.isalpha():
            totals[st] = {name: int(r.get(header[name]) or 0) for name in CANDIDATES}
    return totals


def main(county_csv, fec_xlsx, out_csv):
    fec = read_fec(fec_xlsx)
    medsl = collections.defaultdict(collections.Counter)
    suppressed = collections.Counter()
    with open(county_csv, newline="") as f:
        seen = set()
        for r in csv.DictReader(f):
            for short, full in CANDIDATES.items():
                if r["candidate"] == full:
                    medsl[r["state_po"]][short] += int(r["votes"])
            county = (r["state_po"], r["county_fips"], r["county_name"])
            if county not in seen:
                seen.add(county)
                suppressed[r["state_po"]] += int(r["suppressed_rows"])
    fields = ["state", "fec_trump", "medsl_trump", "diff_trump",
              "fec_harris", "medsl_harris", "diff_harris", "suppressed_rows", "status"]
    matches = 0
    with open(out_csv, "w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        for st in sorted(fec):
            dt = medsl[st]["TRUMP"] - fec[st]["TRUMP"]
            dh = medsl[st]["HARRIS"] - fec[st]["HARRIS"]
            status = "match" if dt == dh == 0 else "mismatch"
            matches += status == "match"
            w.writerow({"state": st, "fec_trump": fec[st]["TRUMP"], "medsl_trump": medsl[st]["TRUMP"],
                        "diff_trump": dt, "fec_harris": fec[st]["HARRIS"],
                        "medsl_harris": medsl[st]["HARRIS"], "diff_harris": dh,
                        "suppressed_rows": suppressed[st], "status": status})
    print(f"{matches}/{len(fec)} states match the FEC exactly for both candidates -> {out_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: compare_fec_president.py COUNTY_CSV FEC_XLSX OUT_CSV")
    main(*sys.argv[1:])
