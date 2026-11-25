"""Massachusetts reader on fixtures cut from the real 2026 list pages and CSVs (pipeline/make_ma_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.ma import parse_csv, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
SEN, H2, REP, Q1 = "U.S. Senate", "U.S. House 2nd Congressional", "State Representative 1st Barnstable", "Question 1"
LISTS = ["totals_row_mismatches", "totals_row_not_checked", "list_mismatches", "list_not_checked",
         "total_votes_mismatches", "total_votes_not_checked", "non_numeric", "malformed_lines", "duplicate_precincts",
         "duplicate_choices", "contests_without_file", "files_not_in_list", "unexpected_headers", "unreadable_files",
         "missing_files"]
LABELS = [(SEN, "Shiva Ayyadurai", "Unenrolled", "Independent"), (SEN, "Joe Tache", "Unenrolled", "Socialism and Liberation"),
          (REP, "Joe B. Glynn", "Unenrolled", "Gulf War Veteran")]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def text(name):
    with open(os.path.join(FX, name), encoding="utf-8", newline="") as f:
        return f.read()


def run(test, edits=None, drop=()):
    """Parse the fixture pass with some files replaced (edits: {fixture name: new text}) or dropped."""
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    with open(os.path.join(FX, "ma_pass.json")) as f:
        rec = json.load(f)
    files = []
    for x in rec["files"]:
        if x["path"] in drop:
            continue
        body = (edits or {}).get(x["path"], text(x["path"]))
        with open(os.path.join(d, x["path"]), "w", encoding="utf-8", newline="") as f:
            f.write(body)
        files.append(x)
    rec["files"] = files
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump(rec, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "ma_pass.json"), base_dir=FX)

    def test_columns(self):
        self.assertTrue(all(list(r) == COLUMNS for r in self.rows))
        self.assertEqual(self.turnout, [])

    def test_precinct_rows(self):
        got = {(r["choice"], r["party"]): r["votes"] for r in
               find(self.rows, level="precinct", county_name="Abington", precinct_id="-/1", contest_id=SEN)}
        self.assertEqual(got, {("Edward J. Markey", "Democratic"): 779, ("John Deaton", "Republican"): 543,
                               ("Shiva Ayyadurai", "Unenrolled"): 27, ("Joe Tache", "Unenrolled"): 22,
                               ("All Others", ""): 0, ("Blanks", ""): 30})
        r = find(self.rows, level="precinct", county_name="Abington", precinct_id="-/1", contest_id=SEN)[0]
        self.assertEqual((r["precinct_name"], r["county_id"], r["contest_type"], r["contest_scope"], r["vote_type"],
                          r["state"], r["choice_id"]), ("Abington Precinct 1", "Abington", "candidate", "statewide",
                                                        "TOTAL", "MA", ""))

    def test_ward_precinct_name(self):
        r = find(self.rows, level="precinct", county_name="Attleboro", precinct_id="1/A", contest_id=SEN)[0]
        self.assertEqual(r["precinct_name"], "Attleboro Ward 1 Precinct A")

    def test_state_rows(self):
        got = {r["choice"]: r["votes"] for r in find(self.rows, level="state", contest_id=SEN)}
        self.assertEqual((got["Edward J. Markey"], got["Blanks"], len(got)), (1718276, 51371, 6))
        self.assertNotIn("Total Votes Cast", got)

    def test_unopposed_and_district(self):
        self.assertEqual([r["votes"] for r in find(self.rows, level="state", contest_id=H2, choice="James P. McGovern")], [234345])
        self.assertEqual([r["votes"] for r in find(self.rows, level="state", contest_id=REP, choice="Joe B. Glynn")], [6876])

    def test_question(self):
        r = find(self.rows, level="state", contest_id=Q1, choice="Yes")[0]
        self.assertEqual((r["contest_type"], r["party"], r["votes"], r["contest_name"]), ("measure", "", 2272519, Q1))
        self.assertTrue(find(self.rows, level="precinct", county_name="Barnstable", precinct_id="-/1", contest_id=Q1))

    def test_summary_clean(self):
        s = self.summary
        self.assertEqual((s["contests"], s["questions"]), (3, 1))
        self.assertEqual(s["party_label_differences"], LABELS)
        self.assertEqual(s["out_of_scope_offices"], {"Sheriff": 1})
        self.assertEqual(s["out_of_scope_questions"], {"1st Bristol": 1})
        for k in LISTS:
            self.assertEqual(s[k], [], k)


class CsvTest(unittest.TestCase):
    def test_numbers(self):
        t = "City/Town,Ward,Pct,A,All Others,Blanks,Total Votes Cast\n,,,Democratic\nX,-,1,\"1,401\",1,40,\"1,442\"\nX,-,2,\"1,40\",0,0,0\nTOTALS,,,x,1,40,\"1,442\"\n"
        p = parse_csv(t, "contest")
        self.assertEqual(p["lines"][0][3], {"A": 1401, "All Others": 1, "Blanks": 40, "Total Votes Cast": 1442})
        self.assertEqual(p["lines"][1][3]["A"], "1,40")

    def test_question_has_no_party_row(self):
        p = parse_csv(text("ma_q11789.csv"), "question")
        self.assertEqual((p["parties"], p["lines"][0][:3]), ({}, (2, "Barnstable", "-")))


def edit(name, old, new):
    t = text(name)
    assert t.count(old) == 1, old
    return t.replace(old, new)


class CheckTest(unittest.TestCase):
    def test_totals_row_mismatch(self):
        _, s, _ = run(self, {"ma_c173668.csv": edit("ma_c173668.csv", "Brewster,-,1,\"1,478\",588,6,198,\"2,270\"",
                                                    "Brewster,-,1,\"1,479\",588,6,198,\"2,271\"")})
        self.assertEqual(s["totals_row_mismatches"], [(REP, "Christopher Lambton", 15295, 15296),
                                                      (REP, "Total Votes Cast", 24385, 24386)])

    def test_total_votes_mismatch(self):
        _, s, _ = run(self, {"ma_c173668.csv": edit("ma_c173668.csv", "Brewster,-,1,\"1,478\",588,6,198,\"2,270\"",
                                                    "Brewster,-,1,\"1,478\",588,6,198,\"2,271\"")})
        self.assertEqual(s["total_votes_mismatches"], [(REP, "Brewster", "-/1", 2271, 2270)])

    def test_list_mismatch(self):
        _, s, _ = run(self, {"ma_c173668.csv": edit("ma_c173668.csv", 'TOTALS,,,"15,295"', 'TOTALS,,,"15,296"')})
        self.assertIn((REP, "Christopher Lambton", 15295, 15296), s["list_mismatches"])

    def test_list_one_sided(self):
        t = edit("ma_c173668.csv", '"Joe B. Glynn"', '"Joseph B. Glynn"')
        _, s, _ = run(self, {"ma_c173668.csv": t})
        self.assertIn((REP, "Joe B. Glynn", 6876, None), s["list_mismatches"])
        self.assertIn((REP, "Joseph B. Glynn", None, 6876), s["list_mismatches"])

    def test_non_numeric_not_checked(self):
        rows, s, _ = run(self, {"ma_c173668.csv": edit("ma_c173668.csv", "Brewster,-,1,\"1,478\"", "Brewster,-,1,n/a")})
        self.assertEqual(s["non_numeric"], [(REP, "Brewster", "-/1", "Christopher Lambton", "n/a")])
        self.assertIn((REP, "Christopher Lambton"), s["totals_row_not_checked"])
        self.assertIn((REP, "Brewster", "-/1"), s["total_votes_not_checked"])
        self.assertEqual((s["totals_row_mismatches"], s["total_votes_mismatches"]), ([], []))
        r = find(rows, level="precinct", contest_id=REP, county_name="Brewster", precinct_id="-/1", choice="Christopher Lambton")
        self.assertEqual(r[0]["votes"], "")

    def test_list_value_non_numeric_not_checked(self):
        t = text("ma_search.html").replace(">15,295<", ">n/a<", 1)
        _, s, _ = run(self, {"ma_search.html": t})
        self.assertIn((REP, "Christopher Lambton"), s["list_not_checked"])
        self.assertEqual(s["list_mismatches"], [])

    def test_duplicate_precinct(self):
        t = text("ma_c173668.csv").replace("TOTALS", 'Brewster,-,1,"1,478",588,6,198,"2,270"\nTOTALS', 1)
        rows, s, _ = run(self, {"ma_c173668.csv": t})
        self.assertEqual(s["duplicate_precincts"], [(REP, "Brewster", "-/1")])
        self.assertEqual(len(find(rows, level="precinct", contest_id=REP, county_name="Brewster", precinct_id="-/1")), 4)

    def test_duplicate_choice(self):
        t = edit("ma_c173668.csv", '"Joe B. Glynn"', '"Christopher Lambton"')
        _, s, _ = run(self, {"ma_c173668.csv": t})
        self.assertEqual(s["duplicate_choices"], [(REP, "Christopher Lambton")])

    def test_malformed_line(self):
        t = text("ma_c173668.csv").replace("TOTALS", "Brewster,-,9,1\nTOTALS", 1)
        _, s, _ = run(self, {"ma_c173668.csv": t})
        self.assertEqual(s["malformed_lines"], [(REP, 17, 4)])

    def test_unexpected_header_unreadable(self):
        t = edit("ma_c173668.csv", "Total Votes Cast", "Total")
        rows, s, _ = run(self, {"ma_c173668.csv": t})
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["contest 173668"])
        self.assertFalse(find(rows, contest_id=REP))

    def test_html_instead_of_csv(self):
        _, s, _ = run(self, {"ma_q11789.csv": "<html><body>Error</body></html>"})
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["question 11789"])

    def test_no_totals_row(self):
        t = text("ma_c173668.csv")
        t = t[:t.index("TOTALS")]
        _, s, _ = run(self, {"ma_c173668.csv": t})
        self.assertIn((REP, "Christopher Lambton"), s["totals_row_not_checked"])
        self.assertIn((REP, "Christopher Lambton"), s["list_not_checked"])

    def test_contest_without_file(self):
        _, s, _ = run(self, drop=("ma_c173571.csv",))
        self.assertEqual(s["contests_without_file"], [("contest", "173571", H2)])

    def test_file_not_in_list(self):
        t = text("ma_search.html").replace('id="election-id-173668"', 'id="election-id-999"')
        rows, s, _ = run(self, {"ma_search.html": t})
        self.assertEqual(s["files_not_in_list"], [("contest", "173668")])
        self.assertTrue(find(rows, contest_id="contest 173668"))

    def test_missing_search(self):
        rows, s, _ = run(self, drop=("ma_search.html",))
        self.assertEqual(s["missing_files"], ["search"])
        for k in ("list_mismatches", "list_not_checked", "party_label_differences", "contests_without_file",
                  "files_not_in_list", "out_of_scope_offices"):
            self.assertIsNone(s[k], k)
        self.assertEqual(s["totals_row_mismatches"], [])
        self.assertTrue(find(rows, contest_id="contest 173531"))


if __name__ == "__main__":
    unittest.main()
