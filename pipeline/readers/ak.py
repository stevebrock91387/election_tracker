"""Parse Alaska results: the Division of Elections' precinct-level CSV (first-choice results).

Design: docs/superpowers/specs/2026-11-24-step2-ak-reader-design.md.

The pass record lists one CSV: one line per (unit, contest, candidate) with Precinct_name, Pct_Id,
Reg_voters, Contest_Id, Contest_title, Selectable_Options, candidate_id, candidate_name, Party_Code,
total_ballots/votes/under_votes/over_votes, and the same four counts for each vote type (Election
Day, Absentee, Early Voting, Question, Remote). The header ends with a comma (an empty last field).
Units are real precincts ("01-600 Ketchikan No. 1") and district counting units ("District 1 -
Absentee", "… - Early Voting", "…  - Question", "HD99 Fed Overseas Absentee"); Early Voting and Question
units have no Pct_Id. Counts are first choices (round 1 of ranked-choice voting).

Rows: level "precinct", precinct_id = Pct_Id or, when empty, the unit name; precinct_is_virtual "Y"
for counting units; vote types TOTAL and the five source types; contest_type "first choice". No
state rows (the only statewide file is a PDF). The turnout table has one row per unit: registered
voters and the ballots on its U.S. Senator lines.

Nothing is corrected; the summary lists: lines whose vote types don't sum to the total (ballots,
votes, under, over), duplicate (unit, contest, candidate) lines, unit names with two Pct_Ids or two
Reg_voters and real precincts whose Pct_Id differs from the name's prefix, units whose ballots differ
between contests and units with no U.S. Senator line, non-integer counts (votes ""), malformed lines
(wrong field count), and a missing or unreadable file (including a changed header: nothing is read).
Informational: per contest, the statewide sum of ballots - votes - under - over over its units (the
file has no write-in lines; the gap is most likely write-ins, unverified).
"""
import csv
import hashlib
import io
import json
import os
import re

from pipeline.schema import COLUMNS

TYPES = ["Election Day", "Absentee", "Early Voting", "Question", "Remote"]
MEASURES = ["ballots", "votes", "under_votes", "over_votes"]
HEADER = (["Precinct_name", "Reporting_flag", "Pct_Id", "Pct_seq_nbr", "Reg_voters", "Aggregation_ID", "Contest_Id",
           "Contest_seq_nbr", "Contest_title", "Contest_party_name", "Selectable_Options", "Candidate_State_ID",
           "candidate_id", "candidate_name", "Candidate_Type", "cand_seq_nbr", "Party_Code"]
          + [f"total_{m}" for m in MEASURES] + [f"{t}_{m}" for t in TYPES for m in MEASURES] + [""])
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "precinct_id", "precinct_name", "registered_voters", "ballots"]
REAL = re.compile(r"(\d\d-\d{3}) ")
LISTS = ["vote_type_sum_mismatches", "duplicate_entries", "unit_id_conflicts", "units_ballots_vary_by_contest",
         "units_without_senate_line", "non_numeric", "malformed_lines"]


