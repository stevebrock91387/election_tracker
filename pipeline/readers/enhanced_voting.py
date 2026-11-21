"""Parse an Enhanced Voting media export (JSON) into common-format rows.

Format reference: docs/Arizona Media JSON Guide.pdf and docs/az-feed.md.

- Statewide items: TOTAL + one row per vote-type group (statewide statuses are
  documented as unused, so reporting_status is "").
- County items: TOTAL (status "") + groups, each group row carrying the county's
  status for that group when the file gives one (UT gives none).
- Precinct results: TOTAL + groups, all carrying the precinct's reportingStatus.
- Missing groupResults or precinctResults just produce fewer rows.
- Ranked-choice contests (contestType "RankChoice", or non-empty
  rankedChoiceResults / the guide's spelling rankChoiceResults) are not
  parsed: no rows are emitted for them, and each is listed in
  summary["skipped_ranked_choice"] as (county or "statewide", id, name).
  Nothing is half-parsed, and one local RCV race (e.g. Arlington County, VA)
  does not block the rest of the file.
- contest_scope is "statewide" for any contest id present in the state-level
  ballotItems (checked on all seven 2026 files: a county item with such an id
  is always the same race, only its name may differ), else "local".
- A file using the guide's alternate name "localityResults" instead of
  "localResults" raises UnsupportedFormat rather than parse as zero counties.

Nothing is corrected. The summary reports:
- statewide total vs the sum of county totals, matched by (contest id, option
  id): the guide's option key. Option names are not reliable keys (GA spells
  "Richard Woods (I) (Rep)" and "Richard Woods (I)(Rep)" under one id).
  pairs_compared counts matched pairs; options_only_in_counties lists county
  options with no statewide match in a statewide contest.
- vote-type groups vs the option total, at state, county and precinct level.
  Groups with a null voteCount are listed in groups_not_published instead,
  since nothing can be summed.
"""
import collections
import hashlib
import json

from pipeline.schema import COLUMNS


class UnsupportedFormat(ValueError):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse(path, state, source_id):
    with open(path, "rb") as f:
        d = json.load(f)
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=state, source_id=source_id, source_sha256=_sha256(path),
                source_created_at=d.get("createdAt", ""), election_name=d.get("electionName", ""),
                election_date=d.get("electionDate", ""))
    rows = []
    summary = {"election_name": d.get("electionName", ""), "created_at": d.get("createdAt", ""),
               "counties": len(d.get("localResults") or []), "has_precincts": False,
               "has_vote_types": False, "mismatches_state_vs_counties": [],
               "pairs_compared": 0, "options_only_in_counties": [],
               "mismatches_groups_vs_total": [], "groups_not_published": [],
               "skipped_ranked_choice": []}
    if "localResults" not in d and "localityResults" in d:
        raise UnsupportedFormat("file uses 'localityResults'; this reader expects 'localResults'")

    def skip_ranked_choice(item, where):
        if (item.get("rankedChoiceResults") or item.get("rankChoiceResults")
                or item.get("contestType") == "RankChoice"):
            summary["skipped_ranked_choice"].append((where, item.get("id"), item.get("name")))
            return True
        return False

    statewide_ids = {item["id"] for item in d["results"]["ballotItems"]}

    def contest(item):
        scope = "statewide" if item["id"] in statewide_ids else "local"
        return dict(contest_id=item["id"], contest_scope=scope, contest_name=item["name"],
                    contest_type=item.get("contestType", ""), vote_for=item.get("voteFor", ""))

    def emit(fields, option, groups, statuses, total_status, level, county_id):
        common = dict(base, **fields, choice=option["name"], choice_id=option["id"],
                      party=option.get("politicalParty") or "")
        rows.append(dict(common, vote_type="TOTAL", votes=option["voteCount"],
                         reporting_status=total_status))
        for g in groups or []:
            summary["has_vote_types"] = True
            rows.append(dict(common, vote_type=g["groupName"], votes=g["voteCount"],
                             reporting_status=statuses(g["groupName"])))
        if groups:
            where = (level, county_id, fields.get("precinct_id", ""), fields["contest_id"], option["name"])
            if any(g["voteCount"] is None for g in groups):
                summary["groups_not_published"].append(where)
            else:
                gsum = sum(g["voteCount"] for g in groups)
                if gsum != option["voteCount"]:
                    summary["mismatches_groups_vs_total"].append(where + (option["voteCount"], gsum))

    statewide = {}
    for item in d["results"]["ballotItems"]:
        if skip_ranked_choice(item, "statewide"):
            continue
        for o in item["ballotOptions"]:
            statewide[(item["id"], o["id"])] = (o["name"], o["voteCount"])
            emit(dict(level="state", **contest(item)), o, o.get("groupResults"),
                 lambda g: "", "", "state", "")

    county_sum = collections.Counter()
    county_name = {}
    for c in d.get("localResults") or []:
        status_by_group = {s["groupName"]: s["status"] for s in (c.get("reportingStatuses") or [])}
        cfields = dict(county_id=c["id"], county_name=c["name"])
        for item in c["ballotItems"]:
            if skip_ranked_choice(item, c["name"]):
                continue
            for o in item["ballotOptions"]:
                county_sum[(item["id"], o["id"])] += o["voteCount"] or 0
                county_name.setdefault((item["id"], o["id"]), o["name"])
                emit(dict(level="county", **cfields, **contest(item)), o, o.get("groupResults"),
                     lambda g: status_by_group.get(g, ""), "", "county", c["id"])
                for p in o.get("precinctResults") or []:
                    summary["has_precincts"] = True
                    pfields = dict(level="precinct", **cfields, precinct_id=p["id"],
                                   precinct_name=p["name"], precinct_is_virtual=p.get("isVirtual"),
                                   **contest(item))
                    st = p.get("reportingStatus") or ""
                    emit(pfields, dict(o, voteCount=p["voteCount"]), p.get("groupResults"),
                         lambda g, st=st: st, st, "precinct", c["id"])

    statewide_contests = {cid for cid, _ in statewide}
    for key, (name, total) in statewide.items():
        if key in county_sum:
            summary["pairs_compared"] += 1
            if county_sum[key] != total:
                summary["mismatches_state_vs_counties"].append((key[0], key[1], name, total, county_sum[key]))
    for key, csum in county_sum.items():
        if key[0] in statewide_contests and key not in statewide:
            summary["options_only_in_counties"].append((key[0], key[1], county_name[key], csum))
    return rows, summary
