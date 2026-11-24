"""Parse Ohio results: the Secretary of State's live NIST SP 1500-100 (IEEE 1622.2 V1) XML feed.

Design: docs/superpowers/specs/2026-11-24-step2-oh-reader-design.md.

A pass record lists one file, kind "xml": an ElectionReport in the namespace NS with
- GpUnitCollection: ReportingUnits whose Type attribute is County, State, Congressional,
  StateSenate, StateHouse or Judicial. Result counties ("Adams") carry SubUnitsReported /
  TotalSubUnits (precincts), VotersRegistered and SummaryCounts; a second set of County units
  ("Adams County") carries nothing and no count refers to them.
- PartyCollection (Abbreviation), OfficeCollection, and Election with Name, Date,
  CandidateCollection (BallotName, PartyId) and ContestCollection.
- Each Contest (CandidateContest or BallotMeasureContest) names its own unit in
  JurisdictionalScopeId (the State unit or a district). Each BallotSelection has one VoteCounts
  for that unit plus one per county in it; for a district that splits a county, the county count
  is the part inside the district. Ballot-measure selections have no text, only ObjectIds
  starting _YES / _NO.

Rows: one per (selection, VoteCounts). The own-unit count is level "state" (districts too, as in
the other readers; the contest identifies the district); a County unit's count is level
"county" with county_id = the GpUnit ObjectId. vote_type is "TOTAL" for Type="Total" counts;
any other Type is kept under its own name and left out of the sums. contest_scope is
"statewide" (every contest is in the state-level feed). choice is the candidates' ballot names
joined with " and " (tickets), or "Yes"/"No" for ballot measures; party is the first
candidate's party abbreviation as published.

The turnout table has one row per County unit that some count refers to (TURNOUT_COLUMNS).
The Absentee SummaryCounts BallotsCast value is kept under its own name: it exceeds the
county's total ballots everywhere and its meaning is unknown.

Nothing is corrected; the summary lists: county counts that don't sum to the own-unit count
(only when exactly one numeric own-unit count and all county counts are numeric), selections
with no own-unit count or more than one, counts for unknown GpUnits (level "") or for units
that are neither a county nor the contest's own unit (level ""), non-integer counts (votes ""),
unknown candidate ids (choice and party ""), candidates whose party id is unknown (party ""),
ballot-measure ids without a _YES/_NO prefix (choice ""), duplicate (contest, selection, unit,
type) counts, count types other than Total, counties whose absentee BallotsCast exceeds total
ballots, the number of County units no count refers to, contests sharing a name, write-in
selections, an ElectionReport root outside NS, and missing or unreadable files (a body that
isn't XML, or whose root isn't ElectionReport, e.g. an HTML page). When the file isn't read,
every check and count is None ("not checked").
"""
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET

from pipeline.schema import COLUMNS

NS = "http://grouper.ieee.org/groups/1622/groups/2/V1/1622_2-election_results_reporting.xsd"
E = "{%s}" % NS
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters",
                   "ballots_cast", "provisional_outstanding", "uocava_absentee_outstanding",
                   "absentee_ballots_cast_as_published", "precincts_reported", "precincts_total"]
CHECKS = ["contests", "selections", "counties", "bad_sums", "own_unit_count_missing", "own_unit_count_repeated",
          "unknown_gpunits", "counts_outside_contest", "non_numeric_votes", "unknown_candidates",
          "unknown_parties", "bad_measure_ids", "duplicate_counts", "unexpected_count_types",
          "absentee_exceeds_total", "unreferenced_county_units", "same_named_contests", "write_ins"]
COUNTS = {"contests", "selections", "counties", "unreferenced_county_units"}


def _int(v):
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v)
    return None


def _num(v):
    """An integer when the attribute is one, "" when absent, else the text as published."""
    if v is None:
        return ""
    n = _int(v)
    return v if n is None else n


def _text(el, path):
    return el.findtext(path) if el is not None else None


