"""PDF results-report reader on text cut from the 2026 general PDFs of Camden and Sussex counties, NJ.

Fixtures (pages separated by form feeds, text as pypdfium2 extracts it):
- pdf_camden_pages.txt: the summary page header and statistics, the summary block of the Sterling Regional
  BOE (Magnolia) contest, a district-table statistics page cut to Audubon 1-2 and Magnolia, the contest's
  district-table page, and the start of a municipality table (ignored).
- pdf_sussex_county_pages.txt: the countywide summary header and statistics and the Hamburg Borough Mayor block.
- pdf_sussex_district_pages.txt: Hamburg Boro districts 1 and 2 (statistics and the mayor's race) and Walpack
  Twp district 1's U.S. Senate block, whose counts the county withholds.
- pdf_sussex_countywide.pdf: the real 14-page Sussex countywide summary (needs pypdfium2).
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.pdfreport import (
    CAMDEN, SUSSEX, page_texts, parse_district_table, parse_pass, parse_precinct_report, parse_summary,
)

FX = os.path.join(os.path.dirname(__file__), "fixtures")
HAVE_PDFIUM = importlib.util.find_spec("pypdfium2") is not None


def pages(name):
    with open(os.path.join(FX, name)) as f:
        return f.read().split("\f")


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


MAGNOLIA = "Member of Regional Board of Education Sterling Regional School District - Magnolia"


class CamdenSummaryTest(unittest.TestCase):
    def setUp(self):
        self.contests, self.stats, self.issues = parse_summary(pages("pdf_camden_pages.txt"), CAMDEN)

    def test_contest_block(self):
        (c,) = self.contests
        self.assertEqual((c["name"], c["vote_for"]), (MAGNOLIA, "1"))
        self.assertEqual([(x["choice"], x["party"]) for x in c["choices"]],
                         [("DaNeen Satchell", ""), ("Write-In Totals", ""), ("Overvotes", ""), ("Undervotes", "")])
        self.assertEqual(c["choices"][0]["values"], {"TOTAL": 1154, "Early Voting": 72, "Vote By Mail": 368,
                                                     "Election Day": 699, "Provisional": 15})
        self.assertEqual(c["totals"]["Contest Totals"]["TOTAL"], 1554)

    def test_statistics(self):
        self.assertEqual((self.stats["registered"], self.stats["ballots"]["TOTAL"], self.stats["ballots"]["Provisional"]),
                         (393550, 178067, 4149))

    def test_no_issues(self):
        self.assertEqual(self.issues, {"header_mismatches": [], "unparsed_lines": []})


class CamdenTableTest(unittest.TestCase):
    def setUp(self):
        contests, _, _ = parse_summary(pages("pdf_camden_pages.txt"), CAMDEN)
        self.table, self.turnout, self.issues = parse_district_table(pages("pdf_camden_pages.txt"), contests)

    def test_precinct_values_by_column(self):
        self.assertEqual(self.table[MAGNOLIA]["Magnolia District 1"],
                         {"DaNeen Satchell": 300, "Write-In Totals": 12, "Total Votes Cast": 312, "Overvotes": 0,
                          "Undervotes": 80, "Contest Totals": 392})
        self.assertEqual(sorted(self.table[MAGNOLIA]),
                         ["Magnolia District 1", "Magnolia District 2", "Magnolia District 3", "Magnolia District 4",
                          "Magnolia Provisional", "Totals"])

    def test_turnout_rows(self):
        self.assertEqual(self.turnout["Magnolia Provisional"], (0, 23))
        self.assertEqual(self.turnout["Audubon District 1"], (919, 456))
        self.assertEqual(len(self.turnout), 7)

    def test_municipality_table_ignored(self):
        self.assertNotIn("Tavistock", self.turnout)
        self.assertEqual(self.issues, {"unmatched_headers": [], "unknown_contests": [], "truncated_names": [], "placeholders_nonzero": [], "unparsed_lines": [],
                                       "duplicate_cells": []})

    def test_line_break_hyphen_marker_read_as_hyphen(self):
        # PDFium returns U+FFFE for a hyphen at a line break ("Corry-Gaft" wrapped in a column header)
        p = pages("pdf_camden_pages.txt")
        p[0] = p[0].replace("DaNeen Satchell 1,154", "DaNeen Satchell-Smith 1,154")
        p[2] = p[2].replace("DaNeen\nSatchell\n", "DaNeen\nSatchell\ufffeSmith\n")
        contests, _, _ = parse_summary(p, CAMDEN)
        table, _, issues = parse_district_table(p, contests)
        self.assertEqual(table[MAGNOLIA]["Magnolia District 1"]["DaNeen Satchell-Smith"], 300)
        self.assertEqual(issues["unmatched_headers"], [])

    def test_truncated_table_name_matches_unique_summary_prefix(self):
        p = pages("pdf_camden_pages.txt")
        p[2] = p[2].replace("Regional School District - Magnolia\n", "Regional School District\n")
        contests, _, _ = parse_summary(p, CAMDEN)
        table, _, issues = parse_district_table(p, contests)
        self.assertEqual(table[MAGNOLIA]["Totals"]["DaNeen Satchell"], 1154)
        self.assertEqual(issues["truncated_names"],
                         [("Member of Regional Board of Education Sterling Regional School District", MAGNOLIA)])
        self.assertEqual(issues["unknown_contests"], [])

    def test_placeholder_columns_matched_and_checked_not_kept(self):
        import re
        p = pages("pdf_camden_pages.txt")
        p[0] = p[0].replace("Write-In Totals 33 2", "No Nomination Made 0 0 0 0 0\nWrite-In Totals 33 2")
        p[2] = p[2].replace("Satchell\n", "Satchell\nNo Nomination\nMade\n")
        p[2] = re.sub(r"^((?:Magnolia \S+(?: \d)?|Totals) [\d,]+) ", r"\1 0 ", p[2], flags=re.M)
        p[2] = p[2].replace("Magnolia District 4 322 0 ", "Magnolia District 4 322 2 ")
        contests, _, _ = parse_summary(p, CAMDEN)
        table, _, issues = parse_district_table(p, contests)
        self.assertEqual(issues["unmatched_headers"], [])
        self.assertEqual(table[MAGNOLIA]["Magnolia District 1"]["Write-In Totals"], 12)
        self.assertEqual(issues["placeholders_nonzero"], [(MAGNOLIA, "Magnolia District 4", "No Nomination Made", 2)])

    def test_statistics_then_contest_on_one_page(self):
        p = pages("pdf_camden_pages.txt")
        stats = p[1].split("\n")[:-2]  # drop the footer
        contest = p[2].split("\n")[4:]  # from the contest name on
        p[1:3] = ["\n".join(stats + ["Totals 4,971 2,340"] + contest)]
        contests, _, _ = parse_summary(p, CAMDEN)
        table, turnout, issues = parse_district_table(p, contests)
        self.assertEqual(len(turnout), 7)
        self.assertEqual(table[MAGNOLIA]["Magnolia District 1"]["DaNeen Satchell"], 300)
        self.assertEqual(issues["unparsed_lines"], [])

    def test_unsegmentable_header_listed_and_skipped(self):
        p = pages("pdf_camden_pages.txt")
        p[2] = p[2].replace("DaNeen\n", "DaNeen X\n")
        contests, _, _ = parse_summary(p, CAMDEN)
        table, _, issues = parse_district_table(p, contests)
        self.assertNotIn(MAGNOLIA, table)
        self.assertEqual(issues["unmatched_headers"], [(MAGNOLIA, "DaNeen X Satchell Write-in Totals Total Votes Cast "
                                                                  "Overvotes Undervotes Contest Total")])


def run_pass(test, layout, files):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    recfiles = []
    for kind, fixture in files:
        path = os.path.join(d, kind + ".txt")
        shutil.copy(os.path.join(FX, fixture), path)
        recfiles.append({"kind": kind, "path": path})
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "pdf-test", "state": "NJ", "county": layout["county"], "layout": layout["name"],
                   "files": recfiles}, f)
    return parse_pass(os.path.join(d, "pass.json"), text_pages=pages)


class CamdenPassTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.s, self.turnout = run_pass(self, CAMDEN, [("report_pdf", "pdf_camden_pages.txt")])

    def test_county_rows(self):
        (r,) = find(self.rows, level="county", choice="DaNeen Satchell", vote_type="Vote By Mail")
        self.assertEqual((r["votes"], r["county_name"], r["contest_id"], r["contest_scope"], r["choice_id"], r["vote_for"]),
                         (368, "Camden", MAGNOLIA, "local", "", "1"))
        self.assertEqual(len(find(self.rows, level="county")), 4 * 5)

    def test_precinct_rows(self):
        (r,) = find(self.rows, level="precinct", precinct_name="Magnolia District 2", choice="Overvotes")
        self.assertEqual((r["votes"], r["vote_type"], r["precinct_id"]), (3, "TOTAL", "Magnolia District 2"))
        self.assertEqual(len(find(self.rows, level="precinct")), 5 * 4)
        self.assertEqual(find(self.rows, precinct_name="Totals"), [])

    def test_checks_clean_except_partial_turnout(self):
        s = self.s
        for k in ("sum_mismatches", "precinct_vs_county", "table_totals_vs_county", "table_totals_vs_precincts",
                  "unmatched_headers", "unknown_contests", "truncated_names", "unparsed_lines", "header_mismatches", "duplicate_cells",
                  "contests_without_precincts", "withheld", "placeholders_nonzero"):
            self.assertEqual(s[k], [], k)
        self.assertEqual(s["contests"], 1)
        # the fixture's statistics page is cut to 7 units, so ballots don't add up to the county's
        self.assertEqual(s["turnout_vs_county"], [("registered", 393550, 4971), ("ballots", 178067, 2340)])

    def test_turnout_table(self):
        (t,) = [t for t in self.turnout if t["precinct_name"] == "Magnolia District 4"]
        self.assertEqual((t["county_name"], t["registered_voters"], t["ballots_cast"]), ("Camden", 906, 444))

    def test_precinct_mismatch_listed(self):
        p = pages("pdf_camden_pages.txt")
        p[2] = p[2].replace("Magnolia District 1 300 12 312", "Magnolia District 1 301 12 313")
        contests, _, _ = parse_summary(p, CAMDEN)
        from pipeline.readers.pdfreport import check_precincts
        table, _, _ = parse_district_table(p, contests)
        got = check_precincts(contests, table)
        self.assertIn((MAGNOLIA, "DaNeen Satchell", 1154, 1155), got["precinct_vs_county"])
        self.assertIn((MAGNOLIA, "DaNeen Satchell", 1154, 1155), got["table_totals_vs_precincts"])

    def test_sum_mismatch_listed(self):
        p = pages("pdf_camden_pages.txt")
        p[0] = p[0].replace("Total Votes Cast 1,187 74", "Total Votes Cast 1,188 74")
        contests, _, _ = parse_summary(p, CAMDEN)
        from pipeline.readers.pdfreport import check_sums
        self.assertIn(("", MAGNOLIA, "TOTAL", "Total Votes Cast", 1188, 1187), check_sums(contests, CAMDEN))


class SussexTest(unittest.TestCase):
    def setUp(self):
        self.contests, self.stats, self.issues = parse_summary(pages("pdf_sussex_county_pages.txt"), SUSSEX)
        self.units, self.punits_issues = parse_precinct_report(pages("pdf_sussex_district_pages.txt"), SUSSEX)

    def test_summary_party_prefix_and_placeholder(self):
        (c,) = self.contests
        self.assertEqual(c["name"], "Hamburg Borough Mayor")
        self.assertEqual([(x["choice"], x["party"], x["values"]["TOTAL"]) for x in c["choices"]],
                         [("John Burd", "REP", 791), ("Write-In Totals", "", 53)])
        self.assertEqual(c["placeholders"], [("No Nomination Made", {"TOTAL": 0})])
        self.assertEqual(self.stats["registered"], 112512)
        self.assertEqual(self.stats["ballots"]["Mail-In"], 8145)
        self.assertEqual(self.issues, {"header_mismatches": [], "unparsed_lines": []})

    def test_precinct_units(self):
        self.assertEqual([(u["precinct"], u["suppressed_label"]) for u in self.units],
                         [("Hamburg Boro, District 1", True), ("Hamburg Boro, District 2", True),
                          ("Walpack Twp, District 1", True)])
        (c,) = self.units[0]["contests"]
        self.assertEqual(c["choices"][0]["values"], {"TOTAL": 354})
        self.assertEqual((self.units[0]["registered"], self.units[0]["ballots"]["TOTAL"]), (1084, 511))

    def test_withheld_counts_are_none(self):
        (c,) = self.units[2]["contests"]
        self.assertEqual(c["name"], "U.S. Senate")
        self.assertEqual([(x["choice"], x["party"], x["values"]) for x in c["choices"][:2]],
                         [("Cory Booker", "DEM", {"TOTAL": None}), ("Justin Murphy", "REP", {"TOTAL": None})])

    def test_vote_types_read_when_present(self):
        text = pages("pdf_sussex_county_pages.txt")
        text[0] = text[0].replace("REP John Burd 791 93.72%", "REP John Burd 791 93.72% 501 118 97 0 75 0")
        (c,), _, issues = parse_summary(text, SUSSEX)
        self.assertEqual(c["choices"][0]["values"], {"TOTAL": 791, "Election Day": 501, "Early Voting": 118,
                                                     "Mail-In": 97, "Provisional": 0, "Emergency": 75, "Overseas": 0})
        self.assertEqual(issues["unparsed_lines"], [])


class SussexPassTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.s, self.turnout = run_pass(self, SUSSEX, [("summary_pdf", "pdf_sussex_county_pages.txt"),
                                                                  ("precinct_pdf", "pdf_sussex_district_pages.txt")])

    def test_rows(self):
        (r,) = find(self.rows, level="precinct", precinct_name="Hamburg Boro, District 2", choice="John Burd")
        self.assertEqual((r["votes"], r["party"], r["vote_type"], r["county_name"]), (437, "REP", "TOTAL", "Sussex"))
        self.assertEqual(find(self.rows, choice="No Nomination Made"), [])
        (w,) = find(self.rows, precinct_name="Walpack Twp, District 1", choice="Cory Booker")
        self.assertEqual(w["votes"], "")

    def test_summary(self):
        s = self.s
        self.assertEqual(s["precinct_vs_county"], [])
        self.assertEqual(s["placeholders_dropped"], 3)
        self.assertEqual(s["withheld"], [("Walpack Twp, District 1", "U.S. Senate", 5)])
        self.assertEqual(s["contests_not_in_summary"], [("Walpack Twp, District 1", "U.S. Senate")])
        self.assertEqual(s["turnout_vs_county"], [("registered", 112512, 2530), ("ballots", 57818, 1195)])
        self.assertEqual(s["sum_mismatches"], [])

    def test_turnout(self):
        self.assertEqual([(t["precinct_name"], t["registered_voters"], t["ballots_cast"]) for t in self.turnout],
                         [("Hamburg Boro, District 1", 1084, 511), ("Hamburg Boro, District 2", 1437, 676),
                          ("Walpack Twp, District 1", 9, 8)])


@unittest.skipUnless(HAVE_PDFIUM, "needs pypdfium2 (.venv)")
class RealPdfTest(unittest.TestCase):
    def test_sussex_countywide(self):
        p = page_texts(os.path.join(FX, "pdf_sussex_countywide.pdf"))
        self.assertEqual(len(p), 14)
        contests, stats, issues = parse_summary(p, SUSSEX)
        self.assertEqual(len(contests), 71)
        senate = contests[0]
        self.assertEqual((senate["name"], senate["choices"][0]["choice"], senate["choices"][0]["values"]["TOTAL"]),
                         ("U.S. Senate", "Justin Murphy", 29466))
        self.assertEqual(stats["ballots"]["TOTAL"], 57818)
        self.assertEqual(issues, {"header_mismatches": [], "unparsed_lines": []})


def question(name):
    return {"name": name, "vote_for": "1", "placeholders": [], "totals": {},
            "choices": [{"choice": c, "party": "", "values": {}} for c in ("Yes", "No", "Overvotes", "Undervotes")]}


@unittest.skipUnless(HAVE_PDFIUM, "needs pypdfium2 (.venv)")
class SideBySideTest(unittest.TestCase):
    """Camden pages 173 and 177: the County Question and Collingswood's municipal question printed side by side."""

    def setUp(self):
        self.pages = page_texts(os.path.join(FX, "pdf_camden_side_by_side.pdf"))
        contests = [question("County Question County"), question("Collingswood Borough Municipal Question")]
        self.table, _, self.issues = parse_district_table(self.pages, contests)

    def test_each_contest_becomes_its_own_page(self):
        self.assertEqual(len(self.pages), 4)
        self.assertEqual([p.split("\n")[1] for p in self.pages],
                         ["County Question County", "Collingswood Borough Municipal Question"] * 2)

    def test_values_go_to_their_contest_by_position(self):
        self.assertEqual(self.table["County Question County"]["Audubon District 1"],
                         {"Yes": 248, "No": 69, "Total Votes Cast": 317, "Overvotes": 0, "Undervotes": 139,
                          "Contest Totals": 456})
        self.assertEqual(self.table["Collingswood Borough Municipal Question"]["Collingswood District 10"],
                         {"Yes": 288, "No": 163, "Total Votes Cast": 451, "Overvotes": 0, "Undervotes": 24,
                          "Contest Totals": 475})
        self.assertNotIn("Audubon District 1", self.table["Collingswood Borough Municipal Question"])
        self.assertEqual(self.issues["unparsed_lines"], [])
        self.assertEqual(self.issues["unmatched_headers"], [])


class RunnerTest(unittest.TestCase):
    def test_fetch_pass_records_both_files(self):
        from pipeline import run_pdfreport

        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        src = {"state": "NJ", "county": "Sussex", "layout": "sussex", "min_interval_s": 120,
               "files": {"summary_pdf": "https://example.test/a", "precinct_pdf": "https://example.test/b"}}
        rec = run_pdfreport.fetch_pass("pdf-x", src, raw_dir=d, now=lambda: 0.0,
                                       opener=lambda url: (200, b"%PDF-1.4"), sleep=lambda s: None)
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["layout"], r["county"], [x["kind"] for x in r["files"]]),
                         ("sussex", "Sussex", ["summary_pdf", "precinct_pdf"]))
        self.assertTrue(all(x["path"].endswith(".pdf") for x in r["files"]))


if __name__ == "__main__":
    unittest.main()
