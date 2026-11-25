"""Delaware reader on fixtures cut from the 2026 general files (pipeline/make_de_fixture.py)."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.de import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
KINDS = ["statewide", "district", "county", "turnout"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def load():
    with open(os.path.join(FX, "de_pass.json")) as f:
        rec = json.load(f)
    data = {}
    for k in KINDS:
        with open(os.path.join(FX, f"de_{k}.json")) as f:
            data[k] = json.load(f)
    return rec, data


def parse_data(test, rec, data, raw=None, kinds=KINDS):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    for k in kinds:
        with open(os.path.join(d, f"{k}.json"), "w") as f:
            f.write(raw[k] if raw and k in raw else json.dumps(data[k]))
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump(dict(rec, files=[{"kind": k, "path": f"{k}.json"} for k in kinds]), f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "de_pass.json"), base_dir=FX)

    def test_state_rows(self):
        t, = find(self.rows, level="state", contest_id="200", choice_id="13804", vote_type="TOTAL")
        m, = find(self.rows, level="state", contest_id="200", choice_id="13804", vote_type="Machine Votes")
        self.assertEqual((t["votes"], m["votes"], t["party"]), (240587, 140838, "Democratic Party"))
        self.assertEqual(t["reporting_status"], "530/530 precincts, OFFICIAL RESULTS")
        self.assertEqual((t["election_date"], t["contest_name"]), ("2026-11-03", "U.S. Senator"))

    def test_district_rows(self):
        r, = find(self.rows, level="precinct", precinct_id="01-01", contest_id="200", choice_id="13804", vote_type="TOTAL")
        self.assertEqual((r["votes"], r["precinct_name"], r["reporting_status"]), (595, "Election District 01-01", ""))
        self.assertEqual(len(find(self.rows, level="precinct", precinct_id="01-01", choice_id="13804")), 4)

    def test_county_rows(self):
        nc, = find(self.rows, level="county", contest_id="200", choice_id="13804", county_id="10003")
        self.assertEqual((nc["votes"], nc["county_name"]), (144910, "New Castle"))
        self.assertFalse(find(self.rows, level="county", contest_id="1010"))
        self.assertFalse(find(self.rows, county_name="Wilmington"))

    def test_county_offices_excluded(self):
        self.assertFalse([r for r in self.rows if r["contest_name"].startswith("New Castle County")])

    def test_turnout(self):
        self.assertEqual(sorted(t["representative_district"] for t in self.turnout), ["01", "02"])
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)

    def test_district_count_checked(self):
        # The fixture holds 3 districts, so every in-scope contest's count differs from its Total Precincts.
        self.assertIn("200", [x[0] for x in self.summary["district_count_mismatches"]])

    def test_summary_clean_parts(self):
        for k in ("state_lines_without_districts", "district_lines_without_state", "county_parts_mismatches",
                  "county_lines_without_state", "state_lines_without_county", "duplicate_entries", "shared_contest_orders",
                  "non_numeric", "malformed_entries", "unreadable_files", "missing_files"):
            self.assertEqual(self.summary[k], [], k)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)


class SyntheticTest(unittest.TestCase):
    def setUp(self):
        self.rec, self.d = load()

    def test_statewide_unreadable(self):
        rows, s, _ = parse_data(self, self.rec, self.d, raw={"statewide": "<html>no</html>"})
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["statewide"])
        self.assertTrue(find(rows, level="precinct"))
        self.assertEqual({r["choice_id"] for r in rows}, {""})
        self.assertIsNone(s["district_vs_state_mismatches"])
        self.assertIsNone(s["district_count_mismatches"])

    def test_lines_both_directions(self):
        self.d["district"].append(dict(self.d["district"][0], **{"Candidate Name": "NOBODY"}))
        self.d["statewide"].append(dict(self.d["statewide"][0], **{"Candidate Name": "GHOST", "Candidate Id": 1}))
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("U.S. Senator", "NOBODY"), s["district_lines_without_state"])
        self.assertIn(("U.S. Senator", "GHOST"), s["state_lines_without_districts"])

    def test_district_sum_mismatch_listed(self):
        rows, s, _ = parse_data(self, self.rec, self.d)
        sums = {}
        for x in self.d["district"]:
            k = (x["Contest Title"], x["Candidate Name"])
            for f in ("Total Votes", "Machine Votes", "Absentee Votes", "Early Voting Votes"):
                sums[(k, f)] = sums.get((k, f), 0) + int(x[f].replace(",", ""))
        for x in self.d["statewide"]:
            for f in ("Total Votes", "Machine Votes", "Absentee Votes", "Early Voting Votes"):
                x[f] = str(sums.get(((x["Contest Title"], x["Candidate Name"]), f), 0))
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual(s["district_vs_state_mismatches"], [])
        self.d["statewide"][0]["Total Votes"] = str(int(self.d["statewide"][0]["Total Votes"]) + 1)
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual([m[:3] for m in s["district_vs_state_mismatches"]], [("U.S. Senator", "CHRIS COONS", "TOTAL")])

    def test_county_checks(self):
        self.d["county"][0]["Wilmington"] += 1
        self.d["county"][1]["State"] += 1
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(s["county_parts_mismatches"])
        self.assertTrue(any(x[1] == self.d["county"][1]["Candidate Name"] for x in s["county_vs_state_mismatches"]))

    def test_count_parsing(self):
        self.d["district"][0]["Total Votes"] = "1,23x"
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual(len(s["non_numeric"]), 1)
        self.assertIn("", [r["votes"] for r in rows if r["level"] == "precinct"])

    def test_turnout_all_row_checked(self):
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(s["turnout_total_mismatches"])  # fixture: 2 of 41 districts
        all_ = next(t for t in self.d["turnout"] if t["Representative District"] == "ALL")
        rest = [t for t in self.d["turnout"] if t is not all_]
        all_["Ballots Cast"] = f"{sum(int(t['Ballots Cast'].replace(',', '')) for t in rest):,}"
        all_["Reg Voters"] = f"{sum(int(t['Reg Voters'].replace(',', '')) for t in rest):,}"
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual(s["turnout_total_mismatches"], [])

    def test_duplicates_and_malformed(self):
        self.d["district"].append(copy.deepcopy(self.d["district"][0]))
        self.d["statewide"].append("bad")
        self.d["statewide"].append(dict(self.d["statewide"][0], **{"Contest Title": "Something Else"}))
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(s["duplicate_entries"])
        self.assertTrue(s["malformed_entries"])
        self.assertIn("200", [x[0] for x in s["shared_contest_orders"]])

    def test_missing_file(self):
        rows, s, _ = parse_data(self, self.rec, self.d, kinds=["statewide", "district", "county"])
        self.assertEqual(s["missing_files"], ["turnout"])
        self.assertIsNone(s["turnout_total_mismatches"])


if __name__ == "__main__":
    unittest.main()
