"""Parse Florida results: the Division of Elections' pipe-delimited files, with party from the
tab-delimited file.

Design: docs/superpowers/specs/2026-11-24-step2-fl-reader-design.md.

A pass record lists three files (UTF-8, one record per line):
- info: [r|FLDOS|seq|race name|election type|race id], [c|FLDOS|seq|race id|last|first|candidate
  id], [p|FLDOS|seq|race id|unit id|precincts], [u|FLDOS|seq|county name|unit id]. Unit ids are
  "12" + the county FIPS (12001 Alachua). Candidate ids are unique only within a race: every
  retention question and amendment uses 10 = Yes and 20 = No.
- votes: [V|FLDOS|seq|status (I incomplete, F finished)|race id|unit id|precincts reporting|
  candidate id|votes].
- tab: header ElectionDate, PartyCode, PartyName, RaceCode, RaceName, CountyCode, CountyName,
  Juris1num, Juris2num, Precincts, PrecinctsReporting, CanNameLast, CanNameFirst, CanNameMiddle,
  CanVotes; no ids. Its RaceName is the pipe race name, or for retention questions and
  amendments the part after the pipe name's first colon.

Rows: one per V record, level "county", county_id = the unit id (the 5-digit FIPS), choice = "first
last" as published (a Governor ticket reads "Donalds Avila"), contest_type and party from the tab
file where its row joins on (race name, county name, last, first), else empty. reporting_status =
"<reporting>/<precincts> precincts, status <letter>" ("?" when the p record is missing).
election_date from the tab file. There are no statewide rows in these files.

Nothing is corrected; the summary lists: V records with unknown race or unit ids or an unknown
(race, candidate) pair, duplicate (race, unit, candidate) records, non-integer votes or precinct
counts (votes ""), precincts reporting above the p count, missing p records, status letters other
than I/F (and counts of each), races with no votes, pipe-vs-tab vote differences (and V records
with no tab row), races whose name isn't in the tab file, candidates with more than one party,
malformed lines, and missing or unreadable files. Without the info or votes file there are no
rows and the checks are None; without the tab file the tab checks are None.
"""
import csv
import hashlib
import io
import json
import os
import re

from pipeline.schema import COLUMNS

FIELDS = {"r": 6, "c": 7, "p": 6, "u": 5, "V": 9}
TAB_CHECKS = ["pipe_vs_tab_differences", "races_not_in_tab", "candidates_with_several_parties"]
LISTS = ["unknown_races", "unknown_units", "unknown_choices", "duplicate_records", "non_numeric",
         "reporting_exceeds_precincts", "missing_precinct_counts", "unexpected_status", "races_without_votes",
         "malformed_records"] + TAB_CHECKS


def _int(v):
    return int(v) if re.fullmatch(r"\d+", v.strip()) else None


def _records(kind, text, summary):
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        f = s[1:-1].split("|") if s.startswith("[") and s.endswith("]") else None
        if f is None or FIELDS.get(f[0]) != len(f):
            summary["malformed_records"].append((kind, n, s[:60]))
            continue
        out.append(f)
    return out


