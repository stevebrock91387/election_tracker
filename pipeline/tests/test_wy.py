"""Wyoming reader on the real 2026 results ZIP (unmodified) and on synthetic grids."""
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile

from pipeline.readers.wy import PBP, SUMMARIES, TBC, TURNOUT_COLUMNS, parse_blocks, parse_pass, parse_workbooks, read_xlsx
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
SEN = "United States Senator"
# Real source discrepancy: the summaries and the precinct workbook spell Teton's HD 22 winner differently.
TETON = [("Teton", "House District 22", "Andrew Byron", 1399, None), ("Teton", "House District 22", "Andrew P Byron", None, 1399)]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def member(name):
    with zipfile.ZipFile(os.path.join(FX, "wy_results.zip")) as z:
        return z.read(name)


def grid(*rows):
    """Rows given as {row number: [cells]}; gaps become empty rows."""
    spec = dict(rows)
    return [list(spec.get(n, [])) for n in range(1, max(spec) + 1)]


class ReadXlsxTest(unittest.TestCase):
    def test_pbp_sheets_in_order(self):
        sheets = read_xlsx(member(PBP))
        self.assertEqual(len(sheets), 23)
        self.assertEqual((sheets[0][0], sheets[-1][0]), ("Albany", "Weston"))
        g = dict(sheets)["Albany"]
        self.assertEqual((g[3][0], g[3][1], g[3][5]), ("Precinct", "Harriet\nHageman (R)", "Undervotes"))
        self.assertEqual(g[4][:3], ["13-1", "403", "820"])
        self.assertEqual(g[15][0], "Total")

    def test_summaries_sheet_names(self):
        self.assertEqual([n for n, _ in read_xlsx(member(SUMMARIES))],
                         ["Statewide Total Ballots Cast", "Statewide Candidates", "Statewide Senate Odd",
                          "Statewide House", "Statewide Judicial", "Statewide Ballot Issue"])

    def test_tbc(self):
        g = dict(read_xlsx(member(TBC)))["Albany"]
        self.assertEqual((g[2][:2], g[3][:2]), (["Precinct", "Total Ballots Cast"], ["13-1", "1244"]))

    def test_date_formatted_names_rendered(self):
        notes = {}
        g = dict(read_xlsx(member(PBP), notes))["Carbon"]
        self.assertEqual([g[i][0] for i in (4, 5, 6)], ["01-01", "01-02", "02-01"])
        self.assertIn(("Carbon", "A5", "44562", "01-01"), notes["date_formatted_cells"])
        self.assertEqual(notes["unrendered_formats"], [])
        self.assertEqual({c[0] for c in notes["date_formatted_cells"]}, {"Carbon", "Converse", "Crook"})

    def test_format_render(self):
        from pipeline.readers.wy import render_date
        self.assertEqual(render_date("44562", "mm\\-dd", False), "01-01")
        self.assertEqual(render_date("44594", "m\\-d", False), "2-2")
        self.assertEqual(render_date("44562", "yyyy-mm-dd", False), "2022-01-01")
        self.assertEqual(render_date("0", "mm\\-dd", True), "01-01")
        self.assertIsNone(render_date("44562", "[$-409]mmmm d", False))
        self.assertIsNone(render_date("44562.5", "mm\\-dd", False))

    def test_not_a_workbook(self):
        with self.assertRaises(ValueError):
            read_xlsx(b"<html>blocked</html>")


