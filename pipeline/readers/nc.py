"""Parse North Carolina results: the statewide precinct ZIP, checked against the dashboard.

Design: docs/superpowers/specs/2026-11-23-step2-nc-reader-design.md.

A pass record lists two files:
- zip: the State Board's precinct results ZIP. One tab-separated member (named in the pass
  record) with a header row, CRLF line endings, one line per (county, precinct, contest,
  choice): County, Election Date, Precinct, Contest Group ID, Contest Type (S statewide or
  district, C county), Contest Name, Choice, Choice Party, Vote For, then votes by method
  (Election Day, Early Voting, Absentee by Mail, Provisional), Total Votes, Real Precinct
  (N for administrative precincts: absentee, early-voting sites, transfers).
- dashboard: the results dashboard's statewide file, a JSON list with one object per
  (contest group gid, choice name bnm): contest name cnm, vote for vfr, party pty, total vct,
  and by method evc (Election Day), ovc (Early Voting), avc (Absentee by Mail), pvc
  (Provisional), precincts reporting prt of ptl. The method mapping is inferred from sums
  (the state does not document it).

Rows (contest type S only): precinct rows from the ZIP, one per method plus TOTAL (the
published Total Votes); state rows from the dashboard, the same five vote types. Neither
file has choice ids, so choice_id is empty and the check joins on (contest group id, choice
name as published). county_id is empty (the ZIP names counties, no codes). Dashboard rows
for contests the ZIP marks as type C are out of scope: skipped and counted.

Nothing is corrected; the summary lists: dashboard values that differ from the ZIP's
precinct sums (contest, choice, vote type, dashboard, ZIP sum), dashboard rows with no ZIP
match (still emitted), type-S ZIP contests and choices the dashboard lacks, ZIP rows whose
methods don't sum to Total, non-integer counts (row kept with votes "", left out of the
sums), lines with the wrong field count (skipped), a header that differs from the expected
one (read by column name when every expected column is present, else the ZIP is not read),
choice names with control characters (e.g. NUL; row kept), duplicate (county, precinct,
contest, choice) keys, a ZIP without the expected member, and missing or unreadable files.
A check that could not run (either file unusable) is None, not an empty list.
"""
import hashlib
import json
import os
import re
import zipfile

from pipeline.schema import COLUMNS

HEADER = ["County", "Election Date", "Precinct", "Contest Group ID", "Contest Type", "Contest Name", "Choice",
          "Choice Party", "Vote For", "Election Day", "Early Voting", "Absentee by Mail", "Provisional",
          "Total Votes", "Real Precinct"]
METHODS = ["Election Day", "Early Voting", "Absentee by Mail", "Provisional"]
VOTE_TYPES = METHODS + ["TOTAL"]
DASH_KEYS = {"Election Day": "evc", "Early Voting": "ovc", "Absentee by Mail": "avc", "Provisional": "pvc",
             "TOTAL": "vct"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v)
    return None


