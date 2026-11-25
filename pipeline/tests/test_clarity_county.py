"""Clarity county-level XML (New Jersey counties) on Atlantic County's real 2026 file and edited copies."""
import io
import os
import shutil
import tempfile
import unittest
import zipfile

from pipeline.readers.clarity import COUNTY_TURNOUT_COLUMNS, parse_county_xml
from pipeline.run_clarity import DEFAULT_SOURCES, load_sources
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
ATL = os.path.join(FX, "clarity_nj_atlantic.zip")
SEN = "0004"
# The eight NJ Clarity counties that publish reports/detailxml.zip (the other seven publish JSON only).
NJ_COUNTIES = {"Atlantic": "127487", "Burlington": "127582", "Cape_May": "127585", "Essex": "127486",
               "Hudson": "127495", "Mercer": "127554", "Ocean": "127556", "Union": "127567"}


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def xml():
    with zipfile.ZipFile(ATL) as z:
        return z.read("detail.xml").decode("utf-8")


def parse_text(test, text, county="Atlantic"):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    path = os.path.join(d, "x.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("detail.xml", text)
    return parse_county_xml(path, "NJ", county, "nj-test")


def once(text, old, new):
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1)


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_county_xml(ATL, "NJ", "Atlantic", "nj-test")

    def test_columns(self):
        self.assertTrue(all(list(r) == COLUMNS for r in self.rows))
        self.assertTrue(all(list(r) == COUNTY_TURNOUT_COLUMNS for r in self.turnout))

    def test_precinct_rows(self):
        got = find(self.rows, level="precinct", precinct_id="Absecon W1 D1", contest_id=SEN, choice_id="001")
        self.assertEqual(sorted(r["vote_type"] for r in got), ["Early Voting", "Election Day", "Provisional", "Vote by Mail"])
        r = got[0]
        self.assertEqual((r["county_name"], r["contest_name"], r["contest_scope"], r["choice"], r["party"], r["state"],
                          r["precinct_name"], r["vote_for"], r["reporting_status"]),
                         ("Atlantic", "United States Senate", "local", "REP Justin MURPHY", "REP", "NJ",
                          "Absecon W1 D1", "1", "4"))

    def test_county_rows(self):
        got = {r["vote_type"]: r["votes"] for r in find(self.rows, level="county", contest_id=SEN, choice_id="001")}
        self.assertEqual(got, {"TOTAL": 38951, "Election Day": 26565, "Early Voting": 8350, "Vote by Mail": 3683,
                               "Provisional": 353})
        r = find(self.rows, level="county", contest_id=SEN, choice_id="001")[0]
        self.assertEqual((r["reporting_status"], r["source_created_at"], r["election_name"]),
                         ("145/145 precincts", "11/19/2026 1:05:19 PM EST", "2026 General Election"))

    def test_no_contest_level_vote_type_rows(self):
        self.assertFalse(find(self.rows, vote_type="regVotersCounty"))
        self.assertEqual(self.summary["contest_vote_types"], {"regVotersCounty": 65})
        self.assertEqual(self.summary["contest_vote_types_emitted"], [])

    def test_turnout(self):
        t = {r["precinct_name"]: r for r in self.turnout}
        self.assertEqual((t["Absecon W1 D1"]["registered_voters"], t["Absecon W1 D1"]["ballots_cast"],
                          t["Absecon W1 D1"]["percent_reporting"]), (1287, 722, "4"))
        self.assertEqual((t[""]["registered_voters"], t[""]["ballots_cast"]), (206628, 95945))
        self.assertEqual(len(self.turnout), 146)

    def test_summary(self):
        s = self.summary
        self.assertEqual(s["turnout_table"], "present")
        self.assertEqual((s["contests"], s["precincts"], s["region"], s["vote_types"]),
                         (65, 145, "Atlantic", ["Early Voting", "Election Day", "Provisional", "Vote by Mail"]))
        for k in ("mismatches_vote_types_vs_total", "mismatches_precincts_vs_vote_type", "region_mismatch",
                  "unknown_elements", "precincts_not_in_turnout", "turnout_precincts_without_results",
                  "duplicate_precincts", "non_numeric", "vote_type_sum_not_checked", "precinct_sum_not_checked",
                  "unnamed_vote_types", "choices_without_vote_types"):
            self.assertEqual(s[k], [], k)


