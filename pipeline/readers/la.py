"""Parse Louisiana results: the SOS live-results JSON blobs, by parish.

Design: docs/superpowers/specs/2026-11-24-step2-la-reader-design.md.

A pass record lists: races (RacesCandidates_Multiparish: Races.WriteTime, Races.Race[] with ID,
SpecificTitle, GeneralTitle, OfficeLevel, NumberToBeElected and Choice[] {ID, Desc}), votes
(Votes_Multiparish: per race PrecinctsReporting/Expected, NumAbsenteeReporting/Expected,
VoterCountQualified, VoterCountVoted, Choice[] {ID, VoteTotal, Outcome}), and per in-scope race
parish-<race> (Parishes.Parish[]: ParishValue, the same counts, Choice[]) and early-<race>
(EarlyVoting.Parish[]: ParishValue, HasReported, Choice[] {ID, VoteTotal}). District races list only
their parishes. Choice ids are unique only within a race (amendments all use 3 = YES, 4 = NO). The
record carries the in-scope race ids and the parish code -> name list.

Rows: state rows from votes (TOTAL); parish rows (level "county", county_id = parish code) from the
parish files (TOTAL) and the early files (vote type "EarlyVoting", reported parishes only).
choice = Desc as published; party = the trailing parenthesised upper-case code in Desc ("REP"), else
"". reporting_status = "<precincts reporting>/<expected> precincts, <absentee>/<expected> absentee".
source_created_at = the races file's WriteTime; election_date from the record (MM/DD/YYYY);
election_name "" (no blob names the election).

The turnout table has one row per (race, parish): qualified, voted, precincts and absentee counts.

Nothing is corrected; the summary lists: parish sums that differ from the state value per (race,
choice) and per count (qualified, voted, precincts, absentee), early votes above the parish total,
choices in one file and not the other (races vs votes, votes vs parishes, parishes vs early, in both
directions), parishes in the parish file missing from the early file, state counts missing or
non-integer, in-scope races missing from the races or votes file or without a parish or early file
(a race missing from the votes file makes the parish checks and runoff list None), early parishes
not reported, parish codes not in the list, non-integer
counts (votes ""), duplicate (race, parish, choice), malformed entries, each race's outcomes and the
races with a Runoff outcome, and missing or unreadable files. Checks that need a file that wasn't
read are None (for any race: the lists are not per race).
"""
import hashlib
import json
import os
import re

from pipeline.schema import COLUMNS

COUNTS = ("PrecinctsReporting", "PrecinctsExpected", "NumAbsenteeReporting", "NumAbsenteeExpected",
          "VoterCountQualified", "VoterCountVoted")
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "contest_id", "county_id", "county_name",
                   "voters_qualified", "voters_voted", "precincts_reporting", "precincts_expected",
                   "absentee_reporting", "absentee_expected"]
PARISH_LISTS = ["parish_vs_state_mismatches", "parish_count_mismatches", "choices_not_in_parishes",
                "choices_only_in_parishes"]
EARLY_LISTS = ["early_exceeds_total", "early_not_reported", "early_choices_unknown", "early_parishes_missing",
               "early_choices_missing"]
RACE_LISTS = ["choices_not_in_races", "choices_not_in_votes"]
LISTS = PARISH_LISTS + EARLY_LISTS + RACE_LISTS + ["races_missing", "unknown_parishes", "non_numeric",
                                                   "duplicate_entries", "malformed_entries", "runoff_races",
                                                   "state_counts_missing"]
PARTY = re.compile(r"\(([A-Z]{1,6})\)\s*$")


