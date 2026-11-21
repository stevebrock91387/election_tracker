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
- A county whose vote array length differs from sum.json's for a contest is
  skipped and listed; contests in ALL.json missing from sum.json are listed.
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
               "mismatches_total_area_vs_state": [], "skipped_length_mismatch": [],
               "contests_only_in_counties": []}
    rows, contests = [], {}
    for c in s["Contests"]:
        summary["contests"] += 1
        k = c["K"]
        choices = [dict(base, contest_id=k, contest_name=c.get("C", ""), vote_for=str(c.get("VF", "")),
                        choice=name, choice_id=str(cid), party=party or "", vote_type="TOTAL")
                   for name, cid, party in zip(c["CH"], c["CHAggId"], c["P"])]
        contests[k] = (choices, c["V"])
        for ch, v in zip(choices, c["V"]):
            rows.append(dict(ch, level="state", source_sha256=sum_sha, votes=v))

    county_sum = {k: [0] * len(v) for k, (_, v) in contests.items()}
    for area in a["Contests"]:
        name = area["A"]
        if name != "-1":
            summary["counties"] += 1
        for k, votes in zip(area["C"], area["V"]):
            if k not in contests:
                summary["contests_only_in_counties"].append((name, k))
                continue
            choices, state_v = contests[k]
            if len(votes) != len(choices):
                summary["skipped_length_mismatch"].append((name, k))
                continue
            if name == "-1":
                for ch, sv, av in zip(choices, state_v, votes):
                    if sv != av:
                        summary["mismatches_total_area_vs_state"].append((k, ch["choice_id"], sv, av))
                continue
            for i, (ch, v) in enumerate(zip(choices, votes)):
                county_sum[k][i] += v
                rows.append(dict(ch, level="county", county_name=name, source_sha256=all_sha, votes=v))
    for k, (choices, state_v) in contests.items():
        for ch, sv, cs in zip(choices, state_v, county_sum[k]):
            if sv != cs:
                summary["mismatches_counties_vs_state"].append((k, ch["choice_id"], sv, cs))
    return rows, summary
