"""Parse Tally ENR results (AR, ND) into common-format rows, county level.

Design: docs/superpowers/specs/2026-11-21-step2-tally-reader-design.md.

A pass record lists three kinds of saved responses, each wrapped in the same envelope
(versionID, lastUpdated, electionID, isOfficial, errorMessage, response):
- info (Election/GetElectionInfo): election name and date, parties, counties (by FIPS code);
- list (Contest/GetContestSearchList): contest names, voteFor, choice names;
- results (Contest/GetContestResults, one per contest type): per contest the statewide
  choices and, under "locations", the same per county (FIPS code).

Rows: state rows from each contest's choices, county rows from each county's choices,
vote_type "TOTAL" (no vote types in these files), contest_scope "statewide". Names are
joined by id: contest and choice from the list, party from info by partyID, county from
info by FIPS code. choice is the list's name as published (it carries a party prefix,
e.g. "REP Tom Cotton"). reporting_status is "<reporting>/<total> precincts", plus
", <n> partial" when some precincts are partially reported. source_created_at is the
results file's lastUpdated.

Nothing is corrected; the summary lists: each file's isOfficial, the distinct versionIDs
(more than one means the files come from different moments), responses for another
election, non-empty errorMessage, contests or choices missing from the list (rows kept
with empty names), unknown party or county ids, county sums that differ from the
contest's own statewide choice totals, write-in entries in the writeInChoices arrays
(listed, not emitted), write-ins published as an ordinary choice (North Dakota's "write-in",
id 9901: rows kept, since they are part of the totals, and listed under write_in_choices),
vote counts that aren't integers (row kept with votes "", left out of the sums), files that
are missing from the pass or can't be read as a JSON object, results files with no contests,
and contests with no county results (so an empty file never reads as a clean check). A file
whose response is null (an error reply) is read as empty and its errorMessage listed.
"""
import hashlib
import json
import os
import re

from pipeline.schema import COLUMNS


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v)
    return None


