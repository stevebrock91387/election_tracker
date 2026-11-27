"""Parse LiveVoterTurnout ENR results: one county's summary XML (docs/lvt.md).

Source: livevoterturnout.com/ENR/<site>/<election id>/summary_<election id>.xml, the file the results
page's own script reads. Root <NewDataSet>; optional county header fields (TotalBallotsCast,
RegisteredVoters, GeneratedDate: Bergen has them, Salem doesn't); then one <Table> per (race, choice)
with RaceID, RaceName, VoteFor, ContestantID, ContestantName, Party, one element per vote type (names
differ by county: EarlyVotingVotes or EarlyVotes, VotebyMailBallotsVotes or MailBallotVotes,
ElectionDayVotes, ProvisionalVotes, CustomVotes), TotalVotes, and race-level TimesCounted, OverVotes,
UnderVotes, BlankVoted repeated on every choice.

Rows (level "county", county_name from the pass record, contest_scope "local" like the NJ Clarity
counties: join on county + contest_id + choice_id): one per choice and vote type (the element name,
unchanged) plus TOTAL; OverVotes and UnderVotes as choices with choice_id "" and vote_type TOTAL.
GeneratedDate, when present, is source_created_at.

Write-ins: a choice named "Write-In" is kept; the choices after it in the same race are its breakdown
by written name (Salem, 2026: the Write-In line equals their sum in every race; no field marks them).
They are not rows (they would count twice, and the names are private individuals): counted, and
their sum checked against the Write-In line. "Personal Choice" (Bergen) is an ordinary choice.

Nothing is corrected; the summary lists: choices whose vote types don't sum to TotalVotes, race fields
that differ between a race's choices, duplicate (race, choice id) entries (the first is kept),
non-integer counts (votes ""), write-in breakdowns that don't sum to the Write-In line, vote fields
not known to the reader (not read), nonzero values in fields always 0 so far (Votes, BlankVoted),
withdrawn choices (kept), and races where vote_for x TimesCounted differs from the choices plus
over and under votes (informational).
"""
import hashlib
import json
import os
import xml.etree.ElementTree as ET

from pipeline.schema import COLUMNS

VOTE_TYPES = ["EarlyVotingVotes", "EarlyVotes", "VotebyMailBallotsVotes", "MailBallotVotes", "ElectionDayVotes",
              "ProvisionalVotes", "CustomVotes"]
RACE_FIELDS = ["RaceName", "VoteFor", "TimesCounted", "OverVotes", "UnderVotes"]
UNUSED = ["Votes", "BlankVoted"]  # 0 in every 2026 file
NOT_VOTE_TYPES = {"TotalVotes", "OverVotes", "UnderVotes", "MinimumVotes"} | set(UNUSED)
WRITE_IN = "write-in"
LISTS = ["vote_type_sum_mismatches", "race_fields_vary", "duplicate_choices", "non_numeric",
         "write_in_breakdown_mismatches", "unknown_vote_fields", "nonzero_unused_fields", "withdrawn",
         "ballot_balance_differences"]


def _int(v):
    v = (v or "").strip()
    return int(v) if v.isascii() and v.isdigit() else None


