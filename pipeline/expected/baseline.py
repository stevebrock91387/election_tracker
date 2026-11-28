"""Each county's top race in one year, among the offices that passed the FEC check (step 4).

baselines(totals, checks, year, provenance) -> (rows, listed).
- Contest votes per county = every candidate's votes, write-ins included (tallies were dropped upstream).
  A contest is (office, special): US HOUSE is summed over the county's districts; where an office has two
  contests in a year (a special Senate election, or a House seat's full and unexpired terms), the larger
  contest is the office's votes in that county (the same voters cast both).
- Eligible offices: US SENATE and US HOUSE whose (state, office) check passed; GOVERNOR when each federal
  office in the state passed or has no check entry (no race on either side). GOVERNOR isn't in the FEC
  compilation: its rows are tagged check "not checked", checked_via "federal rows".
- top_office: the eligible office with the most votes; a tie goes US SENATE, GOVERNOR, US HOUSE.
- County "" (MEDSL rows with no county) is never a row. A county with no eligible office is listed as
  (state, county_fips, county_name, reason). A county with no MEDSL rows at all (e.g. every race
  uncontested with no votes published) cannot be seen here; compute lists it when the other year has it.
"""
import collections

BASELINE_COLUMNS = ["state", "county_fips", "county_name", "year", "top_office", "votes", "suppressed_rows",
                    "check", "checked_via", "medsl_source", "fec_file_sha256"]
ORDER = ("US SENATE", "GOVERNOR", "US HOUSE")
FEDERAL = ("US SENATE", "US HOUSE")


def _eligible(st, office, checks):
    if office in FEDERAL:
        c = checks.get((st, office))
        return c is not None and c["passed"]
    return all(checks.get((st, o), {"passed": True})["passed"] for o in FEDERAL)


def baselines(totals, checks, year, provenance):
    contest = collections.Counter()
    suppressed = {}
    names = {}
    for r in totals:
        if not r["county_fips"]:
            continue
        county = (r["state_po"], r["county_fips"])
        names[county] = r["county_name"]
        contest[county + (r["office"], bool(r["special"]))] += r["votes"]
        suppressed[county + (r["office"],)] = r["suppressed_rows"]
    office_votes = collections.defaultdict(dict)
    for (st, fips, office, _), v in contest.items():
        office_votes[(st, fips)][office] = max(v, office_votes[(st, fips)].get(office, 0))
    rows, listed = [], []
    for (st, fips), offices in sorted(office_votes.items()):
        ok = [o for o in ORDER if o in offices and _eligible(st, o, checks)]
        if not ok:
            why = "; ".join(f"{o}: {checks[(st, o)]['reason'] if (st, o) in checks else 'federal office failed'}"
                            for o in ORDER if o in offices)
            listed.append((st, fips, names[(st, fips)], f"no eligible office ({why})"))
            continue
        best = max(ok, key=lambda o: (offices[o], -ORDER.index(o)))
        gov = best == "GOVERNOR"
        rows.append({"state": st, "county_fips": fips, "county_name": names[(st, fips)], "year": year,
                     "top_office": best, "votes": offices[best], "suppressed_rows": suppressed[(st, fips, best)],
                     "check": "not checked" if gov else "passed", "checked_via": "federal rows" if gov else "",
                     "medsl_source": provenance["medsl_source"], "fec_file_sha256": provenance["fec_file_sha256"]})
    return rows, listed
