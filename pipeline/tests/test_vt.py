"""Vermont reader on fixtures cut from the 2026 general files (pipeline/make_vt_fixture.py)."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.vt import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
KINDS = ["election", "federal", "stateWide", "senate", "house", "turnOut"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def load():
    out = {}
    for k in KINDS:
        with open(os.path.join(FX, f"vt_{k}.json")) as f:
            out[k] = json.load(f)
    return out


def office(data, kind, i=0):
    return data[kind]["d"][0]["o"][i]


def entry(o, tn, n=0):
    return [c for c in o["cs"] if c["tn"] == tn][n]


def parse_data(test, data, raw=None, kinds=KINDS):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    for k in kinds:
        with open(os.path.join(d, f"{k}.json"), "w") as f:
            f.write(raw[k] if raw and k in raw else json.dumps(data[k]))
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "vt-test", "state": "VT", "snapshot": "20261117185828",
                   "files": [{"kind": k, "path": f"{k}.json"} for k in kinds]}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "vt_pass.json"), base_dir=FX)

    def test_congress_total(self):
        r, = find(self.rows, level="state", contest_id="4", choice_id="225757")
        self.assertEqual((r["votes"], r["party"], r["reporting_status"], r["vote_for"], r["contest_type"]),
                         (198758, "DEMOCRATIC", "0/0", "1", "federal"))
        self.assertEqual(r["source_created_at"], "11/17/2026 06:58 PM")

    def test_split_town_rows(self):
        b = find(self.rows, level="town", contest_id="4", choice_id="225757", county_id="50")
        self.assertEqual(sorted(x["votes"] for x in b), sorted([3712, 1231, 2311, 2660, 2025, 3263]))
        self.assertIn("CHITTENDEN-13|CHITTENDEN-SOUTHEAST_", [x["precinct_id"] for x in b])
        self.assertEqual({x["county_name"] for x in b}, {"BURLINGTON"})
        self.assertEqual(self.summary["duplicate_entries"], [])

    def test_governor_and_extras(self):
        s, = find(self.rows, level="state", contest_id="5", choice_id="225759")
        j, = find(self.rows, level="state", contest_id="5", choice_id="225760")
        self.assertEqual((s["votes"], s["party"], j["party"]), (162048, "REPUBLICAN", "DEM/PROG"))
        b, = find(self.rows, level="state", contest_id="5", choice="Blank Votes")
        o, = find(self.rows, level="state", contest_id="5", choice="Overvotes")
        self.assertEqual((b["votes"], o["votes"], b["choice_id"]), (2131, 324, ""))

    def test_districts(self):
        sen = find(self.rows, contest_id="12:CHI CT 1")
        self.assertTrue(sen)
        self.assertEqual({r["vote_for"] for r in sen}, {"3"})
        col = {r["precinct_id"] for r in find(self.rows, contest_id="11:CHI 20", level="town", county_id="63")}
        self.assertEqual(col, {"CHITTENDEN-20|GRAND ISLE_", "CHITTENDEN-20|CHITTENDEN-CENTRAL_"})

    def test_turnout(self):
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        a, = [t for t in self.turnout if t["county_id"] == "16"]
        self.assertEqual((a["county_name"], a["registered_voters"], a["ballots"], a["absentee"]), ("ADDISON", 1175, 755, 438))
        self.assertEqual(self.summary["turnout_mismatches"], [])

    def test_summary(self):
        s = self.summary
        self.assertEqual(s["sc_mismatches"], [])
        balint = [m for m in s["sum_mismatches"] if m[:2] == ("4", "225757")]
        town_sum = sum(r["votes"] for r in find(self.rows, level="town", contest_id="4", choice_id="225757"))
        self.assertEqual(balint, [("4", "225757", 198758, town_sum)])
        for k in ("total_entry_missing", "total_entry_repeated", "unknown_towns", "non_numeric",
                  "choices_not_in_total", "towns_missing_from_turnout",
                  "malformed_entries", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual({r["level"] for r in self.rows}, {"state", "town"})
        names = [r["choice"] for r in self.rows if r["choice"].startswith("WRITE-IN ")]
        self.assertTrue(names)


class SyntheticTest(unittest.TestCase):
    def setUp(self):
        self.d = load()

    def test_sum_mismatch_listed(self):
        before = {m[:2]: m for m in parse_data(self, self.d)[1]["sum_mismatches"]}
        rc = entry(office(self.d, "stateWide"), "STATE WIDE")["rc"]
        for r in rc:
            if r["cid"] == 225759:
                r["vc"] += 1
        after = {m[:2]: m for m in parse_data(self, self.d)[1]["sum_mismatches"]}
        self.assertEqual(after[("5", "225759")][2], before[("5", "225759")][2] + 1)

    def test_total_entry_missing_and_repeated(self):
        o = office(self.d, "house")
        tot = [c for c in o["cs"] if c["tid"] == 0][0]
        o["cs"].append(copy.deepcopy(tot))
        s = parse_data(self, self.d)[1]
        self.assertEqual(s["total_entry_repeated"], ["11:CHI 20"])
        o["cs"] = [c for c in o["cs"] if c["tid"] != 0]
        s = parse_data(self, self.d)[1]
        self.assertEqual(s["total_entry_missing"], ["11:CHI 20"])

    def test_sc_mismatch_listed(self):
        entry(office(self.d, "federal"), "ADDISON")["sc"] += 1
        s = parse_data(self, self.d)[1]
        self.assertEqual([m[:2] for m in s["sc_mismatches"]], [("4", "16")])
        self.assertTrue(s["turnout_mismatches"])

    def test_unknown_town_listed(self):
        e = copy.deepcopy(entry(office(self.d, "federal"), "ADDISON"))
        e["tid"], e["tn"] = 999, "NOWHERE"
        office(self.d, "federal")["cs"].append(e)
        s = parse_data(self, self.d)[1]
        self.assertEqual(s["unknown_towns"], [999])

    def test_duplicate_part_listed(self):
        o = office(self.d, "federal")
        o["cs"].append(copy.deepcopy(entry(o, "ADDISON")))
        s = parse_data(self, self.d)[1]
        self.assertTrue(s["duplicate_entries"])
        self.assertTrue(all(d[0] == "4" and d[1] == 16 for d in s["duplicate_entries"]))

    def test_non_numeric_listed(self):
        entry(office(self.d, "federal"), "ADDISON")["rc"][0]["vc"] = "n/a"
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(len(s["non_numeric"]), 1)
        self.assertIn("", [r["votes"] for r in find(rows, level="town", county_id="16", contest_id="4")])

    def test_choice_not_in_total_listed(self):
        entry(office(self.d, "federal"), "ADDISON")["rc"].append(
            {"cid": 1, "cn": "NOBODY", "vc": 0, "isWriteIn": False, "pn": None})
        s = parse_data(self, self.d)[1]
        self.assertEqual(s["choices_not_in_total"], [("4", "1")])

    def test_unreadable_results_file(self):
        rows, s, _ = parse_data(self, self.d, raw={"senate": "<html>error</html>"})
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["senate"])
        self.assertFalse(find(rows, contest_id="12:CHI CT 1"))
        self.assertTrue(find(rows, contest_id="4"))
        for k in ("sum_mismatches", "sc_mismatches", "duplicate_entries", "non_numeric", "choices_not_in_total",
                  "choices_not_in_towns", "total_entry_missing"):
            self.assertIsNone(s[k], k)

    def test_empty_results_file_unreadable(self):
        rows, s, _ = parse_data(self, self.d, raw={"house": '{"d": []}'})
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["house"])
        self.assertIsNone(s["sum_mismatches"])

    def test_malformed_entries_listed_not_fatal(self):
        o = office(self.d, "federal")
        entry(o, "ADDISON")["rc"].append(None)
        o["cs"].append(None)
        self.d["stateWide"]["d"][0]["o"].append("bad")
        self.d["election"]["towns"].append(None)
        self.d["turnOut"]["d"].append("bad")
        rows, s, _ = parse_data(self, self.d)
        self.assertTrue(find(rows, contest_id="4", county_id="16"))
        self.assertEqual({m[0] for m in s["malformed_entries"]}, {"federal", "stateWide", "election", "turnOut"})

    def test_choice_only_in_total_listed(self):
        tot = entry(office(self.d, "federal"), "STATE WIDE")
        tot["rc"].append({"cid": 7, "cn": "GHOST", "vc": 5000, "isWriteIn": False, "pn": None})
        tot["sc"] += 5000
        s = parse_data(self, self.d)[1]
        self.assertIn(("4", "7"), s["choices_not_in_towns"])

    def test_turnout_total_and_missing_towns(self):
        self.d["turnOut"]["d"] = [t for t in self.d["turnOut"]["d"] if t["tid"] != 16]
        s = parse_data(self, self.d)[1]
        self.assertEqual(s["towns_missing_from_turnout"], [16])
        self.assertTrue(s["turnout_total_mismatches"])

    def test_turnout_check_per_federal_office(self):
        second = copy.deepcopy(office(self.d, "federal"))
        second["oid"] = 99
        self.d["federal"]["d"][0]["o"].append(second)
        s = parse_data(self, self.d)[1]
        self.assertEqual(s["turnout_mismatches"], [])

    def test_missing_file_listed(self):
        rows, s, t = parse_data(self, self.d, kinds=[k for k in KINDS if k != "turnOut"])
        self.assertEqual(s["missing_files"], ["turnOut"])
        self.assertIsNone(s["turnout_mismatches"])
        self.assertEqual(t, [])


if __name__ == "__main__":
    unittest.main()
