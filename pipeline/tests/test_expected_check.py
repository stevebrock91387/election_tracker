"""Step 4: FEC official totals and the exact per-(state, office) check of MEDSL."""
import collections
import io
import os
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

from pipeline.expected.check import check
from pipeline.expected.fec import district_key, read_fec

FEC_HEADER = ["1", "STATE ABBREVIATION", "STATE", "DISTRICT", "FEC ID", "(I) INCUMBENT INDICATOR",
              "CANDIDATE NAME (First)", "CANDIDATE NAME (Last)", "CANDIDATE NAME", "TOTAL VOTES", "PARTY",
              "PRIMARY VOTES", "PRIMARY %", "RUNOFF VOTES", "RUNOFF %", "GENERAL VOTES ", "GENERAL %",
              "GE RUNOFF ELECTION VOTES (GA)", "GE RUNOFF ELECTION % (GA)",
              "COMBINED GE PARTY TOTALS (when applicable)", "COMBINED GE PARTY % (when applicable)"]


def fec_row(st, district, cand, party, general, combined=None, label=None):
    r = [None] * len(FEC_HEADER)
    r[1], r[3], r[8], r[9], r[10], r[15], r[19] = st, district, cand, label, party, general, combined
    return r


def col(n):
    s = ""
    n += 1
    while n:
        n, m = divmod(n - 1, 26)
        s = chr(65 + m) + s
    return s


def xlsx(sheets):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                             for i, (n, _) in enumerate(sheets)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(sheets))) + "</Relationships>")
        for i, (_, grid) in enumerate(sheets):
            rows = "".join(f'<row r="{ri + 1}">' + "".join(
                f'<c r="{col(ci)}{ri + 1}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
                for ci, v in enumerate(row) if v is not None) + "</row>" for ri, row in enumerate(grid))
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml",
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       f"<sheetData>{rows}</sheetData></worksheet>")
    return buf.getvalue()


def m(st, office, cand, votes, district="STATEWIDE", fips="01001", special=False, writein=False):
    return {"state_po": st, "county_fips": fips, "county_name": "C", "office": office, "district": district,
            "special": special, "candidate": cand, "writein": writein, "votes": votes, "suppressed_rows": 0}


def f(st, office, cand, votes, district="", special=False, writein=False):
    return {"state_po": st, "office": office, "district": district, "special": special, "candidate": cand,
            "writein": writein, "votes": votes}


NOTES = {"suppressed": collections.Counter(), "blank_county": collections.Counter()}


