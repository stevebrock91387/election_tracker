"""Parse ResultsAjax-engine results (MT, NE, NM, OR, SD) into common-format rows, county level.

Design: docs/superpowers/specs/2026-11-21-step2-resultsajax-reader-design.md.

parse_page reads a results page's BuildCounty('<type>', '<raceID>', '<osn>', '<party>')
calls: one per race shown on that page.

parse_race reads one race's GetMapData JSON: {"d": [...]} or, in New Mexico, a bare list.
{"d": null} means no data (Montana returns it when party is not 0).

parse_media_csv reads a media CSV (statewide totals; SD, NE, NM): one row per (race,
candidate). PrecinctsReporting may be written ="671/671"; the wrapper is removed.

parse_pass turns a fetch pass record into rows and a summary:
- County rows only from the race JSON, vote_type "TOTAL" (no vote types published),
  contest_scope "statewide", party = PartyCode as published (Oregon's "NON" kept),
  reporting_status "<PrecinctsReporting>/<TotalPrecincts> precincts" as published.
  county_id has surrounding whitespace stripped (New Mexico pads it): the one normalisation.
- State rows only from media CSVs; Montana and Oregon publish none, so they get none and
  statewide_check is "not available" rather than a clean result.
- Ids are compared as strings. Nothing is corrected; the summary lists races with no data,
  failed races (from the pass record), duplicate (race, county, candidate) keys, county
  sums that differ from the media CSV, and races found only on pages or only in the CSV.
  A vote count that isn't an integer (New Mexico publishes "*" for one county) gets
  votes "" and is listed under non_numeric_votes; it is left out of the county sum, so the
  media check shows the gap rather than hiding it.
"""
import csv
import hashlib
import io
import json
import os
import re

from pipeline.schema import COLUMNS

_BUILD_COUNTY = re.compile(r"BuildCounty\('([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)")


def parse_page(html):
    """[(type, race_id, osn, party)] in page order, duplicates removed."""
    out = []
    for m in _BUILD_COUNTY.finditer(html):
        if m.groups() not in out:
            out.append(m.groups())
    return out


def parse_race(body):
    """Records of one race's GetMapData response; None when the service returned no data."""
    data = json.loads(body.decode("utf-8-sig"))
    if isinstance(data, dict):
        return data.get("d")
    return data


def _unwrap(value):
    m = re.fullmatch(r'="(.*)"', value or "")
    return m.group(1) if m else (value or "")


def parse_media_csv(text):
    """{(race_id, candidate_id): {votes, race_name, candidate_name, party, precincts}}."""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("RaceID"):
            continue
        out[(row["RaceID"].strip(), row["CandidateID"].strip())] = {
            "votes": int(row["CandidateVotes"]), "race_name": row.get("RaceName") or "",
            "candidate_name": row.get("CandidateName") or "", "party": row.get("PartyCode") or "",
            "vote_for": row.get("VoteFor") or "", "precincts": _unwrap(row.get("PrecinctsReporting"))}
    return out


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    state, source_id = rec["state"], rec["source_id"]

    def path(p):
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=state, source_id=source_id, contest_scope="statewide", vote_type="TOTAL")
    summary = {"races_on_pages": 0, "races_parsed": 0, "races_no_data": [], "failed_races": rec["failed_races"],
               "counties_per_race": {}, "duplicate_keys": [], "statewide_check": "not available",
               "mismatches_counties_vs_media": [], "media_races_not_on_pages": [], "page_races_not_in_media": [],
               "non_numeric_votes": []}
    page_races, media, media_sha, rows = [], {}, {}, []
    for x in rec["files"]:
        if x["kind"] == "page":
            for _, race_id, _, _ in parse_page(_read(path(x["path"])).decode("utf-8", "replace")):
                if race_id not in page_races:
                    page_races.append(race_id)
        elif x["kind"] == "media":
            body = _read(path(x["path"]))
            sha = hashlib.sha256(body).hexdigest()
            for k, v in parse_media_csv(body.decode("utf-8-sig", "replace")).items():
                media[k], media_sha[k] = v, sha
            summary["statewide_check"] = "media CSV"
    summary["races_on_pages"] = len(page_races)

    sums, seen, parsed = {}, set(), []
    for x in rec["files"]:
        if x["kind"] != "race":
            continue
        body = _read(path(x["path"]))
        records = parse_race(body)
        if not records:
            summary["races_no_data"].append(x["race_id"])
            continue
        parsed.append(x["race_id"])
        sha = hashlib.sha256(body).hexdigest()
        counties = set()
        for r in records:
            race, cand, cid = str(r["RaceID"]), str(r["CandidateID"]), str(r["CountyID"]).strip()
            if (race, cid, cand) in seen:
                summary["duplicate_keys"].append((race, cid, cand))
            seen.add((race, cid, cand))
            counties.add(cid)
            raw = str(r["calcCandidateVotes"]).strip()
            if re.fullmatch(r"-?\d+", raw):
                votes = int(raw)
                sums[(race, cand)] = sums.get((race, cand), 0) + votes
            else:
                votes = ""
                summary["non_numeric_votes"].append((race, cid, cand, raw))
            rows.append(dict(base, source_sha256=sha, level="county", county_id=cid,
                             county_name=r.get("CountyName") or "", contest_id=race,
                             contest_name=r.get("RaceName") or "", vote_for=str(r.get("VoteFor", "")),
                             choice=r.get("calcCandidate") or "", choice_id=cand, party=r.get("PartyCode") or "",
                             votes=votes,
                             reporting_status=f"{r.get('PrecinctsReporting')}/{r.get('TotalPrecincts')} precincts"))
        summary["counties_per_race"][x["race_id"]] = len(counties)
    summary["races_parsed"] = len(parsed)

    for (race, cand), v in media.items():
        rows.append(dict(base, source_sha256=media_sha[(race, cand)], level="state", contest_id=race,
                         contest_name=v["race_name"], vote_for=v["vote_for"], choice=v["candidate_name"],
                         choice_id=cand, party=v["party"], votes=v["votes"],
                         reporting_status=f"{v['precincts']} precincts" if v["precincts"] else ""))
    if summary["statewide_check"] == "media CSV":
        media_races = {race for race, _ in media}
        for key in sorted(set(media) | {k for k in sums if k[0] in media_races}):
            if key[0] not in parsed:
                continue
            csv_v, sum_v = media.get(key, {}).get("votes"), sums.get(key, 0)
            if csv_v != sum_v:
                summary["mismatches_counties_vs_media"].append((key[0], key[1], csv_v, sum_v))
        summary["media_races_not_on_pages"] = sorted(media_races - set(page_races))
        summary["page_races_not_in_media"] = [r for r in page_races if r not in media_races]
    return rows, summary
