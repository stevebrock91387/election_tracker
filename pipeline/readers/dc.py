"""Parse District of Columbia results: DCBOE's precinct CSV checked against its citywide JSON.

Design: docs/superpowers/specs/2026-11-24-step2-dc-reader-design.md.

A pass record lists: info (getElectionInfo: ElectionName, ElectionDate, LastUpdated,
PrecinctsCounted, TotalPrecincts, ElectionResultsTypeName, CsvLink), csv (ElectionDate,
ElectionName, ContestNumber, ContestName, PrecinctNumber, WardNumber, Candidate, Party, Votes; one row
per precinct, contest and candidate, plus ContestNumber -2 registered voters and -1 ballots cast per
precinct) and citywide (getCityWide: contests with ContestNumber, OfficeName, IsRCV and ElectionData
[{Contestant, Votes, CandidateNumber, PartyCode}]). Candidate and Contestant are the same text
("DEM Robert White", "Write-in", "OVER VOTES", "UNDER VOTES").

Rows (contests >= 0 whose name doesn't start "ANC-"): precinct rows from the CSV (county_id 11001,
precinct_name "Ward <w> Precinct <p>"), state rows from the citywide JSON. choice_id = the
citywide CandidateNumber, "" for OVER VOTES and UNDER VOTES. party = the CSV's Party (the JSON gives
over and under votes a candidate's party); the JSON's PartyCode only when the CSV wasn't read.
contest_type "RCV first rank" for IsRCV contests. The turnout table has one row per precinct: ward,
registered voters, ballots cast.

Nothing is corrected; the summary lists: precinct sums that differ from citywide votes, citywide
lines with no CSV rows and CSV lines with no citywide line, party differences (over/under excepted),
precincts whose ward differs between rows, duplicate (contest, precinct, candidate), non-integer
votes (votes ""), precincts missing the registered or ballots row, ballots above registered, the
info's precinct count vs the CSV's (None when the info or its count is unusable), CSV contest
numbers that are neither a non-negative integer nor -1/-2 (rows skipped), citywide lines with no
usable CandidateNumber (choice_id "") and repeated citywide lines (last kept), malformed entries,
and missing or unreadable files. Checks that
need a file that wasn't read are None.
"""
import csv
import hashlib
import io
import json
import os
import re

from pipeline.schema import COLUMNS

NOT_CHOICES = {"OVER VOTES", "UNDER VOTES"}
CSV_HEAD = {"ContestNumber", "ContestName", "PrecinctNumber", "WardNumber", "Candidate", "Party", "Votes"}
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "precinct_id", "ward", "registered_voters", "ballots_cast"]
CROSS = ["precinct_vs_citywide_mismatches", "citywide_lines_without_precincts", "precinct_lines_without_citywide",
         "party_differences"]
CSV_ONLY = ["ward_conflicts", "duplicate_entries", "ballots_exceed_registered", "precincts_missing_specials",
            "precinct_count_mismatch", "unexpected_contest_numbers"]
LISTS = CROSS + CSV_ONLY + ["non_numeric", "malformed_entries", "missing_candidate_numbers", "duplicate_citywide_lines"]