class BlocksTest(unittest.TestCase):
    def test_two_blocks_and_total(self):
        g = grid((1, [None, "title"]), (3, [None, "A Office", None, "B Office"]),
                 (4, ["Precinct", "X\nOne (R)", "Write-Ins", "Y (D)", "Undervotes"]),
                 (5, ["1-1", "5", "1", "-", "-"]), (6, ["1-2", "7", "0", "3", "2"]), (7, ["Total", "12", "1", "3", "2"]))
        contests, problems = parse_blocks(g)
        self.assertEqual([c["name"] for c in contests], ["A Office", "B Office"])
        a, b = contests
        self.assertEqual([h for _, h in a["columns"]], ["X\nOne (R)", "Write-Ins"])
        self.assertEqual([u for _, u, _ in a["units"]], ["1-1", "1-2"])
        self.assertEqual(b["units"][0][2], {3: "-", 4: "-"})
        self.assertEqual(b["total"], {3: "3", 4: "2"})
        self.assertEqual(problems, {"blank_headers": [], "out_of_place_cells": [], "trailing_text": [], "layout": []})

    def test_trailing_empty_headers_ignored(self):
        g = grid((3, [None, "A"]), (4, ["Precinct", "X (R)", None, None]), (5, ["1-1", "5", None, None]),
                 (6, ["Total", "5"]))
        (c,), problems = parse_blocks(g)
        self.assertEqual(c["columns"], [(1, "X (R)")])
        self.assertEqual(problems["blank_headers"], [])

    def test_blank_header_with_values_listed(self):
        g = grid((3, [None, "A"]), (4, ["Precinct", "X (R)", None, "Y (D)"]), (5, ["1-1", "5", "9", "1"]),
                 (6, ["Total", "5", "9", "1"]))
        (c,), problems = parse_blocks(g)
        self.assertEqual([h for _, h in c["columns"]], ["X (R)", "Y (D)"])
        self.assertEqual(problems["blank_headers"], [("A", 2)])

    def test_trailing_text_after_total(self):
        g = grid((3, [None, "A"]), (4, ["Precinct", "X (R)"]), (5, ["1-1", "5"]), (6, ["Total", "5"]),
                 (8, [None, " "]), (10, [None, "Note: something"]))
        _, problems = parse_blocks(g)
        self.assertEqual(problems["trailing_text"], [(10, "Note: something")])

    def test_unit_without_name_listed(self):
        g = grid((3, [None, "A"]), (4, ["Precinct", "X (R)"]), (5, [None, "5"]), (6, ["Total", "5"]))
        (c,), problems = parse_blocks(g)
        self.assertEqual((c["units"], problems["out_of_place_cells"]), ([], [(5, 1, "5")]))

    def test_no_contest_row(self):
        g = grid((4, ["Precinct", "X (R)"]), (5, ["1-1", "5"]))
        contests, problems = parse_blocks(g)
        self.assertEqual((contests, problems["layout"]), ([], ["no contest names in row 3"]))

    def test_no_total_row(self):
        g = grid((3, [None, "A"]), (4, ["Precinct", "X (R)"]), (5, ["1-1", "5"]))
        (c,), problems = parse_blocks(g)
        self.assertIsNone(c["total"])
        self.assertEqual(problems["layout"], ["no Total row"])


BASE = {"state": "WY", "source_id": "wy-test", "source_sha256": "abc"}
LISTS = ["total_row_mismatches", "total_row_not_checked", "county_mismatches", "county_not_checked",
         "ballots_mismatches", "non_numeric", "empty_cells", "duplicate_units", "duplicate_choices",
         "duplicate_contests", "blank_headers", "out_of_place_cells", "unmatched_tbc_precincts", "sheet_mismatches",
         "layout_problems", "unrendered_formats", "unreadable_members", "missing_members", "unreadable_files",
         "missing_files"]


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "wy_pass.json"), base_dir=FX)

    def test_columns(self):
        self.assertTrue(all(list(r) == COLUMNS for r in self.rows))
        self.assertTrue(all(list(r) == TURNOUT_COLUMNS for r in self.turnout))

    def test_precinct_rows(self):
        got = {(r["choice"], r["party"]): r["votes"] for r in
               find(self.rows, level="precinct", county_name="Albany", precinct_id="13-1", contest_id=SEN)}
        self.assertEqual(got, {("Harriet Hageman", "R"): 403, ("James Byrd", "D"): 820, ("Write-Ins", ""): 7,
                               ("Overvotes", ""): 0, ("Undervotes", ""): 14})
        r = find(self.rows, level="precinct", precinct_id="13-1", contest_id=SEN, choice="James Byrd")[0]
        self.assertEqual((r["county_id"], r["vote_type"], r["contest_type"], r["contest_scope"], r["choice_id"], r["state"],
                          r["source_sha256"]), ("Albany", "TOTAL", "candidate", "statewide", "", "WY", self.summary["sha256"]))

    def test_rendered_precinct_name(self):
        self.assertTrue(find(self.rows, level="precinct", county_name="Carbon", precinct_id="01-01", contest_id=SEN))
        self.assertFalse(find(self.rows, level="precinct", county_name="Carbon", precinct_id="44562"))

    def test_county_and_state_rows(self):
        c = find(self.rows, level="county", county_name="Albany", contest_id=SEN, choice="Harriet Hageman")
        s = find(self.rows, level="state", contest_id=SEN, choice="Harriet Hageman")
        self.assertEqual(([r["votes"] for r in c], [r["votes"] for r in s]), ([5450], [122174]))
        self.assertEqual(s[0]["county_id"], "")

    def test_measure_and_retention(self):
        prop = "Statewide Ballot Proposition Proposed Initiative Proposition Number One"
        r = find(self.rows, level="county", county_name="Albany", contest_id=prop, choice="For")[0]
        self.assertEqual((r["contest_type"], r["votes"]), ("measure", 4632))
        j = find(self.rows, level="state", contest_id="Supreme Court Justice, Wyoming Supreme Court Bridget Hill")
        self.assertEqual({r["contest_type"] for r in j}, {"retention"})
        self.assertEqual({r["choice"] for r in j}, {"Yes", "No", "Overvotes", "Undervotes"})

    def test_dash_gives_no_row(self):
        self.assertFalse(find(self.rows, level="county", county_name="Albany", contest_id="House District 1"))
        self.assertGreater(self.summary["not_on_ballot_cells"], 0)

    def test_turnout(self):
        t = {(r["county_name"], r["precinct_id"]): r["ballots_cast"] for r in self.turnout}
        self.assertEqual((t[("Albany", "13-1")], len(t)), (1244, 432))

    def test_counts_and_clean(self):
        s = self.summary
        self.assertEqual((s["counties"], s["precincts"]), (23, 432))
        self.assertEqual(sorted(r[0] for r in s["empty_unit_rows"]), ["Campbell", "Laramie", "Natrona", "Sweetwater"])
        self.assertEqual([c[:3] for c in s["empty_cells"]], [("Teton", "1-12", "Senate District 17")])
        self.assertEqual({c[:2] for c in s["date_formatted_cells"]}, {("PbP", "Carbon"), ("PbP", "Converse"), ("PbP", "Crook")})
        self.assertEqual(s["trailing_text"][0][0], "Statewide Ballot Issue")
        self.assertEqual(s["county_mismatches"], TETON)
        for k in LISTS:
            if k not in ("empty_cells", "county_mismatches"):
                self.assertEqual(s[k], [], k)

    def test_ballot_balance_informational(self):
        self.assertIsInstance(self.summary["ballot_balance_mismatches"], list)