def _int(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d+", v.strip()):
        return int(v)
    return None


def _dicts(seq, where, summary):
    if seq is None:
        return []
    if not isinstance(seq, list):
        seq = [seq] if isinstance(seq, dict) else None
        if seq is None:
            summary["malformed_entries"].append(where)
            return []
    out = []
    for x in seq:
        if isinstance(x, dict):
            out.append(x)
        else:
            summary["malformed_entries"].append(where)
    return out


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    races_in_scope = [str(r) for r in rec.get("races") or []]
    parish_names = rec.get("parishes") or {}
    kinds = ["races", "votes"] + [f"{k}-{r}" for r in races_in_scope for k in ("parish", "early")]
    summary = {"contests": 0, "parishes": 0, "outcomes": {}}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in kinds if k not in paths]
    top = {"races": ("Races", "Race"), "votes": ("Races", "Race"), "parish": ("Parishes", "Parish"),
           "early": ("EarlyVoting", "Parish")}
    data, sha, meta = {}, {}, {}
    for k in kinds:
        if k not in paths:
            continue
        outer, inner = top[k.split("-")[0]]
        try:
            with open(paths[k], "rb") as f:
                body = f.read()
            obj = json.loads(body.decode("utf-8-sig"))
            box = obj.get(outer) if isinstance(obj, dict) else None
            if not isinstance(box, dict) or inner not in box:
                raise ValueError(f"no {outer}.{inner}")
            data[k], sha[k], meta[k] = _dicts(box[inner], (k, inner), summary), hashlib.sha256(body).hexdigest(), box
        except (OSError, ValueError, UnicodeDecodeError) as e:
            summary["unreadable_files"].append((k, str(e)))

    date = rec.get("election_date", "")
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide",
                election_date=f"{date[4:6]}/{date[6:8]}/{date[:4]}" if re.fullmatch(r"\d{8}", date) else date,
                source_created_at=meta.get("races", {}).get("WriteTime") or "")
    info = {str(r.get("ID")): r for r in data.get("races", [])}
    votes = {str(r.get("ID")): r for r in data.get("votes", [])}
    rows, turnout, seen = [], [], set()

    def choice_info(rid, cid):
        for c in _dicts((info.get(rid) or {}).get("Choice"), ("races", rid), summary):
            if str(c.get("ID")) == cid:
                desc = c.get("Desc") if isinstance(c.get("Desc"), str) else ""
                m = PARTY.search(desc)
                return desc, m.group(1) if m else ""
        return "", ""

    def count(raw, where):
        n = _int(raw)
        if n is None:
            summary["non_numeric"].append(where + (raw,))
        return n

    def status(x):
        return (f"{x.get('PrecinctsReporting', '')}/{x.get('PrecinctsExpected', '')} precincts, "
                f"{x.get('NumAbsenteeReporting', '')}/{x.get('NumAbsenteeExpected', '')} absentee")

    for rid in races_in_scope:
        r = info.get(rid)
        if "races" in data and r is None:
            summary["races_missing"].append(("races", rid))
        if "votes" in data and rid not in votes:
            summary["races_missing"].append(("votes", rid))
        r = r or {}
        crow = dict(base, contest_id=rid, contest_name=r.get("SpecificTitle") or "", contest_type=r.get("GeneralTitle") or "",
                    vote_for=str(r.get("NumberToBeElected") or ""))
        summary["contests"] += 1
        state_votes, outcomes = {}, []
        v = votes.get(rid)
        if v is not None and r:
            race_ids = {str(c.get("ID")) for c in _dicts(r.get("Choice"), ("races", rid), summary)}
            vote_ids = {str(c.get("ID")) for c in _dicts(v.get("Choice"), ("votes", rid), summary)}
            summary["choices_not_in_races"] += [(rid, c) for c in sorted(vote_ids - race_ids)]
            summary["choices_not_in_votes"] += [(rid, c) for c in sorted(race_ids - vote_ids)]
        if v is not None:
            for f_ in COUNTS:
                if f_ not in v:
                    summary["state_counts_missing"].append((rid, f_))
                elif _int(v.get(f_)) is None:
                    summary["non_numeric"].append(("state", rid, "", f_, v.get(f_)))
            for c in _dicts(v.get("Choice"), ("votes", rid), summary):
                cid = str(c.get("ID"))
                n = count(c.get("VoteTotal"), ("state", rid, "", cid))
                state_votes[cid] = n
                outcomes.append((cid, c.get("Outcome")))
                desc, party = choice_info(rid, cid)
                rows.append(dict(crow, level="state", source_sha256=sha["votes"], reporting_status=status(v),
                                 choice_id=cid, choice=desc, party=party, vote_type="TOTAL", votes="" if n is None else n))
            summary["outcomes"][rid] = outcomes
            if any(o == "Runoff" for _, o in outcomes):
                summary["runoff_races"].append(rid)
        pk, ek = f"parish-{rid}", f"early-{rid}"
        totals = {}
        if pk in data:
            sums, csums = {}, {}
            for p in data[pk]:
                code = str(p.get("ParishValue", ""))
                if code not in parish_names and code not in summary["unknown_parishes"]:
                    summary["unknown_parishes"].append(code)
                for f_ in COUNTS:
                    n = count(p.get(f_), ("parish", rid, code, f_))
                    if n is not None:
                        csums[f_] = csums.get(f_, 0) + n
                turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha[pk], contest_id=rid,
                                    county_id=code, county_name=parish_names.get(code, ""),
                                    voters_qualified=_int(p.get("VoterCountQualified")) if _int(p.get("VoterCountQualified")) is not None else p.get("VoterCountQualified", ""),
                                    voters_voted=_int(p.get("VoterCountVoted")) if _int(p.get("VoterCountVoted")) is not None else p.get("VoterCountVoted", ""),
                                    precincts_reporting=p.get("PrecinctsReporting", ""), precincts_expected=p.get("PrecinctsExpected", ""),
                                    absentee_reporting=p.get("NumAbsenteeReporting", ""), absentee_expected=p.get("NumAbsenteeExpected", "")))
                prow = dict(crow, level="county", source_sha256=sha[pk], county_id=code,
                            county_name=parish_names.get(code, ""), reporting_status=status(p))
                for c in _dicts(p.get("Choice"), (pk, code), summary):
                    cid = str(c.get("ID"))
                    key = (rid, code, cid, "TOTAL")
                    if key in seen:
                        summary["duplicate_entries"].append(key)
                    seen.add(key)
                    n = count(c.get("VoteTotal"), ("parish", rid, code, cid))
                    totals[(code, cid)] = n
                    if n is not None:
                        sums[cid] = sums.get(cid, 0) + n
                    desc, party = choice_info(rid, cid)
                    rows.append(dict(prow, choice_id=cid, choice=desc, party=party, vote_type="TOTAL",
                                     votes="" if n is None else n))
            if v is not None:
                for cid, n in state_votes.items():
                    if cid not in sums:
                        summary["choices_not_in_parishes"].append((rid, cid))
                    elif n is not None and sums[cid] != n:
                        summary["parish_vs_state_mismatches"].append((rid, cid, n, sums[cid]))
                summary["choices_only_in_parishes"] += [(rid, c) for c in sorted(set(sums) - set(state_votes))]
                for f_ in COUNTS:
                    n = _int(v.get(f_))
                    if n is not None and csums.get(f_) != n:
                        summary["parish_count_mismatches"].append((rid, f_, n, csums.get(f_)))
        elif rid in races_in_scope:
            summary["races_missing"].append(("parish", rid))
        if ek in data:
            early_codes = set()
            for p in data[ek]:
                code = str(p.get("ParishValue", ""))
                early_codes.add(code)
                if code not in parish_names and code not in summary["unknown_parishes"]:
                    summary["unknown_parishes"].append(code)
                if pk in data:
                    early_ids = {str(c.get("ID")) for c in p.get("Choice") or [] if isinstance(c, dict)}
                    summary["early_choices_missing"] += [(rid, code, c) for (pc, c) in sorted(totals)
                                                         if pc == code and c not in early_ids
                                                         and str(p.get("HasReported")) == "1"]
                if str(p.get("HasReported")) != "1":
                    summary["early_not_reported"].append((rid, code))
                    continue
                prow = dict(crow, level="county", source_sha256=sha[ek], county_id=code,
                            county_name=parish_names.get(code, ""))
                for c in _dicts(p.get("Choice"), (ek, code), summary):
                    cid = str(c.get("ID"))
                    key = (rid, code, cid, "EarlyVoting")
                    if key in seen:
                        summary["duplicate_entries"].append(key)
                    seen.add(key)
                    n = count(c.get("VoteTotal"), ("early", rid, code, cid))
                    if pk in data:
                        t = totals.get((code, cid))
                        if (code, cid) not in totals:
                            summary["early_choices_unknown"].append((rid, code, cid))
                        elif n is not None and t is not None and n > t:
                            summary["early_exceeds_total"].append((rid, code, cid, n, t))
                    desc, party = choice_info(rid, cid)
                    rows.append(dict(prow, choice_id=cid, choice=desc, party=party, vote_type="EarlyVoting",
                                     votes="" if n is None else n))
            if pk in data:
                summary["early_parishes_missing"] += [(rid, c) for c in sorted({pc for pc, _ in totals} - early_codes)]
        elif rid in races_in_scope:
            summary["races_missing"].append(("early", rid))
    summary["parishes"] = len({t["county_id"] for t in turnout})

    in_votes = "votes" in data and all(r in votes for r in races_in_scope)
    parish_read = all(f"parish-{r}" in data for r in races_in_scope) and in_votes
    if not parish_read:
        for k in PARISH_LISTS:
            summary[k] = None
    if not all(f"early-{r}" in data for r in races_in_scope) or not all(f"parish-{r}" in data for r in races_in_scope):
        for k in EARLY_LISTS:
            summary[k] = None
    if not in_votes:
        summary["runoff_races"] = None
    if "votes" not in data or "races" not in data:
        for k in RACE_LISTS:
            summary[k] = None
    return rows, summary, turnout
