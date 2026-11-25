"""Parse Indiana results: the Indiana ENR category JSON (state and county totals, with ids) and the
precinct-level CSV of every office (names only). Module name in_ because `in` is a keyword.

Design: docs/superpowers/specs/2026-11-24-step2-in-reader-design.md.

A pass record lists: settings (Root: VersionType, CurrentElection, ...), elections (Root.List:
headings with office categories), offcat-<category> (Root: StatewideSummary.Race[] with OFFICEID,
OFFICE_TITLE, NumofSeats and candidates NAME_ON_BALLOT, PARTY, TOTAL; OfficeCategory with
OFFICE_CATEGORY_NAME and Regions.Region[] -> Races.Race[] per county with OFFICEID, Jurisdiction
{FIPS, JURISDICTION_NAME} and candidates CANDIDATEID, NAME_ON_BALLOT, PARTY_ABBREV, TOTAL_VOTES; for
statewide offices the race jurisdiction is "Indiana" and the county is the region, MAP_FIPS), turnout
(root.CountyTurnout[] per county plus "Total") and csv (one row per precinct, office, candidate).
A single item may be an object instead of a one-element list.

Rows: state rows from StatewideSummary (choice_id = the CANDIDATEID that name has in the office's
county races), county rows from the regions (county_id = FIPS), precinct rows from the CSV for the
record's categories (matched by category name), joined to office, candidate and county ids on (office
title, county name, name on ballot), compared case-insensitively. contest_type = the category name;
election_name = the CSV's Election; election_date = settings CurrentElection; source_created_at =
the category file's WriteTime (empty on precinct rows). reporting_status is empty everywhere: the
source has no reporting flag, so an unreported precinct can't be told from one with zero votes (the
summary counts precinct units, units named "...Nv" and all-zero units).

Nothing is corrected; the summary lists: precinct sums that differ from county totals, precinct rows
that join no county line, county lines with no precinct rows, county sums that differ from statewide
totals, statewide candidates with no county id, state-vs-county party codes that differ beyond case,
duplicate entries, non-integer counts (votes ""), counties without FIPS, the turnout Total vs the
county sums, Federal/State categories in the index that the record doesn't cover (judges and
prosecutors excepted), malformed entries (skipped) and missing or unreadable files. Checks that need
a file that wasn't read are None.
"""
import csv
import hashlib
import io
import json
import os
import re

from pipeline.schema import COLUMNS

TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters",
                   "voters_voting", "in_person", "absentee"]
TURNOUT_FIELDS = ("REGISTERED_VOTERS", "VotersVoting", "InPerson", "Absentee")
NOT_IN_SCOPE = {"1020", "1028", "1008", "1010"}  # judges and prosecuting attorney: county-jurisdiction offices
CSV_HEAD = {"Election", "ReportingCountyName", "DataEntryJurisdictionName", "Office", "OfficeCategory",
            "NameonBallot", "PoliticalParty", "TotalVotes"}
LISTS = ["precinct_vs_county_mismatches", "unmatched_precinct_rows", "county_lines_without_precincts",
         "county_vs_state_mismatches", "statewide_without_id", "party_differences", "duplicate_entries",
         "non_numeric", "counties_without_fips", "turnout_total_mismatches", "uncovered_categories",
         "malformed_entries"]


