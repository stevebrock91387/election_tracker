"""Step 4: the 2026 dry-run score (each county's actual top-race vote against its expected range)."""
import os
import tempfile
import unittest

from pipeline.db import connect
from pipeline.expected.score import actuals_2026, classify_office, score


class ClassifyTest(unittest.TestCase):
    def test_classify_office(self):
        cases = {
            "United States Senator": "US SENATE", "U.S. Senate": "US SENATE", "U. S. Senator": "US SENATE",
            "U.S.  Senate": "US SENATE", "Senator in Congress": "US SENATE", "Member, United States Senate": "US SENATE",
            "For United States Senator - 6  Year Term": "US SENATE",
            "State Senate District 12": None, "Senate District 4": None, "Senator in General Assembly District 32": None,
            "Member of the House of Representatives 1st Congressional District": "US HOUSE",
            "Member of the House of Representatives": "US HOUSE",
            "Member of House of Representatives 7th Congressional District": "US HOUSE",
            "Regent of the University of Colorado - Congressional District 2": None, "HOUSE OF REPRESENTATIVES - CD 1": "US HOUSE",
            "House of Representatives 2nd Cong": "US HOUSE", "Member, House of Representatives (9th District)": "US HOUSE",
            "Representative in Congress District 6": "US HOUSE", "Representative to Congress - District 01": "US HOUSE",
            "Representative to the 120th United States Congress - District 1": "US HOUSE",
            "U.S. Congress District 04": "US HOUSE", "Member of Congress - 1st Congressional District": "US HOUSE",
            "Congressional District 5 - U.S. Representative": "US HOUSE", "U.S. Representative, Dist II": "US HOUSE",
            "UNITED STATES REPRESENTATIVE, 6TH CONGRESSIONAL DISTRICT": "US HOUSE",
            "U. S. Representative -- 1st Congressional District": "US HOUSE",
            "State House of Representatives - District 174": None, "NC HOUSE OF REPRESENTATIVES DISTRICT 013": None,
            "State Board of Education Member - Congressional District 1": None,
            "Lieutenant Governor": None, "GOVERNOR AND LIEUTENANT GOVERNOR": "GOVERNOR", "Governor": "GOVERNOR",
            "Governor / Lt. Governor": "GOVERNOR", "Governor & Lt Governor": "GOVERNOR",
            "For Governor and Lt. Governor": "GOVERNOR", "Governor's Council 1st": None,
            "Constitutional Amendment 1: ... to require the governor to provide veto messages": None,
        }
        for name, want in cases.items():
            self.assertEqual(classify_office(name, "XX"), want, name)

    def test_dc_shadow_offices_not_federal(self):
        self.assertIsNone(classify_office("UNITED STATES SENATOR", "DC"))
        self.assertIsNone(classify_office("UNITED STATES REPRESENTATIVE CITYWIDE", "DC"))
        self.assertEqual(classify_office("DELEGATE TO THE HOUSE OF REPRESENTATIVES FROM THE DISTRICT OF COLUMBIA", "DC"),
                         "US HOUSE")


class ActualsTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(os.path.join(tempfile.mkdtemp(), "s.sqlite"))
        self.sid = 0

    def snap(self, source, state, seen="2026-11-20T00:00:00Z"):
        self.sid += 1
        self.conn.execute("INSERT INTO snapshot (snapshot_id, source_id, state, first_seen_utc) VALUES (?,?,?,?)",
                          (self.sid, source, state, seen))
        return self.sid

    def res(self, sid, level, county, contest, choice, votes, county_id="", vote_type="TOTAL", precinct=""):
        self.conn.execute("INSERT INTO result (snapshot_id, level, county_id, county_name, precinct_name, contest_name,"
                          " choice, vote_type, votes) VALUES (?,?,?,?,?,?,?,?,?)",
                          (sid, level, county_id, county, precinct, contest, choice, vote_type, votes))

    def test_actuals_sum_precincts_when_no_county_rows(self):
        s = self.snap("nc-2026-general", "NC")
        for p, v in (("P1", 100), ("P2", 50)):
            self.res(s, "precinct", "WAKE", "US SENATE", "A", v, precinct=p)
            self.res(s, "precinct", "WAKE", "US SENATE", "Over Votes", 9, precinct=p)
            self.res(s, "precinct", "WAKE", "US SENATE", "A", 1, precinct=p, vote_type="Early Voting")
        self.res(s, "state", "", "US SENATE", "A", 150)
        rows, _ = actuals_2026(self.conn)
        self.assertEqual([(r["county_name"], r["top_office"], r["votes"]) for r in rows], [("WAKE", "US SENATE", 150)])

    def test_county_rows_house_summed_and_top_office(self):
        s = self.snap("tx-2026-general", "TX")
        self.res(s, "county", "HARRIS", "U. S. SENATOR", "A", 1000, county_id="48201")
        self.res(s, "county", "HARRIS", "U. S. Representative District 2", "B", 600, county_id="48201")
        self.res(s, "county", "HARRIS", "U. S. Representative District 7", "C", 500, county_id="48201")
        self.res(s, "county", "HARRIS", "State Senate District 4", "D", 9999, county_id="48201")
        (r,), _ = actuals_2026(self.conn)
        self.assertEqual((r["top_office"], r["votes"], r["county_id"]), ("US HOUSE", 1100, "48201"))

    def test_town_states_and_unnamed_listed(self):
        self.res(self.snap("ev-RI-2026-general", "RI"), "county", "Bristol", "Governor", "A", 10)
        self.res(self.snap("ak-2026-general", "AK"), "precinct", "", "U.S. Senator", "A", 10, precinct="01-446")
        rows, listed = actuals_2026(self.conn)
        self.assertEqual(rows, [])
        self.assertEqual(listed, [("AK", "ak-2026-general", "", "not scored: no county names"),
                                  ("RI", "ev-RI-2026-general", "", "not scored: towns")])

    def test_withheld_cells_counted(self):
        s = self.snap("clarity-NJ-Middlesex-2026-general", "NJ")
        self.res(s, "county", "Middlesex", "US Senate", "A", 100)
        self.res(s, "county", "Middlesex", "US Senate", "B", None)
        (r,), _ = actuals_2026(self.conn)
        self.assertEqual((r["votes"], r["withheld"]), (100, 1))

    def test_two_sources_one_county(self):
        for src in ("lvt-NJ-Bergen-2026-general", "pdf-NJ-Bergen-2026-general"):
            self.res(self.snap(src, "NJ"), "county", "Bergen", "US Senate", "A", 100)
        rows, listed = actuals_2026(self.conn)
        self.assertEqual([(r["votes"], r["source_id"]) for r in rows],
                         [(100, "lvt-NJ-Bergen-2026-general pdf-NJ-Bergen-2026-general")])
        self.res(self.snap("x-NJ-Bergen", "NJ"), "county", "Bergen", "US Senate", "A", 101)
        rows, listed = actuals_2026(self.conn)
        self.assertEqual(rows, [])
        self.assertIn(("NJ", "lvt-NJ-Bergen-2026-general pdf-NJ-Bergen-2026-general x-NJ-Bergen", "Bergen",
                       "not scored: sources differ (100, 100, 101)"), listed)


def ex(st, fips, name, point, low, high):
    return {"state": st, "county_fips": fips, "county_name": name, "target": 2026, "point": point, "low": low,
            "high": high, "method": "raw", "reason": "", "years_used": "2018 2022"}


def act(st, name, votes, county_id=""):
    return {"state": st, "county_name": name, "county_id": county_id, "top_office": "US SENATE", "votes": votes,
            "source_id": "s", "withheld": 0}


class ScoreTest(unittest.TestCase):
    def test_score_inside_and_miss(self):
        per, summary = score([ex("TX", "48201", "HARRIS", 1200, 1000, 1200), ex("TX", "48001", "ANDERSON", 100, 90, 110)],
                             [act("TX", "Harris", 1300, "48201"), act("TX", "anderson county", 95)])
        got = {r["county"]: (r["inside"], r["miss"], r["miss_pct"]) for r in per}
        self.assertEqual(got["HARRIS"], (False, 100, 100 / 1200))
        self.assertEqual(got["ANDERSON"], (True, 0, 0.0))
        self.assertEqual((summary["TX"]["scored"], summary["TX"]["inside_share"]), (2, 0.5))
        self.assertEqual(summary["ALL"]["p90_abs_miss_pct"], 100 / 1200)

    def test_fips_only_when_it_is_the_states(self):
        # GA's county ids are sequence numbers ("001"), not FIPS: join on the name
        per, _ = score([ex("GA", "13001", "APPLING", 10, 10, 10)], [act("GA", "Appling", 10, "001")])
        self.assertEqual(len(per), 1)

    def test_unmatched_county_listed(self):
        per, summary = score([ex("TX", "48201", "HARRIS", 1200, 1000, 1200)], [act("TX", "Nowhere", 5)])
        self.assertEqual(per, [])
        self.assertIn(("TX", "Nowhere", "no expected row"), summary["not_scored"])
        self.assertIn(("TX", "HARRIS", "no 2026 actual"), summary["not_scored"])


if __name__ == "__main__":
    unittest.main()
