"""Parse Delaware results: the Department of Elections' ENR JSON files.

Design: docs/superpowers/specs/2026-11-24-step2-de-reader-design.md.

A pass record lists four JSON lists of flat objects:
- statewide: one line per (contest, candidate): Election Name/Date, Results Type, Total Precincts,
  Precincts Reported, Party Name, Contest Sorting Order, Contest Title, Candidate Id, Candidate Name,
  Machine Votes, Absentee Votes, Early Voting Votes, Total Votes ("140,838"), ReportTime.
- district: the same per Election District ("Election District 01-01"), without ids or precinct counts.
- county: per candidate, integer columns Wilmington, Rest of New Castle, New Castle, Sussex, Kent, State.
- turnout: per Representative District (and "ALL"): Ballots Cast, Reg Voters.
(Contest title, candidate name) is the join key between files; the statewide file supplies the ids.

Rows for contests whose title doesn't start with an excluded prefix (county offices): state rows from
the statewide file, precinct rows from the district file (four vote types each: TOTAL and the
source's Machine Votes, Absentee Votes, Early Voting Votes), and county rows (TOTAL) for New Castle
(10003), Kent (10001) and Sussex (10005) for contests that aren't legislative districts. contest_id =
Contest Sorting Order. Counts are parsed after removing thousands separators.

Nothing is corrected; the summary lists: district sums that differ from statewide values (per vote
type), lines in the statewide file with no district lines and the reverse, county State columns that
differ from statewide totals, county parts that don't add up (Wilmington + Rest = New Castle; New
Castle + Kent + Sussex = State), county lines missing from or extra to the statewide file, contests
whose number of districts with lines differs from Total Precincts, turnout ALL vs the district sums,
contest sorting orders shared by two titles and titles with two sorting orders, a contest whose
lines disagree on Total Precincts (its district-count check is then skipped), duplicate lines (in any
file; a repeated turnout district is skipped after the first), non-integer counts (votes ""),
malformed entries, and missing or unreadable files. Checks that need a file that wasn't read are None.
"""
import hashlib
import json
import os
import re

from pipeline.schema import COLUMNS

VOTES = [("TOTAL", "Total Votes"), ("Machine Votes", "Machine Votes"), ("Absentee Votes", "Absentee Votes"),
         ("Early Voting Votes", "Early Voting Votes")]
COUNTIES = [("New Castle", "10003"), ("Kent", "10001"), ("Sussex", "10005")]
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "representative_district", "ballots_cast", "registered_voters"]
DISTRICT_CHECKS = ["district_vs_state_mismatches", "state_lines_without_districts", "district_lines_without_state",
                   "district_count_mismatches"]
COUNTY_CHECKS = ["county_vs_state_mismatches", "county_lines_without_state", "state_lines_without_county"]
LISTS = DISTRICT_CHECKS + COUNTY_CHECKS + ["county_parts_mismatches", "turnout_total_mismatches", "shared_contest_orders",
                                           "duplicate_entries", "non_numeric", "malformed_entries",
                                           "precinct_total_conflicts", "contest_order_conflicts"]


