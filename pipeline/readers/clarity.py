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

Nothing is corrected. The summary lists: vote types that don't sum to the
choice total, counties that don't sum to their vote type, and unknown child
elements of Contest/Choice (listed, not parsed).
"""
import gzip
import hashlib
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
