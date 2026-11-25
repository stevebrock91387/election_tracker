"""Parse Clarity (Scytl) statewide results into common-format rows, county level.

Design: docs/superpowers/specs/2026-11-20-step2-clarity-reader-design.md.

parse_xml reads reports/detailxml.zip (CO, SC, WV):
- State rows: TOTAL (the choice's totalVotes) plus one row per VoteType as published.
- County rows: one per (VoteType, County) as published. No county TOTAL row is
  made up, since none is published (CO's only type is "Total Votes", WV's is
  "Election Day").
- County reporting_status: "<reported>/<participating> precincts" from the
  contest's ParticipatingCounties entry for that county, else "".
- Turnout: one row per county from ElectionVoterTurnout (registered voters,
  ballots cast, precincts), returned separately (TURNOUT_COLUMNS).

contest_scope is "statewide" for every contest: the contest key is unique across
a statewide file, even for local contests the file carries. county_id is empty
(Clarity gives county names only). contest_type is "question" when
isQuestion="true", else "".

parse_json reads json/sum.json + json/ALL.json (Iowa, which publishes no XML):
- State rows from sum.json (TOTAL), county rows from ALL.json (TOTAL; the
  values are totals, no vote types). An ALL.json area's votes for a contest are
  in sum.json's choice order; that position gives choice, choice_id (CHAggId)
  and party. State rows carry sum.json's hash, county rows ALL.json's.
- The area named "-1" is the statewide total, not a county: it is compared with
  sum.json and not emitted.
- A sum.json contest whose CH/CHAggId/P/V lengths disagree is skipped and
  listed (no rows anywhere for it). A county whose vote array length differs
  from sum.json's for a contest is skipped and listed; an area whose C and V
  lengths differ is skipped whole and listed; contests in ALL.json missing from
  sum.json are listed.
- The "-1" check reports how many contests it compared and which sum.json
  contests had no "-1" entry, so "0 mismatches" can't mean "never checked".
- election_name, source_created_at and election_date are empty (not in these files).

Nothing is corrected. The XML summary lists: vote types that don't sum to the
choice total, counties that don't sum to their vote type, and unknown child
elements of Contest/Choice (listed, not parsed).
"""
import gzip
import hashlib
import json
import os
import xml.etree.ElementTree as ET
import zipfile
import zlib

from pipeline.schema import COLUMNS

TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_name", "registered_voters", "ballots_cast",
                   "precincts_participating", "precincts_reported"]


class UnsupportedFormat(ValueError):
    pass


