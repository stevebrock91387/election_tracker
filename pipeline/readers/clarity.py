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
import xml.etree.ElementTree as ET
import zipfile

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
COUNTY_LISTS = ["mismatches_vote_types_vs_total", "mismatches_precincts_vs_vote_type", "vote_type_sum_not_checked",
                "region_mismatch", "unknown_elements", "precincts_not_in_turnout", "turnout_precincts_without_results",
                "duplicate_precincts", "non_numeric"]


def _count(v):
    return int(v) if v is not None and v.isdigit() else None


def parse_county_xml(zip_path, state, county, source_id):
    """One county's Clarity detail XML (New Jersey counties): units are <Precinct>, not <County>.

    Design: docs/superpowers/specs/2026-11-25-step2-nj-clarity-counties-design.md.
    Rows: county rows (TOTAL = totalVotes, one per VoteType) and precinct rows (one per VoteType and
    Precinct). Contest keys are local to the county's file, so contest_scope is "local". A contest-level
    VoteType (e.g. regVotersCounty) is counted in contest_vote_types and checked, not emitted. Nothing is
    corrected; a non-integer count gives votes "" and moves its sums to vote_type_sum_not_checked.
    """
    summary = {"region": None, "timestamp": None, "contests": 0, "precincts": 0, "vote_types": [],
               "contest_vote_types": {}, "unreadable": []}
    summary.update({k: [] for k in COUNTY_LISTS})
    try:
        with zipfile.ZipFile(zip_path) as z:
            if "detail.xml" not in z.namelist():
                raise UnsupportedFormat(f"no detail.xml (members: {z.namelist()})")
            root = ET.fromstring(z.read("detail.xml"))
    except (OSError, zipfile.BadZipFile, ET.ParseError, UnsupportedFormat) as e:
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
    if vt is not None:
        for p in vt.findall("Precincts/Precinct"):
            name = p.get("name") or ""
            turnout_names.add(name)
            turnout.append({"state": state, "source_id": source_id, "source_sha256": sha, "county_name": county,
                            "precinct_name": name, "registered_voters": _count(p.get("totalVoters")),
                            "ballots_cast": _count(p.get("ballotsCast")),
                            "percent_reporting": p.get("percentReporting") or ""})
        turnout.append({"state": state, "source_id": source_id, "source_sha256": sha, "county_name": county,
                        "precinct_name": "", "registered_voters": _count(vt.get("totalVoters")),
                        "ballots_cast": _count(vt.get("ballotsCast")), "percent_reporting": ""})
    reporting = {t["precinct_name"]: t["percent_reporting"] for t in turnout if t["precinct_name"]}

    rows, vote_types, result_names = [], set(), set()

    def units(cid, chid, vtype, el, row):
        """Emit precinct rows under one VoteType element; return their sum or None."""
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
                rows.append(dict(row, level="precinct", precinct_id=name, precinct_name=name, vote_type=vtype,
                                 votes="" if v is None else v, reporting_status=reporting.get(name, "")))
        return total

    for c in root.findall("Contest"):
        summary["contests"] += 1
        cid = c.get("key")
        contest = dict(base, contest_id=cid, contest_name=c.get("text", ""), vote_for=c.get("voteFor", ""),
                       contest_type="question" if c.get("isQuestion") == "true" else "")
        status = f"{c.get('precinctsReported', '')}/{c.get('precinctsReporting', '')} precincts"
        for el in c:
            if el.tag == "VoteType":  # contest-level (not a choice): counted and checked, no rows
                name = el.get("name")
                summary["contest_vote_types"][name] = summary["contest_vote_types"].get(name, 0) + 1
                s, v = units(cid, "", name, el, None), _count(el.get("votes"))
                if s is not None and v is not None and s != v:
                    summary["mismatches_precincts_vs_vote_type"].append((cid, "", name, v, s))
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
            vt_sum = 0
            for el in ch:
                if el.tag != "VoteType":
                    summary["unknown_elements"].append((cid, el.tag))
                    continue
                name, votes = el.get("name"), _count(el.get("votes"))
                vote_types.add(name)
                if votes is None:
                    summary["non_numeric"].append((cid, chid, name, "", el.get("votes")))
                    vt_sum = None
                elif vt_sum is not None:
                    vt_sum += votes
                rows.append(dict(choice, level="county", vote_type=name, votes="" if votes is None else votes,
                                 reporting_status=status))
                s = units(cid, chid, name, el, choice)
                if s is not None and votes is not None and s != votes:
                    summary["mismatches_precincts_vs_vote_type"].append((cid, chid, name, votes, s))
            if total is None or vt_sum is None:
                summary["vote_type_sum_not_checked"].append((cid, chid))
            elif ch.find("VoteType") is not None and vt_sum != total:
                summary["mismatches_vote_types_vs_total"].append((cid, chid, total, vt_sum))
    summary["vote_types"] = sorted(vote_types)
    summary["precincts"] = len(result_names)
    summary["precincts_not_in_turnout"] = sorted(result_names - turnout_names)
    summary["turnout_precincts_without_results"] = sorted(turnout_names - result_names)
    return rows, summary, turnout