class CheckTest(unittest.TestCase):
    def test_precinct_sum_mismatch(self):
        t = once(xml(), '<Precinct name="Absecon W1 D1" votes="', '<Precinct name="Absecon W1 D1" votes="1')
        _, s, _ = parse_text(self, t)
        self.assertEqual(s["mismatches_precincts_vs_vote_type"], [(SEN, "", "regVotersCounty", 0, 10)])

    def test_vote_type_total_mismatch(self):
        t = once(xml(), 'totalVotes="38951"', 'totalVotes="38952"')
        _, s, _ = parse_text(self, t)
        self.assertEqual(s["mismatches_vote_types_vs_total"], [(SEN, "001", 38952, 38951)])

    def test_non_numeric(self):
        t = once(xml(), '<VoteType name="Election Day" votes="26565">', '<VoteType name="Election Day" votes="n/a">')
        rows, s, _ = parse_text(self, t)
        self.assertIn((SEN, "001", "Election Day", "", "n/a"), s["non_numeric"])
        self.assertIn((SEN, "001"), s["vote_type_sum_not_checked"])
        self.assertEqual(s["mismatches_vote_types_vs_total"], [])
        r = find(rows, level="county", contest_id=SEN, choice_id="001", vote_type="Election Day")
        self.assertEqual(r[0]["votes"], "")

    def test_contest_level_over_under_votes_are_rows(self):
        t = xml().replace('<VoteType name="regVotersCounty" votes="0">', '<VoteType name="Undervotes" votes="0">', 1)
        rows, s, _ = parse_text(self, t)
        c = find(rows, level="county", contest_id=SEN, choice="Undervotes")
        self.assertEqual([(r["vote_type"], r["votes"], r["choice_id"], r["party"]) for r in c], [("TOTAL", 0, "", "")])
        self.assertEqual(len(find(rows, level="precinct", contest_id=SEN, choice="Undervotes")), 145)
        self.assertEqual(s["contest_vote_types"], {"Undervotes": 1, "regVotersCounty": 64})
        self.assertEqual(s["contest_vote_types_emitted"], ["Undervotes"])

    def test_region_mismatch(self):
        _, s, _ = parse_text(self, xml(), county="Bergen")
        self.assertEqual(s["region_mismatch"], [("Bergen", "Atlantic")])

    def test_precinct_not_in_turnout(self):
        t = once(xml(), '<Precinct name="Absecon W1 D1" totalVoters', '<Precinct name="Absecon W1 D1 X" totalVoters')
        _, s, _ = parse_text(self, t)
        self.assertEqual(s["precincts_not_in_turnout"], ["Absecon W1 D1"])
        self.assertEqual(s["turnout_precincts_without_results"], ["Absecon W1 D1 X"])

    def test_duplicate_precinct(self):
        t = once(xml(), '<Precinct name="Absecon W1 D2" votes="', '<Precinct name="Absecon W1 D1" votes="')
        rows, s, _ = parse_text(self, t)
        self.assertTrue(s["duplicate_precincts"])

    def test_unknown_element(self):
        t = once(xml(), "<Choice ", "<Note/><Choice ")
        _, s, _ = parse_text(self, t)
        self.assertEqual(s["unknown_elements"], [(SEN, "Note")])

    def test_not_xml(self):
        rows, s, t = parse_text(self, "<html>blocked")
        self.assertEqual((rows, t), ([], []))
        self.assertTrue(s["unreadable"])
        self.assertIsNone(s["mismatches_precincts_vs_vote_type"])


def nth(text, old, new, n):
    """Replace the n-th (0-based) occurrence of old."""
    i = -1
    for _ in range(n + 1):
        i = text.index(old, i + 1)
    return text[:i] + new + text[i + len(old):]