def _read(paths, kind, summary):
    try:
        with open(paths[kind], "rb") as f:
            body = f.read()
        return hashlib.sha256(body).hexdigest(), body.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        summary["unreadable_files"].append((kind, str(e)))
        return None


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"races": 0, "choices": 0, "counties": 0, "records": 0, "status_counts": {}, "zero_precincts_reporting": 0}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in ("info", "votes", "tab") if k not in paths]
    got = {k: _read(paths, k, summary) for k in ("info", "votes", "tab") if k in paths}

    info = _records("info", got["info"][1], summary) if got.get("info") else None
    votes = _records("votes", got["votes"][1], summary) if got.get("votes") else None
    if got.get("votes") and not votes and got["votes"][1].strip():
        # Not a single valid record: an error page rather than a votes file.
        summary["unreadable_files"].append(("votes", "no valid V records"))
        votes = None
    if info is None or votes is None:
        for k in ["races", "choices", "counties", "records", "status_counts", "zero_precincts_reporting"] + LISTS:
            if k != "malformed_records":
                summary[k] = None
        return [], summary

    races = {f[5]: f[3] for f in info if f[0] == "r"}
    choices = {(f[3], f[6]): (f[4], f[5]) for f in info if f[0] == "c"}
    precincts = {(f[3], f[4]): f[5] for f in info if f[0] == "p"}
    units = {f[4]: f[3].strip() for f in info if f[0] == "u"}
    summary.update(races=len(races), choices=len(choices), counties=len(units))

    # Tab file: race code and party per joined row.
    tab_rows, race_code, election_date = None, {}, ""
    if got.get("tab"):
        reader = csv.DictReader(io.StringIO(got["tab"][1]), delimiter="\t")
        need = {"RaceName", "RaceCode", "CountyName", "CanNameLast", "CanNameFirst", "PartyCode", "CanVotes"}
        if not need <= set(reader.fieldnames or []):
            summary["unreadable_files"].append(("tab", f"header lacks {sorted(need - set(reader.fieldnames or []))}"))
        else:
            tab_rows = {}
            for t in reader:
                name = (t["RaceName"] or "").strip()
                race_code.setdefault(name, t["RaceCode"])
                election_date = election_date or (t.get("ElectionDate") or "")
                tab_rows[(name, (t["CountyName"] or "").strip(), (t["CanNameLast"] or "").strip(),
                          (t["CanNameFirst"] or "").strip())] = t

    def tab_name(race_id):
        """The tab file's name for a pipe race: the full name, or the part after its first colon."""
        n = races.get(race_id, "").strip()
        for cand in (n, n.split(":", 1)[1].strip() if ":" in n else None):
            if cand and cand in race_code:
                return cand
        return None

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], source_sha256=got["votes"][0], level="county",
                contest_scope="statewide", election_date=election_date, vote_type="TOTAL")
    rows, seen, voted, parties = [], set(), set(), {}
    for f in votes:
        if f[0] != "V":
            summary["malformed_records"].append(("votes", f[0], "|".join(f)[:60]))
            continue
        _, _, _, status, rid, uid, rep_raw, cid, votes_raw = f
        summary["records"] += 1
        summary["status_counts"][status] = summary["status_counts"].get(status, 0) + 1
        if status not in ("I", "F"):
            summary["unexpected_status"].append((rid, uid, cid, status))
        if rid not in races:
            summary["unknown_races"].append(rid)
        if uid not in units and uid not in summary["unknown_units"]:
            summary["unknown_units"].append(uid)
        if (rid, cid) not in choices and (rid, cid) not in summary["unknown_choices"]:
            summary["unknown_choices"].append((rid, cid))
        if (rid, uid, cid) in seen:
            summary["duplicate_records"].append((rid, uid, cid))
        seen.add((rid, uid, cid))
        voted.add(rid)
        n, rep = _int(votes_raw), _int(rep_raw)
        if n is None:
            summary["non_numeric"].append(("votes", rid, uid, cid, votes_raw))
        if rep is None:
            summary["non_numeric"].append(("precincts reporting", rid, uid, cid, rep_raw))
        total = _int(precincts[(rid, uid)]) if (rid, uid) in precincts else None
        if (rid, uid) not in precincts and (rid, uid) not in summary["missing_precinct_counts"]:
            summary["missing_precinct_counts"].append((rid, uid))
        if rep is not None and total is not None and rep > total:
            summary["reporting_exceeds_precincts"].append((rid, uid, cid, rep, total))
        if rep == 0:
            summary["zero_precincts_reporting"] += 1
        last, first = choices.get((rid, cid), ("", ""))
        tname = tab_name(rid) if tab_rows is not None else None
        t = tab_rows.get((tname, units.get(uid, ""), last.strip(), first.strip())) if tname else None
        if tab_rows is not None and tname is not None:
            if t is None:
                summary["pipe_vs_tab_differences"].append((rid, uid, cid, n, None))
            elif n is None or (t["CanVotes"] or "").strip() != str(n):
                summary["pipe_vs_tab_differences"].append((rid, uid, cid, n, t["CanVotes"]))
        party = (t["PartyCode"] or "") if t else ""
        if t:
            parties.setdefault((rid, cid), set()).add(party)
        rows.append(dict(base, county_id=uid, county_name=units.get(uid, ""), contest_id=rid,
                         contest_name=races.get(rid, ""), contest_type=race_code.get(tname, "") if tname else "",
                         choice_id=cid, choice=" ".join(x for x in (first.strip(), last.strip()) if x), party=party,
                         votes="" if n is None else n,
                         reporting_status=f"{rep_raw}/{precincts.get((rid, uid), '?')} precincts, status {status}"))
    summary["races_without_votes"] = sorted({r for r, _ in choices} - voted)
    if tab_rows is None:
        for k in TAB_CHECKS:
            summary[k] = None
    else:
        summary["races_not_in_tab"] = sorted(r for r in races if tab_name(r) is None)
        summary["candidates_with_several_parties"] = sorted((r, c, sorted(p)) for (r, c), p in parties.items() if len(p) > 1)
    return rows, summary