def _L(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def _int(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d+", v.strip()):
        return int(v)
    return None


def _cf(s):
    return (s or "").strip().casefold()


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    cats = list(rec.get("categories") or [])
    kinds = ["settings", "elections"] + [f"offcat-{c}" for c in cats] + ["turnout", "csv"]
    summary = {"version_type": rec.get("version_type", ""), "contests": 0, "counties": 0, "precinct_units": 0,
               "nv_units": 0, "all_zero_units": 0, "write_times": {}}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in kinds if k not in paths]
    data, sha = {}, {}
    for k in kinds:
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
                root = obj.get("root" if k == "turnout" else "Root") if isinstance(obj, dict) else None
                if not isinstance(root, dict):
                    raise ValueError("no Root object")
                if k.startswith("offcat-") and not isinstance(root.get("OfficeCategory"), dict):
                    raise ValueError("no OfficeCategory")
                obj = root
            data[k], sha[k] = obj, hashlib.sha256(body).hexdigest()
        except (OSError, ValueError, UnicodeDecodeError) as e:
            summary["unreadable_files"].append((k, str(e)))

    settings = data.get("settings", {})
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide", vote_type="TOTAL",
                election_date=settings.get("CurrentElection", "") if isinstance(settings.get("CurrentElection"), str) else "")
    csv_rows = data.get("csv")
    if csv_rows:
        base["election_name"] = csv_rows[0].get("Election") or ""

    # Category names: from the index, else from the category files themselves.
    cat_names = {}
    if "elections" in data:
        for h in _L(data["elections"].get("List")):
            if not isinstance(h, dict):
                summary["malformed_entries"].append(("elections", "List"))
                continue
            for item in _L((h.get("Items") or {}).get("Item") if isinstance(h.get("Items"), dict) else None):
                if not isinstance(item, dict):
                    continue
                cid, nm = str(item.get("OFFICECATEGORYID", "")), item.get("OFFICE_CATEGORY_NAME", "")
                if cid in cats:
                    cat_names[cid] = nm
                elif h.get("Heading") in ("Federal", "State") and cid not in NOT_IN_SCOPE:
                    summary["uncovered_categories"].append((cid, nm))
    else:
        summary["uncovered_categories"] = None

    rows = []
    county_index = {}   # (office title cf, county cf, name cf) -> (office id, cand id, fips, votes)
    office_by_title = {}  # (office title cf, county cf) -> (office id, fips, category name)
    county_sums, cand_ids, county_party, seen_county, fips_by_name = {}, {}, {}, set(), {}
    state_lines = []
    read_cats = set()
    for c in cats:
        k = f"offcat-{c}"
        if k not in data:
            continue
        root = data[k]
        oc = root["OfficeCategory"]
        cname = oc.get("OFFICE_CATEGORY_NAME", "") or cat_names.get(c, "")
        cat_names.setdefault(c, cname)
        read_cats.add(c)
        wt = root.get("WriteTime", "")
        summary["write_times"][c] = wt
        regions = oc.get("Regions") if isinstance(oc.get("Regions"), dict) else {}
        for reg in _L(regions.get("Region")):
            if not isinstance(reg, dict):
                summary["malformed_entries"].append((k, "Region"))
                continue
            races = reg.get("Races") if isinstance(reg.get("Races"), dict) else {}
            for race in _L(races.get("Race")):
                if not isinstance(race, dict):
                    summary["malformed_entries"].append((k, "Race"))
                    continue
                j = race.get("Jurisdiction") if isinstance(race.get("Jurisdiction"), dict) else {}
                if j.get("JURISDICTION_NAME") == "Indiana":
                    county, fips = reg.get("MAP_JURISDICTION_NAME", ""), reg.get("MAP_FIPS")
                else:
                    county, fips = j.get("JURISDICTION_NAME", ""), j.get("FIPS")
                fips = str(fips) if fips else ""
                if fips:
                    fips_by_name[_cf(county)] = fips
                elif (county,) not in [(x,) for x in summary["counties_without_fips"]]:
                    summary["counties_without_fips"].append(county)
                oid = str(race.get("OFFICEID", ""))
                office_by_title[(_cf(race.get("OFFICE_TITLE")), _cf(county))] = (oid, fips, cname)
                crow = dict(base, level="county", source_sha256=sha[k], source_created_at=wt, contest_id=oid,
                            contest_name=race.get("OFFICE_TITLE", ""), contest_type=cname,
                            vote_for=str(race.get("NumofSeats", "")), county_id=fips, county_name=county)
                cands = race.get("Candidates") if isinstance(race.get("Candidates"), dict) else {}
                for cd in _L(cands.get("Candidate")):
                    if not isinstance(cd, dict):
                        summary["malformed_entries"].append((k, "Candidate"))
                        continue
                    cid, name = str(cd.get("CANDIDATEID", "")), cd.get("NAME_ON_BALLOT", "")
                    n = _int(cd.get("TOTAL_VOTES"))
                    if n is None:
                        summary["non_numeric"].append(("county", oid, county, cid, cd.get("TOTAL_VOTES")))
                    key = (oid, _cf(county), cid)
                    if key in seen_county:
                        summary["duplicate_entries"].append(("county",) + key)
                    seen_county.add(key)
                    county_index[(_cf(race.get("OFFICE_TITLE")), _cf(county), _cf(name))] = (oid, cid, fips, n)
                    cand_ids.setdefault((oid, _cf(name)), cid)
                    county_party.setdefault((oid, cid), cd.get("PARTY_ABBREV", ""))
                    if n is not None:
                        county_sums[(oid, cid)] = county_sums.get((oid, cid), 0) + n
                    rows.append(dict(crow, choice_id=cid, choice=name, party=cd.get("PARTY_ABBREV", "") or "",
                                     votes="" if n is None else n))
        sw = root.get("StatewideSummary") if isinstance(root.get("StatewideSummary"), dict) else {}
        for race in _L(sw.get("Race")):
            if not isinstance(race, dict):
                summary["malformed_entries"].append((k, "StatewideSummary"))
                continue
            oid = str(race.get("OFFICEID", ""))
            summary["contests"] += 1
            srow = dict(base, level="state", source_sha256=sha[k], source_created_at=wt, contest_id=oid,
                        contest_name=race.get("OFFICE_TITLE", ""), contest_type=cname,
                        vote_for=str(race.get("NumofSeats", "")))
            cands = race.get("Candidates") if isinstance(race.get("Candidates"), dict) else {}
            for cd in _L(cands.get("Candidate")):
                if not isinstance(cd, dict):
                    summary["malformed_entries"].append((k, "Candidate"))
                    continue
                name = cd.get("NAME_ON_BALLOT", "")
                n = _int(cd.get("TOTAL"))
                if n is None:
                    summary["non_numeric"].append(("state", oid, "", name, cd.get("TOTAL")))
                state_lines.append((oid, name, n, cd.get("PARTY", "") or ""))
                rows.append(dict(srow, choice=name, party=cd.get("PARTY", "") or "", votes="" if n is None else n,
                                 choice_id=cand_ids.get((oid, _cf(name)), "")))
    # State lines vs county lines.
    for oid, name, n, party in state_lines:
        cid = cand_ids.get((oid, _cf(name)))
        if cid is None:
            summary["statewide_without_id"].append((oid, name))
            continue
        if n is not None and county_sums.get((oid, cid)) != n:
            summary["county_vs_state_mismatches"].append((oid, cid, n, county_sums.get((oid, cid))))
        if _cf(party) != _cf(county_party.get((oid, cid))):
            summary["party_differences"].append((oid, cid, party, county_party.get((oid, cid))))
    summary["counties"] = len(fips_by_name)

    # Precinct rows from the CSV.
    if csv_rows is not None:
        names = {_cf(n) for n in cat_names.values()}
        precinct_sums, seen, units = {}, set(), {}
        for r in csv_rows:
            if _cf(r.get("OfficeCategory")) not in names:
                continue
            office, county, name = r.get("Office") or "", r.get("ReportingCountyName") or "", r.get("NameonBallot") or ""
            precinct = r.get("DataEntryJurisdictionName") or ""
            n = _int(r.get("TotalVotes"))
            if n is None:
                summary["non_numeric"].append(("precinct", office, county, precinct, name, r.get("TotalVotes")))
            key = (_cf(office), _cf(county), _cf(precinct), _cf(name))
            if key in seen:
                summary["duplicate_entries"].append(("precinct",) + key)
            seen.add(key)
            u = units.setdefault((_cf(county), precinct), [0])
            u[0] += n or 0
            hit = county_index.get((_cf(office), _cf(county), _cf(name)))
            oinfo = office_by_title.get((_cf(office), _cf(county)), ("", fips_by_name.get(_cf(county), ""), ""))
            if hit is None:
                summary["unmatched_precinct_rows"].append((office, county, precinct, name))
            elif n is not None:
                precinct_sums[(_cf(office), _cf(county), _cf(name))] = precinct_sums.get(
                    (_cf(office), _cf(county), _cf(name)), 0) + n
            rows.append(dict(base, level="precinct", source_sha256=sha["csv"], county_name=county,
                             county_id=hit[2] if hit else oinfo[1], precinct_name=precinct,
                             contest_id=hit[0] if hit else oinfo[0], contest_name=office,
                             contest_type=oinfo[2] or (r.get("OfficeCategory") or ""),
                             vote_for=r.get("NumberofOfficeSeats") or "", choice_id=hit[1] if hit else "",
                             choice=name, party=r.get("PoliticalParty") or "", votes="" if n is None else n))
        summary["precinct_units"] = len(units)
        summary["nv_units"] = sum(1 for (_, p) in units if p.rstrip().endswith("Nv"))
        summary["all_zero_units"] = sum(1 for v in units.values() if v[0] == 0)
        if any(f"offcat-{c}" not in data for c in cats):
            summary["precinct_vs_county_mismatches"] = summary["county_lines_without_precincts"] = None
        else:
            for key, (oid, cid, fips, n) in county_index.items():
                if key not in precinct_sums:
                    if n:
                        summary["county_lines_without_precincts"].append((oid, fips or key[1], cid))
                elif n is not None and precinct_sums[key] != n:
                    summary["precinct_vs_county_mismatches"].append((oid, fips or key[1], cid, n, precinct_sums[key]))
    else:
        for k in ("precinct_vs_county_mismatches", "unmatched_precinct_rows", "county_lines_without_precincts"):
            summary[k] = None
        summary["precinct_units"] = summary["nv_units"] = summary["all_zero_units"] = None

    # Turnout table.
    turnout = []
    if "turnout" in data:
        total, sums = None, dict.fromkeys(TURNOUT_FIELDS, 0)
        for t in _L(data["turnout"].get("CountyTurnout")):
            if not isinstance(t, dict):
                summary["malformed_entries"].append(("turnout", "CountyTurnout"))
                continue
            if t.get("County") == "Total":
                total = t
                continue
            turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha["turnout"],
                                county_id=fips_by_name.get(_cf(t.get("County")), ""), county_name=t.get("County", ""),
                                registered_voters=t.get("REGISTERED_VOTERS", ""), voters_voting=t.get("VotersVoting", ""),
                                in_person=t.get("InPerson", ""), absentee=t.get("Absentee", "")))
            for f in TURNOUT_FIELDS:
                n = _int(t.get(f))
                sums[f] = sums[f] + n if n is not None and sums[f] is not None else None
        if total is None:
            summary["turnout_total_mismatches"].append(("Total entry absent", None, None))
        else:
            for f in TURNOUT_FIELDS:
                if _int(total.get(f)) is None or sums[f] is None or _int(total.get(f)) != sums[f]:
                    summary["turnout_total_mismatches"].append((f, total.get(f), sums[f]))
    else:
        summary["turnout_total_mismatches"] = None
    if any(f"offcat-{c}" not in data for c in cats):
        summary["county_vs_state_mismatches"] = summary["statewide_without_id"] = None
    return rows, summary, turnout