def _status(x):
    s = f"{x.get('precinctsReporting')}/{x.get('totalPrecincts')} precincts"
    partial = x.get("precinctsPartiallyReporting") or 0
    return s + (f", {partial} partial" if partial else "")


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)

    def load(p):
        p = p if os.path.isabs(p) else os.path.join(base_dir, p)
        with open(p, "rb") as f:
            body = f.read()
        d = json.loads(body.decode("utf-8-sig"))
        if not isinstance(d, dict):
            raise ValueError(f"top level is {type(d).__name__}, not an object")
        return d, hashlib.sha256(body).hexdigest()

    summary = {"contests": 0, "choices": 0, "counties": 0, "is_official": {}, "version_ids": [],
               "election_id_mismatches": [], "errors": [], "contests_missing_from_list": [],
               "choices_missing_from_list": [], "unknown_party_ids": [], "unknown_location_ids": [],
               "mismatches_counties_vs_state": [], "write_ins": [], "write_in_choices": [], "non_numeric_votes": [],
               "unreadable_files": [], "missing_files": [], "contests_without_counties": [],
               "results_files_without_contests": []}
    docs = []
    for x in rec["files"]:
        label = x["kind"] if x["kind"] != "results" else f"results-{x['type']}"
        try:
            d, sha = load(x["path"])
        except (OSError, ValueError) as e:
            summary["unreadable_files"].append((label, f"{x['path']}: {e}"))
            if x["kind"] == "results":
                summary["results_files_without_contests"].append(label)
            continue
        if not isinstance(d.get("response"), dict):
            d["response"] = {}
        docs.append((x, label, d, sha))
        summary["is_official"][label] = d.get("isOfficial")
        if d.get("versionID") not in summary["version_ids"]:
            summary["version_ids"].append(d.get("versionID"))
        if str(d.get("electionID")) != str(rec["election_id"]):
            summary["election_id_mismatches"].append((label, d.get("electionID")))
        if d.get("errorMessage"):
            summary["errors"].append((label, d["errorMessage"]))

    kinds = {x["kind"] for x in rec["files"]}
    summary["missing_files"] = [k for k in ("info", "list", "results") if k not in kinds]
    info = next((d["response"] for x, _, d, _ in docs if x["kind"] == "info"), {}) or {}
    names = next((d["response"].get("contests") for x, _, d, _ in docs if x["kind"] == "list"), {}) or {}
    parties = info.get("parties") or {}
    places = info.get("locations") or {}

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide", vote_type="TOTAL",
                election_name=info.get("name") or "", election_date=(info.get("date") or "")[:10])
    rows, counties, unknown_party, unknown_loc = [], set(), [], []

    def emit(contest, ch, level, extra):
        cid, chid = contest["contestID"], str(ch.get("choiceID"))
        listed = names.get(cid)
        entry = ((listed or {}).get("choices") or {}).get(chid, {})
        name = entry.get("name", "")
        if (entry.get("isWriteIn") or name.strip().lower() in ("write-in", "write-ins", "write in")) \
                and (cid, chid) not in summary["write_in_choices"]:
            summary["write_in_choices"].append((cid, chid))
        if listed and chid not in (listed.get("choices") or {}) and (cid, chid) not in summary["choices_missing_from_list"]:
            summary["choices_missing_from_list"].append((cid, chid))
        pid = (ch.get("partyID") or "").strip()
        party = ""
        if pid:
            if pid in parties:
                party = parties[pid].get("partyName") or ""
            elif (cid, chid, pid) not in unknown_party:
                unknown_party.append((cid, chid, pid))
        votes = _int(ch.get("totalVotes"))
        if votes is None:
            summary["non_numeric_votes"].append((cid, extra.get("county_id", ""), chid, ch.get("totalVotes")))
        rows.append(dict(base, **extra, level=level, contest_id=cid, contest_name=(listed or {}).get("contestName", ""),
                         vote_for=str((listed or {}).get("voteFor", "")), choice=name, choice_id=chid, party=party,
                         votes="" if votes is None else votes))
        return chid, votes

    for x, label, d, sha in docs:
        if x["kind"] != "results":
            continue
        common = {"source_sha256": sha, "source_created_at": d.get("lastUpdated") or ""}
        contests = d["response"].get("contests") or {}
        if not contests:
            summary["results_files_without_contests"].append(label)
        for cid, c in contests.items():
            summary["contests"] += 1
            if cid not in names:
                summary["contests_missing_from_list"].append(cid)
            state_totals = {}
            for ch in c.get("choices") or []:
                summary["choices"] += 1
                chid, v = emit(c, ch, "state", dict(common, reporting_status=_status(c)))
                state_totals[chid] = v
            for w in c.get("writeInChoices") or []:
                summary["write_ins"].append((cid, "", w))
            sums = {}
            if not c.get("locations"):
                summary["contests_without_counties"].append(cid)
            for loc_id, loc in (c.get("locations") or {}).items():
                counties.add(loc_id)
                if loc_id not in places:
                    unknown_loc.append((cid, loc_id))
                extra = dict(common, county_id=loc_id, county_name=(places.get(loc_id) or {}).get("locationName", ""),
                             reporting_status=_status(loc))
                for ch in loc.get("choices") or []:
                    chid, v = emit(c, ch, "county", extra)
                    if v is not None:
                        sums[chid] = sums.get(chid, 0) + v
                for w in (loc.get("writeinChoices") or []) + (loc.get("writeInChoices") or []):
                    summary["write_ins"].append((cid, loc_id, w))
            if c.get("locations"):
                for chid in list(state_totals) + [k for k in sums if k not in state_totals]:
                    if state_totals.get(chid) != sums.get(chid, 0):
                        summary["mismatches_counties_vs_state"].append((cid, chid, state_totals.get(chid), sums.get(chid, 0)))
    summary["counties"] = len(counties)
    summary["unknown_party_ids"] = unknown_party
    summary["unknown_location_ids"] = unknown_loc
    return rows, summary