def read_body(path):
    """File bytes, un-gzipped when the saved body is gzip (Iowa's server sends gzip unasked)."""
    with open(path, "rb") as f:
        data = f.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def parse_xml(zip_path, state, source_id):
    with zipfile.ZipFile(zip_path) as z:
        if "detail.xml" not in z.namelist():
            raise UnsupportedFormat(f"{zip_path}: no detail.xml (members: {z.namelist()})")
        root = ET.fromstring(z.read("detail.xml"))
    sha = _sha256(zip_path)
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=state, source_id=source_id, source_sha256=sha,
                source_created_at=root.findtext("Timestamp") or "",
                election_name=root.findtext("ElectionName") or "",
                election_date=root.findtext("ElectionDate") or "", contest_scope="statewide")
    rows, vote_types = [], set()
    summary = {"election_name": base["election_name"], "timestamp": base["source_created_at"],
               "contests": 0, "counties": 0, "vote_types": [],
               "mismatches_vote_types_vs_total": [], "mismatches_counties_vs_vote_type": [],
               "unknown_elements": []}

    for c in root.findall("Contest"):
        summary["contests"] += 1
        cid = c.get("key")
        status = {p.get("name"): f"{p.get('precinctsReported')}/{p.get('precinctsParticipating')} precincts"
                  for p in c.findall("ParticipatingCounties/County")}
        for el in c:
            if el.tag not in ("ParticipatingCounties", "Choice"):
                summary["unknown_elements"].append((cid, el.tag))
        contest = dict(base, contest_id=cid, contest_name=c.get("text", ""),
                       contest_type="question" if c.get("isQuestion") == "true" else "",
                       vote_for=c.get("voteFor", ""))
        for ch in c.findall("Choice"):
            chid = ch.get("key")
            for el in ch:
                if el.tag != "VoteType":
                    summary["unknown_elements"].append((cid, el.tag))
            choice = dict(contest, choice=ch.get("text", ""), choice_id=chid, party=ch.get("party", ""))
            total = int(ch.get("totalVotes"))
            rows.append(dict(choice, level="state", vote_type="TOTAL", votes=total))
            vt_sum = 0
            for vt in ch.findall("VoteType"):
                name, votes = vt.get("name"), int(vt.get("votes"))
                vote_types.add(name)
                vt_sum += votes
                rows.append(dict(choice, level="state", vote_type=name, votes=votes))
                csum = 0
                for cty in vt.findall("County"):
                    cname, cvotes = cty.get("name"), int(cty.get("votes"))
                    csum += cvotes
                    rows.append(dict(choice, level="county", county_name=cname, vote_type=name,
                                     votes=cvotes, reporting_status=status.get(cname, "")))
                if csum != votes:
                    summary["mismatches_counties_vs_vote_type"].append((cid, chid, name, votes, csum))
            if vt_sum != total:
                summary["mismatches_vote_types_vs_total"].append((cid, chid, total, vt_sum))

    turnout = []
    for cty in root.findall("ElectionVoterTurnout/Counties/County"):
        turnout.append({"state": state, "source_id": source_id, "source_sha256": sha,
                        "county_name": cty.get("name"), "registered_voters": int(cty.get("totalVoters")),
                        "ballots_cast": int(cty.get("ballotsCast")),
                        "precincts_participating": int(cty.get("precinctsParticipating")),
                        "precincts_reported": int(cty.get("precinctsReported"))})
    summary["counties"] = len(turnout)
    summary["vote_types"] = sorted(vote_types)
    return rows, summary, turnout


def parse_json(sum_path, all_path, state, source_id):
    s = json.loads(read_body(sum_path))
    a = json.loads(read_body(all_path))
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=state, source_id=source_id, contest_scope="statewide")
    sum_sha, all_sha = _sha256(sum_path), _sha256(all_path)
    summary = {"contests": 0, "counties": 0, "mismatches_counties_vs_state": [],
               "mismatches_total_area_vs_state": [], "total_area_contests_compared": 0,
               "contests_missing_total_area": [], "skipped_contest_length_mismatch": [],
               "skipped_length_mismatch": [], "skipped_areas": [], "contests_only_in_counties": []}
    rows, contests, skipped = [], {}, set()
    for c in s["Contests"]:
        summary["contests"] += 1
        k = c["K"]
        lengths = {f: len(c[f]) for f in ("CH", "CHAggId", "P", "V")}
        if len(set(lengths.values())) != 1:
            summary["skipped_contest_length_mismatch"].append((k, lengths))
            skipped.add(k)
            continue
        choices = [dict(base, contest_id=k, contest_name=c.get("C", ""), vote_for=str(c.get("VF", "")),
                        choice=name, choice_id=str(cid), party=party or "", vote_type="TOTAL")
                   for name, cid, party in zip(c["CH"], c["CHAggId"], c["P"])]
        contests[k] = (choices, c["V"])
        for ch, v in zip(choices, c["V"]):
            rows.append(dict(ch, level="state", source_sha256=sum_sha, votes=v))

    county_sum = {k: [0] * len(v) for k, (_, v) in contests.items()}
    in_total_area = set()
    for area in a["Contests"]:
        name = area["A"]
        if len(area["C"]) != len(area["V"]):
            summary["skipped_areas"].append((name, "contest keys and vote arrays differ in length"))
            continue
        if name != "-1":
            summary["counties"] += 1
        for k, votes in zip(area["C"], area["V"]):
            if k in skipped:
                continue
            if k not in contests:
                summary["contests_only_in_counties"].append((name, k))
                continue
            choices, state_v = contests[k]
            if len(votes) != len(choices):
                summary["skipped_length_mismatch"].append((name, k))
                continue
            if name == "-1":
                in_total_area.add(k)
                for ch, sv, av in zip(choices, state_v, votes):
                    if sv != av:
                        summary["mismatches_total_area_vs_state"].append((k, ch["choice_id"], sv, av))
                continue
            for i, (ch, v) in enumerate(zip(choices, votes)):
                county_sum[k][i] += v
                rows.append(dict(ch, level="county", county_name=name, source_sha256=all_sha, votes=v))
    summary["total_area_contests_compared"] = len(in_total_area)
    summary["contests_missing_total_area"] = [k for k in contests if k not in in_total_area]
    for k, (choices, state_v) in contests.items():
        for ch, sv, cs in zip(choices, state_v, county_sum[k]):
            if sv != cs:
                summary["mismatches_counties_vs_state"].append((k, ch["choice_id"], sv, cs))
    return rows, summary


