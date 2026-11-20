#!/opt/homebrew/bin/python3
"""Build scenarios/data/baseline_2024_states.csv from the FEC's official 2024 results.

    /opt/homebrew/bin/python3 -m scenarios.build_baseline [XLSX] [OUT_CSV]

Input: the FEC "Official 2024 Presidential General Election Results" workbook
(data/raw/fec-2024/2024presgeresults.xlsx; SHA-256 recorded in
evidence/fetch-fec-2024presgeresults.csv). Columns are found by header name.
r = TRUMP, d = HARRIS, other = TOTAL VOTES - r - d. ev_awarded_r/_d are the
FEC's own electoral-vote award columns, kept as the answer key for tests.

Has its own small xlsx reader on purpose: the scenario model does not import
the results pipeline (tools/).
"""
import csv
import sys
import xml.etree.ElementTree as ET
import zipfile

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DEFAULT_XLSX = "data/raw/fec-2024/2024presgeresults.xlsx"
DEFAULT_OUT = "scenarios/data/baseline_2024_states.csv"
FIELDS = ["state", "electoral_votes", "r", "d", "other", "total", "ev_awarded_r", "ev_awarded_d"]


def _read_sheet(path):
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
    return rows


def build_states_csv(xlsx_path, out_csv):
    rows = _read_sheet(xlsx_path)
    col = {v: k for k, v in rows[0].items()}

    def num(r, name):
        return int(r.get(col[name]) or 0)

    out = []
    for r in rows[1:]:
        st = r.get("A", "")
        if len(st) != 2 or not st.isalpha():
            continue
        trump, harris, total = num(r, "TRUMP"), num(r, "HARRIS"), num(r, "TOTAL VOTES")
        out.append({"state": st, "electoral_votes": num(r, "ELECTORAL VOTES"),
                    "r": trump, "d": harris, "other": total - trump - harris, "total": total,
                    "ev_awarded_r": num(r, "ELECTORAL VOTE: TRUMP (R)"),
                    "ev_awarded_d": num(r, "ELECTORAL VOTE: HARRIS (D)")})
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    return len(out)


if __name__ == "__main__":
    args = sys.argv[1:] + [None, None]
    n = build_states_csv(args[0] or DEFAULT_XLSX, args[1] or DEFAULT_OUT)
    print(f"wrote {n} rows")
