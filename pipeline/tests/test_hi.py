"""Hawaii reader on a fixture cut from the 2026 certified text files (pipeline/make_hi_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.make_hi_fixture import records
from pipeline.readers.hi import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
GOV = "43"
CORDERY = "(R) CORDERY, Gary For GOVERNOR ANTHONY, Daniel For LIEUTENANT GOVERNOR"


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def raw(name):
    with open(os.path.join(FX, f"hi_{name}.txt"), encoding="utf-8", newline="") as f:
        return f.read()


def parse_texts(test, summary=None, media=None, kinds=("summary", "media")):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    texts = {"summary": raw("summary") if summary is None else summary,
             "media": raw("media") if media is None else media}
    for k in kinds:
        with open(os.path.join(d, f"{k}.txt"), "w", encoding="utf-8", newline="") as f:
            f.write(texts[k])
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "hi-test", "state": "HI", "files": [{"kind": k, "path": f"{k}.txt"} for k in kinds]}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


def edit(text, match, index, value, head):
    """Set field `index` on the first data record whose fields start with `match` (a dict index->value)."""
    recs = records(text)
    for i, r in enumerate(recs[head:], start=head):
        f = r.rstrip("\r\n").split("\t")
        if all(f[k] == v for k, v in match.items()):
            f[index] = value
            recs[i] = "\t".join(f) + r[len(r.rstrip("\r\n")):]
            return "".join(recs)
    raise AssertionError(f"no record matches {match}")


def drop(text, match, head):
    recs = records(text)
    keep = recs[:head] + [r for r in recs[head:] if not all(r.split("\t")[k] == v for k, v in match.items())]
    assert len(keep) < len(recs), match
    return "".join(keep)


def media_edit(match, index, value, text=None):
    return edit(raw("media") if text is None else text, match, index, value, 3)


def summary_edit(match, index, value, text=None):
    return edit(raw("summary") if text is None else text, match, index, value, 2)


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "hi_pass.json"), base_dir=FX)

    def test_columns(self):
        self.assertTrue(all(list(r) == COLUMNS for r in self.rows))
        self.assertTrue(all(list(r) == TURNOUT_COLUMNS for r in self.turnout))

    def test_plain_unit_rows(self):
        got = find(self.rows, level="precinct", precinct_id="1", contest_id=GOV, choice_id="1")
        self.assertEqual({r["vote_type"]: r["votes"] for r in got}, {"TOTAL": 651, "Mail votes": 651, "In-Person votes": 0})
        r = got[0]
        self.assertEqual((r["precinct_name"], r["precinct_is_virtual"], r["choice"], r["party"], r["reporting_status"],
                          r["contest_type"], r["contest_scope"], r["contest_name"], r["state"]),
                         ("01-01", "N", CORDERY, "R", "Reporting 1", "candidate", "statewide",
                          "Governor and Lieutenant Governor", "HI"))

    def test_vsc_unit_rows(self):
        got = find(self.rows, level="precinct", precinct_id="280", contest_id=GOV, choice_id="2")
        self.assertEqual({r["vote_type"]: r["votes"] for r in got}, {"TOTAL": 46, "Mail votes": 0, "In-Person votes": 46})
        self.assertEqual((got[0]["precinct_name"], got[0]["precinct_is_virtual"], got[0]["reporting_status"]),
                         ("01-01 VSC", "Y", "Reporting 0"))

    def test_no_prefix_party_from_column(self):
        r = find(self.rows, level="precinct", precinct_id="23", contest_id="47", choice_id="1")[0]
        self.assertEqual((r["choice"], r["party"]), ("ENRIQUEZ, Lloyd K.", ""))

    def test_measure(self):
        r = find(self.rows, level="state", contest_id="38", choice_id="2", vote_type="TOTAL")[0]
        self.assertEqual((r["contest_type"], r["choice"], r["votes"]), ("measure", "YES", 227129))

    def test_state_rows(self):
        got = find(self.rows, level="state", contest_id=GOV, choice_id="2")
        self.assertEqual({r["vote_type"]: r["votes"] for r in got}, {"TOTAL": 279445, "Mail Votes": 271589, "In-Person Votes": 7856})
        self.assertEqual(got[0]["reporting_status"], "247 of 494 precincts counted")
        self.assertEqual(got[0]["party"], "D")

    def test_state_blank_over_invalid(self):
        for choice, mail, inp in [("Blank Votes", 6941, 263), ("Over Votes", 494, 27), ("Invalid Votes", 0, 0)]:
            got = find(self.rows, level="state", contest_id=GOV, choice=choice)
            self.assertEqual({r["vote_type"]: r["votes"] for r in got},
                             {"TOTAL": mail + inp, "Mail Votes": mail, "In-Person Votes": inp}, choice)
            self.assertEqual((got[0]["choice_id"], got[0]["party"]), ("", ""))

    def test_turnout(self):
        t = {r["precinct_id"]: r for r in self.turnout}
        self.assertEqual((t["1"]["precinct_name"], t["1"]["registered_voters"], t["1"]["ballots"], t["1"]["reporting"]),
                         ("01-01", 6555, 3046, "1"))
        self.assertEqual((t["280"]["registered_voters"], t["280"]["ballots"]), (0, 93))

    def test_counts_and_clean_checks(self):
        s = self.summary
        self.assertEqual((s["contests"], s["units"], s["vsc_units"], s["plain_units"]), (4, 494, 247, 247))
        self.assertEqual(s["lines"], {"summary": 8, "media": 2000})
        self.assertEqual(s["parties_from_prefix"], 4)
        for k in ("state_precinct_mismatches", "state_precinct_not_checked", "registered_not_checked",
                  "precinct_count_not_checked", "total_mismatches", "registered_mismatches", "precinct_count_mismatches",
                  "title_mismatches", "choice_name_mismatches", "unit_conflicts", "duplicate_lines", "non_numeric",
                  "malformed_lines", "inconsistent_contest_fields", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)
        self.assertEqual(s["preamble"]["media"][0][:2], ["Column1", "Column2"])
        self.assertEqual(s["preamble"]["summary"][0][0], "#FormatVersion 1")

    def test_row_count(self):
        # media: 2000 lines x 3 vote types; summary: 8 lines x 3 + 4 contests x 3 extra choices x 3
        self.assertEqual(len(self.rows), 6000 + 24 + 36)


class CheckTest(unittest.TestCase):
    def test_state_precinct_mismatch(self):
        _, s, _ = parse_texts(self, media=media_edit({2: "1", 6: GOV, 9: "1"}, 13, "652"))
        self.assertEqual(s["state_precinct_mismatches"], [(GOV, "1", "Mail Votes", 95894, 95895)])

    def test_state_only_choice(self):
        _, s, _ = parse_texts(self, media=drop(raw("media"), {6: "47", 9: "2"}, 3))
        self.assertIn(("47", "2", "Mail Votes", 3006, None), s["state_precinct_mismatches"])

    def test_precinct_only_choice(self):
        _, s, _ = parse_texts(self, summary=drop(raw("summary"), {0: "47", 14: "2"}, 2))
        self.assertIn(("47", "2", "Mail Votes", None, 3006), s["state_precinct_mismatches"])

    def test_total_mismatch(self):
        _, s, _ = parse_texts(self, summary=summary_edit({0: "23", 14: "1"}, 20, "6549"))
        self.assertEqual(s["total_mismatches"], [("23", "1", 6549, 6548)])

    def test_registered_mismatch(self):
        text = raw("summary")
        for cand in ("1", "2"):
            text = summary_edit({0: "47", 14: cand}, 11, "853400", text)
        _, s, _ = parse_texts(self, summary=text)
        self.assertEqual(s["registered_mismatches"], [("47", 853400, 853399)])

    def test_precinct_count_mismatch(self):
        text = raw("summary")
        for cand in ("1", "2"):
            text = summary_edit({0: "47", 14: cand}, 13, "3", text)
        _, s, _ = parse_texts(self, summary=text)
        self.assertEqual(s["precinct_count_mismatches"], [("47", 4, 3, 4, 2)])

    def test_title_mismatch(self):
        _, s, _ = parse_texts(self, media=media_edit({2: "23", 6: "47", 9: "1"}, 7, "Council, Dist 4"))
        self.assertIn(("47", "Councilmember, Dist 4", "Council, Dist 4"), s["title_mismatches"])

    def test_choice_name_mismatch(self):
        _, s, _ = parse_texts(self, media=media_edit({2: "23", 6: "47", 9: "1"}, 10, "ENRIQUES, Lloyd K."))
        self.assertIn(("47", "1", "ENRIQUEZ, Lloyd K.", "ENRIQUES, Lloyd K."), s["choice_name_mismatches"])

    def test_unit_conflict(self):
        _, s, _ = parse_texts(self, media=media_edit({2: "23", 6: "47", 9: "1"}, 4, "4637"))
        self.assertEqual([c[0] for c in s["unit_conflicts"]], ["23"])

    def test_duplicate_line(self):
        recs = records(raw("media"))
        dup = next(r for r in recs[3:] if r.split("\t")[2] == "23" and r.split("\t")[6] == "47")
        rows, s, _ = parse_texts(self, media="".join(recs) + dup)
        self.assertEqual(s["duplicate_lines"], [("media", "47", "1", "23")])
        self.assertEqual(len(find(rows, level="precinct", precinct_id="23", contest_id="47", choice_id="1")), 3)

    def test_non_numeric(self):
        rows, s, _ = parse_texts(self, media=media_edit({2: "23", 6: "47", 9: "1"}, 13, "n/a"))
        self.assertEqual(s["non_numeric"], [("media", "23", "47", "1", "Mail votes", "n/a")])
        got = {r["vote_type"]: r["votes"] for r in find(rows, level="precinct", precinct_id="23", contest_id="47", choice_id="1")}
        self.assertEqual((got["Mail votes"], got["TOTAL"]), ("", ""))
        self.assertEqual(s["state_precinct_not_checked"], [("47", "1", "Mail Votes")])
        self.assertFalse([m for m in s["state_precinct_mismatches"] if m[:3] == ("47", "1", "Mail Votes")])

    def test_malformed_line(self):
        recs = records(raw("media"))
        _, s, _ = parse_texts(self, media="".join(recs) + "01-01\tonly\tthree\r\n")
        self.assertEqual(s["malformed_lines"], [("media", len(recs) + 1, 3)])

    def test_inconsistent_contest_fields(self):
        _, s, _ = parse_texts(self, summary=summary_edit({0: "47", 14: "2"}, 5, "545"))
        self.assertEqual(s["inconsistent_contest_fields"], [("47", "Mail Blank Votes", ["544", "545"])])

    def test_party_column_used_without_prefix(self):
        rows, _, _ = parse_texts(self, media=media_edit({2: "23", 6: "47", 9: "1"}, 11, "N"))
        self.assertEqual(find(rows, level="precinct", precinct_id="23", contest_id="47", choice_id="1")[0]["party"], "N")


class ReviewFixTest(unittest.TestCase):
    def unit23(self, index, value):
        text = raw("media")
        for cid, ch in [("47", "1"), ("47", "2")]:
            text = media_edit({2: "23", 6: cid, 9: ch}, index, value, text)
        return text

    def test_non_numeric_reg_voters_not_checked(self):
        _, s, _ = parse_texts(self, media=self.unit23(3, "n/a"))
        self.assertIsNone(s["registered_mismatches"])
        self.assertIn(("media", "23", "", "", "Reg_voters", "n/a"), s["non_numeric"])

    def test_non_numeric_ballots_and_reporting_listed(self):
        text = self.unit23(4, "x")
        text = edit(text, {2: "23", 6: "47", 9: "1"}, 5, "y", 3)
        text = edit(text, {2: "23", 6: "47", 9: "2"}, 5, "y", 3)
        _, s, _ = parse_texts(self, media=text)
        self.assertIn(("media", "23", "", "", "Ballots", "x"), s["non_numeric"])
        self.assertIn(("media", "23", "", "", "Reporting", "y"), s["non_numeric"])
        self.assertEqual(sum(1 for n in s["non_numeric"] if n[1] == "23"), 2)

    def test_conflicting_reg_voters_not_summed(self):
        _, s, _ = parse_texts(self, media=media_edit({2: "23", 6: "47", 9: "1"}, 3, "9999999"))
        self.assertIsNone(s["registered_mismatches"])
        self.assertEqual([c[0] for c in s["unit_conflicts"]], ["23"])

    def test_registered_published_non_numeric_not_checked(self):
        text = raw("summary")
        for cand in ("1", "2"):
            text = summary_edit({0: "47", 14: cand}, 11, "n/a", text)
        _, s, _ = parse_texts(self, summary=text)
        self.assertEqual(s["registered_mismatches"], [])
        self.assertEqual(s["registered_not_checked"], ["47"])

    def test_inconsistent_precinct_counts_not_checked(self):
        _, s, _ = parse_texts(self, summary=summary_edit({0: "47", 14: "2"}, 12, "5"))
        self.assertEqual(s["precinct_count_mismatches"], [])
        self.assertEqual(s["precinct_count_not_checked"], ["47"])

    def test_one_sided_non_numeric_not_checked(self):
        text = drop(raw("summary"), {0: "47", 14: "2"}, 2)
        media = media_edit({2: "23", 6: "47", 9: "2"}, 13, "n/a")
        _, s, _ = parse_texts(self, summary=text, media=media)
        self.assertIn(("47", "2", "Mail Votes"), s["state_precinct_not_checked"])
        self.assertNotIn(("47", "2", "Mail Votes", None, None), s["state_precinct_mismatches"])
        self.assertIn(("47", "2", "In-Person Votes", None, 170), s["state_precinct_mismatches"])

    def test_state_side_non_numeric_without_media_line(self):
        text = summary_edit({0: "47", 14: "2"}, 18, "")
        media = drop(raw("media"), {6: "47", 9: "2"}, 3)
        _, s, _ = parse_texts(self, summary=text, media=media)
        self.assertIn(("47", "2", "Mail Votes"), s["state_precinct_not_checked"])
        self.assertIn(("47", "2", "In-Person Votes", 170, None), s["state_precinct_mismatches"])

    def test_nothing_read_line_checks_none(self):
        _, s, _ = parse_texts(self, kinds=())
        for k in ("duplicate_lines", "non_numeric", "malformed_lines"):
            self.assertIsNone(s[k], k)


class FileTest(unittest.TestCase):
    def test_missing_summary(self):
        rows, s, _ = parse_texts(self, kinds=("media",))
        self.assertEqual(s["missing_files"], ["summary"])
        self.assertEqual(len(find(rows, level="state")), 0)
        self.assertEqual(len(rows), 6000)
        for k in ("state_precinct_mismatches", "total_mismatches", "registered_mismatches", "precinct_count_mismatches",
                  "title_mismatches", "choice_name_mismatches"):
            self.assertIsNone(s[k], k)
        self.assertEqual(s["unit_conflicts"], [])

    def test_missing_media(self):
        rows, s, _ = parse_texts(self, kinds=("summary",))
        self.assertEqual(s["missing_files"], ["media"])
        self.assertEqual(len(find(rows, level="precinct")), 0)
        self.assertEqual(s["total_mismatches"], [])
        for k in ("state_precinct_mismatches", "registered_mismatches", "precinct_count_mismatches",
                  "title_mismatches", "choice_name_mismatches", "unit_conflicts"):
            self.assertIsNone(s[k], k)

    def test_nothing(self):
        rows, s, t = parse_texts(self, kinds=())
        self.assertEqual((rows, t, s["missing_files"]), ([], [], ["summary", "media"]))
        self.assertIsNone(s["total_mismatches"])

    def test_changed_header_unreadable(self):
        text = raw("media").replace("Mail votes", "Mail Votes", 1)
        rows, s, _ = parse_texts(self, media=text)
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["media"])
        self.assertEqual(len(find(rows, level="precinct")), 0)

    def test_html_unreadable(self):
        _, s, _ = parse_texts(self, summary="<html><body>Not found</body></html>")
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["summary"])

    def test_header_only_unreadable(self):
        recs = records(raw("summary"))
        _, s, _ = parse_texts(self, summary="".join(recs[:2]))
        self.assertEqual(s["unreadable_files"], [("summary", "no data lines")])

    def test_preamble_without_column_line(self):
        recs = records(raw("media"))
        rows, s, _ = parse_texts(self, media="".join(recs[1:]))
        self.assertEqual(s["unreadable_files"], [])
        self.assertEqual(len(find(rows, level="precinct")), 6000)
        self.assertEqual(s["preamble"]["media"], [["#FormatVersion 1"] + [""] * 15])


if __name__ == "__main__":
    unittest.main()
