"""Florida reader on fixtures cut from the 2026 general files (pipeline/make_fl_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.fl import parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def text(kind):
    with open(os.path.join(FX, f"fl_{kind}.txt"), "rb") as f:
        return f.read().decode("utf-8")


class Base(unittest.TestCase):
    def parse(self, info=None, votes=None, tab=None, kinds=("info", "votes", "tab")):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        given = {"info": info, "votes": votes, "tab": tab}
        for k in kinds:
            with open(os.path.join(d, f"{k}.txt"), "wb") as f:
                f.write((given[k] if given[k] is not None else text(k)).encode("utf-8"))
        with open(os.path.join(d, "pass.json"), "w") as f:
            json.dump({"source_id": "fl-test", "state": "FL", "files": [{"kind": k, "path": f"{k}.txt"} for k in kinds]}, f)
        return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(Base):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary = parse_pass(os.path.join(FX, "fl_pass.json"), base_dir=FX)

    def test_senate_rows(self):
        m, = find(self.rows, contest_id="120000", choice_id="89119", county_id="12001")
        self.assertEqual((m["votes"], m["choice"], m["party"], m["contest_type"]), (34835, "Ashley Moody", "REP", "USS"))
        self.assertEqual((m["county_name"], m["level"], m["reporting_status"]), ("Alachua", "county", "0/63 precincts, status I"))
        self.assertEqual((m["contest_name"], m["election_date"], m["vote_type"]), ("United States Senator", "11/03/2026", "TOTAL"))
        n, = find(self.rows, contest_id="120000", choice_id="90009", county_id="12001")
        self.assertEqual((n["votes"], n["party"]), (69813, "DEM"))

    def test_ticket_name_as_published(self):
        r = find(self.rows, contest_id="160000", choice_id="89042")
        self.assertTrue(r)
        self.assertEqual({x["choice"] for x in r}, {"Donalds Avila"})

    def test_yes_no_ids_per_race(self):
        amd = find(self.rows, contest_id="900001", choice_id="10", county_id="12001")
        ret = find(self.rows, contest_id="500001", choice_id="10", county_id="12001")
        self.assertEqual(len(amd), 1)
        self.assertEqual(len(ret), 1)
        self.assertEqual((amd[0]["choice"], amd[0]["contest_type"]), ("Yes for Approval", "AMD"))
        self.assertEqual(ret[0]["contest_type"], "SCJ")
        self.assertNotEqual(amd[0]["votes"], ret[0]["votes"])

    def test_summary(self):
        s = self.summary
        self.assertEqual((s["races"], s["counties"], s["records"]), (6, 3, 59))
        self.assertEqual(set(s["status_counts"]), {"I"})
        for k in ("unknown_races", "unknown_units", "unknown_choices", "duplicate_records", "non_numeric",
                  "reporting_exceeds_precincts", "missing_precinct_counts", "unexpected_status", "races_without_votes",
                  "pipe_vs_tab_differences", "races_not_in_tab", "candidates_with_several_parties",
                  "malformed_records", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)

    def test_every_row(self):
        self.assertEqual(len(self.rows), 59)
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
            self.assertEqual(r["contest_scope"], "statewide")


class SyntheticTest(Base):
    def test_unreadable_votes_not_checked(self):
        rows, s = self.parse(votes="<!DOCTYPE html><html><body>Forbidden</body></html>")
        self.assertEqual(rows, [])
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["votes"])
        self.assertIsNone(s["pipe_vs_tab_differences"])
        self.assertIsNone(s["races_without_votes"])

    def test_tab_missing_still_rows(self):
        rows, s = self.parse(kinds=("info", "votes"))
        self.assertEqual(len(rows), 59)
        self.assertEqual({r["party"] for r in rows}, {""})
        self.assertEqual({r["contest_type"] for r in rows}, {""})
        self.assertEqual(s["missing_files"], ["tab"])
        self.assertIsNone(s["pipe_vs_tab_differences"])
        self.assertIsNone(s["races_not_in_tab"])

    def test_precincts_checks(self):
        v = text("votes").replace("|I|120000|12003|9|", "|I|120000|12003|99|")
        rows, s = self.parse(votes=v)
        self.assertTrue(s["reporting_exceeds_precincts"])
        self.assertEqual({x[:2] for x in s["reporting_exceeds_precincts"]}, {("120000", "12003")})
        self.assertGreater(s["zero_precincts_reporting"], 0)

    def test_unknown_ids_listed(self):
        v = text("votes").replace("|I|120000|12001|0|89119|", "|I|120000|12999|0|77777|", 1)
        rows, s = self.parse(votes=v)
        self.assertEqual(s["unknown_units"], ["12999"])
        self.assertEqual(s["unknown_choices"], [("120000", "77777")])
        r, = find(rows, choice_id="77777")
        self.assertEqual((r["choice"], r["county_name"]), ("", ""))

    def test_duplicate_record_listed(self):
        first = text("votes").splitlines(keepends=True)[0]
        rows, s = self.parse(votes=text("votes") + first)
        self.assertEqual(len(s["duplicate_records"]), 1)

    def test_malformed_record_listed(self):
        rows, s = self.parse(votes=text("votes") + "garbage line\r\n[V|FLDOS|1|I|120000]\r\n")
        self.assertEqual(len(s["malformed_records"]), 2)
        self.assertEqual(len(rows), 59)

    def test_non_numeric_listed(self):
        v = text("votes").replace("|89119|34835]", "|89119|n/a]", 1)
        rows, s = self.parse(votes=v)
        self.assertEqual(s["non_numeric"], [("votes", "120000", "12001", "89119", "n/a")])
        r, = find(rows, choice_id="89119", county_id="12001")
        self.assertEqual(r["votes"], "")

    def test_pipe_vs_tab_difference_listed(self):
        t = text("tab").replace("\t34835", "\t34836", 1)
        rows, s = self.parse(tab=t)
        self.assertEqual(s["pipe_vs_tab_differences"], [("120000", "12001", "89119", 34835, "34836")])


if __name__ == "__main__":
    unittest.main()
