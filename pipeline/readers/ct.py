"""Parse Connecticut results: the CT EMS public-reporting static JSON, by town.

Design: docs/superpowers/specs/2026-11-24-step2-ct-reader-design.md.

A pass record lists eight files (kinds) from one data version:
- lookup (Lookupdata.json): election {DT, DNM, ...}, townIds {id: name}, counties {id: name},
  countyTowns [{TownID, CountyID}], officeList [{id: {NM, OT, ...}}], partyIds {id: {CD, NM}},
  candidateIds {id: {NM, P (party id), AD (home address), ...}}.
- state (stateVotes): {office id: [{candidate id: {V, TO}}]}; town (townVotes): {town id: {office
  id: [same]}}. Each party line is its own candidate id (a cross-endorsed candidate has several).
- townstatus {town id: {TS, PR}}; officeprecincts {office id: "673 of 774 (86.95%)"};
  grouping (candidateGrouping) {office id: [{candidate id: {V}}]}: combined totals per person;
  turnout (voterTurnout) {town id: {NM, PR, EV, VV, ABR, ABC, EBR, EBC, EDR, EDC, TO}} plus a
  "Total" entry.

Rows (offices whose OT is in the record's office_types): state rows from stateVotes, town rows
(level "town"; town id and name in county_id / county_name) from townVotes; one row per party
line, vote_type TOTAL. party is the line's party CD ("" when the party id is unknown).
reporting_status: townStatus PR on town rows, officePrecincts on state rows, as published.
election_name / election_date from the lookup; source_created_at is empty (the feed has no
timestamp; the version number is in the summary). Candidate addresses (AD) are never copied.

The turnout table has one row per town (TURNOUT_COLUMNS): EV as registered_voters (it sums to the
election's registered total), VV as ballots, the other codes as published.

Nothing is corrected; the summary lists: town sums that differ from the state value, lines in one
file and not the other, grouping totals that differ from the sum of the office's same-named lines,
same-named multi-line choices with no grouping entry (and grouping entries matching no line), the
turnout Total entry vs the town sums, non-integer counts (votes ""), unknown town, office,
candidate and party ids, office types outside SW C S A PD SM (skipped), in-scope offices with no
state entry, duplicate (office, line) entries, and missing or unreadable files. Without the lookup
nothing can be scoped or named: no rows, and every check is None. Other checks that need a file
that wasn't read are None.
"""
import hashlib
import json
import os
import re

from pipeline.schema import COLUMNS

KNOWN_OFFICE_TYPES = {"SW", "C", "S", "A", "PD", "SM"}
TURNOUT_FIELDS = ("EV", "VV", "ABR", "ABC", "EBR", "EBC", "EDR", "EDC")
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "county", "registered_voters",
                   "ballots", "abr", "abc", "ebr", "ebc", "edr", "edc", "precincts_reporting"]
LISTS = ["mismatches_state_vs_town", "state_lines_missing_from_towns", "town_lines_missing_from_state",
         "grouping_mismatches", "multi_line_names_without_grouping", "grouping_without_lines", "multi_line_names",
         "unknown_parties", "unknown_towns", "unknown_offices", "unknown_candidates", "unknown_office_types",
         "in_scope_offices_without_state_entry", "non_numeric_votes", "duplicate_lines", "turnout_total_mismatches"]
KINDS = ("version", "lookup", "state", "town", "townstatus", "turnout", "grouping", "officeprecincts")


def _int(v):
    return int(v) if isinstance(v, str) and re.fullmatch(r"\d+", v) else None


