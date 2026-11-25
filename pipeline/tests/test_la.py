"""Louisiana reader on fixtures cut from the 2026 general blobs (pipeline/make_la_fixture.py)."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.la import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
RACES = ["67997", "70199", "13833", "13836"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def load():
    with open(os.path.join(FX, "la_pass.json")) as f:
        rec = json.load(f)
    data = {}
    for x in rec["files"]:
        with open(os.path.join(FX, x["path"])) as f:
            data[x["kind"]] = json.load(f)
    return rec, data


def parse_data(test, rec, data, raw=None, drop=()):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    files = []
    for k, obj in data.items():
        if k in drop:
            continue
        with open(os.path.join(d, f"{k}.json"), "w") as f:
            f.write(raw[k] if raw and k in raw else json.dumps(obj))
        files.append({"kind": k, "path": f"{k}.json"})
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump(dict(rec, files=files), f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "la_pass.json"), base_dir=FX)

    def test_state_row(self):
        r, = find(self.rows, level="state", contest_id="67997", choice_id="124655")
        self.assertEqual((r["votes"], r["party"], r["vote_type"]), (746466, "REP", "TOTAL"))
        self.assertEqual(r["reporting_status"], "3722/3722 precincts, 64/64 absentee")
        self.assertEqual((r["election_date"], r["contest_type"]), ("11/03/2026", "U.S. Senator"))
        self.assertTrue(r["source_created_at"])

    def test_parish_rows(self):
        p = find(self.rows, level="county", contest_id="67997", choice_id="124655", county_id="17", vote_type="TOTAL")
        e = find(self.rows, level="county", contest_id="67997", choice_id="124655", county_id="17", vote_type="EarlyVoting")
        self.assertEqual((len(p), len(e)), (1, 1))
        self.assertEqual(p[0]["county_name"], "East Baton Rouge")
        self.assertLessEqual(e[0]["votes"], p[0]["votes"])

    def test_amendment_choices_per_race(self):
        a = find(self.rows, level="state", contest_id="13833", choice_id="3")
        b = find(self.rows, level="state", contest_id="13836", choice_id="3")
        self.assertEqual((len(a), len(b)), (1, 1))
        self.assertNotEqual(a[0]["votes"], b[0]["votes"])
        self.assertEqual(a[0]["party"], "")

    def test_runoff_listed(self):
        self.assertIn("70199", self.summary["runoff_races"])

    def test_turnout(self):
        self.assertTrue(self.turnout)
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        self.assertTrue(find(self.turnout, contest_id="67997", county_id="17"))

    def test_summary_clean_parts(self):
        s = self.summary
        for k in ("early_exceeds_total", "early_not_reported", "early_choices_unknown", "races_missing",
                  "unknown_parishes", "non_numeric", "duplicate_entries", "malformed_entries", "unreadable_files",
                  "missing_files", "choices_not_in_parishes", "choices_only_in_parishes", "choices_not_in_races",
                  "choices_not_in_votes", "early_parishes_missing", "early_choices_missing", "state_counts_missing"):
            self.assertEqual(s[k], [], k)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual({r["level"] for r in self.rows}, {"state", "county"})


class SyntheticTest(unittest.TestCase):
    def setUp(self):
        self.rec, self.d = load()

    def test_unreadable_parish_file(self):
        rows, s, _ = parse_data(self, self.rec, self.d, raw={"parish-70199": "<html>no</html>"})
        self.assertIn("parish-70199", [x[0] for x in s["unreadable_files"]])
        self.assertFalse(find(rows, level="county", contest_id="70199", vote_type="TOTAL"))
        self.assertTrue(find(rows, level="county", contest_id="67997"))
        self.assertIsNone(s["parish_vs_state_mismatches"])
        self.assertIsNone(s["early_exceeds_total"])

    def test_unknown_parish_listed(self):
        p = copy.deepcopy(self.d["parish-67997"]["Parishes"]["Parish"][0])
        p["ParishValue"] = "99"
        self.d["parish-67997"]["Parishes"]["Parish"].append(p)
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual(s["unknown_parishes"], ["99"])
        self.assertEqual({r["county_name"] for r in find(rows, county_id="99")}, {""})

    def test_parish_sum_mismatch_listed(self):
        rows, s, _ = parse_data(self, self.rec, self.d)
        before = {m[:2]: m for m in s["parish_vs_state_mismatches"]}
        self.d["parish-67997"]["Parishes"]["Parish"][0]["Choice"][0]["VoteTotal"] = str(
            int(self.d["parish-67997"]["Parishes"]["Parish"][0]["Choice"][0]["VoteTotal"]) + 1)
        cid = str(self.d["parish-67997"]["Parishes"]["Parish"][0]["Choice"][0]["ID"])
        rows, s, _ = parse_data(self, self.rec, self.d)
        after = {m[:2]: m for m in s["parish_vs_state_mismatches"]}
        self.assertEqual(after[("67997", cid)][3], before[("67997", cid)][3] + 1)

    def test_early_exceeds_total_listed(self):
        e = self.d["early-67997"]["EarlyVoting"]["Parish"][0]
        e["Choice"][0]["VoteTotal"] = "99999999"
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual(len(s["early_exceeds_total"]), 1)

    def test_non_numeric_and_malformed_listed(self):
        self.d["parish-67997"]["Parishes"]["Parish"][0]["Choice"][0]["VoteTotal"] = "n/a"
        self.d["parish-67997"]["Parishes"]["Parish"].append("bad")
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(any(x[0] == "parish" and x[-1] == "n/a" for x in s["non_numeric"]))
        self.assertTrue(s["malformed_entries"])
        self.assertTrue(rows)

    def test_duplicate_listed(self):
        p = self.d["parish-67997"]["Parishes"]["Parish"]
        p.append(copy.deepcopy(p[0]))
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(s["duplicate_entries"])

    def _race(self, kind, rid):
        return next(r for r in self.d[kind]["Races"]["Race"] if r["ID"] == rid)

    def test_votes_missing_race_not_checked(self):
        self.d["votes"]["Races"]["Race"] = [r for r in self.d["votes"]["Races"]["Race"] if r["ID"] != "70199"]
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("votes", "70199"), s["races_missing"])
        self.assertIsNone(s["parish_vs_state_mismatches"])
        self.assertIsNone(s["runoff_races"])

    def test_races_vs_votes_choices_listed(self):
        self._race("votes", "67997")["Choice"].append({"ID": "777", "VoteTotal": "0", "Outcome": None})
        self._race("races", "67997")["Choice"].append({"ID": "888", "Desc": "Zero Votes (IND)"})
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertEqual(s["choices_not_in_races"], [("67997", "777")])
        self.assertEqual(s["choices_not_in_votes"], [("67997", "888")])

    def test_early_missing_parish_and_choice_listed(self):
        e = self.d["early-67997"]["EarlyVoting"]["Parish"]
        gone = e.pop(0)["ParishValue"]
        e[0]["Choice"].pop(0)
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("67997", gone), s["early_parishes_missing"])
        self.assertEqual(len([x for x in s["early_choices_missing"] if x[0] == "67997"]), 1)

    def test_state_counts_bad_listed(self):
        v = self._race("votes", "67997")
        v["VoterCountVoted"] = "n/a"
        del v["PrecinctsExpected"]
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(any(x[0] == "state" and x[-1] == "n/a" for x in s["non_numeric"]))
        self.assertIn(("67997", "PrecinctsExpected"), s["state_counts_missing"])

    def test_each_check_lists(self):
        # choice only in parishes / missing from parishes
        p0 = self.d["parish-67997"]["Parishes"]["Parish"][0]
        p0["Choice"].append({"ID": "555", "VoteTotal": "1", "Outcome": None})
        v = self._race("votes", "70199")
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("67997", "555"), s["choices_only_in_parishes"])
        self.assertTrue(s["parish_count_mismatches"])  # three-parish fixture: counts can't sum to the state's
        self.d["parish-70199"]["Parishes"]["Parish"] = [
            dict(p, Choice=[c for c in p["Choice"] if c["ID"] != v["Choice"][0]["ID"]])
            for p in self.d["parish-70199"]["Parishes"]["Parish"]]
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("70199", v["Choice"][0]["ID"]), s["choices_not_in_parishes"])

    def test_early_unknown_choice_and_not_reported(self):
        e = self.d["early-67997"]["EarlyVoting"]["Parish"]
        e[0]["Choice"].append({"ID": "666", "VoteTotal": "1"})
        e[1]["HasReported"] = "0"
        code = e[1]["ParishValue"]
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertIn(("67997", e[0]["ParishValue"], "666"), s["early_choices_unknown"])
        self.assertIn(("67997", code), s["early_not_reported"])
        self.assertFalse(find(rows, contest_id="67997", county_id=code, vote_type="EarlyVoting"))

    def test_early_duplicate_listed(self):
        e = self.d["early-67997"]["EarlyVoting"]["Parish"]
        e.append(copy.deepcopy(e[0]))
        rows, s, _ = parse_data(self, self.rec, self.d)
        self.assertTrue(any(k[3] == "EarlyVoting" for k in s["duplicate_entries"]))

    def test_row_fields_pinned(self):
        rows, s, t = parse_data(self, self.rec, self.d)
        p = self.d["parish-67997"]["Parishes"]["Parish"][0]
        code = p["ParishValue"]
        r = find(rows, level="county", contest_id="67997", county_id=code, vote_type="TOTAL")[0]
        self.assertEqual(r["reporting_status"], f"{p['PrecinctsReporting']}/{p['PrecinctsExpected']} precincts, "
                                                f"{p['NumAbsenteeReporting']}/{p['NumAbsenteeExpected']} absentee")
        self.assertEqual((r["vote_for"], r["contest_name"]), ("1", "U. S. Senator"))
        tr, = find(t, contest_id="67997", county_id=code)
        self.assertEqual((tr["voters_qualified"], tr["voters_voted"]),
                         (int(p["VoterCountQualified"]), int(p["VoterCountVoted"])))
        e = find(rows, level="county", contest_id="67997", county_id=code, vote_type="EarlyVoting")[0]
        self.assertNotEqual(e["source_sha256"], r["source_sha256"])
        a = find(rows, level="state", contest_id="13833", choice_id="3")[0]["choice"]
        b = find(rows, level="state", contest_id="13836", choice_id="3")[0]["choice"]
        own = {c["ID"]: c["Desc"] for c in self._race("races", "13836")["Choice"]}
        self.assertEqual(b, own["3"])
        self.assertTrue(a)

    def test_missing_file_listed(self):
        rows, s, _ = parse_data(self, self.rec, self.d, drop=("early-13836",))
        self.assertEqual(s["missing_files"], ["early-13836"])
        self.assertIn(("early", "13836"), s["races_missing"])
        self.assertIsNone(s["early_exceeds_total"])


if __name__ == "__main__":
    unittest.main()