class ReviewFixTest(unittest.TestCase):
    def test_choice_level_precinct_sum_mismatch(self):
        # occurrence 0 is the contest-level regVotersCounty; 1 is Murphy's Election Day
        t = nth(xml(), '<Precinct name="Absecon W1 D1" votes="', '<Precinct name="Absecon W1 D1" votes="1', 1)
        _, s, _ = parse_text(self, t)
        self.assertEqual([m[:3] for m in s["mismatches_precincts_vs_vote_type"]], [(SEN, "001", "Election Day")])

    def test_precinct_non_numeric_not_checked(self):
        t = nth(xml(), '<Precinct name="Absecon W1 D1" votes="', '<Precinct name="Absecon W1 D1" votes="x', 1)
        rows, s, _ = parse_text(self, t)
        self.assertIn((SEN, "001", "Election Day"), s["precinct_sum_not_checked"])
        self.assertEqual(s["mismatches_precincts_vs_vote_type"], [])
        r = find(rows, level="precinct", contest_id=SEN, choice_id="001", precinct_id="Absecon W1 D1", vote_type="Election Day")
        self.assertEqual(r[0]["votes"], "")

    def test_unicode_digit_listed_not_crash(self):
        t = nth(xml(), '<Precinct name="Absecon W1 D1" votes="', '<Precinct name="Absecon W1 D1" votes="\u00b3', 1)
        _, s, _ = parse_text(self, t)
        self.assertTrue(any(n[4] and n[4].startswith("\u00b3") for n in s["non_numeric"]))

    def test_unnamed_vote_type_listed_not_crash(self):
        t = xml().replace('<VoteType name="Provisional" votes="353">', '<VoteType votes="353">', 1)
        rows, s, _ = parse_text(self, t)
        self.assertEqual(s["unnamed_vote_types"], [(SEN, "001")])
        self.assertFalse([r for r in rows if r["vote_type"] is None or r["choice"] is None])
        self.assertIn((SEN, "001"), s["vote_type_sum_not_checked"])

    def test_choice_without_vote_types_listed(self):
        t = xml()
        start = t.index('<Choice key="001"')
        head_end = t.index(">", start) + 1
        end = t.index("</Choice>", start)
        t = t[:head_end] + t[end:]
        rows, s, _ = parse_text(self, t)
        self.assertEqual(s["choices_without_vote_types"], [(SEN, "001")])
        self.assertEqual([r["vote_type"] for r in find(rows, contest_id=SEN, choice_id="001")], ["TOTAL"])

    def test_vote_type_without_precincts_not_checked(self):
        t = xml()
        start = t.index('<VoteType name="Election Day" votes="26565">')
        end = t.index("</VoteType>", start)
        t = t[:start] + '<VoteType name="Election Day" votes="26565">' + t[end:]
        _, s, _ = parse_text(self, t)
        self.assertIn((SEN, "001", "Election Day"), s["precinct_sum_not_checked"])
        self.assertEqual(s["mismatches_precincts_vs_vote_type"], [])

    def test_no_turnout_table_checks_none(self):
        t = xml()
        start, end = t.index("<VoterTurnout"), t.index("</VoterTurnout>") + len("</VoterTurnout>")
        _, s, turnout = parse_text(self, t[:start] + t[end:])
        self.assertEqual((turnout, s["turnout_table"]), ([], "missing"))
        self.assertIsNone(s["precincts_not_in_turnout"])
        self.assertIsNone(s["turnout_precincts_without_results"])

    def test_duplicate_precinct_choice_level(self):
        t = nth(xml(), '<Precinct name="Absecon W1 D2" votes="', '<Precinct name="Absecon W1 D1" votes="', 1)
        rows, s, _ = parse_text(self, t)
        self.assertEqual(s["duplicate_precincts"], [(SEN, "001", "Election Day", "Absecon W1 D1")])
        got = find(rows, level="precinct", contest_id=SEN, choice_id="001", precinct_id="Absecon W1 D1", vote_type="Election Day")
        self.assertEqual(len(got), 1)

    def test_rows_carry_configured_county(self):
        rows, s, _ = parse_text(self, xml(), county="Bergen")
        self.assertEqual({r["county_name"] for r in rows}, {"Bergen"})

    def test_corrupt_zip_listed(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        data = open(ATL, "rb").read()
        bad = data[:300] + bytes(b ^ 0xFF for b in data[300:900]) + data[900:]
        path = os.path.join(d, "x.zip")
        with open(path, "wb") as f:
            f.write(bad)
        rows, s, _ = parse_county_xml(path, "NJ", "Atlantic", "nj-test")
        self.assertEqual(rows, [])
        self.assertTrue(s["unreadable"])


class ConfigTest(unittest.TestCase):
    def test_nj_counties(self):
        src = load_sources(DEFAULT_SOURCES)
        for county, eid in NJ_COUNTIES.items():
            s = src[f"clarity-NJ-{county}-2026-general"]
            self.assertEqual((s["state"], s["format"], s["county"], s["base"], s["min_interval_s"]),
                             ("NJ", "county_xml", county.replace("_", " "),
                              f"https://results.enr.clarityelections.com/NJ/{county}/{eid}", 120))

    def test_runner_dispatch(self):
        import contextlib
        import glob
        from pipeline.run_clarity import main
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", "clarity-NJ-Atlantic-2026-general", ATL, "--parsed-dir", out])
        self.assertEqual(len(glob.glob(os.path.join(out, "clarity-NJ-Atlantic-2026-general", "*.csv"))), 2)
        self.assertIn("precincts: 145", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
