"""Maryland reader: real pages from the 2026 general results site and small synthetic pages."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.md import parse_page, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
CHECKS = ["vote_type_sum_mismatches", "totals_row_mismatches", "county_state_mismatches", "contests_one_side",
          "contests_not_checked", "reporting_mismatches", "county_title_mismatches", "non_numeric",
          "duplicate_choices", "duplicate_contests", "unexpected_columns", "malformed_rows",
          "contests_without_reporting", "page_problems", "out_of_scope_titles", "mixed_refresh"]
TYPES = ["Early Voting", "Election Day", "Mail-In Ballot", "Provisional"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def table(first, rows, party=True, totals=True):
    head = f"<th>{first}</th>" + ("<th>Party</th>" if party else "")
    head += "".join(f"<th>{t}</th>" for t in TYPES) + "<th>Total</th><th>Percentage</th>"
    body = ""
    for r in rows:
        name, p, nums = r[0], r[1], r[2:]
        body += f"<tr><td><div>{name}</div></td>" + (f"<td>{p}</td>" if party else "")
        body += "".join(f"<td> {n}</td>" for n in nums) + "<td>0.00%</td></tr>"
    if totals:
        sums = [sum(int(str(x).replace(",", "")) for x in col if str(x).replace(",", "").isdigit()) for col in zip(*[r[2:] for r in rows])]
        body += "<tr><td><div><b>Totals</b></div></td>" + ("<td></td>" if party else "")
        body += "".join(f"<td> <b>{s:,}</b></td>" for s in sums) + "<td><b>100.00%</b></td></tr>"
    return f'<div class="tableWrapper"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def page(title, sections, refreshed="11/23/2026 07:40:42 PM"):
    return (f"<html><body><h1> Unofficial 2026 Gubernatorial General Election Results for {title}</h1>"
            f"<div>Last refreshed: {refreshed}</div><div>NR: not reported</div>{''.join(sections)}</body></html>")


def gov(rep="(5 of 5 election day precincts reported)", moore=(10, 20, 30, 5, 65), cox=(1, 2, 3, 0, 6)):
    return ("<h2>Governor / Lt. Governor</h2><h3>Vote for 1</h3>" + rep +
            table("Name", [("Wes Moore and Aruna Miller", "Democratic") + tuple(moore),
                           ("Dan Cox and Rob Krop", "Republican") + tuple(cox)]))


def senate(d, rep, a=(1, 1, 1, 1, 4)):
    return (f"<h2>State Senator</h2><h3>District {d}</h3><h4>Vote for 1</h4>{rep}" +
            table("Name", [("A Person", "Democratic") + tuple(a)]))


def delegates(d, rep, a=(2, 2, 2, 2, 8)):
    return (f"<h2>House of Delegates</h2><h3>District {d}</h3><h4>Vote for up to 3</h4>{rep}" +
            table("Name", [("B Person", "Republican") + tuple(a)]))


def run(test, pages, counties=None, office_pages=None, question_pages=None, missing=(), offices=None):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    files = []
    for (kind, n), text in pages.items():
        p = f"{kind}_{n}.html"
        if (kind, n) not in missing:
            with open(os.path.join(d, p), "w") as f:
                f.write(text)
        files.append({"kind": kind, "number": n, "path": p})
    rec = {"source_id": "md-test", "state": "MD", "counties": counties or {"1": "Allegany County", "2": "Anne Arundel County"},
           "office_pages": office_pages or {"1": "Governor / Lt. Governor", "5": "State Senator", "6": "House of Delegates"},
           "question_pages": question_pages or {}, "files": files,
           "offices": offices or ["Governor / Lt. Governor", "State Senator", "House of Delegates"], "questions": []}
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump(rec, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class PageTest(unittest.TestCase):
    def test_headings(self):
        p = parse_page(page("Allegany County", [gov(), senate(14, "(2 of 3 election day precincts reported)"),
                                                delegates(14, "(2 of 3 election day precincts reported)")]))
        self.assertEqual(p["title"], "Allegany County")
        self.assertEqual(p["refreshed"], "11/23/2026 07:40:42 PM")
        self.assertEqual([(c["office"], c["district"], c["vote_for"], c["reporting"]) for c in p["contests"]],
                         [("Governor / Lt. Governor", None, "1", (5, 5)),
                          ("State Senator", "District 14", "1", (2, 3)),
                          ("House of Delegates", "District 14", "3", (2, 3))])

    def test_retention_heading(self):
        sec = ("<h2>Judge, Appellate Court of Maryland At Large</h2>"
               "<h3>Dan Friedman<br>Vote Yes or No<br>For continuance in office</h3>(1 of 1 election day precincts reported)"
               + table("Dan Friedman", [("Yes", None, 1, 1, 1, 1, 4), ("No", None, 0, 0, 0, 1, 1)], party=False))
        c, = parse_page(page("Allegany County", [sec]))["contests"]
        self.assertEqual((c["district"], c["vote_for"], c["retention"]), ("Dan Friedman", "1", True))
        self.assertEqual([r[0] for r in c["rows"]], ["Yes", "No"])

    def test_table_without_heading_and_heading_without_table(self):
        p = parse_page(page("Allegany County", [table("Name", [("X", "Democratic", 1, 1, 1, 1, 4)]),
                                                "<h2>Sheriff</h2><h3>Vote for 1</h3>", gov()]))
        self.assertEqual([c["office"] for c in p["contests"]], ["Governor / Lt. Governor"])
        self.assertEqual(len(p["problems"]), 2)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "md_pass.json"), base_dir=FX)

    def test_county_rows(self):
        r = {x["vote_type"]: x["votes"] for x in find(self.rows, level="county", county_id="16",
                                                      contest_id="Governor / Lt. Governor", choice="Wes Moore and Aruna Miller")}
        self.assertEqual(r, {"Early Voting": 76721, "Election Day": 128150, "Mail-In Ballot": 93483, "Provisional": 12690, "TOTAL": 311044})
        x = find(self.rows, county_id="16", contest_id="Governor / Lt. Governor", vote_type="TOTAL")[0]
        self.assertEqual((x["county_name"], x["party"], x["vote_for"], x["contest_type"], x["reporting_status"], x["contest_scope"]),
                         ("Montgomery County", "Democratic", "1", "candidate", "257 of 257 election day precincts reported", "statewide"))

    def test_state_rows(self):
        r = find(self.rows, level="state", contest_id="Representative in Congress District 8", choice="Jamie Raskin", vote_type="TOTAL")
        self.assertEqual([(x["votes"], x["reporting_status"]) for x in r], [(245949, "199 of 199 election day precincts reported")])

    def test_retention_and_question(self):
        r = find(self.rows, county_id="15", contest_id="Judge, Appellate Court of Maryland At Large Dan Friedman", vote_type="TOTAL")
        self.assertEqual([(x["choice"], x["votes"], x["contest_type"], x["party"]) for x in r],
                         [("Yes", 6103, "retention", ""), ("No", 1212, "retention", "")])
        q = find(self.rows, county_id="16", contest_id="Question 1: Constitutional Amendment", vote_type="TOTAL")
        self.assertEqual([(x["choice"], x["votes"], x["contest_type"]) for x in q],
                         [("For the Constitutional Amendment", 285846, "question"),
                          ("Against the Constitutional Amendment", 69450, "question")])

    def test_district_ids_include_office(self):
        ids = {x["contest_id"] for x in find(self.rows, county_id="15")}
        self.assertIn("State Senator District 36", ids)
        self.assertIn("House of Delegates District 36", ids)
        self.assertEqual({x["vote_for"] for x in find(self.rows, contest_id="House of Delegates District 36")}, {"3"})

    def test_scope(self):
        self.assertNotIn("County Executive", {x["contest_name"] for x in self.rows})
        self.assertIn("County Executive", self.summary["out_of_scope_titles"])
        self.assertIn("Sheriff", self.summary["out_of_scope_titles"])

    def test_checks(self):
        s = self.summary
        for k in ("vote_type_sum_mismatches", "totals_row_mismatches", "county_title_mismatches", "non_numeric",
                  "duplicate_choices", "duplicate_contests", "unexpected_columns", "malformed_rows",
                  "contests_without_reporting", "page_problems", "mixed_refresh", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)
        nc = dict((c, why) for c, why in s["contests_not_checked"])
        self.assertEqual(nc["Governor / Lt. Governor"], "county pages cover 267 of 1979 precincts")
        self.assertEqual(nc["Representative in Congress District 8"], "county pages cover 198 of 199 precincts")
        self.assertEqual(nc["State Senator District 36"], "office page not in the pass")
        self.assertEqual(s["refresh_times"], {"11/23/2026 07:40:42 PM": 6})
        self.assertEqual(s["not_reported"], 0)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual(self.turnout, [])


class SyntheticPassTest(unittest.TestCase):
    R = "(5 of 5 election day precincts reported)"

    def clean(self, over=None):
        pages = {("county", "1"): page("Allegany County", [gov(rep="(2 of 2 election day precincts reported)",
                                                                moore=(4, 8, 12, 2, 26), cox=(1, 1, 1, 0, 3))]),
                 ("county", "2"): page("Anne Arundel County", [gov(rep="(3 of 3 election day precincts reported)",
                                                                    moore=(6, 12, 18, 3, 39), cox=(0, 1, 2, 0, 3))]),
                 ("office", "1"): page("Governor / Lt. Governor", [gov()])}
        pages.update(over or {})
        return pages

    def test_clean_cross_check(self):
        rows, s, _ = run(self, self.clean())
        self.assertEqual((s["county_state_mismatches"], s["contests_not_checked"], s["reporting_mismatches"]), ([], [], []))

    def test_county_state_mismatch_both_directions(self):
        o = page("Governor / Lt. Governor", [gov(moore=(10, 20, 30, 5, 65), cox=(1, 2, 3, 0, 6)).replace(
            "Dan Cox and Rob Krop", "Dan Cox")])
        rows, s, _ = run(self, self.clean({("office", "1"): o}))
        m = s["county_state_mismatches"]
        self.assertIn(("Governor / Lt. Governor", "Dan Cox", "TOTAL", 6, None), m)
        self.assertIn(("Governor / Lt. Governor", "Dan Cox and Rob Krop", "TOTAL", None, 6), m)

    def test_value_mismatch(self):
        o = page("Governor / Lt. Governor", [gov(moore=(10, 20, 30, 6, 66))])
        rows, s, _ = run(self, self.clean({("office", "1"): o}))
        self.assertIn(("Governor / Lt. Governor", "Wes Moore and Aruna Miller", "Provisional", 6, 5), s["county_state_mismatches"])
        self.assertIn(("Governor / Lt. Governor", "Wes Moore and Aruna Miller", "TOTAL", 66, 65), s["county_state_mismatches"])

    def test_reporting_mismatch_live(self):
        o = page("Governor / Lt. Governor", [gov(rep="(4 of 5 election day precincts reported)")])
        rows, s, _ = run(self, self.clean({("office", "1"): o}))
        self.assertEqual(s["reporting_mismatches"], [("Governor / Lt. Governor", "4 of 5", "5 of 5")])

    def test_office_page_unreadable(self):
        rows, s, _ = run(self, self.clean({("office", "1"): "<html>Attention Required! | Cloudflare</html>"}))
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["office 1"])
        self.assertEqual(s["contests_not_checked"], [("Governor / Lt. Governor", "office page not read")])
        self.assertIsNone(s["county_state_mismatches"])
        rows, s, _ = run(self, self.clean(), missing=[("office", "1")])
        self.assertEqual(s["contests_not_checked"], [("Governor / Lt. Governor", "office page not read")])

    def test_no_state_page_read_means_none(self):
        pages = self.clean()
        del pages[("office", "1")]
        rows, s, _ = run(self, pages)
        self.assertIsNone(s["county_state_mismatches"])
        self.assertIsNone(s["reporting_mismatches"])

    def test_nothing_read(self):
        rows, s, _ = run(self, {("county", "1"): "<html>blocked</html>"})
        self.assertEqual(rows, [])
        for k in CHECKS:
            self.assertIsNone(s[k], k)

    def test_contest_one_side(self):
        c1 = page("Allegany County", [gov(rep="(5 of 5 election day precincts reported)"), senate(1, self.R)])
        o = page("State Senator", [senate(2, self.R)])
        rows, s, _ = run(self, {("county", "1"): c1, ("office", "1"): page("Governor / Lt. Governor", [gov()]), ("office", "5"): o},
                         counties={"1": "Allegany County"})
        self.assertEqual(sorted(s["contests_one_side"]), [("State Senator District 1", "county pages only"),
                                                          ("State Senator District 2", "office page only")])

    def test_nr_and_non_numeric(self):
        sec = gov(moore=("NR", 20, 30, 5, 55), cox=("1x", 2, 3, 0, 6))
        rows, s, _ = run(self, {("county", "1"): page("Allegany County", [sec])}, counties={"1": "Allegany County"})
        self.assertEqual(s["not_reported"], 1)
        self.assertEqual(find(rows, choice="Wes Moore and Aruna Miller", vote_type="Early Voting")[0]["votes"], "")
        self.assertEqual([n[3:] for n in s["non_numeric"]], [("Early Voting", "1x")])

    def test_sums(self):
        sec = gov(moore=(10, 20, 30, 5, 66))
        rows, s, _ = run(self, {("county", "1"): page("Allegany County", [sec])}, counties={"1": "Allegany County"})
        self.assertEqual(s["vote_type_sum_mismatches"], [("county", "1", "Governor / Lt. Governor", "Wes Moore and Aruna Miller", 66, 65)])
        self.assertEqual(s["totals_row_mismatches"], [])
        sec = sec.replace("<b>72</b>", "<b>73</b>")
        rows, s, _ = run(self, {("county", "1"): page("Allegany County", [sec])}, counties={"1": "Allegany County"})
        self.assertEqual(s["totals_row_mismatches"], [("county", "1", "Governor / Lt. Governor", "Total", 73, 72)])

    def test_title_duplicates_columns_refresh(self):
        dup = gov() + gov()
        bad_cols = gov().replace("<th>Percentage</th>", "<th>Pct</th>")
        pages = {("county", "1"): page("Garrett County", [dup], refreshed="11/04/2026 01:00:00 AM"),
                 ("county", "2"): page("Anne Arundel County", [bad_cols])}
        rows, s, _ = run(self, pages)
        self.assertEqual(s["county_title_mismatches"], [("1", "Allegany County", "Garrett County")])
        self.assertEqual(s["duplicate_contests"], [("county 1", "Governor / Lt. Governor")])
        self.assertEqual([u[0] for u in s["unexpected_columns"]], ["county 2"])
        self.assertEqual(len(s["mixed_refresh"]), 2)

    def test_duplicate_choice_and_malformed_row(self):
        sec = gov().replace("</tbody>", "<tr><td><div>Dan Cox and Rob Krop</div></td><td>Republican</td>" +
                            "<td> 1</td>" * 4 + "<td> 4</td><td>0%</td></tr><tr><td>short</td></tr></tbody>")
        rows, s, _ = run(self, {("county", "1"): page("Allegany County", [sec])}, counties={"1": "Allegany County"})
        self.assertEqual(s["duplicate_choices"], [("county 1", "Governor / Lt. Governor", "Dan Cox and Rob Krop")])
        self.assertEqual(len(s["malformed_rows"]), 1)
        self.assertEqual(len(find(rows, choice="Dan Cox and Rob Krop", vote_type="TOTAL")), 1)

    def test_missing_reporting(self):
        rows, s, _ = run(self, {("county", "1"): page("Allegany County", [gov(rep="")])}, counties={"1": "Allegany County"})
        self.assertEqual(s["contests_without_reporting"], [("county 1", "Governor / Lt. Governor")])
        self.assertEqual({r["reporting_status"] for r in rows}, {""})


if __name__ == "__main__":
    unittest.main()