COUNTY_TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_name", "precinct_name", "registered_voters",
                          "ballots_cast", "percent_reporting"]
# Contest-level VoteTypes that are not results: regVotersCounty is 0 in every 2026 NJ file (a placeholder).
CONTEST_VOTE_TYPES_NOT_EMITTED = {"regVotersCounty"}
COUNTY_LISTS = ["mismatches_vote_types_vs_total", "mismatches_precincts_vs_vote_type", "vote_type_sum_not_checked",
                "precinct_sum_not_checked", "region_mismatch", "unknown_elements", "unnamed_vote_types",
                "choices_without_vote_types", "precincts_not_in_turnout", "turnout_precincts_without_results",
                "duplicate_precincts", "non_numeric"]


def _count(v):
    """int for an ASCII digit string, else None (listed by the caller)."""
    return int(v) if v is not None and v.isascii() and v.isdigit() else None


def parse_county_xml(zip_path, state, county, source_id):
    """One county's Clarity detail XML (New Jersey counties): units are <Precinct>, not <County>.

    Design: docs/superpowers/specs/2026-11-25-step2-nj-clarity-counties-design.md.
    Rows: county rows (TOTAL = totalVotes, one per VoteType) and precinct rows (one per VoteType and
    Precinct), all labelled with the configured county. Contest keys are local to the county's file, so
    contest_scope is "local": join on (county or source_id, contest_id, choice_id, choice).
    Contest-level VoteTypes (Overvotes, Undervotes in some counties; regVotersCounty in others) are
    counted in contest_vote_types; all but CONTEST_VOTE_TYPES_NOT_EMITTED become rows with that name as
    the choice (choice_id "", vote_type TOTAL, since they aren't split by vote type).
    Nothing is corrected. A count that isn't ASCII digits gives votes "" and is listed; a comparison it
    (or a total with no published breakdown) prevents goes to a *_not_checked list, never a mismatch.
    Without a turnout table the turnout comparisons are None.
    """
    summary = {"region": None, "timestamp": None, "contests": 0, "precincts": 0, "vote_types": [],
               "contest_vote_types": {}, "contest_vote_types_emitted": [], "turnout_table": None, "unreadable": []}
    summary.update({k: [] for k in COUNTY_LISTS})
    try:
        with zipfile.ZipFile(zip_path) as z:
            if "detail.xml" not in z.namelist():
                raise UnsupportedFormat(f"no detail.xml (members: {z.namelist()})")
            root = ET.fromstring(z.read("detail.xml"))
    except (OSError, zipfile.BadZipFile, ET.ParseError, UnsupportedFormat, zlib.error, EOFError) as e:
        summary["unreadable"].append(str(e))
        for k in COUNTY_LISTS:
            summary[k] = None
        return [], summary, []
    sha = _sha256(zip_path)
    region = root.findtext("Region") or ""
    summary.update(region=region, timestamp=root.findtext("Timestamp") or "")
    if region != county:
        summary["region_mismatch"].append((county, region))
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=state, source_id=source_id, source_sha256=sha, source_created_at=summary["timestamp"],
                election_name=root.findtext("ElectionName") or "", election_date=root.findtext("ElectionDate") or "",
                contest_scope="local", county_name=county)

    turnout, turnout_names = [], set()
    vt = root.find("VoterTurnout")
    precincts_el = vt.findall("Precincts/Precinct") if vt is not None else []
    summary["turnout_table"] = "present" if precincts_el else ("empty" if vt is not None else "missing")
    for p in precincts_el:
        name = p.get("name") or ""
        turnout_names.add(name)
        turnout.append({"state": state, "source_id": source_id, "source_sha256": sha, "county_name": county,
                        "precinct_name": name, "registered_voters": _count(p.get("totalVoters")),
                        "ballots_cast": _count(p.get("ballotsCast")),
                        "percent_reporting": p.get("percentReporting") or ""})
    if vt is not None:
        turnout.append({"state": state, "source_id": source_id, "source_sha256": sha, "county_name": county,
                        "precinct_name": "", "registered_voters": _count(vt.get("totalVoters")),
                        "ballots_cast": _count(vt.get("ballotsCast")), "percent_reporting": ""})
    reporting = {t["precinct_name"]: t["percent_reporting"] for t in turnout if t["precinct_name"]}

    rows, vote_types, result_names = [], set(), set()

    def units(cid, chid, vtype, el, row):
        """Emit precinct rows under one VoteType element; return (sum or None, number of precincts)."""
        total, seen = 0, set()
        for p in el:
            if p.tag != "Precinct":
                summary["unknown_elements"].append((cid, p.tag))
                continue
            name = p.get("name") or ""
            if name in seen:
                summary["duplicate_precincts"].append((cid, chid, vtype, name))
                continue
            seen.add(name)
            result_names.add(name)
            v = _count(p.get("votes"))
            if v is None:
                summary["non_numeric"].append((cid, chid, vtype, name, p.get("votes")))
                total = None
            elif total is not None:
                total += v
            if row is not None:
                rows.append(dict(row, level="precinct", precinct_id=name, precinct_name=name,
                                 vote_type=row["vote_type"] or vtype,  # contest-level rows carry TOTAL
                                 votes="" if v is None else v, reporting_status=reporting.get(name, "")))
        return total, len(seen)

    def check_units(cid, chid, vtype, votes, el, row):
        s, n = units(cid, chid, vtype, el, row)
        if votes is None or s is None or (n == 0 and votes != 0):
            summary["precinct_sum_not_checked"].append((cid, chid, vtype))
        elif s != votes:
            summary["mismatches_precincts_vs_vote_type"].append((cid, chid, vtype, votes, s))

    for c in root.findall("Contest"):
        summary["contests"] += 1
        cid = c.get("key")
        contest = dict(base, contest_id=cid, contest_name=c.get("text", ""), vote_for=c.get("voteFor", ""),
                       contest_type="question" if c.get("isQuestion") == "true" else "")
        status = f"{c.get('precinctsReported', '')}/{c.get('precinctsReporting', '')} precincts"
        for el in c:
            if el.tag == "VoteType":  # contest-level (not a choice): counted, checked, rows unless excluded
                name = el.get("name")
                if not name:
                    summary["unnamed_vote_types"].append((cid, ""))
                    continue
                summary["contest_vote_types"][name] = summary["contest_vote_types"].get(name, 0) + 1
                v = _count(el.get("votes"))
                if v is None:
                    summary["non_numeric"].append((cid, "", name, "", el.get("votes")))
                row = None
                if name not in CONTEST_VOTE_TYPES_NOT_EMITTED:
                    if name not in summary["contest_vote_types_emitted"]:
                        summary["contest_vote_types_emitted"].append(name)
                    row = dict(contest, choice=name, choice_id="", party="", vote_type="TOTAL")
                    rows.append(dict(row, level="county", votes="" if v is None else v, reporting_status=status))
                check_units(cid, "", name, v, el, row)
            elif el.tag != "Choice":
                summary["unknown_elements"].append((cid, el.tag))
        for ch in c.findall("Choice"):
            chid = ch.get("key")
            choice = dict(contest, choice=ch.get("text", ""), choice_id=chid, party=ch.get("party", ""))
            total = _count(ch.get("totalVotes"))
            if total is None:
                summary["non_numeric"].append((cid, chid, "TOTAL", "", ch.get("totalVotes")))
            rows.append(dict(choice, level="county", vote_type="TOTAL", votes="" if total is None else total,
                             reporting_status=status))
            vt_sum, n_types = 0, 0
            for el in ch:
                if el.tag != "VoteType":
                    summary["unknown_elements"].append((cid, el.tag))
                    continue
                name, votes = el.get("name"), _count(el.get("votes"))
                if not name:
                    summary["unnamed_vote_types"].append((cid, chid))
                    vt_sum = None
                    continue
                n_types += 1
                vote_types.add(name)
                if votes is None:
                    summary["non_numeric"].append((cid, chid, name, "", el.get("votes")))
                    vt_sum = None
                elif vt_sum is not None:
                    vt_sum += votes
                rows.append(dict(choice, level="county", vote_type=name, votes="" if votes is None else votes,
                                 reporting_status=status))
                check_units(cid, chid, name, votes, el, choice)
            if n_types == 0 and vt_sum is not None:
                summary["choices_without_vote_types"].append((cid, chid))
            elif total is None or vt_sum is None:
                summary["vote_type_sum_not_checked"].append((cid, chid))
            elif vt_sum != total:
                summary["mismatches_vote_types_vs_total"].append((cid, chid, total, vt_sum))
    summary["vote_types"] = sorted(vote_types)
    summary["contest_vote_types"] = dict(sorted(summary["contest_vote_types"].items()))
    summary["precincts"] = len(result_names)
    if summary["turnout_table"] == "present":
        summary["precincts_not_in_turnout"] = sorted(result_names - turnout_names)
        summary["turnout_precincts_without_results"] = sorted(turnout_names - result_names)
    else:
        summary["precincts_not_in_turnout"] = summary["turnout_precincts_without_results"] = None
    return rows, summary, turnout