def parse_pass(record_path, base_dir="."):
    """(rows, summary) for one pass record listing the summary XML (kind "summary_xml")."""
    with open(record_path) as f:
        rec = json.load(f)
    summary = {k: [] for k in LISTS}
    summary.update(contests=0, vote_types=[], write_in_names_dropped=0, generated=None, registered_voters=None,
                   ballots_cast=None, unreadable_files=[], missing_files=[])
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"]))
             for x in rec["files"]}
    root = None
    if "summary_xml" not in paths:
        summary["missing_files"] = ["summary_xml"]
    else:
        try:
            with open(paths["summary_xml"], "rb") as f:
                body = f.read()
            root = ET.fromstring(body)
            sha = hashlib.sha256(body).hexdigest()
        except (OSError, ET.ParseError) as e:
            summary["unreadable_files"].append(("summary_xml", str(e)))
            root = None
    if root is None:
        for k in LISTS + ["contests", "write_in_names_dropped"]:
            summary[k] = None
        return [], summary

    summary.update(generated=root.findtext("GeneratedDate"), registered_voters=_int(root.findtext("RegisteredVoters")),
                   ballots_cast=_int(root.findtext("TotalBallotsCast")))
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], source_sha256=sha,
                source_created_at=summary["generated"] or "", level="county", county_name=rec["county"],
                contest_scope="local")

    races = {}  # RaceID -> list of field dicts, document order
    unknown = set()
    for t in root.findall("Table"):
        d = {c.tag: (c.text or "") for c in t}
        races.setdefault(d.get("RaceID", ""), []).append(d)
        for tag in d:
            if tag.endswith("Votes") and tag not in NOT_VOTE_TYPES and tag not in VOTE_TYPES:
                unknown.add(tag)
    summary["unknown_vote_fields"] = sorted(unknown)

    rows, vt_seen = [], []

    def count(rid, cid, field, raw):
        v = _int(raw)
        if v is None:
            summary["non_numeric"].append((rid, cid, field, raw))
        return v

    for rid, entries in races.items():
        summary["contests"] += 1
        first = entries[0]
        for field in RACE_FIELDS:
            vals = sorted({e.get(field, "") for e in entries})
            if len(vals) > 1:
                summary["race_fields_vary"].append((rid, field, vals))
        contest = dict(base, contest_id=rid, contest_name=first.get("RaceName", ""), vote_for=first.get("VoteFor", ""))
        seen, kept_total, in_breakdown, wi_total, wi_sum = set(), 0, False, None, 0
        for e in entries:
            cid = e.get("ContestantID", "")
            if in_breakdown:
                summary["write_in_names_dropped"] += 1
                v = count(rid, cid, "TotalVotes", e.get("TotalVotes"))
                wi_sum = None if wi_sum is None or v is None else wi_sum + v
                continue
            if cid in seen:
                summary["duplicate_choices"].append((rid, cid))
                continue
            seen.add(cid)
            if e.get("ContestantWithdrawn") == "Y":
                summary["withdrawn"].append((rid, cid, e.get("ContestantName", "")))
            for field in UNUSED:
                if e.get(field, "0") not in ("0", ""):
                    summary["nonzero_unused_fields"].append((rid, cid, field, e[field]))
            choice = dict(contest, choice=e.get("ContestantName", ""), choice_id=cid, party=e.get("Party", ""))
            parts = 0
            for vt in VOTE_TYPES:
                if vt not in e:
                    continue
                if vt not in vt_seen:
                    vt_seen.append(vt)
                v = count(rid, cid, vt, e[vt])
                parts = None if parts is None or v is None else parts + v
                rows.append(dict(choice, vote_type=vt, votes="" if v is None else v))
            total = count(rid, cid, "TotalVotes", e.get("TotalVotes"))
            rows.append(dict(choice, vote_type="TOTAL", votes="" if total is None else total))
            if parts is not None and total is not None and parts != total:
                summary["vote_type_sum_mismatches"].append((rid, cid, parts, total))
            kept_total = None if kept_total is None or total is None else kept_total + total
            if choice["choice"].strip().lower() == WRITE_IN:
                in_breakdown, wi_total = True, total
        if in_breakdown and wi_total is not None and wi_sum is not None and wi_sum > 0 and wi_sum != wi_total:
            summary["write_in_breakdown_mismatches"].append((rid, wi_total, wi_sum))
        ou = {}
        for name in ("OverVotes", "UnderVotes"):
            if name in first:
                ou[name] = count(rid, "", name, first[name])
                rows.append(dict(contest, choice=name, choice_id="", vote_type="TOTAL",
                                 votes="" if ou[name] is None else ou[name]))
        vf, tc = _int(first.get("VoteFor")), _int(first.get("TimesCounted"))
        if None not in (vf, tc, kept_total, ou.get("OverVotes"), ou.get("UnderVotes")):
            rhs = kept_total + ou["OverVotes"] + ou["UnderVotes"]
            if vf * tc != rhs:
                summary["ballot_balance_differences"].append((rid, contest["contest_name"], vf * tc, rhs))
    summary["vote_types"] = vt_seen
    return rows, summary
