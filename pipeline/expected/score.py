"""The 2026 dry run: each county's actual top-race vote against its expected range (step 4).

classify_office(contest_name, state) -> "US SENATE" | "GOVERNOR" | "US HOUSE" | None. The name is
lower-cased, dots become spaces, whitespace collapses, and "u s" becomes "us". Then, in order:
- GOVERNOR: the whole name is "governor", optionally "for " before it, optionally followed by
  "and" / "&" / "/" and "lt" or "lieutenant governor" (a joint ticket). "Lieutenant Governor",
  "Governor's Council" and ballot questions mentioning the governor are None.
- DC: only "delegate to the house ..." (US HOUSE); DC's "United States Senator" and "United States
  Representative Citywide" are its shadow offices, None.
- None if the name has the word "state", "general assembly", "nc house", "board of education",
  "amendment" or "council".
- US SENATE: "us senate" / "us senator" / "united states senate(or)", or "senator in congress".
- US HOUSE: "us house" / "us representative" / "united states house|representative", "representative in|to
  ... congress", "member of congress", "us congress", or a name beginning "house of representatives",
  "member of (the) house of representatives" or "member, house of representatives" (NJ, VA).

actuals_2026(conn) -> (rows, listed); rows {state, county_name, county_id, top_office, votes, source_id,
withheld}. From each source's latest non-pruned snapshot, vote_type TOTAL rows at level county, or, for a
source with no county rows, its precinct rows summed by county. Choices that are tallies (over, under and
blank votes; TALLIES) don't count; a NULL vote (withheld by the source) counts 0 and is counted in withheld.
Contest votes per county are summed; US SENATE and GOVERNOR take their largest contest, US HOUSE sums its
contests (districts); the top office is the largest, ties US SENATE, GOVERNOR, US HOUSE. Not scored, listed:
states whose county units are towns (TOWN_STATES; also any source with level "town" rows), and sources
whose rows carry no county name. A county reported by two sources is kept once when they agree (source_id
names both), else listed.

score(expected_rows, actual_rows) -> (per_county, summary). Join: county_id when it is a 5-digit FIPS
starting with the state's FIPS prefix (taken from the expected rows' county_fips; TX AR ND FL DE IN), else
(state, norm_county(name)). per_county {state, county, county_fips, actual, point, low, high, method,
inside, miss, miss_pct, error_pct}: miss = actual - nearest bound (0 inside), miss_pct = miss / point,
error_pct = (actual - point) / point. summary[state] and summary["ALL"]: scored, inside_share,
median_abs_miss_pct, p90_abs_miss_pct, median_abs_error_pct (nearest rank); summary["not_scored"]: (state,
county, reason) for actuals with no expected row and expected rows (in states with any actual) with none.
"""
import collections
import math
import re

from pipeline.expected.compute import norm_county
from pipeline.expected.medsl import TALLIES

ORDER = ("US SENATE", "GOVERNOR", "US HOUSE")
TOWN_STATES = {"CT", "MA", "RI", "VT"}  # 2026 county units are towns (RI's EV "county" rows are its 39 towns + 1)
_GOV = re.compile(r"^(for )?governor(\s*(and|&|/)\s*(lt|lieutenant) governor)?$")
_NOT = re.compile(r"\bstate\b|general assembly|\bnc house\b|board of education|amendment|council")
_SEN = re.compile(r"\b(us|united states) senat(e|or)\b|\bsenator in congress\b")
_HOUSE = re.compile(r"\b(us|united states) (house|representative)|\brepresentative (in|to)\b.*\bcongress\b"
                    r"|\bmember of congress\b|\bus congress\b"
                    r"|^(member of (the )?|member, )?house of representatives\b")
_TALLY = {re.sub(r"\s+", "", t.lower()) for t in TALLIES} | {
    "overvotes", "undervotes", "blankvotes", "blanks", "blank", "invalidvotes", "blankbutcircled", "blankwriteins"}


def _norm(name):
    n = " ".join(name.lower().replace(".", " ").split())
    return re.sub(r"\bu s\b", "us", n)


def classify_office(contest_name, state):
    n = _norm(contest_name)
    if _GOV.match(n):
        return "GOVERNOR"
    if state == "DC":
        return "US HOUSE" if n.startswith("delegate to the house") else None
    if _NOT.search(n):
        return None
    if _SEN.search(n):
        return "US SENATE"
    if _HOUSE.search(n):
        return "US HOUSE"
    return None


def _tally(choice):
    return re.sub(r"\s+", "", (choice or "").lower()) in _TALLY