def _int(v):
    return int(v) if isinstance(v, str) and re.fullmatch(r"\d+", v.strip()) else None


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"lines": 0, "contests": 0, "units": 0, "real_precincts": 0, "reporting_flags": {},
               "writein_gap_by_contest": {}}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"])) for x in rec["files"]}
    summary["missing_files"] = [k for k in ("csv",) if k not in paths]
    lines = None
    if "csv" in paths:
        try:
            with open(paths["csv"], "rb") as f:
                body = f.read()
            lines = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
            if not lines or lines[0] != HEADER:
                raise ValueError("header differs from the expected one")
            sha = hashlib.sha256(body).hexdigest()
        except (OSError, ValueError, UnicodeDecodeError, csv.Error) as e:
            summary["unreadable_files"].append(("csv", str(e)))
            lines = None
    if lines is None:
        for k in LISTS + ["lines", "contests", "units", "real_precincts", "writein_gap_by_contest", "reporting_flags"]:
            summary[k] = None
        return [], summary, []

    col = {name: i for i, name in enumerate(HEADER) if name}
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], source_sha256=sha, level="precinct",
                contest_scope="statewide", contest_type="first choice")
    rows, seen = [], set()
    ids, regs, ballots_by_unit, senate_ballots, units_order = {}, {}, {}, {}, []
    per_unit_contest = {}  # (unit, contest) -> {"ballots", "under", "over", "votes"}
    for n, f in enumerate(lines[1:], start=2):
        if not f or f == [""]:
            continue
        if len(f) != len(HEADER):
            summary["malformed_lines"].append((n, len(f)))
            continue
        v = {name: f[i] for name, i in col.items()}
        summary["lines"] += 1
        name, pct, cid, cand = v["Precinct_name"], v["Pct_Id"], v["Contest_Id"], v["candidate_id"]
        summary["reporting_flags"][v["Reporting_flag"]] = summary["reporting_flags"].get(v["Reporting_flag"], 0) + 1
        if name not in ids:
            units_order.append(name)
        ids.setdefault(name, set()).add(pct)
        regs.setdefault(name, set()).add(v["Reg_voters"])
        key = (name, cid, cand)
        if key in seen:
            summary["duplicate_entries"].append(key)
            continue
        seen.add(key)
        counts = {}
        for field in [f"total_{m}" for m in MEASURES] + [f"{t}_{m}" for t in TYPES for m in MEASURES]:
            counts[field] = _int(v[field])
            if counts[field] is None:
                summary["non_numeric"].append((pct or name, cid, cand, field, v[field]))
        for m in MEASURES:
            parts = [counts[f"{t}_{m}"] for t in TYPES]
            if counts[f"total_{m}"] is not None and None not in parts and sum(parts) != counts[f"total_{m}"]:
                summary["vote_type_sum_mismatches"].append((pct or name, cid, cand, m.replace("_votes", "") if m != "votes" else "votes",
                                                            counts[f"total_{m}"], sum(parts)))
        b = counts["total_ballots"]
        ballots_by_unit.setdefault(name, set()).add(b)
        if v["Contest_title"] == "U.S. Senator" and b is not None:
            senate_ballots[name] = b
        uc = per_unit_contest.setdefault((name, cid), {"ballots": b, "under": counts["total_under_votes"],
                                                       "over": counts["total_over_votes"], "votes": 0})
        uc["votes"] = None if uc["votes"] is None or counts["total_votes"] is None else uc["votes"] + counts["total_votes"]
        row = dict(base, precinct_id=pct or name, precinct_name=name,
                   precinct_is_virtual="N" if REAL.match(name) else "Y", contest_id=cid,
                   contest_name=v["Contest_title"], vote_for=v["Selectable_Options"], choice_id=cand,
                   choice=v["candidate_name"], party=v["Party_Code"])
        for vt, field in [("TOTAL", "total_votes")] + [(t, f"{t}_votes") for t in TYPES]:
            rows.append(dict(row, vote_type=vt, votes="" if counts[field] is None else counts[field]))

    for name in units_order:
        m = REAL.match(name)
        if len(ids[name]) > 1 or len(regs[name]) > 1:
            summary["unit_id_conflicts"].append((name, sorted(ids[name]), sorted(regs[name])))
        elif m and next(iter(ids[name])) != m.group(1):
            summary["unit_id_conflicts"].append((name, sorted(ids[name]), sorted(regs[name])))
        vals = ballots_by_unit[name]
        if len(vals) > 1:
            summary["units_ballots_vary_by_contest"].append((name, sorted(x for x in vals if x is not None)))
        if name not in senate_ballots:
            summary["units_without_senate_line"].append(name)
    turnout = [dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha, precinct_id=next(iter(ids[n])) or n,
                    precinct_name=n, registered_voters=_int(next(iter(regs[n]))) if _int(next(iter(regs[n]))) is not None else next(iter(regs[n])),
                    ballots=senate_ballots.get(n, "")) for n in units_order]
    for (name, cid), uc in per_unit_contest.items():
        if None in uc.values():
            continue
        summary["writein_gap_by_contest"][cid] = summary["writein_gap_by_contest"].get(cid, 0) + (
            uc["ballots"] - uc["votes"] - uc["under"] - uc["over"])
    summary.update(contests=len({c for _, c in per_unit_contest}), units=len(units_order),
                   real_precincts=sum(1 for n in units_order if REAL.match(n)))
    return rows, summary, turnout