def books():
    with zipfile.ZipFile(os.path.join(FX, "wy_results.zip")) as z:
        return {m: read_xlsx(z.read(m)) for m in (PBP, TBC, SUMMARIES)}


def sheet(b, member_, name):
    return dict(b[member_])[name]


class CheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = books()

    def fresh(self):
        import copy
        return copy.deepcopy(self.real)

    def test_total_row_mismatch(self):
        b = self.fresh()
        sheet(b, PBP, "Albany")[4][1] = "404"  # 13-1 Hageman
        _, s, _ = parse_workbooks(BASE, b)
        self.assertEqual(s["total_row_mismatches"], [("Albany", SEN, "Harriet Hageman", 5450, 5451)])
        self.assertEqual(s["county_mismatches"], TETON)

    def test_county_mismatch(self):
        b = self.fresh()
        sheet(b, SUMMARIES, "Statewide Candidates")[4][1] = "5451"  # Albany Hageman
        _, s, _ = parse_workbooks(BASE, b)
        self.assertIn(("Albany", SEN, "Harriet Hageman", 5451, 5450), s["county_mismatches"])
        self.assertIn(("Statewide Candidates", SEN, "Harriet Hageman", 122174, 122175), s["total_row_mismatches"])

    def test_county_one_sided(self):
        b = self.fresh()
        g = sheet(b, SUMMARIES, "Statewide Candidates")
        g[4][1] = "-"
        _, s, _ = parse_workbooks(BASE, b)
        self.assertIn(("Albany", SEN, "Harriet Hageman", None, 5450), s["county_mismatches"])

    def test_non_numeric_not_checked(self):
        b = self.fresh()
        sheet(b, PBP, "Albany")[4][1] = "n/a"
        rows, s, _ = parse_workbooks(BASE, b)
        self.assertIn(("Albany", "13-1", SEN, "Harriet Hageman", "n/a"), s["non_numeric"])
        self.assertIn(("Albany", SEN, "Harriet Hageman"), s["total_row_not_checked"])
        self.assertEqual(s["total_row_mismatches"], [])
        r = find(rows, level="precinct", county_name="Albany", precinct_id="13-1", contest_id=SEN, choice="Harriet Hageman")
        self.assertEqual(r[0]["votes"], "")

    def test_ballots_mismatch(self):
        b = self.fresh()
        sheet(b, SUMMARIES, "Statewide Total Ballots Cast")[4][1] = "13409"
        _, s, _ = parse_workbooks(BASE, b)
        self.assertEqual(s["ballots_mismatches"], [("Albany", 13408, 13409)])

    def test_ballot_balance(self):
        b = self.fresh()
        sheet(b, TBC, "Albany")[3][1] = "1245"
        _, s, _ = parse_workbooks(BASE, b)
        self.assertIn(("Albany", "13-1", SEN, 1244, 1245), s["ballot_balance_mismatches"])

    def test_unmatched_tbc(self):
        b = self.fresh()
        sheet(b, TBC, "Albany")[3][0] = "13-9"
        _, s, _ = parse_workbooks(BASE, b)
        self.assertEqual(sorted(s["unmatched_tbc_precincts"]), [("Albany", "13-1", "pbp only"), ("Albany", "13-9", "tbc only")])

    def test_duplicate_unit(self):
        b = self.fresh()
        g = sheet(b, PBP, "Albany")
        g[5][0] = "13-1"
        rows, s, _ = parse_workbooks(BASE, b)
        self.assertEqual(s["duplicate_units"], [("Albany", "13-1")])
        self.assertEqual(len(find(rows, level="precinct", county_name="Albany", precinct_id="13-1", contest_id=SEN)), 5)

    def test_duplicate_choice(self):
        b = self.fresh()
        sheet(b, PBP, "Albany")[3][2] = "Harriet\nHageman (R)"
        _, s, _ = parse_workbooks(BASE, b)
        self.assertIn(("Albany", SEN, "Harriet Hageman"), s["duplicate_choices"])

    def test_sheet_mismatch(self):
        b = self.fresh()
        b[TBC] = [x for x in b[TBC] if x[0] != "Weston"]
        _, s, _ = parse_workbooks(BASE, b)
        self.assertIn(("Weston", "pbp, summaries", "tbc"), s["sheet_mismatches"])

    def test_missing_tbc_member(self):
        b = self.fresh()
        del b[TBC]
        rows, s, t = parse_workbooks(BASE, b)
        self.assertEqual((s["missing_members"], t), ([TBC], []))
        for k in ("ballots_mismatches", "ballot_balance_mismatches", "unmatched_tbc_precincts"):
            self.assertIsNone(s[k], k)
        self.assertEqual(s["county_mismatches"], TETON)
        self.assertTrue(find(rows, level="precinct"))

    def test_missing_summaries_member(self):
        b = self.fresh()
        del b[SUMMARIES]
        rows, s, _ = parse_workbooks(BASE, b)
        self.assertIsNone(s["county_mismatches"])
        self.assertIsNone(s["ballots_mismatches"])
        self.assertFalse(find(rows, level="county"))

    def test_missing_pbp_member(self):
        b = self.fresh()
        del b[PBP]
        rows, s, _ = parse_workbooks(BASE, b)
        for k in ("county_mismatches", "ballot_balance_mismatches", "duplicate_units", "empty_cells"):
            self.assertIsNone(s[k], k)
        self.assertTrue(find(rows, level="county"))