def actuals_2026(conn):
    snaps = conn.execute("""SELECT snapshot_id, source_id, state FROM snapshot s WHERE pruned = 0 AND first_seen_utc =
                            (SELECT max(first_seen_utc) FROM snapshot WHERE source_id = s.source_id AND pruned = 0)
                            ORDER BY source_id""").fetchall()
    listed, found = [], collections.defaultdict(list)
    for sid, source, state in snaps:
        levels = {r[0] for r in conn.execute("SELECT DISTINCT level FROM result WHERE snapshot_id = ?", (sid,))}
        if state in TOWN_STATES or "town" in levels:
            listed.append((state, source, "", "not scored: towns"))
            continue
        level = "county" if "county" in levels else "precinct"
        contest = collections.Counter()
        withheld = collections.Counter()
        ids = {}
        for cid, cname, contest_name, choice, votes in conn.execute(
                "SELECT county_id, county_name, contest_name, choice, votes FROM result "
                "WHERE snapshot_id = ? AND level = ? AND vote_type = 'TOTAL'", (sid, level)):
            office = classify_office(contest_name or "", state)
            if office is None or _tally(choice):
                continue
            key = cname or ""
            ids.setdefault(key, cid or "")
            contest[(key, office, contest_name)] += votes or 0
            withheld[key] += votes is None
        if not contest:
            continue
        if not any(k[0] for k in contest):
            listed.append((state, source, "", "not scored: no county names"))
            continue
        offices = collections.defaultdict(collections.Counter)
        for (county, office, _), v in contest.items():
            o = offices[county]
            o[office] = o[office] + v if office == "US HOUSE" else max(o[office], v)
        for county, o in offices.items():
            if not county:
                listed.append((state, source, "", "not scored: rows with no county name"))
                continue
            top = max(o, key=lambda x: (o[x], -ORDER.index(x)))
            found[(state, norm_county(county))].append({"state": state, "county_name": county, "county_id": ids[county],
                                                        "top_office": top, "votes": o[top], "source_id": source,
                                                        "withheld": withheld[county]})
    rows = []
    for (state, _), hits in sorted(found.items()):
        if len({(h["top_office"], h["votes"]) for h in hits}) > 1:
            listed.append((state, " ".join(h["source_id"] for h in hits), hits[0]["county_name"],
                           "not scored: sources differ (" + ", ".join(str(h["votes"]) for h in hits) + ")"))
            continue
        row = dict(hits[0])
        row["source_id"] = " ".join(h["source_id"] for h in hits)
        rows.append(row)
    return rows, sorted(listed)


def _rank(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[max(1, math.ceil(p * len(s))) - 1]


def _summary(per):
    return {"scored": len(per), "inside_share": sum(r["inside"] for r in per) / len(per) if per else None,
            "median_abs_miss_pct": _rank([abs(r["miss_pct"]) for r in per], 0.5),
            "p90_abs_miss_pct": _rank([abs(r["miss_pct"]) for r in per], 0.9),
            "median_abs_error_pct": _rank([abs(r["error_pct"]) for r in per], 0.5)}


def score(expected_rows, actual_rows):
    prefix = {}
    by_fips, by_name = {}, {}
    for e in expected_rows:
        prefix.setdefault(e["state"], e["county_fips"][:2])
        by_fips[e["county_fips"]] = e
        by_name[(e["state"], norm_county(e["county_name"]))] = e
    per, not_scored, used = [], [], set()
    for a in actual_rows:
        cid = a["county_id"]
        if len(cid) == 5 and cid.isdigit() and cid[:2] == prefix.get(a["state"]):
            e = by_fips.get(cid)
        else:
            e = by_name.get((a["state"], norm_county(a["county_name"])))
        if e is None or e["state"] != a["state"]:
            not_scored.append((a["state"], a["county_name"], "no expected row"))
            continue
        used.add((e["state"], e["county_fips"]))
        v = a["votes"]
        miss = v - e["high"] if v > e["high"] else v - e["low"] if v < e["low"] else 0
        per.append({"state": e["state"], "county": e["county_name"], "county_fips": e["county_fips"], "actual": v,
                    "point": e["point"], "low": e["low"], "high": e["high"], "method": e["method"],
                    "inside": miss == 0, "miss": miss, "miss_pct": miss / e["point"] if e["point"] else None,
                    "error_pct": (v - e["point"]) / e["point"] if e["point"] else None})
    states_with_actuals = {a["state"] for a in actual_rows}
    for e in expected_rows:
        if e["state"] in states_with_actuals and (e["state"], e["county_fips"]) not in used:
            not_scored.append((e["state"], e["county_name"], "no 2026 actual"))
    not_scored += [(r["state"], r["county"], "expected point 0") for r in per if r["miss_pct"] is None]
    per = [r for r in per if r["miss_pct"] is not None]
    summary = {st: _summary([r for r in per if r["state"] == st]) for st in sorted({r["state"] for r in per})}
    summary["ALL"] = _summary(per)
    summary["not_scored"] = sorted(not_scored)
    return per, summary
