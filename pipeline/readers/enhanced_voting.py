"""Parse an Enhanced Voting media export (JSON) into common-format rows.

Format reference: docs/Arizona Media JSON Guide.pdf and docs/az-feed.md.

- Statewide items: TOTAL + one row per vote-type group (statewide statuses are
  documented as unused, so reporting_status is "").
- County items: TOTAL (status "") + groups, each group row carrying the county's
  status for that group when the file gives one (UT gives none).
- Precinct results: TOTAL + groups, all carrying the precinct's reportingStatus.
- Missing groupResults or precinctResults just produce fewer rows.
- Ranked-choice results are not handled: UnsupportedFormat.

Nothing is corrected. Two internal mismatches are reported in the summary:
statewide total vs the sum of county totals (contest/choice pairs present in
both), and vote-type groups vs the option total.
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
               "mismatches_groups_vs_total": []}

    def check_item(item, where):
        if item.get("rankedChoiceResults"):
            raise UnsupportedFormat(f"{where}: ranked-choice results in {item.get('id')} are not supported")

    def contest(item):
        return dict(contest_id=item["id"], contest_name=item["name"],
                    contest_type=item.get("contestType", ""), vote_for=item.get("voteFor", ""))

    def emit(fields, option, groups, statuses, total_status, level, county_id):
        common = dict(base, **fields, choice=option["name"], party=option.get("politicalParty") or "")
        rows.append(dict(common, vote_type="TOTAL", votes=option["voteCount"],
                         reporting_status=total_status))
        for g in groups or []:
            summary["has_vote_types"] = True
            rows.append(dict(common, vote_type=g["groupName"], votes=g["voteCount"],
                             reporting_status=statuses(g["groupName"])))
        if groups and level in ("state", "county"):
            gsum = sum(g["voteCount"] or 0 for g in groups)
            if gsum != option["voteCount"]:
                summary["mismatches_groups_vs_total"].append(
                    (level, county_id, fields["contest_id"], option["name"], option["voteCount"], gsum))

    statewide = {}
    for item in d["results"]["ballotItems"]:
        check_item(item, "statewide")
        for o in item["ballotOptions"]:
            statewide[(item["id"], o["name"])] = o["voteCount"]
            emit(dict(level="state", **contest(item)), o, o.get("groupResults"),
                 lambda g: "", "", "state", "")

    county_sum = collections.Counter()
    for c in d.get("localResults") or []:
        status_by_group = {s["groupName"]: s["status"] for s in (c.get("reportingStatuses") or [])}
        cfields = dict(county_id=c["id"], county_name=c["name"])
        for item in c["ballotItems"]:
            check_item(item, c["name"])
            for o in item["ballotOptions"]:
                county_sum[(item["id"], o["name"])] += o["voteCount"] or 0
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

    for key, total in statewide.items():
        if key in county_sum and county_sum[key] != total:
            summary["mismatches_state_vs_counties"].append((key[0], key[1], total, county_sum[key]))
    return rows, summary