def _read_zip(path, member, summary):
    """Return (sha256, member timestamp, header, lines) or None when the ZIP can't be used."""
    with open(path, "rb") as f:
        body = f.read()
    sha = hashlib.sha256(body).hexdigest()
    try:
        with zipfile.ZipFile(path) as z:
            if member not in z.namelist():
                summary["missing_member"].append(member)
                return None
            info = z.getinfo(member)
            raw = z.read(info)
    except zipfile.BadZipFile as e:
        summary["unreadable_files"].append(("zip", str(e)))
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        summary["unreadable_files"].append(("zip", f"member is not UTF-8: {e}"))
        return None
    lines = text.split("\n")
    lines = [l[:-1] if l.endswith("\r") else l for l in lines]
    stamp = "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time
    return sha, stamp, lines[0].split("\t"), lines[1:]


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"contests": 0, "choices": 0, "counties": 0, "precincts": 0, "dashboard_rows": 0,
               "dashboard_rows_out_of_scope": 0, "zip_member_timestamp": "",
               "mismatches_dashboard_vs_zip": [], "dashboard_rows_without_zip_match": [],
               "zip_contests_missing_from_dashboard": [], "zip_choices_missing_from_dashboard": [],
               "bad_sums": [], "non_numeric_votes": [], "wrong_field_count": [], "unexpected_header": [],
               "control_characters": [], "duplicate_keys": [], "missing_member": [], "unreadable_files": [],
               "missing_files": []}
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in ("zip", "dashboard") if k not in paths]

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide")
    rows = []

    # Precinct rows from the ZIP.
    sums, zip_types, zip_choices, s_contests = {}, {}, set(), set()
    zip_ok = False
    election_date = ""
    z = None
    if "zip" in paths:
        try:
            z = _read_zip(paths["zip"], rec["member"], summary)
        except OSError as e:
            summary["unreadable_files"].append(("zip", str(e)))
    if z is not None:
        sha, stamp, header, lines = z
        summary["zip_member_timestamp"] = stamp
        if header != HEADER:
            summary["unexpected_header"] = header
        if set(HEADER) <= set(header):
            zip_ok = True
            col = {name: header.index(name) for name in HEADER}
            seen, counties, precincts = set(), set(), set()
            common = dict(base, level="precinct", source_sha256=sha, source_created_at=stamp)
            for n, l in enumerate(lines, start=2):
                if l == "":
                    continue
                f = l.split("\t")
                if len(f) != len(header):
                    summary["wrong_field_count"].append((n, len(f)))
                    continue
                v = {name: f[i] for name, i in col.items()}
                gid, ctype, choice = v["Contest Group ID"], v["Contest Type"], v["Choice"]
                zip_types.setdefault(gid, set()).add(ctype)
                if ctype != "S":
                    continue
                county, prec = v["County"], v["Precinct"]
                election_date = election_date or v["Election Date"]
                key = (county, prec, gid, choice)
                if key in seen:
                    summary["duplicate_keys"].append(key)
                seen.add(key)
                if _CONTROL.search(choice):
                    summary["control_characters"].append((county, prec, gid, choice))
                s_contests.add(gid)
                zip_choices.add((gid, choice))
                counties.add(county)
                precincts.add((county, prec))
                counts = {}
                for vt in VOTE_TYPES:
                    raw = v["Total Votes" if vt == "TOTAL" else vt]
                    counts[vt] = _int(raw)
                    if counts[vt] is None:
                        summary["non_numeric_votes"].append(("zip", county, prec, gid, choice, vt, raw))
                    else:
                        acc = sums.setdefault((gid, choice), dict.fromkeys(VOTE_TYPES, 0))
                        acc[vt] += counts[vt]
                m = [counts[vt] for vt in METHODS]
                if None not in m and counts["TOTAL"] is not None and sum(m) != counts["TOTAL"]:
                    summary["bad_sums"].append((county, prec, gid, choice, m, counts["TOTAL"]))
                row = dict(common, election_date=v["Election Date"], county_name=county, precinct_id=prec,
                           precinct_is_virtual="Y" if v["Real Precinct"] == "N" else "N", contest_id=gid,
                           contest_name=v["Contest Name"], contest_type=ctype, vote_for=v["Vote For"],
                           choice=choice, party=v["Choice Party"].strip())
                for vt in VOTE_TYPES:
                    rows.append(dict(row, vote_type=vt, votes="" if counts[vt] is None else counts[vt]))
            summary.update(contests=len(s_contests), choices=len(zip_choices), counties=len(counties),
                           precincts=len(precincts))

    # State rows from the dashboard.
    dash = None
    if "dashboard" in paths:
        try:
            with open(paths["dashboard"], "rb") as f:
                body = f.read()
            dash = json.loads(body.decode("utf-8-sig"))
            if not isinstance(dash, list) or not all(isinstance(x, dict) for x in dash):
                raise ValueError("not a JSON list of objects")
        except (OSError, ValueError) as e:
            summary["unreadable_files"].append(("dashboard", str(e)))
            dash = None
    if dash is not None:
        dsha = hashlib.sha256(body).hexdigest()
        common = dict(base, level="state", source_sha256=dsha, election_date=election_date)
        seen = set()
        for x in dash:
            gid, choice = str(x.get("gid", "")), str(x.get("bnm", ""))
            if zip_ok and zip_types.get(gid) and "S" not in zip_types[gid]:
                summary["dashboard_rows_out_of_scope"] += 1
                continue
            summary["dashboard_rows"] += 1
            seen.add((gid, choice))
            if zip_ok and (gid, choice) not in zip_choices:
                summary["dashboard_rows_without_zip_match"].append((gid, choice))
            row = dict(common, contest_id=gid, contest_name=x.get("cnm", ""), vote_for=str(x.get("vfr", "")),
                       choice=choice, party=str(x.get("pty", "")).strip(),
                       reporting_status=f"{x.get('prt', '')}/{x.get('ptl', '')} precincts")
            for vt in VOTE_TYPES:
                raw = x.get(DASH_KEYS[vt], "")
                n = _int(raw)
                if n is None:
                    summary["non_numeric_votes"].append(("dashboard", "", "", gid, choice, vt, raw))
                elif zip_ok and (gid, choice) in sums and sums[(gid, choice)][vt] != n:
                    summary["mismatches_dashboard_vs_zip"].append((gid, choice, vt, n, sums[(gid, choice)][vt]))
                rows.append(dict(row, vote_type=vt, votes="" if n is None else n))
        if zip_ok:
            dash_contests = {g for g, _ in seen}
            summary["zip_contests_missing_from_dashboard"] = sorted(s_contests - dash_contests)
            summary["zip_choices_missing_from_dashboard"] = sorted(
                (g, c) for g, c in zip_choices - seen if g in dash_contests)

    if not (zip_ok and dash is not None):
        for k in ("mismatches_dashboard_vs_zip", "dashboard_rows_without_zip_match",
                  "zip_contests_missing_from_dashboard", "zip_choices_missing_from_dashboard"):
            summary[k] = None
    return rows, summary
