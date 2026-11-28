"""MEDSL precinct returns -> county candidate totals for US SENATE, US HOUSE and GOVERNOR (step 4).

read_precincts(paths, year) yields normalized precinct rows from MEDSL zips (each member CSV is read in
place, nothing is extracted; macOS __MACOSX/ metadata members, as in 2022 WV's zip, are skipped). Kept: office in OFFICES and stage GEN. Fields: state_po, county_fips,
county_name, jurisdiction_fips, precinct, office, district, special (bool), candidate, party (party_detailed),
writein (bool), mode, votes (the string as published). The 2018 GitHub copy uses the same column names as
2022 in a different order (COLUMNS_2018 is the identity map); MEDSL spells booleans TRUE/True/FALSE/False.

load_fixes(path) / apply_fixes(rows, fixes, applied) apply medsl_fixes.toml to the rows of the fix's state,
year and office whose fields equal all of `match` (a list value matches any of its items). Actions: "drop"
removes those rows; "set" replaces fields from the fix's `set` table (writein only, never votes). The first
matching fix wins. `applied` receives (fix id, rows matched) per fix, in file order, zero included.

county_totals(rows) sums with the rules of tools/medsl_county.py:
- candidates in TALLIES (NON_CANDIDATES plus the tally lines listed there) are dropped; a blank writein flag
  is allowed only on those;
- votes "*" (suppressed) are not counted; each such row adds 1 to its county's suppressed_rows and to
  notes["suppressed"][(state, office)];
- within one (county, jurisdiction, precinct, office, district, special, candidate, writein flag, party line),
  if any row has mode TOTAL only TOTAL rows count, otherwise every mode is summed. The party line is
  party_detailed, so a fusion candidate's lines each choose their own mode set before being added together.
  A name with both named and write-in rows (VT 2018: write-ins recorded as "BERNIE SANDERS") gives two
  output rows, one per flag;
- any other non-integer votes value raises ValueError (nothing is guessed).
Rows with a blank county_fips go to county "" (kept for the state check, never a county baseline) and are
counted in notes["blank_county"][state]. Output rows: state_po, county_fips, county_name, office, district,
special, candidate, writein, votes, suppressed_rows (the county's suppressed rows for that office).
"""
import collections
import csv
import io
import os
import tomllib
import zipfile

from tools.medsl_county import NON_CANDIDATES

OFFICES = {"US SENATE", "US HOUSE", "GOVERNOR"}
COLUMNS_2018 = {}  # identity: the 2018 headers already match 2022's
# Tally lines in the 2018 and 2022 files that tools/medsl_county.NON_CANDIDATES doesn't name (surveyed
# 2026-11-27 over US SENATE, US HOUSE and GOVERNOR): counts of ballots, blanks, over/under votes and voids,
# never votes for a candidate. Write-in lines (REJECTED WRITE-INS, SCATTERING, ...) are not here: whether the
# FEC counts them is for the exact check to show.
TALLIES = NON_CANDIDATES | {
    "BALLOTS CAST", "BLANK", "BLANK (2)", "BLANK VOTES", "BLANK/VOID", "BLANK WRITE-IN", "CONTEST TOTALS",
    "FEDERAL BALLOTS", "FEDERAL VOTES", "OVERVOTES", "REGISTERED VOTERS", "STATE BALLOTS", "STATE VOTES",
    "TIMES BLANK VOTED", "TOTAL", "TOTAL VOTES", "UNDER/OVER", "UNDER/OVER VOTES", "UNDERVOTES", "VOID", "VOIDS",
    # NYC's five counties only, both years: ballots by type per election district (Queens 001/23, 2022 Senate:
    # PUBLIC COUNTER 1,071 + ABSENTEE / MILITARY 57 + AFFIDAVIT 11 = 1,139 ballots, 1,121 candidate votes)
    "PUBLIC COUNTER", "ABSENTEE / MILITARY", "AFFIDAVIT", "FEDERAL", "MANUALLY COUNTED EMERGENCY",
}
FIXES = os.path.join(os.path.dirname(__file__), "medsl_fixes.toml")
FIX_FIELDS = ("id", "state", "year", "office", "action", "change", "evidence", "before", "after", "match")
ACTIONS = {"drop", "set"}
SETTABLE = {"writein"}  # a "set" fix never changes a vote count


def _bool(v):
    s = v.strip().upper()
    if not s:
        return None  # VT 2022 tally lines; county_totals refuses it on a candidate
    if s in ("TRUE", "FALSE"):
        return s == "TRUE"
    raise ValueError(f"not a MEDSL boolean: {v!r}")