def _read(path, summary):
    """Return (sha256, root) or None when the file can't be used."""
    try:
        with open(path, "rb") as f:
            body = f.read()
    except OSError as e:
        summary["unreadable_files"].append(("xml", str(e)))
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        summary["unreadable_files"].append(("xml", f"not XML: {e}"))
        return None
    if root.tag != E + "ElectionReport":
        if root.tag.rpartition("}")[2] == "ElectionReport":
            summary["unexpected_namespace"].append(root.tag)
        else:
            summary["unreadable_files"].append(("xml", f"root element is {root.tag!r}, not ElectionReport"))
        return None
    return hashlib.sha256(body).hexdigest(), root


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {k: 0 if k in COUNTS else [] for k in CHECKS}
    summary.update(election_status="", unexpected_namespace=[], unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in ("xml",) if k not in paths]
    got = _read(paths["xml"], summary) if "xml" in paths else None
    if got is None:
        for k in CHECKS:
            summary[k] = None
        return [], summary, []
    sha, root = got
    summary["election_status"] = root.get("Status", "")

    gpunits = {g.get("ObjectId"): g for g in root.iter(E + "GpUnit")}
    parties = {p.get("ObjectId"): p.get("Abbreviation", "") for p in root.iter(E + "Party")}
    candidates = {}
    for c in root.iter(E + "Candidate"):
        pid = c.findtext(E + "PartyId")
        party = ""
        if pid is not None:
            if pid in parties:
                party = parties[pid]
            else:
                summary["unknown_parties"].append((c.get("ObjectId"), pid))
        candidates[c.get("ObjectId")] = (c.findtext(f"{E}BallotName/{E}LanguageString") or "", party)

    election = root.find(E + "Election")
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], source_sha256=sha,
                source_created_at=root.get("GeneratedDate", ""), contest_scope="statewide",
                election_name=_text(election, f"{E}Name/{E}LanguageString") or "",
                election_date=election.get("Date", "") if election is not None else "")

    rows, names, referenced = [], {}, set()
    contests = list(root.iter(E + "Contest"))
    for c in contests:
        cid, cname = c.get("ObjectId"), c.get("Name", "")
        names.setdefault(cname, []).append(cid)
        own = c.findtext(E + "JurisdictionalScopeId")
        ctype = next((k.get("Value", "") for k in c.findall(E + "Code") if k.get("OtherType") == "ContestType"), "")
        is_measure = c.get(XSI_TYPE) == "BallotMeasureContest"
        crow = dict(base, contest_id=cid, contest_name=cname, contest_type=ctype, vote_for=c.get("VotesAllowed", ""))
        for s in c.findall(E + "BallotSelection"):
            sid = s.get("ObjectId", "")
            summary["selections"] += 1
            if s.get("IsWriteIn") == "true":
                summary["write_ins"].append((cid, sid))
            choice, party = "", ""
            if is_measure:
                choice = "Yes" if sid.startswith("_YES") else "No" if sid.startswith("_NO") else ""
                if not choice:
                    summary["bad_measure_ids"].append((cid, sid))
            else:
                ids = [x.text for x in s.iter(E + "CandidateId")]
                unknown = [i for i in ids if i not in candidates]
                for i in unknown:
                    summary["unknown_candidates"].append((cid, sid, i))
                if ids and not unknown:
                    choice = " and ".join(candidates[i][0] for i in ids)
                    party = candidates[ids[0]][1]
            srow = dict(crow, choice=choice, choice_id=sid, party=party)
            own_counts, county_sum, sum_ok, seen = [], 0, True, set()
            for vc in s.iter(E + "VoteCounts"):
                gid, vtype, raw = vc.findtext(E + "GpUnitId"), vc.get("Type", ""), vc.get("Count")
                key = (gid, vtype)
                if key in seen:
                    summary["duplicate_counts"].append((cid, sid, gid))
                seen.add(key)
                total = vtype == "Total"
                if not total:
                    summary["unexpected_count_types"].append((cid, sid, gid, vtype))
                n = _int(raw)
                if n is None:
                    summary["non_numeric_votes"].append((cid, sid, gid, raw))
                row = dict(srow, vote_type="TOTAL" if total else vtype, votes="" if n is None else n)
                g = gpunits.get(gid)
                if gid == own:
                    row["level"] = "state"
                    if total:
                        own_counts.append(n)
                elif g is None:
                    summary["unknown_gpunits"].append((cid, sid, gid))
                    row["county_id"] = gid
                elif g.get("Type") == "County":
                    referenced.add(gid)
                    sub, tot = g.get("SubUnitsReported"), g.get("TotalSubUnits")
                    row.update(level="county", county_id=gid, county_name=g.get("Name", ""),
                               reporting_status=f"{sub}/{tot} precincts" if sub is not None and tot is not None else "")
                    if total:
                        if n is None:
                            sum_ok = False
                        else:
                            county_sum += n
                else:
                    summary["counts_outside_contest"].append((cid, sid, gid))
                    row.update(county_id=gid, county_name=g.get("Name", ""))
                rows.append(row)
            if not own_counts:
                summary["own_unit_count_missing"].append((cid, sid))
            elif len(own_counts) > 1:
                summary["own_unit_count_repeated"].append((cid, sid))
            elif sum_ok and own_counts[0] is not None and own_counts[0] != county_sum:
                summary["bad_sums"].append((cid, sid, own_counts[0], county_sum))

    turnout = []
    for gid, g in gpunits.items():
        if g.get("Type") != "County":
            continue
        if gid not in referenced:
            summary["unreferenced_county_units"] += 1
            continue
        sc = {}
        for x in g.findall(E + "SummaryCounts"):
            sc.setdefault(x.get("Type"), x)
        get = lambda t, a: _num(sc[t].get(a)) if t in sc else ""
        t = dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha, county_id=gid,
                 county_name=g.get("Name", ""), registered_voters=_num(g.get("VotersRegistered")),
                 ballots_cast=get("Total", "BallotsCast"),
                 provisional_outstanding=get("Provisional", "BallotsOutstanding"),
                 uocava_absentee_outstanding=get("Absentee", "BallotsOutstanding"),
                 absentee_ballots_cast_as_published=get("Absentee", "BallotsCast"),
                 precincts_reported=_num(g.get("SubUnitsReported")), precincts_total=_num(g.get("TotalSubUnits")))
        turnout.append(t)
        a, b = t["absentee_ballots_cast_as_published"], t["ballots_cast"]
        if isinstance(a, int) and isinstance(b, int) and a > b:
            summary["absentee_exceeds_total"].append((gid, t["county_name"], a, b))

    summary.update(contests=len(contests), counties=len(referenced),
                   same_named_contests=[(n, ids) for n, ids in names.items() if len(ids) > 1])
    return rows, summary, turnout