class CheckTest(unittest.TestCase):
    def test_exact_match_passes(self):
        med = [m("ID", "US SENATE", "A", 60, fips="16001"), m("ID", "US SENATE", "A", 40, fips="16003"),
               m("ID", "US SENATE", "B", 50), m("ID", "US SENATE", "W1", 3, writein=True)]
        fec = [f("ID", "US SENATE", "Smith, A", 100), f("ID", "US SENATE", "Jones, B", 50),
               f("ID", "US SENATE", "Scattered", 3, writein=True)]
        out = check(med, fec, 2022, NOTES)
        self.assertEqual(out[("ID", "US SENATE")], {"passed": True, "differences": [], "reason": "passed"})

    def test_one_vote_off_fails_with_district_listed(self):
        med = [m("ID", "US HOUSE", "A", 100, district="001"), m("ID", "US HOUSE", "B", 50, district="002")]
        fec = [f("ID", "US HOUSE", "A", 100, district="01"), f("ID", "US HOUSE", "B", 51, district="02")]
        out = check(med, fec, 2022, NOTES)[("ID", "US HOUSE")]
        self.assertFalse(out["passed"])
        self.assertEqual(out["reason"], "differences")
        (d,) = out["differences"]
        self.assertEqual((d["district"], d["medsl"], d["fec"]), ("02", [["B", 50]], [["B", 51]]))

    def test_fusion_lines_summed_against_combined(self):
        med = [m("NY", "US SENATE", "A", 100), m("NY", "US SENATE", "A", 5)]
        self.assertTrue(check(med, [f("NY", "US SENATE", "A", 105)], 2022, NOTES)[("NY", "US SENATE")]["passed"])

    def test_at_large_district_keys_match(self):
        for d in ("0", "000", "00", "AT-LARGE", "AT LARGE", "0.0"):
            self.assertEqual(district_key("US HOUSE", d), "00", d)
        self.assertEqual(district_key("US HOUSE", "23.0"), "23")
        self.assertEqual(district_key("US HOUSE", "13-FULL TERM"), "13")
        self.assertEqual(district_key("US HOUSE", "07 - UNEXPIRED TERM"), "07")
        self.assertEqual(district_key("US SENATE", "STATEWIDE"), "")
        med = [m("WY", "US HOUSE", "A", 10, district="000")]
        self.assertTrue(check(med, [f("WY", "US HOUSE", "A", 10, district="00")], 2022, NOTES)[("WY", "US HOUSE")]["passed"])

    def test_blank_house_district_is_at_large_when_fec_has_only_00(self):
        # MEDSL 2022 AK and DC leave the House district blank; the FEC writes 00
        med = [m("AK", "US HOUSE", "A", 10, district="")]
        self.assertTrue(check(med, [f("AK", "US HOUSE", "A", 10, district="00")], 2022, NOTES)[("AK", "US HOUSE")]["passed"])
        # a blank district beside numbered ones stays its own contest (a missing district)
        med = [m("AZ", "US HOUSE", "A", 10, district="001"), m("AZ", "US HOUSE", "B", 3, district="")]
        out = check(med, [f("AZ", "US HOUSE", "A", 10, district="01")], 2022, NOTES)[("AZ", "US HOUSE")]
        self.assertEqual([d["district"] for d in out["differences"]], [""])

    def test_special_senate_contest_kept_apart(self):
        med = [m("MN", "US SENATE", "A", 10), m("MN", "US SENATE", "B", 9, special=True)]
        fec = [f("MN", "US SENATE", "A", 10), f("MN", "US SENATE", "B", 9, special=True)]
        self.assertTrue(check(med, fec, 2018, NOTES)[("MN", "US SENATE")]["passed"])
        fec = [f("MN", "US SENATE", "A", 10), f("MN", "US SENATE", "B", 9)]
        self.assertFalse(check(med, fec, 2018, NOTES)[("MN", "US SENATE")]["passed"])

    def test_suppressed_rows_fail_with_reason(self):
        notes = {"suppressed": collections.Counter({("NM", "US HOUSE"): 2}), "blank_county": collections.Counter()}
        out = check([m("NM", "US HOUSE", "A", 10, district="002")], [f("NM", "US HOUSE", "A", 13, district="02")],
                    2022, notes)[("NM", "US HOUSE")]
        self.assertEqual((out["passed"], out["reason"]), (False, "suppressed rows"))

    def test_no_fec_race_reason(self):
        out = check([m("GA", "US SENATE", "A", 10)], [], 2018, NOTES)[("GA", "US SENATE")]
        self.assertEqual((out["passed"], out["reason"]), (False, "not in FEC"))

    def test_writein_only_difference_passes_on_named_candidates(self):
        # Steve 2026-11-27 (option 1): named candidates exact; write-in differences recorded, not failing
        med = [m("AZ", "US SENATE", "A", 100), m("AZ", "US SENATE", "B", 50), m("AZ", "US SENATE", "W", 40, writein=True)]
        fec = [f("AZ", "US SENATE", "A", 100), f("AZ", "US SENATE", "B", 50), f("AZ", "US SENATE", "W", 5, writein=True)]
        out = check(med, fec, 2018, NOTES)[("AZ", "US SENATE")]
        self.assertEqual((out["passed"], out["reason"]), (True, "passed (named candidates)"))
        (d,) = out["differences"]
        self.assertEqual((d["medsl_writein"], d["fec_writein"], d["medsl_extra"]), (40, 5, []))

    def test_extra_medsl_lines_below_smallest_named_pass_and_are_listed(self):
        # MEDSL lists "ALL OTHERS" (MA) or unflagged write-in names as candidates; the FEC counts them as write-ins
        med = [m("MA", "US HOUSE", "A", 100, district="001"), m("MA", "US HOUSE", "ALL OTHERS", 7, district="001")]
        fec = [f("MA", "US HOUSE", "A", 100, district="01"), f("MA", "US HOUSE", "All others", 7, district="01", writein=True)]
        out = check(med, fec, 2018, NOTES)[("MA", "US HOUSE")]
        self.assertEqual(out["reason"], "passed (named candidates)")
        self.assertEqual(out["differences"][0]["medsl_extra"], [["ALL OTHERS", 7]])

    def test_extra_line_as_large_as_a_named_candidate_fails(self):
        med = [m("NY", "US HOUSE", "A", 100, district="001"), m("NY", "US HOUSE", "B", 20, district="001"),
               m("NY", "US HOUSE", "X", 20, district="001")]
        fec = [f("NY", "US HOUSE", "A", 100, district="01"), f("NY", "US HOUSE", "B", 20, district="01")]
        self.assertEqual(check(med, fec, 2018, NOTES)[("NY", "US HOUSE")]["reason"], "differences")

    def test_named_candidate_off_still_fails(self):
        med = [m("AL", "US HOUSE", "A", 99, district="001"), m("AL", "US HOUSE", "W", 9, writein=True, district="001")]
        fec = [f("AL", "US HOUSE", "A", 100, district="01"), f("AL", "US HOUSE", "W", 8, writein=True, district="01")]
        self.assertFalse(check(med, fec, 2018, NOTES)[("AL", "US HOUSE")]["passed"])

    def test_contest_missing_from_fec_with_named_lines_fails(self):
        # MEDSL 2022 AZ and WA rows with a blank district beside numbered ones
        med = [m("WA", "US HOUSE", "A", 10, district="001"), m("WA", "US HOUSE", "B", 3, district="")]
        out = check(med, [f("WA", "US HOUSE", "A", 10, district="01")], 2022, NOTES)[("WA", "US HOUSE")]
        self.assertEqual((out["passed"], out["reason"]), (False, "differences"))

    def test_governor_not_a_key(self):
        self.assertEqual(check([m("GA", "GOVERNOR", "A", 10)], [], 2018, NOTES), {})

    def test_read_fec_on_real_layout(self):
        senate = [FEC_HEADER, [None, None, None, None, "n/a"],
                  fec_row("NY", "S", "Gillibrand, Kirsten E.", "D", "3755489", combined="3915617"),
                  fec_row("NY", "S", "Gillibrand, Kirsten E.", "WF", "160128", combined="3915617"),
                  fec_row("NY", "S", "Farley, Chele", "R", "1700000", combined="1730439"),
                  fec_row("NY", "S", "Farley, Chele  #", "CRV", "30439", combined="1730439"),
                  fec_row("NY", "S", "Scattered", "W", "3872"),
                  fec_row("NY", "S", None, None, "6059023", label="Total State Votes:"),
                  fec_row("MN", "S-UNEXPIRED TERM", "Smith, Tina", "DFL", "1370540"),
                  fec_row("MN", "S-UNEXPIRED TERM", "Painter, Richard W.", "DFL", None)]
        house = [FEC_HEADER, fec_row("AL", None, "DISTRICT 1", None, None),
                 fec_row("AL", "01", "Carl, Jerry", "R", "140592"),
                 fec_row("FL", "05", "Rutherford, John H.", "R", "Unopposed"),
                 fec_row("MI", "13-UNEXPIRED TERM", "Jones, Brenda", "D", "165355"),
                 fec_row("KY", "08 ", "Comer, James", "R", "999"),
                 fec_row("KS", "04", "Thompson, James\xa0A. *", "D", "98445"),
                 fec_row("GU", "00", "Moylan, James", "R", "19915")]
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fec.xlsx")
        with open(path, "wb") as fh:
            fh.write(xlsx([("Publication", [["x"]]), ("7. US Senate Results by State", senate),
                           ("8. US House Results by State", house)]))
        notes = {}
        rows = read_fec(path, 2022, notes)
        got = sorted((r["state_po"], r["office"], r["district"], r["special"], r["candidate"], r["writein"], r["votes"])
                     for r in rows)
        self.assertEqual(got, [
            ("AL", "US HOUSE", "01", False, "Carl, Jerry", False, 140592),
            ("KS", "US HOUSE", "04", False, "Thompson, James A.", False, 98445),
            ("KY", "US HOUSE", "08", False, "Comer, James", False, 999),
            ("MI", "US HOUSE", "13", True, "Jones, Brenda", False, 165355),
            ("MN", "US SENATE", "", True, "Smith, Tina", False, 1370540),
            ("NY", "US SENATE", "", False, "Farley, Chele", False, 1730439),
            ("NY", "US SENATE", "", False, "Gillibrand, Kirsten E.", False, 3915617),
            ("NY", "US SENATE", "", False, "Scattered", True, 3872)])
        self.assertEqual(notes["unopposed"], [("FL", "US HOUSE", "05", "Rutherford, John H.")])
        self.assertEqual(notes["territory_lines"], 1)


if __name__ == "__main__":
    unittest.main()