def _int(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d+", v.strip()):
        return int(v)
    return None


def _in_scope(number, name):
    n = _int(number) if not str(number).startswith("-") else -1
    return n is not None and n >= 0 and not str(name or "").startswith("ANC-")


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"contests": 0, "precincts": 0, "results_type": ""}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in ("info", "csv", "citywide") if k not in paths]
    data, sha = {}, {}
    for k in ("info", "csv", "citywide"):
        if k not in paths:
            continue
        try:
            with open(paths[k], "rb") as f:
                body = f.read()
            text = body.decode("utf-8-sig")
            if k == "csv":
                reader = csv.DictReader(io.StringIO(text))
                if not CSV_HEAD <= set(reader.fieldnames or []):
                    raise ValueError("CSV header lacks expected columns")
                obj = list(reader)
            else:
                obj = json.loads(text)
                if k == "info" and not isinstance(obj, dict):
                    raise ValueError("not a JSON object")
                if k == "citywide" and not isinstance(obj, list):
                    raise ValueError("not a JSON list")
            data[k], sha[k] = obj, hashlib.sha256(body).hexdigest()
        except (OSError, ValueError, UnicodeDecodeError) as e:
            summary["unreadable_files"].append((k, str(e)))

    info = data.get("info", {})
    summary["results_type"] = info.get("ElectionResultsTypeName") or ""
    date = info.get("ElectionDate") if isinstance(info.get("ElectionDate"), str) else ""
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide", vote_type="TOTAL",
                election_name=info.get("ElectionName") or "", election_date=date[:10])
    rows = []

    # Citywide lines: candidate numbers, votes, RCV flags.
    city, cand_no, rcv, city_party = {}, {}, {}, {}
    if "citywide" in data:
        for c in data["citywide"]:
            if not isinstance(c, dict):
                summary["malformed_entries"].append(("citywide", "contest"))
                continue
            if c.get("ContestNumber") is None:
                summary["malformed_entries"].append(("citywide", "ContestNumber", c.get("OfficeName")))
                continue
            cno, name = str(c.get("ContestNumber")), c.get("OfficeName") or ""
            if not _in_scope(cno, name):
                continue
            rcv[cno] = c.get("IsRCV") is True
            data_ = c.get("ElectionData")
            if not isinstance(data_, list):
                summary["malformed_entries"].append(("citywide", cno, "ElectionData"))
                continue
            for e in data_:
                if not isinstance(e, dict) or not isinstance(e.get("Contestant"), str):
                    summary["malformed_entries"].append(("citywide", cno))
                    continue
                who = e["Contestant"]
                if (cno, who) in city:
                    summary["duplicate_citywide_lines"].append((cno, who))
                city[(cno, who)] = (_int(e.get("Votes")), name)
                if who not in NOT_CHOICES:
                    num = e.get("CandidateNumber")
                    if (isinstance(num, int) and not isinstance(num, bool)) or (isinstance(num, str) and num.strip()):
                        cand_no[(cno, who)] = str(num)
                    else:
                        summary["missing_candidate_numbers"].append((cno, who))
                city_party[(cno, who)] = e.get("PartyCode") or ""
                if _int(e.get("Votes")) is None:
                    summary["non_numeric"].append(("citywide", cno, "", who, e.get("Votes")))

    # Precinct rows and turnout from the CSV.
    turnout, csv_party, sums = [], {}, {}
    if "csv" in data:
        wards, specials, seen, csv_lines = {}, {}, set(), set()
        for r in data["csv"]:
            cno, name, prec = r.get("ContestNumber") or "", r.get("ContestName") or "", r.get("PrecinctNumber") or ""
            ward, who = r.get("WardNumber") or "", r.get("Candidate") or ""
            if ward and wards.setdefault(prec, ward) != ward:
                summary["ward_conflicts"].append((prec, wards[prec], ward))
            n = _int(r.get("Votes"))
            if cno in ("-2", "-1"):
                specials.setdefault(prec, {})["registered" if cno == "-2" else "ballots"] = n
                if n is None:
                    summary["non_numeric"].append(("csv", cno, prec, "", r.get("Votes")))
                continue
            if not re.fullmatch(r"\d+", cno.strip()):
                if (cno, name) not in summary["unexpected_contest_numbers"]:
                    summary["unexpected_contest_numbers"].append((cno, name))
                continue
            if not _in_scope(cno, name):
                continue
            key = (cno, prec, who)
            if key in seen:
                summary["duplicate_entries"].append(key)
            seen.add(key)
            if n is None:
                summary["non_numeric"].append(("csv", cno, prec, who, r.get("Votes")))
            else:
                sums[(cno, who)] = sums.get((cno, who), 0) + n
            csv_lines.add((cno, who))
            party = "" if who in NOT_CHOICES else (r.get("Party") or "")
            csv_party.setdefault((cno, who), party)
            rows.append(dict(base, level="precinct", source_sha256=sha["csv"], county_id="11001",
                             county_name="District of Columbia", precinct_id=prec,
                             precinct_name=f"Ward {ward} Precinct {prec}", contest_id=cno, contest_name=name,
                             contest_type="RCV first rank" if rcv.get(cno) else "",
                             choice_id=cand_no.get((cno, who), ""), choice=who, party=party,
                             votes="" if n is None else n))
        for prec in sorted(wards, key=lambda p: _int(p) or 0):
            sp = specials.get(prec, {})
            for k in ("registered", "ballots"):
                if k not in sp:
                    summary["precincts_missing_specials"].append((prec, k))
            if sp.get("registered") is not None and sp.get("ballots") is not None and sp["ballots"] > sp["registered"]:
                summary["ballots_exceed_registered"].append((prec, sp["ballots"], sp["registered"]))
            turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha["csv"], precinct_id=prec,
                                ward=wards[prec], registered_voters=sp.get("registered", ""), ballots_cast=sp.get("ballots", "")))
        summary["precincts"] = len(wards)
        counted = _int(info.get("PrecinctsCounted")) if isinstance(info.get("PrecinctsCounted"), (int, str)) else None
        if "info" not in data or counted is None:
            summary["precinct_count_mismatch"] = None
        elif counted != len(wards):
            summary["precinct_count_mismatch"].append((counted, len(wards)))
        if "citywide" in data:
            for key, (n, _) in city.items():
                if key not in sums and key not in csv_lines:
                    summary["citywide_lines_without_precincts"].append(key)
                elif n is not None and sums.get(key) != n:
                    summary["precinct_vs_citywide_mismatches"].append(key + (n, sums.get(key)))
            summary["precinct_lines_without_citywide"] = sorted(k for k in csv_lines if k not in city)
            for key, p in city_party.items():
                if key[1] not in NOT_CHOICES and key in csv_party and csv_party[key] != p:
                    summary["party_differences"].append(key + (p, csv_party[key]))
    else:
        for k in CSV_ONLY:
            summary[k] = None
    if "csv" not in data or "citywide" not in data:
        for k in CROSS:
            summary[k] = None

    # State rows from the citywide JSON.
    contests = set()
    for (cno, who), (n, name) in city.items():
        contests.add(cno)
        party = csv_party.get((cno, who), "") if "csv" in data else ("" if who in NOT_CHOICES else city_party.get((cno, who), ""))
        rows.append(dict(base, level="state", source_sha256=sha["citywide"], source_created_at=info.get("LastUpdated") or "",
                         reporting_status=f"{info.get('PrecinctsCounted', '')}/{info.get('TotalPrecincts', '')} precincts, "
                                          f"{summary['results_type']}",
                         contest_id=cno, contest_name=name, contest_type="RCV first rank" if rcv.get(cno) else "",
                         choice_id=cand_no.get((cno, who), ""), choice=who, party=party, votes="" if n is None else n))
    summary["contests"] = len(contests) if "citywide" in data else len({r["contest_id"] for r in rows})
    return rows, summary, turnout
