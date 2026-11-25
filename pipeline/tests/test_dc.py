"""DC reader on fixtures cut from the 2026 general files (pipeline/make_dc_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.dc import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
NAMES = {"info": "dc_info.json", "csv": "dc_csv.csv", "citywide": "dc_citywide.json"}


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def raw(kind):
    with open(os.path.join(FX, NAMES[kind]), "rb") as f:
        return f.read().decode("utf-8")


def parse_texts(test, texts=None, kinds=("info", "csv", "citywide")):
    texts = texts or {}
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    for k in kinds:
        with open(os.path.join(d, NAMES[k]), "w", newline="") as f:
            f.write(texts.get(k, raw(k)))
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "dc-test", "state": "DC", "files": [{"kind": k, "path": NAMES[k]} for k in kinds]}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


def edit_csv(match, old, new):
    lines = raw("csv").split("\n")
    i = next(n for n, l in enumerate(lines) if all(m in l for m in match))
    lines[i] = lines[i].replace(old, new)
    return "\n".join(lines)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "dc_pass.json"), base_dir=FX)

    def test_state_row(self):
        r, = find(self.rows, level="state", contest_id="4", choice="DEM Robert White")
        self.assertEqual((r["votes"], r["choice_id"], r["party"], r["contest_type"]), (201900, "2", "DEM", "RCV first rank"))
        self.assertEqual((r["county_id"], r["election_name"], r["election_date"]), ("", "General Election", "2026-11-03"))
        self.assertIn("144/144 precincts", r["reporting_status"])

    def test_precinct_rows(self):
        p = find(self.rows, level="precinct", contest_id="4", choice="DEM Robert White", precinct_id="20")
        self.assertEqual(len(p), 1)
        self.assertEqual((p[0]["county_id"], p[0]["precinct_name"], p[0]["choice_id"]), ("11001", "Ward 1 Precinct 20", "2"))
        self.assertEqual(find(self.rows, level="state", contest_id="6")[0]["contest_type"], "")

    def test_over_under_rows(self):
        for lvl in ("state", "precinct"):
            o = find(self.rows, level=lvl, choice="OVER VOTES")
            self.assertTrue(o)
            self.assertEqual({(r["choice_id"], r["party"]) for r in o}, {("", "")})

    def test_anc_and_specials_excluded(self):
        self.assertTrue("ANC-" in raw("csv"))
        self.assertFalse(find(self.rows, contest_id="29"))
        self.assertFalse([r for r in self.rows if r["contest_id"].startswith("-")])

    def test_turnout(self):
        self.assertEqual(len(self.turnout), 3)
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        t, = [x for x in self.turnout if x["precinct_id"] == "1"]
        self.assertEqual((t["ward"], t["registered_voters"], t["ballots_cast"]), ("6", 7087, 3375))

    def test_summary_clean_parts(self):
        s = self.summary
        for k in ("ward_conflicts", "duplicate_entries", "non_numeric", "ballots_exceed_registered",
                  "precincts_missing_specials", "malformed_entries", "unreadable_files", "missing_files",
                  "party_differences", "citywide_lines_without_precincts", "precinct_lines_without_citywide"):
            self.assertEqual(s[k], [], k)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)


class SyntheticTest(unittest.TestCase):
    def test_citywide_unreadable(self):
        rows, s, _ = parse_texts(self, {"citywide": "<html>blocked</html>"})
        self.assertTrue(find(rows, level="precinct", contest_id="4"))
        self.assertFalse(find(rows, level="state"))
        self.assertEqual({r["choice_id"] for r in rows}, {""})
        self.assertIsNone(s["precinct_vs_citywide_mismatches"])
        self.assertIsNone(s["citywide_lines_without_precincts"])

    def test_lines_both_directions(self):
        c = json.loads(raw("citywide"))
        c[0]["ElectionData"].append({"Contestant": "GHOST", "Votes": 5, "CandidateNumber": 99, "PartyCode": "IND"})
        t = edit_csv(['"DEM Robert White"', ',20,'] if '"' in raw("csv") else ["DEM Robert White", ",20,"],
                     "DEM Robert White", "DEM Robert Whyte")
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c), "csv": t})
        self.assertIn(("4", "GHOST"), s["citywide_lines_without_precincts"])
        self.assertIn(("4", "DEM Robert Whyte"), s["precinct_lines_without_citywide"])

    def test_party_from_csv(self):
        c = json.loads(raw("citywide"))
        for e in c[0]["ElectionData"]:
            if e["Contestant"] == "DEM Robert White":
                e["PartyCode"] = "REP"
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c)})
        r, = find(rows, level="state", contest_id="4", choice="DEM Robert White")
        self.assertEqual(r["party"], "DEM")
        self.assertEqual(s["party_differences"], [("4", "DEM Robert White", "REP", "DEM")])

    def test_ward_conflict_listed(self):
        t = edit_csv(["DEM Robert White", ",20,1,"], ",20,1,", ",20,2,")
        rows, s, _ = parse_texts(self, {"csv": t})
        self.assertEqual([w[0] for w in s["ward_conflicts"]], ["20"])

    def test_precinct_mismatch_listed(self):
        rows, s, _ = parse_texts(self)
        before = {m[:2]: m for m in s["precinct_vs_citywide_mismatches"]}
        t = edit_csv(["DEM Robert White", ",20,1,"], "DEM Robert White,DEM,", "DEM Robert White,DEM,1")
        rows, s, _ = parse_texts(self, {"csv": t})
        after = {m[:2]: m for m in s["precinct_vs_citywide_mismatches"]}
        self.assertNotEqual(after[("4", "DEM Robert White")], before[("4", "DEM Robert White")])

    def test_non_numeric_duplicate_specials(self):
        lines = raw("csv").split("\n")
        i = next(n for n, l in enumerate(lines) if "DEM Robert White" in l and ",20,1," in l)
        lines.append(lines[i])
        j = next(n for n, l in enumerate(lines) if "BALLOTS CAST" in l and ",22," in l)
        lines[j] = lines[j].rsplit(",", 1)[0] + ",999999"
        k = next(n for n, l in enumerate(lines) if "REGISTERED VOTERS" in l and ",1,6," in l)
        del lines[k]
        m = next(n for n, l in enumerate(lines) if "Write-in" in l and ",22," in l)
        lines[m] = lines[m].rsplit(",", 1)[0] + ",n/a"
        rows, s, _ = parse_texts(self, {"csv": "\n".join(lines)})
        self.assertEqual(len(s["duplicate_entries"]), 1)
        self.assertEqual([b[0] for b in s["ballots_exceed_registered"]], ["22"])
        self.assertIn(("1", "registered"), s["precincts_missing_specials"])
        self.assertEqual(len(s["non_numeric"]), 1)

    def test_clean_cross_check(self):
        import csv as _csv
        import io as _io
        sums = {}
        for r in _csv.DictReader(_io.StringIO(raw("csv"))):
            sums[(r["ContestNumber"], r["Candidate"])] = sums.get((r["ContestNumber"], r["Candidate"]), 0) + int(r["Votes"])
        c = json.loads(raw("citywide"))
        for x in c:
            for e in x["ElectionData"]:
                e["Votes"] = sums[(str(x["ContestNumber"]), e["Contestant"])]
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c)})
        self.assertEqual(s["precinct_vs_citywide_mismatches"], [])

    def test_info_unreadable(self):
        rows, s, _ = parse_texts(self, {"info": "<html>no</html>"})
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["info"])
        self.assertIsNone(s["precinct_count_mismatch"])
        self.assertTrue(rows)

    def test_csv_unreadable(self):
        rows, s, _ = parse_texts(self, {"csv": "<html>no</html>"})
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["csv"])
        for k in ("precinct_vs_citywide_mismatches", "citywide_lines_without_precincts", "precinct_lines_without_citywide",
                  "party_differences", "ward_conflicts", "duplicate_entries", "ballots_exceed_registered",
                  "precincts_missing_specials", "precinct_count_mismatch", "unexpected_contest_numbers"):
            self.assertIsNone(s[k], k)
        r, = find(rows, level="state", contest_id="4", choice="DEM Robert White")
        self.assertEqual(r["party"], "DEM")
        self.assertEqual(find(rows, level="state", contest_id="4", choice="OVER VOTES")[0]["party"], "")

    def test_rcv_on_precinct_rows(self):
        rows, s, _ = parse_texts(self)
        self.assertEqual({r["contest_type"] for r in find(rows, level="precinct", contest_id="4")}, {"RCV first rank"})

    def test_bad_election_data_listed(self):
        c = json.loads(raw("citywide"))
        c[0]["ElectionData"] = 5
        c[1]["ElectionData"] = None
        c.append({"OfficeName": "NO NUMBER", "ElectionData": []})
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c)})
        self.assertGreaterEqual(len(s["malformed_entries"]), 3)
        self.assertTrue(rows)

    def test_unexpected_contest_numbers_listed(self):
        t = edit_csv(["DEM Robert White", ",20,1,"], ",4,DELEGATE", ",x4,DELEGATE")
        rows, s, _ = parse_texts(self, {"csv": t})
        self.assertEqual([u[0] for u in s["unexpected_contest_numbers"]], ["x4"])

    def test_candidate_numbers_and_duplicates(self):
        c = json.loads(raw("citywide"))
        for e in c[0]["ElectionData"]:
            if e["Contestant"] == "DEM Robert White":
                e["CandidateNumber"] = None
        c[0]["ElectionData"].append(dict(c[0]["ElectionData"][0]))
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c)})
        self.assertIn(("4", "DEM Robert White"), s["missing_candidate_numbers"])
        self.assertNotIn("None", {r["choice_id"] for r in rows})
        self.assertEqual(len(s["duplicate_citywide_lines"]), 1)

    def test_bad_values_listed(self):
        c = json.loads(raw("citywide"))
        c[0]["ElectionData"][0]["Votes"] = "n/a"
        lines = raw("csv").split("\n")
        j = next(n for n, l in enumerate(lines) if "REGISTERED VOTERS" in l and ",22," in l)
        lines[j] = lines[j].rsplit(",", 1)[0] + ",n/a"
        k = next(n for n, l in enumerate(lines) if "BALLOTS CAST" in l and ",20," in l)
        del lines[k]
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c), "csv": "\n".join(lines)})
        self.assertTrue(any(x[0] == "citywide" for x in s["non_numeric"]))
        self.assertTrue(any(x[0] == "csv" and x[1] == "-2" for x in s["non_numeric"]))
        self.assertIn(("20", "ballots"), s["precincts_missing_specials"])

    def test_malformed_and_missing(self):
        c = json.loads(raw("citywide"))
        c.append("bad")
        c[0]["ElectionData"].append(None)
        rows, s, _ = parse_texts(self, {"citywide": json.dumps(c)})
        self.assertGreaterEqual(len(s["malformed_entries"]), 2)
        rows, s, _ = parse_texts(self, kinds=("info", "csv"))
        self.assertEqual(s["missing_files"], ["citywide"])


if __name__ == "__main__":
    unittest.main()