class FileTest(unittest.TestCase):
    def run_zip(self, data=None, files=True, members=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        if members is not None:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, b in members.items():
                    z.writestr(n, b)
            data = buf.getvalue()
        if data is not None:
            with open(os.path.join(d, "wy.zip"), "wb") as f:
                f.write(data)
        with open(os.path.join(d, "pass.json"), "w") as f:
            json.dump({"source_id": "wy-test", "state": "WY", "files": [{"kind": "zip", "path": "wy.zip"}] if files else []}, f)
        return parse_pass(os.path.join(d, "pass.json"), base_dir=d)

    def test_missing_file(self):
        rows, s, _ = self.run_zip(files=False)
        self.assertEqual((rows, s["missing_files"]), ([], ["zip"]))
        self.assertIsNone(s["county_mismatches"])

    def test_html_zip(self):
        rows, s, _ = self.run_zip(b"<html>blocked</html>")
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["zip"])
        self.assertIsNone(s["total_row_mismatches"])

    def test_unreadable_member(self):
        with zipfile.ZipFile(os.path.join(FX, "wy_results.zip")) as z:
            m = {n: z.read(n) for n in (PBP, SUMMARIES)}
        m[TBC] = b"not a workbook"
        rows, s, _ = self.run_zip(members=m)
        self.assertEqual([u[0] for u in s["unreadable_members"]], [TBC])
        self.assertIsNone(s["ballots_mismatches"])
        self.assertEqual(s["county_mismatches"], TETON)

    def test_other_members_listed(self):
        with zipfile.ZipFile(os.path.join(FX, "wy_results.zip")) as z:
            m = {n: z.read(n) for n in z.namelist()}
        m["readme.txt"] = b"hi"
        _, s, _ = self.run_zip(members=m)
        self.assertEqual(s["other_members"], ["readme.txt"])


if __name__ == "__main__":
    unittest.main()
