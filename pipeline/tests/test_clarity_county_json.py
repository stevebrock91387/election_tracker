"""parse_county_json: one NJ county's Clarity JSON files (sum, ALL, vt, status, one file per vote type).

Fixtures are real 2026 passes cut to a few contests by pipeline/make_clarity_json_fixture.py (write-in
names replaced): Cumberland (contests 1 and 43, five vote types), Morris (0004 and 0005, six types,
"protected" cells, two partial contests), Middlesex (0004, protected cells in ALL.json), Gloucester
(0004, no vote types).
"""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.clarity import COUNTY_TURNOUT_COLUMNS, parse_county_json
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
CHECKS = ["mismatches_precincts_vs_county", "mismatches_total_area_vs_county", "mismatches_vote_types_vs_total",
          "mismatches_area_totals"]


def parse(prefix):
    return parse_county_json(os.path.join(FX, f"{prefix}_pass.json"), base_dir=FX)


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def copy_fixture(prefix):
    """A writable copy of a fixture pass (files and record) for synthetic edits."""
    d = tempfile.mkdtemp()
    with open(os.path.join(FX, f"{prefix}_pass.json")) as f:
        rec = json.load(f)
    for x in rec["files"]:
        shutil.copy(os.path.join(FX, x["path"]), d)
    path = os.path.join(d, "pass.json")
    with open(path, "w") as f:
        json.dump(rec, f)
    return d, path, rec


def edit(d, name, fn):
    with open(os.path.join(d, name)) as f:
        doc = json.load(f)
    fn(doc)
    with open(os.path.join(d, name), "w") as f:
        json.dump(doc, f)


class CumberlandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.s, cls.turnout = parse("nj_cumberland")

    def test_counts(self):
        self.assertEqual(len(self.rows), 11082)
        self.assertEqual(len(find(self.rows, level="county")), 114)
        self.assertEqual(len(find(self.rows, level="precinct")), 10968)
        self.assertEqual((self.s["contests"], self.s["precincts"]), (2, 106))
        self.assertEqual(self.s["vote_types"], ["Early Voting", "Election Day", "Vote-by-Mail", "Provisional",
                                                 "Emergency Votes"])
        self.assertEqual(self.rows[0].keys(), set(COLUMNS))

    def test_known_values(self):
        (r,) = find(self.rows, level="county", contest_id="1", choice_id="1", vote_type="TOTAL")
        self.assertEqual((r["votes"], r["choice"], r["party"], r["county_name"], r["contest_scope"],
                          r["reporting_status"], r["contest_name"], r["vote_for"]),
                         (22078, "Cory BOOKER", "DEM", "Cumberland", "local", "92/92 precincts",
                          "United States Senator", "1"))
        (p,) = find(self.rows, level="precinct", contest_id="1", choice_id="1", precinct_name="Bridgeton W1 D1",
                    vote_type="TOTAL")
        self.assertEqual((p["votes"], p["precinct_id"], p["reporting_status"]), (247, "Bridgeton W1 D1", "4"))
        (e,) = find(self.rows, level="precinct", contest_id="1", choice_id="1", precinct_name="Bridgeton W1 D1",
                    vote_type="Early Voting")
        self.assertEqual(e["votes"], 35)

    def test_every_check_clean(self):
        for k in CHECKS + ["protected_cells", "non_numeric", "skipped_contest_length_mismatch",
                           "skipped_length_mismatch", "skipped_areas", "contests_only_in_areas", "duplicate_areas",
                           "duplicate_contests", "precincts_not_in_status", "status_precincts_without_results",
                           "rcv_contests", "partial_contests", "unreadable", "precinct_sum_not_checked",
                           "total_area_not_checked", "vote_type_sum_not_checked", "area_total_not_checked",
                           "contests_without_precincts", "contests_without_vote_types"]:
            self.assertEqual(self.s[k], [], k)
        # 19 county vote-type sums, 10 vt.json type totals, 726 area totals, 114 "-1" cells, 114 precinct sums,
        # 1,828 precinct vote-type sums
        self.assertEqual(self.s["comparisons"], 2811)
        self.assertEqual(self.s["precinct_vote_types_checked"], 1828)

    def test_turnout(self):
        self.assertEqual(len(self.turnout), 106)
        self.assertEqual(set(self.turnout[0]), set(COUNTY_TURNOUT_COLUMNS))
        t = self.turnout[0]
        self.assertEqual((t["precinct_name"], t["registered_voters"], t["ballots_cast"], t["percent_reporting"],
                          t["county_name"]), ("Bridgeton W1 D1", 1115, 306, "4", "Cumberland"))

    def test_no_write_in_names_in_fixture(self):
        names = {r["choice"] for r in find(self.rows, contest_id="1")}
        self.assertIn("Write-in name 12", names)

    def test_deterministic(self):
        rows, s, t = parse("nj_cumberland")
        self.assertEqual((rows, s, t), (self.rows, self.s, self.turnout))


class MorrisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.s, cls.turnout = parse("nj_morris")

    def test_counts_and_types(self):
        self.assertEqual(len(self.rows), 16695)
        self.assertIn("State/Fed", self.s["vote_types"])
        self.assertEqual(self.s["partial_contests"], [("0004", 398, 400), ("0005", 93, 94)])

    def test_protected_cells_listed_and_empty(self):
        self.assertEqual(len(self.s["protected_cells"]), 2429)
        (r,) = find(self.rows, level="county", contest_id="0004", choice_id="1", vote_type="Provisional")
        self.assertEqual(r["votes"], "")
        self.assertIn(("vt.json", "", "0004", "1", "Provisional"), self.s["protected_cells"])
        self.assertTrue(find(self.rows, level="precinct", votes=""))

    def test_protected_comparisons_not_checked_never_mismatched(self):
        for k in CHECKS:
            self.assertEqual(self.s[k], [], k)
        self.assertIn(("county", "", "0004", "1"), self.s["vote_type_sum_not_checked"])
        self.assertTrue(self.s["precinct_sum_not_checked"])
        self.assertEqual(self.s["non_numeric"], [])


class MiddlesexTest(unittest.TestCase):
    def test_protected_totals(self):
        rows, s, _ = parse("nj_middlesex")
        self.assertEqual(len(rows), 16250)
        self.assertEqual(len(s["protected_cells"]), 145)
        self.assertTrue(any(c[0] == "ALL" for c in s["protected_cells"]))
        for k in CHECKS:
            self.assertEqual(s[k], [], k)
        self.assertTrue(any(c[0] == "ALL" for c in s["precinct_sum_not_checked"]))


class GloucesterTest(unittest.TestCase):
    def test_no_vote_types(self):
        rows, s, turnout = parse("nj_gloucester")
        self.assertEqual(len(rows), 1160)
        self.assertEqual({r["vote_type"] for r in rows}, {"TOTAL"})
        self.assertEqual(s["vote_types"], [])
        self.assertIsNone(s["mismatches_vote_types_vs_total"])
        self.assertIsNone(s["vote_type_sum_not_checked"])
        self.assertEqual(s["mismatches_precincts_vs_county"], [])
        self.assertEqual(len(turnout), 231)