def read_precincts(paths, year):
    cols = COLUMNS_2018 if year == 2018 else {}
    for path in paths:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.lower().endswith(".csv") or name.startswith("__MACOSX/"):
                    continue
                with z.open(name) as f:
                    for raw in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline="")):
                        r = {cols.get(k, k): v for k, v in raw.items()} if cols else raw
                        if r["office"] not in OFFICES or r["stage"] != "GEN":
                            continue
                        yield {"state_po": r["state_po"], "county_fips": r["county_fips"],
                               "county_name": r["county_name"], "jurisdiction_fips": r["jurisdiction_fips"],
                               "precinct": r["precinct"], "office": r["office"], "district": r["district"],
                               "special": _bool(r["special"]), "candidate": r["candidate"],
                               "party": r["party_detailed"], "writein": _bool(r["writein"]), "mode": r["mode"],
                               "votes": r["votes"]}


def load_fixes(path=FIXES):
    with open(path, "rb") as f:
        fixes = tomllib.load(f).get("fix", [])
    for fx in fixes:
        missing = [k for k in FIX_FIELDS if k not in fx]
        if missing:
            raise ValueError(f"fix {fx.get('id', '?')}: missing {', '.join(missing)}")
        if fx["action"] not in ACTIONS:
            raise ValueError(f"fix {fx['id']}: unknown action {fx['action']!r}")
        if fx["action"] == "set":
            if not fx.get("set"):
                raise ValueError(f"fix {fx['id']}: action set needs a [fix.set] table")
            bad = set(fx["set"]) - SETTABLE
            if bad:
                raise ValueError(f"fix {fx['id']}: can't set {', '.join(sorted(bad))} (only {', '.join(sorted(SETTABLE))})")
    return fixes


def _matches(r, fx):
    for k, v in fx["match"].items():
        allowed = [str(x) for x in v] if isinstance(v, list) else [str(v)]
        if str(r.get(k)) not in allowed:
            return False
    return True


def apply_fixes(rows, fixes, applied, year=None):
    counts = collections.Counter()
    try:
        for r in rows:
            for fx in fixes:
                if (r["state_po"] == fx["state"] and r["office"] == fx["office"]
                        and (year is None or year == fx["year"]) and _matches(r, fx)):
                    counts[fx["id"]] += 1
                    if fx["action"] == "set":
                        yield {**r, **fx["set"]}
                    break
            else:
                yield r
    finally:
        applied.extend((fx["id"], counts[fx["id"]]) for fx in fixes if year is None or year == fx["year"])


def _int(v, r):
    try:
        f = float(v)
    except ValueError:
        raise ValueError(f"unreadable votes {v!r}: {r['state_po']} {r['county_name']} {r['precinct']} "
                         f"{r['office']} {r['candidate']}") from None
    if f != int(f):
        raise ValueError(f"fractional votes {v!r}: {r['state_po']} {r['precinct']} {r['candidate']}")
    return int(f)


def county_totals(rows):
    lines = collections.defaultdict(lambda: collections.defaultdict(int))
    suppressed = collections.Counter()
    notes = {"blank_county": collections.Counter(), "suppressed": collections.Counter()}
    for r in rows:
        if r["candidate"] in TALLIES:
            continue
        if r["writein"] is None:
            raise ValueError(f"blank writein flag on a candidate: {r['state_po']} {r['precinct']} {r['candidate']}")
        county = (r["state_po"], r["county_fips"], r["county_name"])
        if not r["county_fips"]:
            notes["blank_county"][r["state_po"]] += 1
        if r["votes"] == "*":
            suppressed[county + (r["office"],)] += 1
            notes["suppressed"][(r["state_po"], r["office"])] += 1
            continue
        contest = (r["office"], r["district"], r["special"], r["candidate"], r["writein"])
        lines[county + (r["jurisdiction_fips"], r["precinct"]) + contest + (r["party"],)][r["mode"]] += _int(r["votes"], r)
    votes = collections.Counter()
    for key, modes in lines.items():
        votes[key[:3] + key[5:10]] += modes["TOTAL"] if "TOTAL" in modes else sum(modes.values())
    out = []
    for key in sorted(votes, key=lambda k: tuple(str(x) for x in k)):
        st, fips, name, office, district, special, cand, wi = key
        out.append({"state_po": st, "county_fips": fips, "county_name": name, "office": office,
                    "district": district, "special": special, "candidate": cand, "writein": wi,
                    "votes": votes[key], "suppressed_rows": suppressed[(st, fips, name, office)]})
    return out, notes
