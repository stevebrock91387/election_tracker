"""Alabama reader: three real county workbooks (pipeline/make_al_fixture.py) and synthetic grids."""
import copy
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile

from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
HAVE_XLRD = importlib.util.find_spec("xlrd") is not None
if HAVE_XLRD:
    from pipeline.readers import al
    from pipeline.readers.al import TURNOUT_COLUMNS, parse_county, parse_pass
CHECKS = ["ballot_balance_mismatches", "partial_blocks", "non_numeric", "non_integer", "duplicate_lines",
          "duplicate_units", "blank_units", "multi_district_units", "counties_registered_all_zero", "missing_header_rows", "unreadable_workbooks",
          "extra_sheets", "other_members"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def grid():
    """A small county: two precincts, an absentee unit, and one in-scope and one local contest."""
    t = "UNITED STATES SENATOR      "
    return [
        ["Contest Title", "Party", "Candidate", "1 TOWN HALL", "PROVIDENCE BAPT CH", "ABSENTEE"],
        ["REGISTERED VOTERS - TOTAL   ", "   ", "Registered Voters - Total  ", 100.0, 200.0, 0.0],
        ["BALLOTS CAST - TOTAL     ", "   ", "Ballots Cast - Total ", 50.0, 80.0, 10.0],
        ["BALLOTS CAST - BLANK     ", "   ", "Ballots Cast - Blank ", 0.0, 1.0, 0.0],
        [t, "DEM", "Everett Wess   ", 20.0, 30.0, 4.0],
        [t, "REP", "Barry Moore    ", 28.0, 48.0, 5.0],
        [t, "NON", "Write-In   ", 0.0, 0.0, 0.0],
        [t, "   ", "Over Votes   ", 1.0, 0.0, 0.0],
        [t, "   ", "Under Votes   ", 1.0, 2.0, 1.0],
        ["STATE REPRESENTATIVE, DISTRICT 9 ", "REP", "A Candidate ", 40.0, None, 8.0],
        ["STATE REPRESENTATIVE, DISTRICT 9 ", "   ", "Over Votes ", 0.0, None, 0.0],
        ["STATE REPRESENTATIVE, DISTRICT 9 ", "   ", "Under Votes ", 10.0, None, 2.0],
        ["TOWN COUNTY SHERIFF  ", "REP", "Someone ", 50.0, 80.0, 10.0],
    ]


def pc(g, county="TOWN"):
    return parse_county(county, g, {"state": "AL", "source_id": "al-test", "source_sha256": "x"})


@unittest.skipUnless(HAVE_XLRD, "needs xlrd (.venv)")
class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "al_pass.json"), base_dir=FX)

    def test_senate_rows(self):
        r = find(self.rows, county_id="COOSA", precinct_id="EQUALITY METHODIST", contest_id="UNITED STATES SENATOR")
        self.assertEqual([(x["choice"], x["party"], x["votes"]) for x in r],
                         [("Everett Wess", "DEM", 59), ("Barry Moore", "REP", 269), ("Write-In", "NON", 0),
                          ("Over Votes", "", 0), ("Under Votes", "", 1)])
        x = r[0]
        self.assertEqual((x["level"], x["vote_type"], x["contest_scope"], x["contest_type"], x["precinct_is_virtual"],
                          x["county_name"], x["choice_id"], x["state"]),
                         ("precinct", "TOTAL", "statewide", "candidate", "N", "COOSA", "", "AL"))

    def test_virtual_units(self):
        self.assertEqual({r["precinct_is_virtual"] for r in find(self.rows, county_id="JACKSON", precinct_id="PROVSIONAL")}, {"Y"})
        self.assertEqual({r["precinct_is_virtual"] for r in find(self.rows, county_id="BULLOCK", precinct_id="ABSENTEE")}, {"Y"})

    def test_scope(self):
        names = {r["contest_name"] for r in self.rows}
        self.assertIn("STRAIGHT PARTY", names)
        self.assertIn("STATE BOARD OF EDUCATION MEMBER DISTRICT 8", names)
        self.assertNotIn("BULLOCK COUNTY SHERIFF", names)
        self.assertNotIn("DISTRICT COURT JUDGE, JACKSON COUNTY, PLACE NO. 1", names)
        self.assertEqual({r["contest_type"] for r in find(self.rows, contest_id="PROPOSED STATEWIDE AMENDMENT 1")}, {"measure"})
        self.assertEqual({r["contest_type"] for r in find(self.rows, contest_id="STRAIGHT PARTY")}, {"straight party"})

    def test_empty_blocks_skipped(self):
        # Bridgeport votes only in House district 22: no rows for district 23 there.
        got = {r["contest_id"] for r in find(self.rows, county_id="JACKSON", precinct_id="BRIDGEPORT SR CTR_")
               if r["contest_id"].startswith("STATE REPRESENTATIVE")}
        self.assertEqual(len(got), 1)

    def test_split_polling_place(self):
        # Woodville carries both House districts; the two blocks together equal its ballots cast.
        r = find(self.rows, county_id="JACKSON", precinct_id="WOODVILLE BOB JONES COMM")
        d22 = sum(x["votes"] for x in r if x["contest_id"] == "STATE REPRESENTATIVE, DISTRICT 22")
        d23 = sum(x["votes"] for x in r if x["contest_id"] == "STATE REPRESENTATIVE, DISTRICT 23")
        self.assertEqual((d22, d23), (407, 11))
        self.assertIn(("JACKSON", "WOODVILLE BOB JONES COMM", "STATE REPRESENTATIVE, DISTRICT 22", 407, 418),
                      self.summary["ballot_balance_mismatches"])
        self.assertIn(("JACKSON", "WOODVILLE BOB JONES COMM", "STATE REPRESENTATIVE",
                       ["STATE REPRESENTATIVE, DISTRICT 22", "STATE REPRESENTATIVE, DISTRICT 23"]),
                      self.summary["multi_district_units"])
        self.assertNotIn("ABSENTEE", [u[1] for u in self.summary["multi_district_units"]])

    def test_turnout(self):
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        t, = [x for x in self.turnout if x["county_id"] == "COOSA" and x["precinct_id"] == "EQUALITY METHODIST"]
        self.assertEqual((t["registered_voters"], t["ballots_cast"], t["ballots_blank"]), (595, 329, 0))

    def test_summary(self):
        s = self.summary
        self.assertEqual(s["counties"], 3)
        self.assertEqual(s["units"], 10 + 14 + 32)
        self.assertEqual(s["counties_registered_all_zero"], ["BULLOCK", "JACKSON"])
        for k in ("partial_blocks", "non_numeric", "non_integer", "duplicate_lines", "duplicate_units", "blank_units",
                  "missing_header_rows", "unreadable_workbooks", "extra_sheets", "other_members",
                  "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)
        self.assertGreater(s["contests_out_of_scope"], 0)

    def test_every_row(self):
        self.assertTrue(self.rows)
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
            self.assertIsInstance(r["votes"], int)


@unittest.skipUnless(HAVE_XLRD, "needs xlrd (.venv)")
class GridTest(unittest.TestCase):
    def test_rows_and_virtual(self):
        rows, turnout, f = pc(grid())
        self.assertEqual({(r["precinct_id"], r["precinct_is_virtual"]) for r in rows},
                         {("1 TOWN HALL", "N"), ("PROVIDENCE BAPT CH", "N"), ("ABSENTEE", "Y")})
        self.assertEqual(find(rows, precinct_id="1 TOWN HALL", choice="Barry Moore")[0]["votes"], 28)
        self.assertNotIn("TOWN COUNTY SHERIFF", {r["contest_id"] for r in rows})
        self.assertEqual(f["out_of_scope"], {"TOWN COUNTY SHERIFF"})

    def test_empty_block_gives_no_rows(self):
        rows, _, f = pc(grid())
        self.assertEqual(find(rows, precinct_id="PROVIDENCE BAPT CH", contest_id="STATE REPRESENTATIVE, DISTRICT 9"), [])
        self.assertEqual(f["partial_blocks"], [])

    def test_multi_district_units(self):
        g = grid()
        g[11:11] = [["STATE REPRESENTATIVE, DISTRICT 10", "DEM", "B Candidate", None, 30.0, None],
                    ["STATE REPRESENTATIVE, DISTRICT 10", "   ", "Under Votes", None, 0.0, None]]
        g[9][4], g[10][4], g[13][4] = 50.0, 0.0, 0.0  # PROVIDENCE now also in district 9
        _, _, f = pc(g)
        self.assertEqual(f["multi_district_units"], [("TOWN", "PROVIDENCE BAPT CH", "STATE REPRESENTATIVE",
                                                      ["STATE REPRESENTATIVE, DISTRICT 10", "STATE REPRESENTATIVE, DISTRICT 9"])])
        g[11][5], g[12][5] = 1.0, 0.0  # ABSENTEE (virtual) in both: not listed
        _, _, f = pc(g)
        self.assertEqual([u[1] for u in f["multi_district_units"]], ["PROVIDENCE BAPT CH"])

    def test_balance(self):
        _, _, f = pc(grid())
        self.assertEqual(f["ballot_balance_mismatches"], [])
        g = grid()
        g[5][4] = 47.0
        _, _, f = pc(g)
        self.assertEqual(f["ballot_balance_mismatches"], [("TOWN", "PROVIDENCE BAPT CH", "UNITED STATES SENATOR", 79, 80)])

    def test_partial_block(self):
        g = grid()
        g[10][4] = 0.0
        rows, _, f = pc(g)
        self.assertEqual(f["partial_blocks"], [("TOWN", "PROVIDENCE BAPT CH", "STATE REPRESENTATIVE, DISTRICT 9")])
        self.assertEqual(len(find(rows, precinct_id="PROVIDENCE BAPT CH", contest_id="STATE REPRESENTATIVE, DISTRICT 9")), 1)

    def test_non_numeric_and_non_integer(self):
        g = grid()
        g[4][3] = "n/a"
        g[5][3] = 28.5
        rows, _, f = pc(g)
        self.assertEqual(f["non_numeric"], [("TOWN", 4, 3, "n/a")])
        self.assertEqual(f["non_integer"], [("TOWN", 5, 3, 28.5)])
        self.assertEqual([r["votes"] for r in find(rows, precinct_id="1 TOWN HALL", choice="Everett Wess")], [""])
        self.assertNotIn(("TOWN", "1 TOWN HALL", "UNITED STATES SENATOR"), [m[:3] for m in f["ballot_balance_mismatches"]])

    def test_duplicates(self):
        g = grid()
        g.append(list(g[5]))
        g[0].append("1 TOWN HALL")
        for r in g[1:]:
            r.append(r[3])
        rows, turnout, f = pc(g)
        self.assertEqual(f["duplicate_lines"], [("TOWN", "UNITED STATES SENATOR", "Barry Moore")])
        self.assertEqual(f["duplicate_units"], [("TOWN", "1 TOWN HALL")])
        self.assertEqual(len(find(rows, precinct_id="1 TOWN HALL", choice="Barry Moore")), 1)
        self.assertEqual(len([t for t in turnout if t["precinct_id"] == "1 TOWN HALL"]), 1)

    def test_blank_unit_header(self):
        g = grid()
        g[0][4] = "   "
        rows, turnout, f = pc(g)
        self.assertEqual(f["blank_units"], [("TOWN", 4)])
        self.assertEqual(find(rows, precinct_id=""), [])
        self.assertEqual([t for t in turnout if t["precinct_id"] == ""], [])

    def test_registered_all_zero(self):
        _, _, f = pc(grid())
        self.assertFalse(f["registered_all_zero"])
        g = grid()
        g[1][3:] = [0.0, 0.0, 0.0]
        _, turnout, f = pc(g)
        self.assertTrue(f["registered_all_zero"])
        self.assertEqual({t["registered_voters"] for t in turnout}, {0})

    def test_missing_header_rows(self):
        g = grid()
        del g[2]
        rows, turnout, f = pc(g)
        self.assertEqual(f["missing_header_rows"], [("TOWN", "BALLOTS CAST - TOTAL")])
        self.assertIsNone(f["ballot_balance_mismatches"])
        self.assertEqual({t["ballots_cast"] for t in turnout}, {""})
        g = grid()
        g[1], g[2] = g[2], g[1]
        _, turnout, f = pc(g)
        t, = [x for x in turnout if x["precinct_id"] == "1 TOWN HALL"]
        self.assertEqual((t["registered_voters"], t["ballots_cast"]), (100, 50))


@unittest.skipUnless(HAVE_XLRD, "needs xlrd (.venv)")
class PassTest(unittest.TestCase):
    def run_zip(self, members=None, raw=None, files=True):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        p = os.path.join(d, "al.zip")
        if raw is not None:
            with open(p, "wb") as f:
                f.write(raw)
        elif members is not None:
            with zipfile.ZipFile(p, "w") as z:
                for name, data in members.items():
                    z.writestr(name, data)
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": "al-test", "state": "AL", "files": [{"kind": "zip", "path": "al.zip"}] if files else []}, f)
        return parse_pass(rec, base_dir=d)

    def real_member(self, county="COOSA"):
        with zipfile.ZipFile(os.path.join(FX, "al_results.zip")) as z:
            return z.read(f"2026_GENERAL_ELECTION-{county}.xls")

    def test_html_zip_unreadable(self):
        rows, s, t = self.run_zip(raw=b"<html>blocked</html>")
        self.assertEqual((rows, t), ([], []))
        self.assertEqual(len(s["unreadable_files"]), 1)
        for k in CHECKS:
            self.assertIsNone(s[k], k)

    def test_missing_file(self):
        rows, s, _ = self.run_zip(files=False)
        self.assertEqual(s["missing_files"], ["zip"])
        self.assertIsNone(s["ballot_balance_mismatches"])
        rows, s, _ = self.run_zip()  # listed in the record but not on disk
        self.assertEqual(len(s["unreadable_files"]), 1)

    def test_no_workbooks(self):
        rows, s, _ = self.run_zip(members={"readme.txt": b"hi"})
        self.assertEqual(len(s["unreadable_files"]), 1)
        self.assertIsNone(s["ballot_balance_mismatches"])

    def test_members_listed(self):
        rows, s, _ = self.run_zip(members={"2026_GENERAL_ELECTION-COOSA.xls": self.real_member(),
                                           "notes.txt": b"x", "2026_GENERAL_ELECTION-BAD.xls": b"not a workbook"})
        self.assertEqual(s["other_members"], ["notes.txt"])
        self.assertEqual([u[0] for u in s["unreadable_workbooks"]], ["2026_GENERAL_ELECTION-BAD.xls"])
        self.assertEqual(s["counties"], 1)
        self.assertTrue(find(rows, county_id="COOSA"))

    def test_oversized_member_refused(self):
        old = al.MAX_MEMBER_BYTES
        al.MAX_MEMBER_BYTES = 1000
        self.addCleanup(setattr, al, "MAX_MEMBER_BYTES", old)
        rows, s, _ = self.run_zip(members={"2026_GENERAL_ELECTION-COOSA.xls": self.real_member()})
        self.assertIn("too large", s["unreadable_workbooks"][0][1])
        self.assertEqual(rows, [])

    def test_wrong_header_unreadable(self):
        orig = al.read_workbook
        def fake(data):
            g, names = orig(data)
            g = copy.deepcopy(g)
            g[0][0] = "Contest"
            return g, names
        al.read_workbook = fake
        self.addCleanup(setattr, al, "read_workbook", orig)
        rows, s, _ = self.run_zip(members={"2026_GENERAL_ELECTION-COOSA.xls": self.real_member()})
        self.assertEqual(rows, [])
        self.assertIn("first row", s["unreadable_workbooks"][0][1])

    def test_extra_sheets_listed(self):
        orig = al.read_workbook
        al.read_workbook = lambda data: (orig(data)[0], ["Precinct Results", "Notes"])
        self.addCleanup(setattr, al, "read_workbook", orig)
        rows, s, _ = self.run_zip(members={"2026_GENERAL_ELECTION-COOSA.xls": self.real_member()})
        self.assertEqual(s["extra_sheets"], [("2026_GENERAL_ELECTION-COOSA.xls", ["Notes"])])
        self.assertTrue(rows)

    def test_county_name_from_token(self):
        rows, s, _ = self.run_zip(members={"2026_GENERAL_ELECTION-ST._CLAIR.xls": self.real_member()})
        self.assertEqual({(r["county_id"], r["county_name"]) for r in rows}, {("ST._CLAIR", "ST. CLAIR")})


if __name__ == "__main__":
    unittest.main()