class SyntheticTest(unittest.TestCase):
    def test_precinct_edit_is_a_mismatch_not_a_correction(self):
        d, path, _ = copy_fixture("nj_cumberland")
        edit(d, "nj_cumberland_all.json", lambda doc: doc["Contests"][0]["V"][0].__setitem__(0, 248))
        rows, s, _ = parse_county_json(path, base_dir=d)
        (p,) = find(rows, level="precinct", contest_id="1", choice_id="1", precinct_name="Bridgeton W1 D1",
                    vote_type="TOTAL")
        self.assertEqual(p["votes"], 248)
        self.assertIn(("ALL", "1", "1", 22078, 22079), s["mismatches_precincts_vs_county"])
        self.assertIn(("ALL", "Bridgeton W1 D1", "1", 289, 290), s["mismatches_area_totals"])
        self.assertIn(("precinct", "Bridgeton W1 D1", "1", "1", 248, 247), s["mismatches_vote_types_vs_total"])

    def test_other_non_numeric_listed(self):
        d, path, _ = copy_fixture("nj_cumberland")
        edit(d, "nj_cumberland_all.json", lambda doc: doc["Contests"][0]["V"][0].__setitem__(1, "27"))
        rows, s, _ = parse_county_json(path, base_dir=d)
        self.assertEqual(s["non_numeric"], [("ALL", "Bridgeton W1 D1", "1", "2", "TOTAL", "27")])
        self.assertEqual(s["protected_cells"], [])
        self.assertIn(("ALL", "1", "2"), s["precinct_sum_not_checked"])
        self.assertEqual(s["mismatches_precincts_vs_county"], [])

    def test_bool_is_not_a_count(self):
        d, path, _ = copy_fixture("nj_cumberland")
        edit(d, "nj_cumberland_all.json", lambda doc: doc["Contests"][0]["V"][0].__setitem__(2, False))
        _, s, _ = parse_county_json(path, base_dir=d)
        self.assertEqual(s["non_numeric"], [("ALL", "Bridgeton W1 D1", "1", "3", "TOTAL", False)])

    def test_malformed_areas_skipped_and_listed(self):
        d, path, _ = copy_fixture("nj_cumberland")

        def damage(doc):
            doc["Contests"][0]["V"][0] = doc["Contests"][0]["V"][0][:-1]  # contest 1: one choice short
            doc["Contests"][1]["T"] = []  # C/V/T lengths differ
            doc["Contests"].append(dict(doc["Contests"][2]))  # duplicate area
            doc["Contests"][3]["C"] = ["99"] + doc["Contests"][3]["C"][1:]  # contest not in sum.json
        edit(d, "nj_cumberland_all.json", damage)
        rows, s, _ = parse_county_json(path, base_dir=d)
        self.assertIn(("ALL", "Bridgeton W1 D1", "1"), s["skipped_length_mismatch"])
        self.assertEqual(s["skipped_areas"], [("ALL", "Bridgeton W2 D1", "C/V/T lengths differ")])
        self.assertEqual(s["duplicate_areas"], [("ALL", "Bridgeton W2 D2")])
        self.assertIn(("ALL", "Bridgeton W2 D3", "99"), s["contests_only_in_areas"])
        self.assertFalse(find(rows, level="precinct", precinct_name="Bridgeton W1 D1", contest_id="1",
                              vote_type="TOTAL"))
        self.assertIn(("ALL", "1", "1"), s["precinct_sum_not_checked"])

    def test_bad_sum_contest_skipped(self):
        d, path, _ = copy_fixture("nj_cumberland")
        edit(d, "nj_cumberland_sum.json", lambda doc: doc["Contests"][1]["CHAggId"].pop())
        rows, s, _ = parse_county_json(path, base_dir=d)
        self.assertEqual(s["skipped_contest_length_mismatch"],
                         [("43", {"CH": 2, "CHAggId": 1, "P": 2, "V": 2})])
        self.assertFalse(find(rows, contest_id="43"))
        self.assertEqual(s["contests_only_in_areas"], [])

    def test_missing_type_file(self):
        d, path, rec = copy_fixture("nj_cumberland")
        os.remove(os.path.join(d, rec["files"][4]["path"]))
        rows, s, _ = parse_county_json(path, base_dir=d)
        self.assertEqual(len(s["unreadable"]), 1)
        self.assertFalse(find(rows, level="precinct", vote_type="Early Voting"))
        self.assertTrue(find(rows, level="county", vote_type="Early Voting"))
        self.assertIsNone(s["precinct_vote_types_checked"])

    def test_missing_sum_gives_nothing(self):
        d, path, rec = copy_fixture("nj_cumberland")
        os.remove(os.path.join(d, rec["files"][0]["path"]))
        rows, s, turnout = parse_county_json(path, base_dir=d)
        self.assertEqual(rows, [])
        self.assertEqual(len(s["unreadable"]), 1)
        for k in CHECKS:
            self.assertIsNone(s[k], k)

    def test_unreadable_status(self):
        d, path, rec = copy_fixture("nj_cumberland")
        edit(d, rec["files"][3]["path"], lambda doc: doc["R"].pop())
        rows, s, turnout = parse_county_json(path, base_dir=d)
        self.assertEqual(turnout, [])
        self.assertIsNone(s["precincts_not_in_status"])
        self.assertEqual(len(s["unreadable"]), 1)
        self.assertTrue(rows)
        self.assertEqual({r["reporting_status"] for r in find(rows, level="precinct")}, {""})


if __name__ == "__main__":
    unittest.main()
