"""Parse Texas results: the Civix ENR statewide file, checked against its county file.

Design: docs/superpowers/specs/2026-11-24-step2-tx-reader-design.md.

A pass record lists two files, both JSON objects whose values are base64-encoded JSON:
- election: Version (plain string), Home (ElecDate, LastUpdatedTime, reporting counts),
  Lookups (County: ID, CN name, MID FIPS) and four result sections, Federal, StateWide,
  StateWideQ (propositions) and Districted, each {OffType, Races: [{id, N, T, Candidates:
  [{ID, N, P, V, EV, ...}]}]}. A section (or its Races) may decode to null: no races.
- county: upload = {county ID: {N, Summary {RV, VC, PRR, NPL, PLR, ...}, Races: {office id:
  {OID, N, OT, PR, TP, C: {candidate id: {id, N, P, V, EV, ...}}}}}}. Candidate ids are
  lowercase "id" here; proposition choices have ids here but null ids in the statewide file.

Rows: state rows from the statewide file, county rows from the county file, vote types TOTAL
(V) and "Early Votes" (EV). District races are level "state" too. county_id is the FIPS code
(Lookups MID). contest_type is the statewide section's OffType for that office, on county
rows too. party is as published in each file (the files use different codes for the same
candidate, e.g. LIB vs L). source_created_at is Home.LastUpdatedTime on state rows and empty
on county rows (the county file states no time). election_date is Home.ElecDate as published.
Choices join across files on (office id, candidate id), or on (office id, choice name) where
the statewide id is null.

The turnout table (TURNOUT_COLUMNS) has one row per county from its Summary; whole-number
floats become integers, other values are kept as published.

Nothing is corrected; the summary lists: statewide values that differ from the county sums,
choices in one file and not the other (a race that some counties lack is normal; only a choice
no county carries is listed), party codes that differ between the files (once per choice),
county keys without a Lookups entry (county_id ""), early votes above total votes, non-integer
counts (votes "", left out of the sums), duplicate choices, an office in two sections, Home
counts with reported > total, county Summary sums that differ from Home, sections that can't
be decoded, and missing or unreadable files. A check that could not run is None.
"""
import base64
import binascii
import hashlib
import json
import os

from pipeline.schema import COLUMNS

SECTIONS = ("Federal", "StateWide", "StateWideQ", "Districted")
VOTE_TYPES = (("TOTAL", "V"), ("Early Votes", "EV"))
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters", "voters",
                   "precincts_reporting", "polling_locations_reporting", "polling_locations_total"]
CROSS = ["mismatches_state_vs_county", "state_choices_missing_from_county", "county_choices_missing_from_state",
         "party_differences", "home_vs_county_summary"]
STATE_ONLY = ["contests", "choices", "null_choice_ids", "party_codes", "office_in_two_sections",
              "home_reported_exceeds_total"]
