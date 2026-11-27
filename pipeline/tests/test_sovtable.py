"""Bergen County, NJ statement-of-votes district report (pipeline/readers/sovtable.py).

pdf_bergen_district.pdf: nine pages of the 2026 general report (735 pages): 1 (U.S. Senate, Allendale and
Alpine, withheld cells), 30 (Senate, Hasbrouck Heights' wrapped provisional-unit name), 505 (Mahwah
Council, 13 columns), 564 and 567 (Teaneck Council, its choices and its Total Votes on separate pages),
651-652 (Maywood Board of Education: a Write-ins value, a hyphen at a line break), 734-735 (the Wyckoff
public question, complete with its county rows).
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.sovtable import check, parse_pages

FX = os.path.join(os.path.dirname(__file__), "fixtures")
PDF = os.path.join(FX, "pdf_bergen_district.pdf")
HAVE_PDFIUM = importlib.util.find_spec("pypdfium2") is not None
STATS = ["Registered Voters", "Voters Cast", "Turnout (%)"]


def row(pages, page, left):
    (r,) = [r for r in pages[page]["rows"] if r[0] == left]
    return r[1]


@unittest.skipUnless(HAVE_PDFIUM, "needs pypdfium2 (.venv)")
class TablePagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pipeline.readers.sovtable import table_pages

        cls.pages = table_pages(PDF)

    def test_labels_from_rotated_header(self):
        self.assertEqual(self.pages[0]["labels"],
                         STATS + ["REP - JUSTIN MURPHY", "DEM - CORY BOOKER", "VERONICA FERNANDEZ", "JOANNE KUNIANSKY",
                                  "Write-ins", "Total Votes"])
        self.assertEqual(self.pages[2]["labels"][3:11],
                         ["JENNIFER DIAMOND", "ROBERT M. FERGUSON III", "CHRISTOPHER M. HOWARD", "MEGAN E. JANKOWSKI",
                          "ANTHONY J. MILLER", "PHILIP S. COLELLA", "JOHN STEPHEN MORIN Jr.", "JANET A. ARIEMMA"])
        self.assertEqual(self.pages[5]["labels"][5], "LYNN O'CONNELL-SORIANO")

    def test_cells_by_position_blank_and_split_numbers(self):
        # "Allendale 2 Early Voting 920 117 12.72% 52 65 117": the two small candidates print nothing,
        # and PDFium's text splits the last 117 into "1 17"
        self.assertEqual(row(self.pages, 0, "Allendale 2 Early Voting"),
                         ["920", "117", "12.72%", "52", "65", "", "", "", "117"])
        self.assertEqual(row(self.pages, 0, "Alpine Provisional Provisional"),
                         ["0", "11", "", "***", "***", "***", "***", "***", "***"])

    def test_wrapped_unit_name_joined(self):
        self.assertEqual(row(self.pages, 1, "Haworth Provisional Mail-In")[:2], ["0", "0"])
        self.assertTrue(any(r[0] == "Hasbrouck Heights Provisional Early Voting" for p in self.pages for r in p["rows"]))
        self.assertEqual([u for p in self.pages for u in p["unparsed"]], [])

    def test_title_and_refresh_time(self):
        self.assertEqual((self.pages[7]["title"], self.pages[7]["refreshed"]),
                         ("1 WYCKOFF PUBLIC QUESTION", "Monday, November 16, 2026 3:22 PM"))

    def test_parse_and_check_complete_contests(self):
        contests, issues = parse_pages(self.pages)
        self.assertEqual(issues, {"label_conflicts": [], "cell_conflicts": [], "unit_type_conflicts": [], "unparsed": []})
        w = contests["WYCKOFF PUBLIC QUESTION"]
        self.assertEqual(w["choices"], ["YES", "NO"])
        self.assertEqual(w["units"]["Wyckoff"]["type"], "municipality")
        self.assertEqual(w["units"]["Wyckoff Provisional"]["type"], "district")
        self.assertEqual(w["units"]["COUNTY"]["kinds"]["Total"]["YES"], 4658)
        # Teaneck: choices on page 564, Total Votes on 567, joined per unit
        t1 = contests["TEANECK COUNCIL"]["units"]["Teaneck 1"]["kinds"]["Total"]
        self.assertEqual((t1["AVI BERLINER"], t1["Total Votes"]), (130, 1499))
        out = check({"WYCKOFF PUBLIC QUESTION": w, "MAYWOOD BOARD OF EDUCATION": contests["MAYWOOD BOARD OF EDUCATION"]})
        for k in ("row_sums", "vote_types_vs_total", "units_vs_municipality", "municipalities_vs_county",
                  "registered_differs_by_type", "missing_columns"):
            self.assertEqual(out[k], [], k)
        # Total Votes counts votes in no printed column; Maywood's 52 equal its "Personal Choice" line elsewhere
        self.assertEqual(out["unattributed"], {"WYCKOFF PUBLIC QUESTION": 0, "MAYWOOD BOARD OF EDUCATION": 52})


def page(title, labels, rows):
    return {"title": title, "labels": STATS + labels, "rows": rows, "unparsed": [], "refreshed": None}


KINDS = ["Early Voting", "Election Day", "Mail-In", "Provisional", "Total"]
# per unit: registered, then per kind [voters cast, YES, NO, Write-ins, Total Votes] ("" = not printed)
A1 = ("100", [["5", "2", "1", "", "3"], ["10", "6", "3", "", "9"], ["2", "1", "1", "", "2"], ["0", "", "", "", ""],
              ["17", "9", "5", "", "14"]])
A2 = ("50", [["4", "3", "", "", "3"], ["6", "4", "1", "", "5"], ["0", "", "", "", ""], ["1", "1", "***", "", "1"],
             ["11", "8", "1", "", "9"]])
A = ("150", [["9", "5", "1", "", "6"], ["16", "10", "4", "", "14"], ["2", "1", "1", "", "2"], ["1", "1", "***", "", "1"],
             ["28", "17", "6", "", "23"]])


def unit(name, data, county=False):
    reg, per = data
    out = []
    for k, v in zip(KINDS, per):
        left = ("Contest Total" if k == "Total" else f"Total - {k}") if county else f"{name} {k}"
        out.append((left, [reg, v[0], ""] + v[1:]))
    return out


class ParseChecksTest(unittest.TestCase):
    """Synthetic contest: town A (two districts), its subtotal, the county rows; one withheld cell."""

    def build(self):
        rows = unit("A 1", A1) + unit("A 2", A2) + unit("A", A) + unit("", A, county=True)
        return [page("1 QUESTION", ["YES", "NO", "Write-ins", "Total Votes"], rows)]

    def test_units_classified_and_values(self):
        c, issues = parse_pages(self.build())
        units = c["QUESTION"]["units"]
        self.assertEqual({u: x["type"] for u, x in units.items()},
                         {"A 1": "district", "A 2": "district", "A": "municipality", "COUNTY": "county"})
        self.assertEqual(units["A 1"]["kinds"]["Early Voting"], {"Registered Voters": 100, "Voters Cast": 5, "YES": 2,
                                                                 "NO": 1, "Write-ins": 0, "Total Votes": 3})
        self.assertIsNone(units["A 2"]["kinds"]["Provisional"]["NO"])

    def test_withheld_cell_skips_its_sums(self):
        out = check(parse_pages(self.build())[0])
        self.assertEqual(out["withheld"], 3)
        for k in ("row_sums", "vote_types_vs_total", "units_vs_municipality", "municipalities_vs_county"):
            self.assertEqual(out[k], [], k)
        self.assertEqual(out["unattributed"], {"QUESTION": 0})

    def test_differences_listed(self):
        p = self.build()
        # A 2's Early Voting YES 3 -> 9: more than its Total Votes, and it no longer adds up anywhere
        p[0]["rows"] = [(l, (c[:3] + ["9"] + c[4:]) if l == "A 2 Early Voting" else c) for l, c in p[0]["rows"]]
        out = check(parse_pages(p)[0])
        self.assertEqual(out["row_sums"], [("QUESTION", "A 2", "Early Voting", 3, 9)])
        self.assertIn(("QUESTION", "A 2", "YES", 8, 14), out["vote_types_vs_total"])
        self.assertIn(("QUESTION", "A", "Early Voting", "YES", 5, 11), out["units_vs_municipality"])

    def test_conflicting_repeat_listed(self):
        p = self.build()
        p.append(page("1 QUESTION", ["Total Votes"], [("A 1 Total", ["100", "17", "", "99"])]))
        _, issues = parse_pages(p)
        self.assertEqual(issues["cell_conflicts"], [("QUESTION", "A 1", "Total", "Total Votes", 14, 99)])


@unittest.skipUnless(HAVE_PDFIUM, "needs pypdfium2 (.venv)")
class PassTest(unittest.TestCase):
    def test_rows_and_turnout(self):
        from pipeline.readers.pdfreport import parse_pass

        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        shutil.copy(PDF, os.path.join(d, "b.pdf"))
        with open(os.path.join(d, "pass.json"), "w") as f:
            json.dump({"source_id": "pdf-b", "state": "NJ", "county": "Bergen", "layout": "bergen",
                       "files": [{"kind": "district_pdf", "path": "b.pdf"}]}, f)
        rows, s, turnout = parse_pass(os.path.join(d, "pass.json"), base_dir=d)
        (r,) = [r for r in rows if r["precinct_name"] == "Allendale 1" and r["choice"] == "JUSTIN MURPHY"
                and r["vote_type"] == "Election Day"]
        self.assertEqual((r["votes"], r["party"], r["level"], r["county_name"], r["contest_scope"]),
                         (308, "REP", "precinct", "Bergen", "local"))
        (c,) = [r for r in rows if r["level"] == "county" and r["contest_name"] == "WYCKOFF PUBLIC QUESTION"
                and r["choice"] == "YES" and r["vote_type"] == "TOTAL"]
        self.assertEqual(c["votes"], 4658)
        self.assertEqual([r for r in rows if r["precinct_name"] in ("Allendale", "Wyckoff")], [])  # subtotals
        (w,) = [r for r in rows if r["precinct_name"] == "Alpine Provisional" and r["choice"] == "JUSTIN MURPHY"
                and r["vote_type"] == "Provisional"]
        self.assertEqual(w["votes"], "")
        (t,) = [t for t in turnout if t["precinct_name"] == "Allendale 1"]
        self.assertEqual((t["registered_voters"], t["ballots_cast"]), (1739, 1013))
        self.assertEqual((s["contests"], s["unparsed"], s["missing_files"]), (5, [], []))


if __name__ == "__main__":
    unittest.main()
