"""Enhanced Voting parser on fixtures cut from the real 2026 AZ and UT exports."""
import copy
import csv
import glob
import json
import os
import tempfile
import unittest

from pipeline.readers.enhanced_voting import UnsupportedFormat, parse
from pipeline.schema import COLUMNS, write_csv

FX = os.path.join(os.path.dirname(__file__), "fixtures")
AZ = os.path.join(FX, "ev_az_greenlee.json")
UT = os.path.join(FX, "ev_ut_piute.json")
FULL_AZ = sorted(glob.glob("data/raw/az-2026/export-110326GeneralElection-*.json"))


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


class EnhancedVotingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.az, cls.az_sum = parse(AZ, "AZ", "ev-AZ-2026-general")
        cls.ut, cls.ut_sum = parse(UT, "UT", "ev-UT-2026-general")

    def test_az_county_totals(self):
        got = {(r["choice"], r["party"]): r["votes"] for r in
               find(self.az, level="county", contest_id="AZ-6", vote_type="TOTAL")}
        self.assertEqual(got[("Juan Ciscomani", "Republican")], 1181)
        self.assertEqual(got[("JoAnna Mendoza", "Democratic")], 824)
        self.assertEqual(got[("Jereme Lance Peters", "Libertarian")], 35)
        self.assertEqual(find(self.az, level="county", contest_id="AZ-6")[0]["county_name"], "Greenlee County")

    def test_az_vote_types(self):
        rows = find(self.az, level="county", contest_id="AZ-6", choice="Juan Ciscomani")
        got = {r["vote_type"]: r["votes"] for r in rows}
        self.assertEqual(got, {"TOTAL": 1181, "Election Day": 436, "Early Voting": 600, "Provisional": 12,
                               "Early A.R.S. 16-579": 0, "Late Early*": 133})
        status = {r["vote_type"]: r["reporting_status"] for r in rows}
        self.assertEqual(status["Early A.R.S. 16-579"], "Not Participating")
        self.assertEqual(status["Election Day"], "Fully Reported")
        self.assertEqual(status["TOTAL"], "")

    def test_az_precinct_row(self):
        (r,) = find(self.az, level="precinct", contest_id="AZ-6", precinct_id="2800",
                    choice="Juan Ciscomani", vote_type="TOTAL")
        self.assertEqual(r["precinct_name"], "001 Eagle")
        self.assertEqual(r["votes"], 17)
        self.assertEqual(r["reporting_status"], "Partially Reported")
        self.assertIs(r["precinct_is_virtual"], False)

    def test_az_statewide_rows(self):
        got = {r["choice"]: r["votes"] for r in find(self.az, level="state", contest_id="AZ-6", vote_type="TOTAL")}
        self.assertEqual(got["JoAnna Mendoza"], 190058)
        self.assertEqual(got["Juan Ciscomani"], 160972)
        self.assertEqual(self.az_sum["election_name"], "2026 General Election")

    def test_mismatch_reported_not_fixed(self):
        mm = {(c, ch): (s, cs) for c, ch, s, cs in self.az_sum["mismatches_state_vs_counties"]}
        self.assertEqual(mm[("AZ-6", "JoAnna Mendoza")], (190058, 824))
        (r,) = find(self.az, level="state", contest_id="AZ-6", choice="JoAnna Mendoza", vote_type="TOTAL")
        self.assertEqual(r["votes"], 190058)

    def test_ut_missing_detail(self):
        got = {r["choice"]: r["votes"] for r in find(self.ut, level="county", contest_id="636107054")}
        self.assertEqual(got, {"CELESTE MALOY": 613, "KENT S. UDELL": 62, "CASSIE EASLEY": 21, "AYDEN SCOTT": 7,
                               "MICHAEL R. STODDARD": 7, "ADONIS HOOSLYN": 0})
        self.assertFalse(find(self.ut, level="precinct"))
        self.assertTrue(all(r["vote_type"] == "TOTAL" for r in self.ut))
        self.assertTrue(all(r["reporting_status"] == "" for r in find(self.ut, level="county")))
        self.assertFalse(self.ut_sum["has_precincts"])
        self.assertFalse(self.ut_sum["has_vote_types"])

    def test_ranked_choice_raises(self):
        with open(UT) as f:
            d = json.load(f)
        bad = copy.deepcopy(d)
        bad["localResults"][0]["ballotItems"][0]["rankedChoiceResults"] = [{"round": 1}]
        path = os.path.join(tempfile.mkdtemp(), "rc.json")
        with open(path, "w") as f:
            json.dump(bad, f)
        with self.assertRaises(UnsupportedFormat):
            parse(path, "UT", "x")

    def test_columns_and_csv(self):
        for r in self.az + self.ut:
            self.assertEqual(list(r), COLUMNS)
        out = os.path.join(tempfile.mkdtemp(), "o.csv")
        n = write_csv(self.az, out)
        self.assertEqual(n, len(self.az))
        with open(out, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)

    @unittest.skipUnless(FULL_AZ, "full AZ raw file not present")
    def test_full_az_file(self):
        rows, s = parse(FULL_AZ[0], "AZ", "ev-AZ-2026-general")
        self.assertEqual(s["counties"], 15)
        self.assertEqual(s["mismatches_state_vs_counties"], [])
        self.assertEqual([m for m in s["mismatches_groups_vs_total"] if m[0] == "state"], [])
        self.assertTrue(s["has_precincts"])
        self.assertTrue(s["has_vote_types"])


if __name__ == "__main__":
    unittest.main()
