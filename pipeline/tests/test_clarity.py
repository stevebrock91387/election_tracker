"""Clarity readers on fixtures cut from the real 2026 CO, SC, WV (XML) and IA (JSON) downloads."""
import csv
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from pipeline.readers.clarity import TURNOUT_COLUMNS, UnsupportedFormat, parse_xml
from pipeline.schema import COLUMNS, write_csv

FX = os.path.join(os.path.dirname(__file__), "fixtures")
CO, SC, WV = (os.path.join(FX, f"clarity_{s}.zip") for s in ("co", "sc", "wv"))


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def xml_variant(src, edit):
    """Copy a fixture zip with detail.xml edited by edit(root)."""
    with zipfile.ZipFile(src) as z:
        root = ET.fromstring(z.read("detail.xml"))
    edit(root)
    path = os.path.join(tempfile.mkdtemp(), "v.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("detail.xml", ET.tostring(root))
    return path


class XmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.co, cls.co_sum, cls.co_turn = parse_xml(CO, "CO", "clarity-CO-2026-general")
        cls.sc, cls.sc_sum, _ = parse_xml(SC, "SC", "clarity-SC-2026-general")
        cls.wv, cls.wv_sum, _ = parse_xml(WV, "WV", "clarity-WV-2026-general")

    def test_co_values(self):
        (r,) = find(self.co, level="state", contest_id="20", choice_id="2", vote_type="TOTAL")
        self.assertEqual((r["choice"], r["party"], r["votes"]), ("John Hickenlooper", "DEM", 1629521))
        (r,) = find(self.co, level="county", county_name="Adams", contest_id="20", choice_id="1")
        self.assertEqual((r["vote_type"], r["votes"], r["reporting_status"]), ("Total Votes", 62394, "395/395 precincts"))
        self.assertFalse(find(self.co, level="county", vote_type="TOTAL"))
        (t,) = [t for t in self.co_turn if t["county_name"] == "Adams"]
        self.assertEqual((t["registered_voters"], t["ballots_cast"], t["precincts_participating"],
                          t["precincts_reported"]), (330215, 202413, 401, 401))
        self.assertEqual(self.co_sum["election_name"], "2026 General")

    def test_sc_vote_types(self):
        got = {r["vote_type"]: r["votes"] for r in
               find(self.sc, level="county", county_name="Abbeville", contest_id="21500", choice_id="003")}
        self.assertEqual(got, {"Election Day": 3824, "Early Voting": 1877, "Absentee By Mail": 38, "Failsafe": 0,
                               "Provisional": 2, "Failsafe Provisional": 0})
        (r,) = find(self.sc, level="state", contest_id="21500", choice_id="003", vote_type="TOTAL")
        self.assertEqual(r["votes"], 1051334)
        self.assertEqual(r["choice"], "REP Alan Wilson / Mike Reichenbach")
        q = find(self.sc, contest_id="40111")
        self.assertTrue(q)
        self.assertEqual({(r["contest_type"], r["contest_scope"]) for r in q}, {("question", "statewide")})

    def test_wv_values(self):
        (r,) = find(self.wv, level="county", county_name="Barbour", contest_id="100", choice_id="001")
        self.assertEqual((r["choice"], r["vote_type"], r["votes"]), ("SHELLEY MOORE CAPITO", "Election Day", 2330))
        (r,) = find(self.wv, level="state", contest_id="100", choice_id="001", vote_type="TOTAL")
        self.assertEqual(r["votes"], 266772)

    def test_columns_and_no_mismatches(self):
        for rows, s in ((self.co, self.co_sum), (self.sc, self.sc_sum), (self.wv, self.wv_sum)):
            for r in rows:
                self.assertEqual(list(r), COLUMNS)
            self.assertEqual(s["mismatches_vote_types_vs_total"], [])
            self.assertEqual(s["mismatches_counties_vs_vote_type"], [])

    def test_vote_type_mismatch_reported(self):
        def edit(root):
            vt = root.find("Contest/Choice/VoteType")
            vt.set("votes", str(int(vt.get("votes")) + 1))
        rows, s, _ = parse_xml(xml_variant(CO, edit), "CO", "x")
        self.assertIn(("20", "1", 942095, 942096), s["mismatches_vote_types_vs_total"])
        self.assertIn(("20", "1", "Total Votes", 942096, 942095), s["mismatches_counties_vs_vote_type"])
        (r,) = find(rows, level="state", contest_id="20", choice_id="1", vote_type="Total Votes")
        self.assertEqual(r["votes"], 942096)

    def test_county_missing_from_participating(self):
        def edit(root):
            pc = root.find("Contest/ParticipatingCounties")
            pc.remove([c for c in pc if c.get("name") == "Adams"][0])
        rows, _, _ = parse_xml(xml_variant(CO, edit), "CO", "x")
        adams = find(rows, level="county", county_name="Adams")
        self.assertTrue(adams)
        self.assertEqual({r["reporting_status"] for r in adams}, {""})

    def test_zip_without_detail_xml(self):
        path = os.path.join(tempfile.mkdtemp(), "o.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("other.xml", "<x/>")
        with self.assertRaises(UnsupportedFormat):
            parse_xml(path, "CO", "x")

    def test_unknown_element_listed(self):
        rows, s, _ = parse_xml(xml_variant(CO, lambda root: ET.SubElement(root.find("Contest"), "Foo")), "CO", "x")
        self.assertIn(("20", "Foo"), s["unknown_elements"])
        self.assertEqual(len(rows), len(self.co))

    def test_turnout_csv(self):
        out = os.path.join(tempfile.mkdtemp(), "t.csv")
        write_csv(self.co_turn, out, TURNOUT_COLUMNS)
        with open(out, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