def _num(v):
    n = _int(v)
    return "" if v is None else (v if n is None else n)


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"version": rec.get("version", ""), "contests": 0, "choices": 0, "towns": 0,
               "office_precincts_below_100": 0}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in KINDS if k not in paths]
    data, sha = {}, {}
    for k in KINDS:
        if k not in paths:
            continue
        try:
            with open(paths[k], "rb") as f:
                body = f.read()
            obj = json.loads(body.decode("utf-8-sig"))
            if not isinstance(obj, dict):
                raise ValueError("not a JSON object")
            data[k], sha[k] = obj, hashlib.sha256(body).hexdigest()
        except (OSError, ValueError) as e:
            summary["unreadable_files"].append((k, str(e)))

    def not_checked(*keys):
        for key in keys:
            summary[key] = None

    if "lookup" not in data:
        not_checked("contests", "choices", "towns", "office_precincts_below_100", *LISTS)
        return [], summary, []

    lk = data["lookup"]
    scope = set(rec.get("office_types") or [])
    offices = {}
    for o in lk.get("officeList") or []:
        for oid, v in o.items():
            offices[oid] = v
    in_scope = set()
    for oid, v in offices.items():
        ot = v.get("OT", "")
        if ot not in KNOWN_OFFICE_TYPES:
            summary["unknown_office_types"].append((oid, ot))
        elif ot in scope:
            in_scope.add(oid)
    cands = lk.get("candidateIds") or {}
    parties = {pid: (p or {}).get("CD", "") for pid, p in (lk.get("partyIds") or {}).items()}
    towns = lk.get("townIds") or {}
    counties = lk.get("counties") or {}
    county_of = {str(ct.get("TownID")): counties.get(str(ct.get("CountyID")), "") for ct in lk.get("countyTowns") or []}
    election = lk.get("election") or {}
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide",
                election_name=election.get("DNM", ""), election_date=election.get("DT", ""))
    op = data.get("officeprecincts", {})
    ts = data.get("townstatus", {})
    rows, seen_unknown = [], set()

    def choice_of(oid, cid):
        c = cands.get(cid)
        if c is None:
            if ("cand", oid, cid) not in seen_unknown:
                seen_unknown.add(("cand", oid, cid))
                summary["unknown_candidates"].append((oid, cid))
            return "", ""
        pid = c.get("P", "")
        if pid not in parties and ("party", cid) not in seen_unknown:
            seen_unknown.add(("party", cid))
            summary["unknown_parties"].append((cid, pid))
        return c.get("NM", ""), parties.get(pid, "")

    def emit(level, unit, oid, lst, row, seen, sums=None):
        for e in lst or []:
            for cid, v in (e or {}).items():
                if (unit, oid, cid) in seen:
                    summary["duplicate_lines"].append((level, unit, oid, cid))
                seen.add((unit, oid, cid))
                raw = (v or {}).get("V")
                n = _int(raw)
                if n is None:
                    summary["non_numeric_votes"].append((level, unit, oid, cid, raw))
                elif sums is not None:
                    sums[(oid, cid)] = sums.get((oid, cid), 0) + n
                name, party = choice_of(oid, cid)
                rows.append(dict(row, choice_id=cid, choice=name, party=party, vote_type="TOTAL",
                                 votes="" if n is None else n))

    def office_row(oid):
        o = offices[oid]
        return dict(base, contest_id=oid, contest_name=o.get("NM", ""), contest_type=o.get("OT", ""))

    def usable(oid):
        if oid not in offices:
            if ("office", oid) not in seen_unknown:
                seen_unknown.add(("office", oid))
                summary["unknown_offices"].append(oid)
            return False
        return oid in in_scope

    # State rows.
    state_lines = {}
    if "state" in data:
        seen = set()
        for oid, lst in data["state"].items():
            if not usable(oid):
                continue
            summary["contests"] += 1
            emit("state", "", oid, lst, dict(office_row(oid), level="state", source_sha256=sha["state"],
                                              reporting_status=op.get(oid, "")), seen)
            for e in lst or []:
                for cid, v in (e or {}).items():
                    state_lines[(oid, cid)] = _int((v or {}).get("V"))
        summary["choices"] = len(state_lines)
        summary["in_scope_offices_without_state_entry"] = sorted(in_scope - set(data["state"]))
        names = {}
        for (oid, cid) in state_lines:
            names.setdefault((oid, choice_of(oid, cid)[0]), []).append(cid)
        summary["multi_line_names"] = [(o, n, ids) for (o, n), ids in names.items() if len(ids) > 1]
    else:
        not_checked("contests", "choices", "in_scope_offices_without_state_entry", "multi_line_names")
    summary["office_precincts_below_100"] = (sum(1 for oid in in_scope if oid in op and "(100" not in op[oid])
                                             if "officeprecincts" in data else None)

    # Town rows.
    town_sums = {}
    if "town" in data:
        seen = set()
        for tid, offs in data["town"].items():
            if tid not in towns:
                summary["unknown_towns"].append(tid)
            row = dict(base, level="town", source_sha256=sha["town"], county_id=tid, county_name=towns.get(tid, ""),
                       reporting_status=(ts.get(tid) or {}).get("PR", ""))
            for oid, lst in (offs or {}).items():
                if usable(oid):
                    emit("town", tid, oid, lst, dict(row, contest_id=oid, contest_name=offices[oid].get("NM", ""),
                                                      contest_type=offices[oid].get("OT", "")), seen, town_sums)
        summary["towns"] = len(data["town"])
    else:
        not_checked("towns", "unknown_towns")

    # State vs towns.
    if "state" in data and "town" in data:
        town_lines = {k for k in town_sums}
        for (oid, cid), n in state_lines.items():
            if (oid, cid) not in town_sums:
                summary["state_lines_missing_from_towns"].append((oid, cid))
            elif n is not None and town_sums[(oid, cid)] != n:
                summary["mismatches_state_vs_town"].append((oid, cid, n, town_sums[(oid, cid)]))
        town_lines |= {(oid, cid) for tid, offs in data["town"].items() for oid, lst in (offs or {}).items()
                       if oid in in_scope for e in lst or [] for cid in (e or {})}
        summary["town_lines_missing_from_state"] = sorted(town_lines - set(state_lines))
    else:
        not_checked("mismatches_state_vs_town", "state_lines_missing_from_towns", "town_lines_missing_from_state")

    # Grouping (combined party lines) vs the state lines.
    if "grouping" in data and "state" in data:
        grouped = set()
        for oid, lst in data["grouping"].items():
            if oid not in in_scope:
                continue
            for e in lst or []:
                for cid, v in (e or {}).items():
                    name = (cands.get(cid) or {}).get("NM")
                    lines = [c for (o, c) in state_lines if o == oid and (cands.get(c) or {}).get("NM") == name]
                    if name is None or not lines:
                        summary["grouping_without_lines"].append((oid, cid))
                        continue
                    grouped.add((oid, name))
                    g, s = _int((v or {}).get("V")), [state_lines[(oid, c)] for c in lines]
                    if g is not None and None not in s and g != sum(s):
                        summary["grouping_mismatches"].append((oid, name, g, sum(s)))
        summary["multi_line_names_without_grouping"] = [(o, n) for o, n, _ in summary["multi_line_names"]
                                                        if (o, n) not in grouped]
    else:
        not_checked("grouping_mismatches", "grouping_without_lines", "multi_line_names_without_grouping")

    # Turnout table.
    turnout = []
    if "turnout" in data:
        total, sums = None, dict.fromkeys(TURNOUT_FIELDS, 0)
        for tid, v in data["turnout"].items():
            v = v or {}
            if v.get("NM") == "Total":
                total = v
                continue
            t = dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha["turnout"], county_id=tid,
                     county_name=v.get("NM", ""), county=county_of.get(tid, ""), registered_voters=_num(v.get("EV")),
                     ballots=_num(v.get("VV")), precincts_reporting=v.get("PR", ""))
            for f in TURNOUT_FIELDS[2:]:
                t[f.lower()] = _num(v.get(f))
            turnout.append({c: t[c] for c in TURNOUT_COLUMNS})
            for f in TURNOUT_FIELDS:
                n = _int(v.get(f))
                sums[f] = sums[f] + n if n is not None and sums[f] is not None else None
        if total is None:
            summary["turnout_total_mismatches"].append(("Total entry absent", None, None))
        else:
            for f in TURNOUT_FIELDS:
                n = _int(total.get(f))
                if n is None or sums[f] is None or n != sums[f]:
                    summary["turnout_total_mismatches"].append((f, total.get(f), sums[f]))
    else:
        not_checked("turnout_total_mismatches")
    return rows, summary, turnout
