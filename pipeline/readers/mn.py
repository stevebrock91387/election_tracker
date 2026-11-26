"""Parse Minnesota results: the Secretary of State's all-races-by-county text file.

Source: electionresultsfiles.sos.mn.gov/<YYYYMMDD>/allracesbycounty.txt (docs/mn.md). ISO-8859-1, CRLF,
no header, 16 semicolon-separated fields per line, one line per (county, office, candidate). The field
meanings below are read from the data, not from a published spec (the page that lists the files sits
behind a bot check; docs/blocked-states.md): unverified.

    0 state ("MN")  1 county id ("01".."87"; not FIPS, no names in the file)  2 precinct (empty here)
    3 office id  4 office name  5 district  6 candidate id (per office)  7 candidate name  8, 9 (empty
    in 2026)  10 party  11 precincts reporting  12 precincts in the office's part of the county
    13 votes  14 percent  15 office total in the county

Rows: level "county", contest_id = office id (unique per contest for the offices in scope),
contest_scope "statewide" (offices that span counties, district races included; the schema's meaning),
vote_type TOTAL, reporting_status "<reporting>/<total>". Write-ins ("WRITE-IN", id 9901) and an
amendment's "ESTIMATED BLANKS" are ordinary choices, as published. No state rows: the file has none.

Scope: offices whose id falls in one of the configured inclusive ranges (string comparison of the
4-digit ids); the others are listed by id and name, not read.

Nothing is corrected; the summary lists: (county, office) pairs whose votes don't sum to the office total,
pairs whose lines disagree on precincts reporting, lines reporting more precincts than the total,
duplicate (county, office, candidate) lines (the first is kept), non-integer counts (votes ""),
malformed lines (field count, or a state other than MN), and a missing or unreadable file (nothing read).
"""
import hashlib
import json
import os
import re

from pipeline.schema import COLUMNS

N_FIELDS = 16
LISTS = ["office_total_mismatches", "reporting_varies", "reporting_over_total", "duplicate_entries", "non_numeric",
         "malformed_lines", "out_of_scope_offices"]
COUNTS = ["lines", "rows", "counties", "contests"]


def _int(v):
    return int(v) if re.fullmatch(r"\d+", v.strip()) else None


def in_scope(office_id, ranges):
    return any(lo <= office_id <= hi for lo, hi in ranges)


def parse_pass(record_path, office_ranges, base_dir="."):
    """(rows, summary) for one pass record listing the text file (kind "txt")."""
    with open(record_path) as f:
        rec = json.load(f)
    summary = {k: [] for k in LISTS}
    summary.update({k: 0 for k in COUNTS}, unreadable_files=[], missing_files=[])
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"]))
             for x in rec["files"]}
    text = None
    if "txt" not in paths:
        summary["missing_files"] = ["txt"]
    else:
        try:
            with open(paths["txt"], "rb") as f:
                body = f.read()
            text = body.decode("latin-1")
            if not text.strip():
                raise ValueError("no data lines")
            sha = hashlib.sha256(body).hexdigest()
        except (OSError, ValueError) as e:
            summary["unreadable_files"].append(("txt", str(e)))
            text = None
    if text is None:
        for k in LISTS + COUNTS:
            summary[k] = None
        return [], summary

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], source_sha256=sha, level="county",
                contest_scope="statewide", vote_type="TOTAL")
    rows, seen, out_of_scope = [], set(), {}
    pairs = {}  # (county, office) -> {"sum": int or None, "total": set, "reporting": set}
    for n, line in enumerate(text.split("\n"), start=1):
        line = line.rstrip("\r")
        if not line:
            continue
        f = line.split(";")
        if len(f) != N_FIELDS:
            summary["malformed_lines"].append((n, len(f)))
            continue
        if f[0] != rec["state"]:
            summary["malformed_lines"].append((n, f"state {f[0]}"))
            continue
        summary["lines"] += 1
        county, office, cand = f[1], f[3], f[6]
        if not in_scope(office, office_ranges):
            out_of_scope.setdefault(office, f[4])
            continue
        key = (county, office, cand)
        if key in seen:
            summary["duplicate_entries"].append(key)
            continue
        seen.add(key)
        rep, tot, votes, total = _int(f[11]), _int(f[12]), _int(f[13]), _int(f[15])
        for name, raw_v, v in (("precincts_reporting", f[11], rep), ("precincts_total", f[12], tot),
                               ("votes", f[13], votes), ("office_total", f[15], total)):
            if v is None:
                summary["non_numeric"].append((county, office, cand, name, raw_v))
        if rep is not None and tot is not None and rep > tot:
            summary["reporting_over_total"].append((county, office, cand, rep, tot))
        p = pairs.setdefault((county, office), {"sum": 0, "total": set(), "reporting": set()})
        p["sum"] = None if p["sum"] is None or votes is None else p["sum"] + votes
        p["total"].add(total)
        p["reporting"].add(f"{f[11]}/{f[12]}")
        rows.append(dict(base, county_id=county, contest_id=office, contest_name=f[4], choice_id=cand,
                         choice=f[7], party=f[10], votes="" if votes is None else votes,
                         reporting_status=f"{f[11]}/{f[12]}"))
    for (county, office), p in pairs.items():
        if len(p["reporting"]) > 1:
            summary["reporting_varies"].append((county, office, sorted(p["reporting"])))
        (total,) = p["total"] if len(p["total"]) == 1 else (None,)
        if len(p["total"]) > 1:
            summary["office_total_mismatches"].append((county, office, p["sum"], sorted(p["total"], key=str)))
        elif p["sum"] is not None and total is not None and p["sum"] != total:
            summary["office_total_mismatches"].append((county, office, p["sum"], total))
    summary.update(rows=len(rows), counties=len({c for c, _ in pairs}), contests=len({o for _, o in pairs}),
                   out_of_scope_offices=sorted(out_of_scope.items()))
    return rows, summary