COUNTY_JSON_CHECKS = ["mismatches_precincts_vs_county", "mismatches_total_area_vs_county",
                      "mismatches_vote_types_vs_total", "mismatches_area_totals", "precinct_sum_not_checked",
                      "total_area_not_checked", "vote_type_sum_not_checked", "area_total_not_checked"]
COUNTY_JSON_LISTS = COUNTY_JSON_CHECKS + [
    "protected_cells", "non_numeric", "skipped_contest_length_mismatch", "duplicate_contests",
    "skipped_length_mismatch", "skipped_areas", "contests_only_in_areas", "duplicate_areas",
    "contests_without_precincts", "contests_without_vote_types", "precincts_not_in_status",
    "status_precincts_without_results", "rcv_contests", "partial_contests"]
PROTECTED = "protected"


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _total(values):
    """Sum of a list of counts, None when any isn't a count."""
    return sum(values) if all(_is_count(v) for v in values) else None


def _load_json(path, summary, label):
    try:
        return json.loads(read_body(path))
    except (OSError, ValueError, EOFError, zlib.error) as e:  # gzip.BadGzipFile is an OSError
        summary["unreadable"].append((label, str(e)))
        return None


def parse_county_json(record_path, base_dir="."):
    """One county's Clarity JSON files (New Jersey counties without detail XML), from a county_json pass record.

    Design: docs/superpowers/specs/2026-11-25-step2-nj-clarity-json-counties-design.md.
    County rows: TOTAL from sum.json, one per vote type from vt.json. Precinct rows: TOTAL from ALL.json,
    one per vote type from that type's file. The "-1" area of each area file is the county total: compared,
    not emitted. choice_id is sum.json's CHAggId; contest_scope "local" (keys are the county's own).
    A cell that isn't a count gives votes "" and is listed: "protected" (the county's privacy filter) in
    protected_cells, anything else in non_numeric; a comparison it prevents goes to a *_not_checked list.
    Labels in the lists: "ALL" or the vote type name for area files, "vt.json" for vt.json.
    Nothing is corrected. Without sum.json there are no rows and the checks are None; without a vote-type
    file its precinct rows are missing and the precinct vote-type check is None; without vt.json (or with
    no vote types published) the vote-type checks are None; without status.json the turnout table is
    empty and its checks are None.
    """
    summary = {"county": None, "version": None, "contests": 0, "precincts": 0, "vote_types": [], "vpcfe": None,
               "comparisons": 0, "precinct_vote_types_checked": 0, "unreadable": []}
    summary.update({k: [] for k in COUNTY_JSON_LISTS})
    with open(record_path) as f:
        rec = json.load(f)
    county, state, source_id = rec["county"], rec["state"], rec["source_id"]
    summary.update(county=county, version=rec.get("version"))
    paths = {}
    for x in rec["files"]:
        paths[(x["kind"], x.get("vote_type", ""))] = os.path.join(base_dir, x["path"])
    docs, shas = {}, {}
    for key, path in paths.items():
        label = key[1] or key[0]
        doc = _load_json(path, summary, label)
        if doc is not None:
            docs[key], shas[key] = doc, _sha256(path)

    s = docs.get(("sum", ""))
    if not isinstance(s, dict) or not isinstance(s.get("Contests"), list):
        if ("sum", "") in docs:
            summary["unreadable"].append(("sum", "no Contests list"))
        for k in COUNTY_JSON_LISTS:
            summary[k] = None
        return [], summary, []
    summary["vpcfe"] = s.get("VPCFE")
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=state, source_id=source_id, contest_scope="local", county_name=county)

    # Contests from sum.json: choices (as row templates) and county totals.
    contests, skipped, rows = {}, set(), []
    for c in s["Contests"]:
        summary["contests"] += 1
        if not isinstance(c, dict):
            summary["skipped_contest_length_mismatch"].append((None, "not an object"))
            continue
        k = str(c.get("K", ""))
        lengths = {f: len(c[f]) if isinstance(c.get(f), list) else None for f in ("CH", "CHAggId", "P", "V")}
        if k in contests or k in skipped:
            summary["duplicate_contests"].append(("sum.json", k))
            continue
        if None in lengths.values() or len(set(lengths.values())) != 1:
            summary["skipped_contest_length_mismatch"].append((k, lengths))
            skipped.add(k)
            continue
        if c.get("IsRCV"):
            summary["rcv_contests"].append(k)
        if _is_count(c.get("PR")) and _is_count(c.get("TP")) and c["PR"] < c["TP"]:
            summary["partial_contests"].append((k, c.get("PR"), c.get("TP")))
        contest = dict(base, contest_id=k, contest_name=c.get("C", ""), vote_for=str(c.get("VF", "")))
        choices = [dict(contest, choice=name, choice_id=str(cid), party=party or "")
                   for name, cid, party in zip(c["CH"], c["CHAggId"], c["P"])]
        status = f"{c.get('PR', '')}/{c.get('TP', '')} precincts"
        contests[k] = {"choices": choices, "total": c["V"], "status": status, "types": None}
        for ch, v in zip(choices, c["V"]):
            rows.append(dict(ch, level="county", vote_type="TOTAL", source_sha256=shas[("sum", "")],
                             votes=_cell(v, "sum.json", "", k, ch["choice_id"], "TOTAL", summary),
                             reporting_status=status))

    # Vote types from vt.json: county rows, per-type totals, and the county vote-type check.
    vt = docs.get(("vt", ""))
    types = vt.get("Types") if isinstance(vt, dict) else None
    if not (isinstance(types, list) and all(isinstance(t, str) and t for t in types)
            and len(set(types)) == len(types) and isinstance(vt.get("Contests"), list)):
        if vt is not None:
            summary["unreadable"].append(("vt", "no Types/Contests lists, or repeated type names"))
        types = None
    summary["vote_types"] = list(types or [])
    if not types:
        for k in ("mismatches_vote_types_vs_total", "vote_type_sum_not_checked", "contests_without_vote_types"):
            summary[k] = None
        summary["precinct_vote_types_checked"] = None
    else:
        seen = set()
        for c in vt["Contests"]:
            if not isinstance(c, dict):
                summary["skipped_length_mismatch"].append(("vt.json", "", None))
                continue
            k = str(c.get("K", ""))
            if k in skipped:
                continue
            if k in seen:
                summary["duplicate_contests"].append(("vt.json", k))
                continue
            if k not in contests:
                summary["contests_only_in_areas"].append(("vt.json", "", k))
                continue
            seen.add(k)
            info = contests[k]
            votes, tots = c.get("Votes"), c.get("T")
            if not (isinstance(votes, list) and len(votes) == len(info["choices"])
                    and all(isinstance(r, list) and len(r) == len(types) for r in votes)
                    and isinstance(tots, list) and len(tots) == len(types)):
                summary["skipped_length_mismatch"].append(("vt.json", "", k))
                continue
            info["types"] = votes
            cells = [[_cell(v, "vt.json", "", k, ch["choice_id"], t, summary) for v, t in zip(r, types)]
                     for ch, r in zip(info["choices"], votes)]
            for i, (ch, r) in enumerate(zip(info["choices"], cells)):
                for t, v in zip(types, r):
                    rows.append(dict(ch, level="county", vote_type=t, votes=v, source_sha256=shas[("vt", "")],
                                     reporting_status=info["status"]))
                _compare(summary, "mismatches_vote_types_vs_total", "vote_type_sum_not_checked",
                         ("county", "", k, ch["choice_id"]), _count_or_none(info["total"][i]), _total(votes[i]))
            for ti, t in enumerate(types):
                _compare(summary, "mismatches_area_totals", "area_total_not_checked", ("vt.json", t, k),
                         _count_or_none(tots[ti]), _total([r[ti] for r in votes]))
        summary["contests_without_vote_types"] = [k for k in contests if k not in seen]

    # Area files: ALL.json (TOTAL) and one per vote type.
    files = [("ALL", "TOTAL", ("all", ""))] + [(t, t, ("type", t)) for t in (types or [])]
    area_values = {}  # (file, area, contest) -> list of cells as published (precinct areas only)
    status_names = None
    st = docs.get(("status", ""))
    reporting, turnout = {}, []
    if isinstance(st, dict) and all(isinstance(st.get(f), list) for f in "PSRB") \
            and len({len(st[f]) for f in "PSRB"}) == 1 and all(isinstance(n, str) for n in st["P"]):
        status_names = set()
        for name, code, reg, bal in zip(st["P"], st["S"], st["R"], st["B"]):
            status_names.add(name)
            code = "" if code is None else str(code)
            reporting[name] = code
            turnout.append({"state": state, "source_id": source_id, "source_sha256": shas[("status", "")],
                            "county_name": county, "precinct_name": name,
                            "registered_voters": reg if _is_count(reg) else None,
                            "ballots_cast": bal if _is_count(bal) else None, "percent_reporting": code})
            for field, v in (("R", reg), ("B", bal)):
                if not _is_count(v):
                    summary["non_numeric"].append(("status.json", name, "", "", field, v))
    elif ("status", "") in docs:
        summary["unreadable"].append(("status", "P/S/R/B are not lists of one length, or a name isn't text"))

    def county_values(info, vtype):
        """The county figures an area file is checked against: sum.json for ALL, vt.json for a type."""
        if vtype == "TOTAL":
            return info["total"]
        return [r[types.index(vtype)] for r in info["types"]] if info["types"] else None

    def not_checked(label, k, which):
        for ch in contests[k]["choices"]:
            summary[which].append((label, k, ch["choice_id"]))

    result_names = set()
    for label, vtype, key in files:
        doc = docs.get(key)
        if doc is not None and not (isinstance(doc, dict) and isinstance(doc.get("Contests"), list)):
            summary["unreadable"].append((label, "no Contests list"))
            doc = None
        if doc is None:  # nothing in this file can be checked; the precinct vote-type check needs every file
            summary["precinct_vote_types_checked"] = None
            for k in contests:
                not_checked(label, k, "precinct_sum_not_checked")
                not_checked(label, k, "total_area_not_checked")
                summary["area_total_not_checked"].append((label, "", k))
            continue
        sums, incomplete, whole_area_skipped, areas_seen, county_area = {}, set(), False, set(), set()
        for a in doc["Contests"]:
            name = a.get("A") if isinstance(a, dict) else None
            if not isinstance(name, str):
                summary["skipped_areas"].append((label, None, "not an object with a text name"))
                whole_area_skipped = True
                continue
            if name in areas_seen:
                summary["duplicate_areas"].append((label, name))
                continue
            areas_seen.add(name)
            ks, vs, ts = a.get("C"), a.get("V"), a.get("T")
            if not (isinstance(ks, list) and isinstance(vs, list) and isinstance(ts, list)
                    and len(ks) == len(vs) == len(ts)):
                summary["skipped_areas"].append((label, name, "C/V/T lengths differ"))
                whole_area_skipped = whole_area_skipped or name != "-1"
                continue
            for k, votes, tot in zip(ks, vs, ts):
                k = str(k)
                if k in skipped:
                    continue
                if k not in contests:
                    summary["contests_only_in_areas"].append((label, name, k))
                    continue
                info = contests[k]
                if not isinstance(votes, list) or len(votes) != len(info["choices"]):
                    summary["skipped_length_mismatch"].append((label, name, k))
                    if name != "-1":
                        incomplete.add(k)
                    continue
                cells = [_cell(v, label, name, k, ch["choice_id"], vtype, summary)
                         for v, ch in zip(votes, info["choices"])]
                _compare(summary, "mismatches_area_totals", "area_total_not_checked", (label, name, k),
                         _count_or_none(tot), _total(votes))
                if name == "-1":
                    county_area.add(k)
                    cv = county_values(info, vtype)
                    for i, ch in enumerate(info["choices"]):
                        _compare(summary, "mismatches_total_area_vs_county", "total_area_not_checked",
                                 (label, k, ch["choice_id"]), _count_or_none(cv[i]) if cv is not None else None,
                                 _count_or_none(votes[i]))
                    continue
                result_names.add(name)
                area_values[(label, name, k)] = votes
                acc = sums.setdefault(k, [0] * len(votes))
                for i, v in enumerate(votes):
                    acc[i] = acc[i] + v if acc[i] is not None and _is_count(v) else None
                for ch, v in zip(info["choices"], cells):
                    rows.append(dict(ch, level="precinct", precinct_id=name, precinct_name=name, vote_type=vtype,
                                     votes=v, source_sha256=shas[key], reporting_status=reporting.get(name, "")))
        for k, info in contests.items():
            if k not in county_area:  # no usable "-1" entry for this contest: its county check didn't run
                not_checked(label, k, "total_area_not_checked")
            # Precinct sums against the county values; a skipped area or contest entry makes them incomplete.
            if whole_area_skipped or k in incomplete:
                not_checked(label, k, "precinct_sum_not_checked")
                continue
            if k not in sums:
                summary["contests_without_precincts"].append((label, k))
                not_checked(label, k, "precinct_sum_not_checked")
                continue
            cv = county_values(info, vtype)
            for i, ch in enumerate(info["choices"]):
                _compare(summary, "mismatches_precincts_vs_county", "precinct_sum_not_checked",
                         (label, k, ch["choice_id"]), _count_or_none(cv[i]) if cv is not None else None, sums[k][i])

    # Precinct vote types against the precinct total.
    if types and summary["precinct_vote_types_checked"] is not None:
        for (label, name, k), totals in area_values.items():
            if label != "ALL":
                continue
            per_type = [area_values.get((t, name, k)) for t in types]
            for i, ch in enumerate(contests[k]["choices"]):
                parts = None if any(p is None for p in per_type) else [p[i] for p in per_type]
                before = summary["comparisons"]
                _compare(summary, "mismatches_vote_types_vs_total", "vote_type_sum_not_checked",
                         ("precinct", name, k, ch["choice_id"]), _count_or_none(totals[i]),
                         None if parts is None else _total(parts))
                summary["precinct_vote_types_checked"] += summary["comparisons"] - before

    summary["precincts"] = len(result_names)
    if status_names is None:
        summary["precincts_not_in_status"] = summary["status_precincts_without_results"] = None
    else:
        summary["precincts_not_in_status"] = sorted(result_names - status_names)
        summary["status_precincts_without_results"] = sorted(status_names - result_names)
    return rows, summary, turnout


def _count_or_none(v):
    return v if _is_count(v) else None


def _cell(v, label, area, k, chid, vtype, summary):
    """A published cell as a row value: the count, or "" (listed) for "protected" or anything else."""
    if _is_count(v):
        return v
    if v == PROTECTED:
        summary["protected_cells"].append((label, area, k, chid, vtype))
    else:
        summary["non_numeric"].append((label, area, k, chid, vtype, v))
    return ""


def _compare(summary, mismatch_key, not_checked_key, ident, expected, got):
    """Record one comparison: a mismatch, a not-checked entry (either side unusable), or a match."""
    if expected is None or got is None:
        summary[not_checked_key].append(ident)
    else:
        summary["comparisons"] += 1
        if expected != got:
            summary[mismatch_key].append(ident + (expected, got))
