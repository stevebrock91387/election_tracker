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
                  "precinct_total_conflicts", "contest_order_conflicts",
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

    def _sw(self, title, name=None):
        return [x for x in self.d["statewide"] if x["Contest Title"] == title and (name is None or x["Candidate Name"] == name)]

    def test_precinct_total_problems(self):
        for x in self._sw("U.S. Senator"):
            x["Total Precincts"] = None
        self._sw("Attorney General")[0]["Total Precincts"] = 999
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(any(n[1] == "U.S. Senator" for n in s["non_numeric"]))
        self.assertIn("Attorney General", [c[0] for c in s["precinct_total_conflicts"]])

    def test_district_count_exact(self):
        for x in self._sw("Attorney General"):
            x["Total Precincts"] = 2  # the fixture holds AG lines for 01-01 and 01-02 only
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertNotIn("Attorney General", [m[1] for m in s["district_count_mismatches"]])
        self.assertIn("U.S. Senator", [m[1] for m in s["district_count_mismatches"]])

    def test_county_duplicates_and_order_conflicts(self):
        self.d["county"].append(copy.deepcopy(self.d["county"][0]))
        self._sw("U.S. Senator")[1]["Contest Sorting Order"] = 201
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(any(d[0] == "county" for d in s["duplicate_entries"]))
        self.assertIn("U.S. Senator", [c[0] for c in s["contest_order_conflicts"]])

    def test_turnout_odd_rows(self):
        self.d["turnout"].append({"Ballots Cast": "1", "Reg Voters": "1"})
        self.d["turnout"].append(copy.deepcopy(self.d["turnout"][0]))
        self.d["turnout"].append(copy.deepcopy(next(t for t in self.d["turnout"] if t["Representative District"] == "ALL")))
        rows, s, t = parse_data(self, self.rec, self.d)
        self.assertTrue(any(m[0] == "turnout" for m in s["malformed_entries"]))
        self.assertTrue(any(d[0] == "turnout" for d in s["duplicate_entries"]))
        self.assertNotIn("", [x["representative_district"] for x in t])
        del self.d["turnout"][:]
        rows, s, t = parse_data(self, self.rec, self.d)
        self.assertEqual(s["turnout_total_mismatches"], [("ALL row absent", None, None)])

    def test_county_checks_both_directions_and_none(self):
        self.d["county"].append(dict(self.d["county"][0], **{"Candidate Name": "NOBODY"}))
        gone = self.d["county"].pop(0)
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("U.S. Senator", "NOBODY"), s["county_lines_without_state"])
        self.assertIn((gone["Contest Title"], gone["Candidate Name"]), s["state_lines_without_county"])
        rows, s, _ = parse_data(self, self.rec, self.d, raw={"county": "<html>"})
        for k in ("county_vs_state_mismatches", "county_lines_without_state", "state_lines_without_county",
                  "county_parts_mismatches"):
            self.assertIsNone(s[k], k)

    def test_each_county_part_and_fips(self):
        rows, s, _ = parse_data(self, self.rec, self.d)
        c = self.d["county"][0]
        k, = find(rows, level="county", choice=c["Candidate Name"], contest_name=c["Contest Title"], county_id="10001")
        x, = find(rows, level="county", choice=c["Candidate Name"], contest_name=c["Contest Title"], county_id="10005")
        self.assertEqual((k["county_name"], k["votes"], x["county_name"], x["votes"]), ("Kent", c["Kent"], "Sussex", c["Sussex"]))
        c["Wilmington"] += 1
        c["Rest of New Castle"] -= 1
        self.assertEqual(parse_data(self, self.rec, self.d)[1]["county_parts_mismatches"], [])
        c["Kent"] += 1
        self.assertEqual(len(parse_data(self, self.rec, self.d)[1]["county_parts_mismatches"]), 1)

    def test_vote_type_mismatch_pinned(self):
        sums = {}
        for x in self.d["district"]:
            for f in ("Total Votes", "Machine Votes", "Absentee Votes", "Early Voting Votes"):
                k = (x["Contest Title"], x["Candidate Name"], f)
                sums[k] = sums.get(k, 0) + int(x[f].replace(",", ""))
        for x in self.d["statewide"]:
            for f in ("Total Votes", "Machine Votes", "Absentee Votes", "Early Voting Votes"):
                x[f] = str(sums.get((x["Contest Title"], x["Candidate Name"], f), 0))
        self.d["statewide"][0]["Early Voting Votes"] = str(int(self.d["statewide"][0]["Early Voting Votes"]) + 1)
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual([m[2] for m in s["district_vs_state_mismatches"]], ["Early Voting Votes"])

    def test_malformed_dicts_and_bad_numbers(self):
        self.d["statewide"].append({"Contest Title": 5})
        self.d["district"].append({"Contest Title": "U.S. Senator"})
        self.d["county"].append({"Candidate Name": None})
        self.d["statewide"][0]["Total Votes"] = "12,34"
        self.d["county"][0]["Kent"] = "x"
        self.d["turnout"][0]["Ballots Cast"] = "x"
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual({m[0] for m in s["malformed_entries"]}, {"statewide", "district", "county"})
        self.assertEqual({n[0] for n in s["non_numeric"]}, {"statewide", "county", "turnout"})

    def test_statewide_duplicate_listed(self):
        self.d["statewide"].append(copy.deepcopy(self.d["statewide"][0]))
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(any(d[0] == "statewide" for d in s["duplicate_entries"]))

    def test_missing_file(self):
        rows, s, _ = parse_data(self, self.rec, self.d, kinds=["statewide", "district", "county"])
        self.assertEqual(s["missing_files"], ["turnout"])
        self.assertIsNone(s["turnout_total_mismatches"])


if __name__ == "__main__":
    unittest.main()
