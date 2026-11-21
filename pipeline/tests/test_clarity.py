"""Clarity readers on fixtures cut from the real 2026 CO, SC, WV (XML) and IA (JSON) downloads."""
import csv
import gzip
import json
import shutil
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from pipeline.readers.clarity import TURNOUT_COLUMNS, UnsupportedFormat, parse_json, parse_xml
from pipeline.schema import COLUMNS, write_csv

FX = os.path.join(os.path.dirname(__file__), "fixtures")
CO, SC, WV = (os.path.join(FX, f"clarity_{s}.zip") for s in ("co", "sc", "wv"))
IA_SUM, IA_ALL = os.path.join(FX, "clarity_ia_sum.json"), os.path.join(FX, "clarity_ia_all.json")


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


def ia_variant(edit_all):
    d = tempfile.mkdtemp()
    with open(IA_ALL) as f:
        a = json.load(f)
    edit_all(a)
    out = os.path.join(d, "all.json")
    with open(out, "w") as f:
        json.dump(a, f)
    return out


def adair(a):
    return [x for x in a["Contests"] if x["A"] == "Adair"][0]


class JsonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ia, cls.ia_sum = parse_json(IA_SUM, IA_ALL, "IA", "clarity-IA-2026-general")

    def test_ia_values(self):
        got = {r["choice_id"]: r["votes"] for r in find(self.ia, level="county", county_name="Adair", contest_id="1000")}
        self.assertEqual(got, {"1": 1921, "2": 1066, "3": 141, "30": 3})
        (r,) = find(self.ia, level="county", county_name="Adair", contest_id="1000", choice_id="2")
        self.assertEqual((r["choice"], r["party"], r["vote_type"], r["contest_scope"]),
                         ("Josh Turek", "DEM", "TOTAL", "statewide"))
        st = {r["choice_id"]: r["votes"] for r in find(self.ia, level="state", contest_id="1000")}
        self.assertEqual(st, {"1": 631276, "2": 688613, "3": 41829, "30": 1653})
        self.assertFalse(find(self.ia, county_name="-1"))
        self.assertEqual(self.ia_sum["mismatches_counties_vs_state"], [])
        self.assertEqual(self.ia_sum["mismatches_total_area_vs_state"], [])
        self.assertEqual(self.ia_sum["counties"], 99)
        for r in self.ia:
            self.assertEqual(list(r), COLUMNS)

    def test_json_gzip_and_plain(self):
        d = tempfile.mkdtemp()
        paths = []
        for src in (IA_SUM, IA_ALL):
            out = os.path.join(d, os.path.basename(src))
            with open(src, "rb") as f, open(out, "wb") as g:
                g.write(gzip.compress(f.read()))
            paths.append(out)
        rows, _ = parse_json(*paths, "IA", "clarity-IA-2026-general")
        strip = lambda rs: [{k: v for k, v in r.items() if k != "source_sha256"} for r in rs]
        self.assertEqual(strip(rows), strip(self.ia))

    def test_json_length_mismatch_skipped(self):
        def edit(a):
            c = adair(a)
            c["V"][c["C"].index("1000")].pop()
        rows, s = parse_json(IA_SUM, ia_variant(edit), "IA", "x")
        self.assertIn(("Adair", "1000"), s["skipped_length_mismatch"])
        self.assertFalse(find(rows, county_name="Adair", contest_id="1000"))
        self.assertTrue(find(rows, county_name="Adams", contest_id="1000"))

    def test_json_county_sum_mismatch(self):
        def edit(a):
            adair(a)["V"][adair(a)["C"].index("1000")][0] += 1
        _, s = parse_json(IA_SUM, ia_variant(edit), "IA", "x")
        self.assertIn(("1000", "1", 631276, 631277), s["mismatches_counties_vs_state"])


    def sum_variant(self, edit):
        with open(IA_SUM) as f:
            d = json.load(f)
        edit(d["Contests"][0])
        out = os.path.join(tempfile.mkdtemp(), "sum.json")
        with open(out, "w") as f:
            json.dump(d, f)
        return out

    def test_sum_json_length_disagreement_skipped_and_listed(self):
        for field in ("CHAggId", "V", "P"):
            path = self.sum_variant(lambda c: c[field].pop())
            rows, s = parse_json(path, IA_ALL, "IA", "x")
            self.assertEqual([c for c, _ in s["skipped_contest_length_mismatch"]], ["1000"], field)
            self.assertFalse(find(rows, contest_id="1000"), field)
            self.assertEqual(s["skipped_length_mismatch"], [], field)

    def test_total_area_compare_counted_and_absence_listed(self):
        self.assertEqual(self.ia_sum["total_area_contests_compared"], 1)
        self.assertEqual(self.ia_sum["contests_missing_total_area"], [])
        _, s = parse_json(IA_SUM, ia_variant(lambda a: a["Contests"].remove(
            [x for x in a["Contests"] if x["A"] == "-1"][0])), "IA", "x")
        self.assertEqual(s["total_area_contests_compared"], 0)
        self.assertEqual(s["contests_missing_total_area"], ["1000"])


if __name__ == "__main__":
    unittest.main()