def _num(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", v.strip()):
        return int(v.strip().replace(",", ""))
    return None


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    excluded = tuple(rec.get("exclude_title_prefixes") or [])
    districtish = tuple(rec.get("district_title_prefixes") or [])
    summary = {"contests": 0, "districts": 0, "results_type": ""}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in ("statewide", "district", "county", "turnout") if k not in paths]
    data, sha = {}, {}
    for k in ("statewide", "district", "county", "turnout"):
        if k not in paths:
            continue
        try:
            with open(paths[k], "rb") as f:
                body = f.read()
            obj = json.loads(body.decode("utf-8-sig"))
            if not isinstance(obj, list):
                raise ValueError("not a JSON list")
            items = []
            for x in obj:
                if isinstance(x, dict):
                    items.append(x)
                else:
                    summary["malformed_entries"].append((k, repr(x)[:40]))
            data[k], sha[k] = items, hashlib.sha256(body).hexdigest()
        except (OSError, ValueError, UnicodeDecodeError) as e:
            summary["unreadable_files"].append((k, str(e)))

    def in_scope(title):
        return isinstance(title, str) and not title.startswith(excluded)

    def count(raw, where):
        n = _num(raw)
        if n is None:
            summary["non_numeric"].append(where + (raw,))
        return n

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide")
    rows = []

    # Statewide lines: ids, contest numbers, election name and date.
    state, order_titles, precinct_totals, title_orders, totals_seen = {}, {}, {}, {}, {}
    if "statewide" in data:
        for x in data["statewide"]:
            title, name = x.get("Contest Title"), x.get("Candidate Name")
            if not isinstance(name, str) or not isinstance(title, str):
                summary["malformed_entries"].append(("statewide", title, name))
                continue
            order = str(x.get("Contest Sorting Order", ""))
            if order_titles.setdefault(order, title) != title and (order, title) not in summary["shared_contest_orders"]:
                summary["shared_contest_orders"].append((order, title))
            title_orders.setdefault(title, set()).add(order)
            if not in_scope(title):
                continue
            key = (title, name)
            if key in state:
                summary["duplicate_entries"].append(("statewide",) + key)
            state[key] = x
            tp = count(x.get("Total Precincts"), ("statewide", title, name, "Total Precincts"))
            totals_seen.setdefault(title, set()).add(tp)
            precinct_totals[title] = tp
            base.update(election_name=x.get("Election Name") or "", election_date=x.get("Election Date") or "")
            summary["results_type"] = x.get("Results Type") or ""
            row = dict(base, level="state", source_sha256=sha["statewide"], source_created_at=x.get("ReportTime") or "",
                       reporting_status=f"{x.get('Precincts Reported', '')}/{x.get('Total Precincts', '')} precincts, "
                                        f"{x.get('Results Type', '')}",
                       contest_id=order, contest_name=title, choice_id=str(x.get("Candidate Id", "")), choice=name,
                       party=x.get("Party Name") or "")
            for vt, field in VOTES:
                n = count(x.get(field), ("statewide", title, name, vt))
                rows.append(dict(row, vote_type=vt, votes="" if n is None else n))
        summary["contests"] = len({t for t, _ in state})
        summary["contest_order_conflicts"] = [(t, sorted(o)) for t, o in title_orders.items() if len(o) > 1]
        for t, vals in totals_seen.items():
            if len(vals) > 1:
                summary["precinct_total_conflicts"].append((t, sorted(vals, key=lambda v: -1 if v is None else v)))
                precinct_totals[t] = None
    else:
        summary["contest_order_conflicts"] = summary["precinct_total_conflicts"] = None

    def ids(title, name, x):
        s = state.get((title, name))
        return (str(s.get("Contest Sorting Order", "")) if s else str(x.get("Contest Sorting Order", "")),
                str(s.get("Candidate Id", "")) if s else "")

    # District lines.
    if "district" in data:
        sums, seen, districts_by_contest, lines = {}, set(), {}, set()
        for x in data["district"]:
            title, name, dist = x.get("Contest Title"), x.get("Candidate Name"), x.get("Election District")
            if not all(isinstance(v, str) for v in (title, name, dist)):
                summary["malformed_entries"].append(("district", title, name, dist))
                continue
            if not in_scope(title):
                continue
            code = dist.replace("Election District", "").strip()
            key = (dist, title, name)
            if key in seen:
                summary["duplicate_entries"].append(("district",) + key)
            seen.add(key)
            lines.add((title, name))
            districts_by_contest.setdefault(title, set()).add(dist)
            cid, chid = ids(title, name, x)
            row = dict(base, level="precinct", source_sha256=sha["district"], precinct_id=code, precinct_name=dist,
                       contest_id=cid, contest_name=title, choice_id=chid, choice=name, party=x.get("Party Name") or "")
            for vt, field in VOTES:
                n = count(x.get(field), ("district", dist, title, name, vt))
                if n is not None:
                    sums[(title, name, vt)] = sums.get((title, name, vt), 0) + n
                rows.append(dict(row, vote_type=vt, votes="" if n is None else n))
        summary["districts"] = len({k[0] for k in seen})
        if "statewide" in data:
            for (title, name), x in state.items():
                if (title, name) not in lines:
                    summary["state_lines_without_districts"].append((title, name))
                    continue
                for vt, field in VOTES:
                    n = _num(x.get(field))
                    if n is not None and sums.get((title, name, vt), 0) != n:
                        summary["district_vs_state_mismatches"].append((title, name, vt, n, sums.get((title, name, vt), 0)))
            summary["district_lines_without_state"] = sorted(lines - set(state))
            for title, total in precinct_totals.items():
                got = len(districts_by_contest.get(title, ()))
                if total is not None and got != total:
                    order = next(str(x.get("Contest Sorting Order", "")) for (t, _), x in state.items() if t == title)
                    summary["district_count_mismatches"].append((order, title, total, got))
    if "district" not in data or "statewide" not in data:
        for k in DISTRICT_CHECKS:
            summary[k] = None

    # County lines.
    if "county" in data:
        county_lines = set()
        county_seen = set()
        for x in data["county"]:
            title, name = x.get("Contest Title"), x.get("Candidate Name")
            if not isinstance(title, str) or not isinstance(name, str):
                summary["malformed_entries"].append(("county", title, name))
                continue
            if not in_scope(title):
                continue
            if (title, name) in county_seen:
                summary["duplicate_entries"].append(("county", title, name))
            county_seen.add((title, name))
            county_lines.add((title, name))
            vals = {k: count(x.get(k), ("county", title, name, k)) for k in
                    ("Wilmington", "Rest of New Castle", "New Castle", "Kent", "Sussex", "State")}
            if None not in vals.values():
                if vals["Wilmington"] + vals["Rest of New Castle"] != vals["New Castle"] or \
                        vals["New Castle"] + vals["Kent"] + vals["Sussex"] != vals["State"]:
                    summary["county_parts_mismatches"].append((title, name))
            s = state.get((title, name))
            if s is not None and vals["State"] is not None and _num(s.get("Total Votes")) != vals["State"]:
                summary["county_vs_state_mismatches"].append((title, name, _num(s.get("Total Votes")), vals["State"]))
            if title.startswith(districtish):
                continue
            cid, chid = ids(title, name, x)
            for cname, fips in COUNTIES:
                n = vals[cname]
                rows.append(dict(base, level="county", source_sha256=sha["county"], county_id=fips, county_name=cname,
                                 contest_id=cid, contest_name=title, choice_id=chid, choice=name,
                                 party=x.get("Party Name") or "", vote_type="TOTAL", votes="" if n is None else n))
        if "statewide" in data:
            summary["county_lines_without_state"] = sorted(county_lines - set(state))
            summary["state_lines_without_county"] = sorted(set(state) - county_lines)
    if "county" not in data or "statewide" not in data:
        for k in COUNTY_CHECKS:
            summary[k] = None
    if "county" not in data:
        summary["county_parts_mismatches"] = None

    # Turnout.
    turnout = []
    if "turnout" in data:
        all_row, sums, seen_rd = None, {"Ballots Cast": 0, "Reg Voters": 0}, set()
        for x in data["turnout"]:
            rd = x.get("Representative District")
            if not isinstance(rd, str) or not rd:
                summary["malformed_entries"].append(("turnout", rd))
                continue
            if rd in seen_rd:
                summary["duplicate_entries"].append(("turnout", rd))
                continue
            seen_rd.add(rd)
            if rd == "ALL":
                all_row = x
                continue
            b, r = count(x.get("Ballots Cast"), ("turnout", rd, "Ballots Cast")), count(x.get("Reg Voters"), ("turnout", rd, "Reg Voters"))
            turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha["turnout"],
                                representative_district=rd if isinstance(rd, str) else "",
                                ballots_cast="" if b is None else b, registered_voters="" if r is None else r))
            for k, v in (("Ballots Cast", b), ("Reg Voters", r)):
                sums[k] = sums[k] + v if v is not None and sums[k] is not None else None
        if all_row is None:
            summary["turnout_total_mismatches"].append(("ALL row absent", None, None))
        else:
            for k in sums:
                n = _num(all_row.get(k))
                if n is None or sums[k] is None or n != sums[k]:
                    summary["turnout_total_mismatches"].append((k, all_row.get(k), sums[k]))
    else:
        summary["turnout_total_mismatches"] = None
    return rows, summary, turnout