COUNTY_ONLY = ["counties", "unknown_counties"]


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v):
    """Whole-number floats as integers; "" when absent; anything else as published."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _dec(v):
    return json.loads(base64.b64decode(v, validate=True).decode("utf-8"))


def _load(path):
    with open(path, "rb") as f:
        body = f.read()
    return hashlib.sha256(body).hexdigest(), json.loads(body.decode("utf-8"))


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"contests": 0, "choices": 0, "counties": 0, "version": "", "last_updated": "", "party_codes": {},
               "null_choice_ids": 0}
    for k in CROSS + ["unknown_counties", "early_exceeds_total", "non_numeric_votes", "duplicate_choices",
                      "office_in_two_sections", "home_reported_exceeds_total", "unreadable_sections",
                      "unreadable_files", "missing_files"]:
        summary[k] = []
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in ("election", "county") if k not in paths]
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide")
    rows, turnout = [], []

    # Statewide file.
    el = None
    if "election" in paths:
        try:
            esha, el = _load(paths["election"])
            if not isinstance(el, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as e:
            summary["unreadable_files"].append(("election", str(e)))
            el = None

    def section(name):
        if name not in el:
            return None
        try:
            return _dec(el[name])
        except (binascii.Error, ValueError, TypeError) as e:
            summary["unreadable_sections"].append((name, str(e)))
            return None

    home, fips, off_type, state_choices = {}, {}, {}, {}
    by_id, by_name = set(), set()
    if el is not None:
        summary["version"] = el.get("Version", "")
        home = section("Home") or {}
        summary["last_updated"] = home.get("LastUpdatedTime", "") or ""
        lookups = section("Lookups") or {}
        for c in lookups.get("County") or []:
            fips[str(c.get("ID"))] = str(c.get("MID", ""))
        base["election_date"] = home.get("ElecDate", "") or ""
        common = dict(base, level="state", source_sha256=esha, source_created_at=summary["last_updated"])
        sections_of = {}
        for name in SECTIONS:
            sec = section(name)
            if not sec:
                continue
            for r in sec.get("Races") or []:
                oid = r.get("id")
                sections_of.setdefault(oid, []).append(name)
                off_type.setdefault(oid, sec.get("OffType") or "")
                summary["contests"] += 1
                crow = dict(common, contest_id=str(oid), contest_name=r.get("N", ""), contest_type=sec.get("OffType") or "")
                for cand in r.get("Candidates") or []:
                    cid = cand.get("ID")
                    if cid is None:
                        summary["null_choice_ids"] += 1
                        key = cand.get("N", "")
                        by_name.add((oid, key))
                    else:
                        key = str(cid)
                        by_id.add((oid, key))
                    if (oid, key) in state_choices:
                        summary["duplicate_choices"].append(("state", "", oid, key))
                    state_choices[(oid, key)] = cand
                    summary["choices"] += 1
                    party = cand.get("P") or ""
                    summary["party_codes"][party] = summary["party_codes"].get(party, 0) + 1
                    _emit(rows, summary, dict(crow, choice=cand.get("N", ""), choice_id="" if cid is None else key,
                                              party=party), cand, ("state", "", oid, key))
        summary["office_in_two_sections"] = [(o, s) for o, s in sections_of.items() if len(s) > 1]
        for name, (a, b) in (("CountiesReporting", ("CR", "CT")), ("PrecinctsReporting", ("PR", "PT")),
                             ("PollingReporting", ("PLR", "PLT"))):
            h = home.get(name) or {}
            rep, tot = _int(h.get(a)), _int(h.get(b))
            if rep is not None and tot is not None and rep > tot:
                summary["home_reported_exceeds_total"].append((name, rep, tot))

    # County file.
    cty = None
    if "county" in paths:
        try:
            csha, raw = _load(paths["county"])
            cty = _dec(raw["upload"])
            if not isinstance(cty, dict):
                raise ValueError("upload is not a JSON object")
        except (OSError, ValueError, KeyError, TypeError, binascii.Error) as e:
            summary["unreadable_files"].append(("county", str(e)))
            cty = None
    sums, seen_county, party_diff = {}, set(), set()
    summary_sums = {"PRR": 0, "NPL": 0, "PLR": 0}
    if cty is not None:
        common = dict(base, level="county", source_sha256=csha)
        for ckey, c in cty.items():
            cname = c.get("N", "")
            if el is not None and ckey not in fips:
                summary["unknown_counties"].append((ckey, cname))
            cfips = fips.get(ckey, "")
            sm = c.get("Summary") or {}
            for k in summary_sums:
                v = _num(sm.get(k))
                summary_sums[k] = summary_sums[k] + v if isinstance(v, int) and summary_sums[k] is not None else None
            turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=csha, county_id=cfips,
                                county_name=cname, registered_voters=_num(sm.get("RV")), voters=_num(sm.get("VC")),
                                precincts_reporting=_num(sm.get("PRR")),
                                polling_locations_reporting=_num(sm.get("PLR")),
                                polling_locations_total=_num(sm.get("NPL"))))
            for oid_s, r in (c.get("Races") or {}).items():
                oid = int(oid_s) if str(oid_s).isdigit() else oid_s
                pr, tp = _num(r.get("PR")), _num(r.get("TP"))
                crow = dict(common, county_id=cfips, county_name=cname, contest_id=str(oid), contest_name=r.get("N", ""),
                            contest_type=off_type.get(oid, ""),
                            reporting_status=f"{pr}/{tp} precincts" if pr != "" and tp != "" else "")
                for cand in (r.get("C") or {}).values():
                    cid, name = cand.get("id"), cand.get("N", "")
                    if cid is not None and (oid, str(cid)) in by_id:
                        key = str(cid)
                    elif (oid, name) in by_name:
                        key = name
                    else:
                        key = name if cid is None else str(cid)
                        if el is not None and (oid, key) not in summary["county_choices_missing_from_state"]:
                            summary["county_choices_missing_from_state"].append((oid, key))
                    if (ckey, oid, key) in seen_county:
                        summary["duplicate_choices"].append(("county", cfips or ckey, oid, key))
                    seen_county.add((ckey, oid, key))
                    st = state_choices.get((oid, key))
                    party = cand.get("P") or ""
                    if st is not None and (st.get("P") or "") != party and (oid, key) not in party_diff:
                        party_diff.add((oid, key))
                        summary["party_differences"].append((oid, key, st.get("P") or "", party))
                    counts = _emit(rows, summary, dict(crow, choice=name, choice_id="" if cid is None else str(cid),
                                                       party=party), cand, ("county", cfips or ckey, oid, key))
                    acc = sums.setdefault((oid, key), {})
                    for vt, n in counts.items():
                        if n is not None:
                            acc[vt] = acc.get(vt, 0) + n
        summary["counties"] = len(cty)

    # Cross-checks.
    if el is not None and cty is not None:
        for (oid, key), cand in state_choices.items():
            if (oid, key) not in sums:
                summary["state_choices_missing_from_county"].append((oid, key))
                continue
            for vt, field in VOTE_TYPES:
                n = _int(cand.get(field))
                if n is not None and sums[(oid, key)].get(vt, 0) != n:
                    summary["mismatches_state_vs_county"].append((oid, key, vt, n, sums[(oid, key)].get(vt, 0)))
        checks = (("CountiesReporting.CT", _int((home.get("CountiesReporting") or {}).get("CT")), len(cty)),
                  ("PrecinctsReporting.PR", _int((home.get("PrecinctsReporting") or {}).get("PR")), summary_sums["PRR"]),
                  ("PollingReporting.PLR", _int((home.get("PollingReporting") or {}).get("PLR")), summary_sums["PLR"]),
                  ("PollingReporting.PLT", _int((home.get("PollingReporting") or {}).get("PLT")), summary_sums["NPL"]))
        for name, h, s in checks:
            if h is not None and s is not None and h != s:
                summary["home_vs_county_summary"].append((name, h, s))
    else:
        for k in CROSS:
            summary[k] = None
    if el is None:
        for k in STATE_ONLY:
            summary[k] = None
    if cty is None:
        for k in COUNTY_ONLY:
            summary[k] = None
    return rows, summary, turnout


def _emit(rows, summary, row, cand, where):
    """Append the TOTAL and Early Votes rows for one choice; return {vote type: int or None}."""
    level, unit, oid, key = where
    counts = {}
    for vt, field in VOTE_TYPES:
        raw = cand.get(field)
        n = _int(raw)
        if n is None:
            summary["non_numeric_votes"].append((level, unit, oid, key, vt, raw))
        counts[vt] = n
        rows.append(dict(row, vote_type=vt, votes="" if n is None else n))
    t, e = counts["TOTAL"], counts["Early Votes"]
    if t is not None and e is not None and e > t:
        summary["early_exceeds_total"].append((level, unit, oid, key, e, t))
    return counts
