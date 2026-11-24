"""Ohio reader on a fixture cut from the 2026 general feed (pipeline/make_oh_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.oh import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
SENATE = "_55A742EA56A709A3E0633390EE0AE290"
HOUSE10 = "_55A742EA571009A3E0633390EE0AE290"
ISSUE3 = "_58F2C0185A8C8A6AE0633390EE0AF8C5"
GOV = "_55A742EA542A09A3E0633390EE0AE290"
SC1, SC2 = "_55A742EA55F109A3E0633390EE0AE290", "_55A742EA564C09A3E0633390EE0AE290"
BROWN = "_BS55A742EA61EF09A3E0633390EE0AE290"
TURNER = "_BS55A742EA571109A3E0633390EE0AE290"
ACTON = "_BS55A742EA5F7909A3E0633390EE0AE290"
ADAMS = "_55A742EA504C09A3E0633390EE0AE290"
STATEWIDE = "_55A742EA50B509A3E0633390EE0AE290"
CD1 = "_55A742EA509109A3E0633390EE0AE290"
# Brown's statewide count, then his Adams count, exactly as they appear in the fixture.
BROWN_STATE = '<VoteCounts Type="Total" Count="2301042">'
BROWN_ADAMS = '<VoteCounts Type="Total" Count="2123">'

with open(os.path.join(FX, "oh.xml"), encoding="utf-8") as _f:
    XML = _f.read()


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "oh_pass.json"), base_dir=FX)

    def test_senate_rows(self):
        st, = find(self.rows, contest_id=SENATE, choice_id=BROWN, level="state")
        self.assertEqual((st["votes"], st["county_id"], st["county_name"]), (2301042, "", ""))
        ad, = find(self.rows, contest_id=SENATE, choice_id=BROWN, county_id=ADAMS)
        self.assertEqual(ad["level"], "county")
        self.assertEqual(ad["votes"], 2123)
        self.assertEqual(ad["county_name"], "Adams")
        self.assertEqual(ad["reporting_status"], "21/21 precincts")
        self.assertEqual((ad["choice"], ad["party"], ad["contest_type"], ad["vote_for"]),
                         ("Sherrod Brown", "DEM", "U.S. Senator", "1"))
        self.assertEqual(ad["contest_name"], "U.S. Senator")

    def test_house_district_rows(self):
        d, = find(self.rows, contest_id=HOUSE10, choice_id=TURNER, level="state")
        self.assertEqual(d["votes"], 144086)
        self.assertEqual(d["choice"], "Mike Turner")
        b, = find(self.rows, contest_id=HOUSE10, choice_id=TURNER, county_name="Butler")
        self.assertEqual(b["votes"], 14876)

    def test_ticket(self):
        st, = find(self.rows, contest_id=GOV, choice_id=ACTON, level="state")
        self.assertEqual((st["choice"], st["party"], st["votes"]), ("Amy Acton and David Pepper", "DEM", 2404178))

    def test_ballot_measure(self):
        yes, = find(self.rows, contest_id=ISSUE3, choice_id="_YES" + ISSUE3[1:], level="state")
        no, = find(self.rows, contest_id=ISSUE3, choice_id="_NO" + ISSUE3[1:], level="state")
        self.assertEqual((yes["choice"], yes["votes"]), ("Yes", 2934245))
        self.assertEqual((no["choice"], no["votes"]), ("No", 1556864))
        self.assertEqual(yes["vote_for"], "")
        self.assertEqual(yes["contest_type"], "Statewide Issues")

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual({r["source_created_at"] for r in self.rows}, {"2026-11-13T09:43:04Z"})
        self.assertEqual({r["election_date"] for r in self.rows}, {"2026-11-03"})
        self.assertEqual({r["election_name"] for r in self.rows}, {"November 3, 2026 General Unofficial Canvass"})
        self.assertEqual({r["vote_type"] for r in self.rows}, {"TOTAL"})
        self.assertEqual({r["contest_scope"] for r in self.rows}, {"statewide"})
        self.assertEqual({r["state"] for r in self.rows}, {"OH"})
        self.assertEqual({r["level"] for r in self.rows}, {"state", "county"})
        self.assertEqual(len({r["source_sha256"] for r in self.rows}), 1)

    def test_summary(self):
        s = self.summary
        self.assertEqual(s["contests"], 7)
        self.assertEqual(s["counties"], 88)
        self.assertEqual(s["election_status"], "UnofficialComplete")
        self.assertEqual(s["unreferenced_county_units"], 88)
        self.assertEqual(len(s["absentee_exceeds_total"]), 88)
        self.assertIn(("Justice of the Supreme Court", [SC1, SC2]), s["same_named_contests"])
        self.assertTrue({(SENATE, x) for x in ("_BS59F4DEB13FEC0F04E0633390EE0A01BC",
                                               "_BS59F4DEB140460F04E0633390EE0A01BC",
                                               "_BS576274EE440573A4E0633390EE0A591D")} <= set(s["write_ins"]))
        for k in ("bad_sums", "own_unit_count_missing", "own_unit_count_repeated", "unknown_gpunits",
                  "counts_outside_contest", "non_numeric_votes", "unknown_candidates", "unknown_parties",
                  "bad_measure_ids", "duplicate_counts", "unexpected_count_types", "unexpected_namespace",
                  "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)

    def test_turnout(self):
        self.assertEqual(len(self.turnout), 88)
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        ad, = [t for t in self.turnout if t["county_id"] == ADAMS]
        self.assertEqual((ad["county_name"], ad["registered_voters"], ad["ballots_cast"],
                          ad["absentee_ballots_cast_as_published"], ad["provisional_outstanding"],
                          ad["uocava_absentee_outstanding"], ad["precincts_reported"], ad["precincts_total"]),
                         ("Adams", 17079, 9169, 62074, 129, 4, 21, 21))


class SyntheticTest(unittest.TestCase):
    """The fixture text edited, written to a temp dir, parsed."""

    def parse(self, text, body=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "oh.xml"), "wb") as f:
            f.write(body if body is not None else text.encode("utf-8"))
        with open(os.path.join(d, "pass.json"), "w") as f:
            json.dump({"source_id": "oh-test", "state": "OH", "files": [{"kind": "xml", "path": "oh.xml"}]}, f)
        return parse_pass(os.path.join(d, "pass.json"), base_dir=d)

    def edit(self, old, new, anchor='ObjectId="' + BROWN + '"'):
        """Replace the first `old` after `anchor` (default: Brown's Senate selection)."""
        i = XML.index(anchor) if anchor else 0
        j = XML.index(old, i)
        return self.parse(XML[:j] + new + XML[j + len(old):])

    def test_bad_sum_listed(self):
        rows, s, _ = self.edit(BROWN_ADAMS, '<VoteCounts Type="Total" Count="2124">')
        self.assertEqual(s["bad_sums"], [(SENATE, BROWN, 2301042, 2301043)])

    def test_own_unit_missing_listed(self):
        i = XML.index(BROWN_STATE, XML.index(BROWN))
        j = XML.index("</VoteCounts>", i) + len("</VoteCounts>")
        rows, s, _ = self.parse(XML[:i] + XML[j:])
        self.assertEqual(s["own_unit_count_missing"], [(SENATE, BROWN)])
        self.assertEqual(s["bad_sums"], [])
        self.assertEqual(find(rows, contest_id=SENATE, choice_id=BROWN, level="state"), [])

    def test_own_unit_repeated_listed(self):
        rows, s, _ = self.edit(BROWN_ADAMS + f"\n              <GpUnitId>{ADAMS}</GpUnitId>",
                               BROWN_ADAMS + f"\n              <GpUnitId>{STATEWIDE}</GpUnitId>")
        self.assertEqual(s["own_unit_count_repeated"], [(SENATE, BROWN)])

    def test_unknown_gpunit_listed(self):
        rows, s, _ = self.edit(f"{BROWN_ADAMS}\n              <GpUnitId>{ADAMS}</GpUnitId>",
                               f"{BROWN_ADAMS}\n              <GpUnitId>_NOSUCHUNIT</GpUnitId>")
        self.assertEqual(s["unknown_gpunits"], [(SENATE, BROWN, "_NOSUCHUNIT")])
        r, = find(rows, contest_id=SENATE, choice_id=BROWN, county_id="_NOSUCHUNIT")
        self.assertEqual(r["level"], "")

    def test_count_outside_contest_listed(self):
        rows, s, _ = self.edit(f"{BROWN_ADAMS}\n              <GpUnitId>{ADAMS}</GpUnitId>",
                               f"{BROWN_ADAMS}\n              <GpUnitId>{CD1}</GpUnitId>")
        self.assertEqual(s["counts_outside_contest"], [(SENATE, BROWN, CD1)])
        r, = find(rows, contest_id=SENATE, choice_id=BROWN, county_id=CD1)
        self.assertEqual((r["level"], r["votes"]), ("", 2123))

    def test_non_numeric_votes_listed(self):
        rows, s, _ = self.edit(BROWN_ADAMS, '<VoteCounts Type="Total" Count="n/a">')
        self.assertEqual(s["non_numeric_votes"], [(SENATE, BROWN, ADAMS, "n/a")])
        r, = find(rows, contest_id=SENATE, choice_id=BROWN, county_id=ADAMS)
        self.assertEqual(r["votes"], "")
        self.assertEqual(s["bad_sums"], [])

    def test_unknown_candidate_and_party_listed(self):
        c = XML.index("<CandidateCollection>")
        text = XML[:c] + XML[c:].replace('<PartyId>', '<PartyId>_X', 1)
        i = text.index('ObjectId="' + BROWN + '"')
        j = text.index("<CandidateId>", i) + len("<CandidateId>")
        rows, s, _ = self.parse(text[:j] + "_NOSUCHCAND" + text[j:])
        self.assertEqual(len(s["unknown_parties"]), 1)
        self.assertEqual(s["unknown_candidates"], [(SENATE, BROWN, "_NOSUCHCAND" + text[j:text.index("<", j)])])
        r, = find(rows, contest_id=SENATE, choice_id=BROWN, county_id=ADAMS)
        self.assertEqual((r["choice"], r["party"]), ("", ""))

    def test_bad_measure_id_listed(self):
        rows, s, _ = self.edit('ObjectId="_YES' + ISSUE3[1:], 'ObjectId="_MAYBE' + ISSUE3[1:], anchor=None)
        self.assertEqual(s["bad_measure_ids"], [(ISSUE3, "_MAYBE" + ISSUE3[1:])])
        r, = find(rows, contest_id=ISSUE3, choice_id="_MAYBE" + ISSUE3[1:], level="state")
        self.assertEqual(r["choice"], "")

    def test_duplicate_count_listed(self):
        block = f"{BROWN_ADAMS}\n              <GpUnitId>{ADAMS}</GpUnitId>\n            </VoteCounts>"
        rows, s, _ = self.edit(block, block + "\n            " + block)
        self.assertEqual(s["duplicate_counts"], [(SENATE, BROWN, ADAMS)])

    def test_unexpected_count_type_listed(self):
        rows, s, _ = self.edit(BROWN_ADAMS, '<VoteCounts Type="Election Day" Count="2123">')
        self.assertEqual(s["unexpected_count_types"], [(SENATE, BROWN, ADAMS, "Election Day")])

    def test_missing_optional_attributes(self):
        text = XML.replace(' VotesAllowed="1"', "").replace(' SubUnitsReported="21" TotalSubUnits="21"', "", 1)
        i = text.index('ObjectId="' + ADAMS + '"')
        j = text.index("<SummaryCounts", i)
        k = text.index("<ContactInformation>", j)
        rows, s, t = self.parse(text[:j] + text[k:])
        ad, = find(rows, contest_id=SENATE, choice_id=BROWN, county_id=ADAMS)
        self.assertEqual((ad["vote_for"], ad["reporting_status"]), ("", ""))
        tad, = [x for x in t if x["county_id"] == ADAMS]
        self.assertEqual((tad["ballots_cast"], tad["absentee_ballots_cast_as_published"], tad["precincts_total"],
                          tad["registered_voters"]), ("", "", "", 17079))
        self.assertEqual(len(s["absentee_exceeds_total"]), 87)

    def test_html_body_not_checked(self):
        rows, s, t = self.parse(None, body=b"<!DOCTYPE html><html><body>Just a moment...</body></html>")
        self.assertEqual((rows, t), ([], []))
        self.assertEqual(len(s["unreadable_files"]), 1)
        for k in ("bad_sums", "own_unit_count_missing", "write_ins", "absentee_exceeds_total",
                  "same_named_contests", "contests", "counties", "unreferenced_county_units"):
            self.assertIsNone(s[k], k)

    def test_unexpected_namespace_listed(self):
        rows, s, t = self.edit('xmlns="http://grouper.ieee.org/groups/1622/groups/2/V1/',
                               'xmlns="http://grouper.ieee.org/groups/1622/groups/2/V2/', anchor=None)
        self.assertEqual(len(s["unexpected_namespace"]), 1)
        self.assertEqual(rows, [])
        self.assertIsNone(s["bad_sums"])

    def test_missing_file_listed(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "pass.json"), "w") as f:
            json.dump({"source_id": "oh-test", "state": "OH", "files": []}, f)
        rows, s, t = parse_pass(os.path.join(d, "pass.json"), base_dir=d)
        self.assertEqual(s["missing_files"], ["xml"])
        self.assertIsNone(s["bad_sums"])


if __name__ == "__main__":
    unittest.main()
