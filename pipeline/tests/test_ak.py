"""Alaska reader on a fixture cut from the 2026 general precinct CSV (pipeline/make_ak_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.ak import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
TYPES = ["TOTAL", "Election Day", "Absentee", "Early Voting", "Question", "Remote"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def raw():
    with open(os.path.join(FX, "ak_csv.csv"), "rb") as f:
        return f.read().decode("utf-8")


def parse_text(test, text=None, files=True):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    if text is not None:
        with open(os.path.join(d, "ak.csv"), "w", newline="") as f:
            f.write(text)
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "ak-test", "state": "AK", "files": [{"kind": "csv", "path": "ak.csv"}] if files else []}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


def edit_line(text, match, field, value):
    """Set one CSV field (by header name) on the first line containing every string in `match`."""
    import csv
    import io
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    head = next(csv.reader([lines[0]]))
    i = next(n for n, l in enumerate(lines) if n and all(m in l for m in match))
    row = next(csv.reader([lines[i]]))
    row[head.index(field)] = value
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="").writerow(row)
    lines[i] = buf.getvalue()
    return ("\r\n" if "\r\n" in text else "\n").join(lines)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "ak_pass.json"), base_dir=FX)

    def test_precinct_rows(self):
        r = {x["vote_type"]: x for x in find(self.rows, precinct_id="01-600", contest_id="6", choice_id="525")}
        self.assertEqual(sorted(r), sorted(TYPES))
        self.assertEqual((r["TOTAL"]["votes"], r["Election Day"]["votes"], r["Absentee"]["votes"]), (263, 263, 0))
        t = r["TOTAL"]
        self.assertEqual((t["party"], t["choice"], t["contest_name"], t["precinct_is_virtual"], t["contest_type"], t["vote_for"]),
                         ("DEM", "Peltola, Mary", "U.S. Senator", "N", "first choice", "1"))
        self.assertEqual(t["level"], "precinct")

    def test_unit_ids(self):
        ev = find(self.rows, precinct_name="District 1 - Early Voting")
        self.assertTrue(ev)
        self.assertEqual({(x["precinct_id"], x["precinct_is_virtual"]) for x in ev}, {("District 1 - Early Voting", "Y")})
        ab = find(self.rows, precinct_name="District 1 - Absentee")
        self.assertEqual({(x["precinct_id"], x["precinct_is_virtual"]) for x in ab}, {("1-1", "Y")})

    def test_turnout(self):
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        k, = [t for t in self.turnout if t["precinct_id"] == "01-600"]
        self.assertEqual((k["registered_voters"], k["ballots"]), (2235, 491))

    def test_gap_reported(self):
        self.assertIn("6", self.summary["writein_gap_by_contest"])

    def test_summary_clean_parts(self):
        for k in ("vote_type_sum_mismatches", "duplicate_entries", "unit_id_conflicts", "non_numeric",
                  "malformed_lines", "unreadable_files", "missing_files", "units_without_senate_line"):
            self.assertEqual(self.summary[k], [], k)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)


class SyntheticTest(unittest.TestCase):
    def test_vote_type_sums(self):
        t = edit_line(raw(), ['"01-600 Ketchikan No. 1"', '"Peltola, Mary"'], "Election Day_votes", "264")
        rows, s, _ = parse_text(self, t)
        self.assertEqual([m[:4] for m in s["vote_type_sum_mismatches"]], [("01-600", "6", "525", "votes")])

    def test_unreadable(self):
        rows, s, _ = parse_text(self, "<html>blocked</html>")
        self.assertEqual(rows, [])
        self.assertEqual(len(s["unreadable_files"]), 1)
        self.assertIsNone(s["vote_type_sum_mismatches"])
        rows, s, _ = parse_text(self, files=False)
        self.assertEqual(s["missing_files"], ["csv"])

    def test_header_change(self):
        t = raw().replace("Election Day_votes", "ElectionDay_votes", 1)
        rows, s, _ = parse_text(self, t)
        self.assertEqual(rows, [])
        self.assertEqual(len(s["unreadable_files"]), 1)

    def test_unit_id_conflicts(self):
        t = edit_line(raw(), ['"01-610 Ketchikan No. 2"', '"Peltola, Mary"'], "Pct_Id", "01-999")
        rows, s, _ = parse_text(self, t)
        self.assertTrue(any(c[0] == "01-610 Ketchikan No. 2" for c in s["unit_id_conflicts"]))

    def test_gap_and_varying_ballots(self):
        t = edit_line(raw(), ['01-600 Ketchikan No. 1', 'Taylor/English'], "total_ballots", "999")
        t = edit_line(t, ['01-600 Ketchikan No. 1', 'Taylor/English'], "Election Day_ballots", "999")
        rows, s, _ = parse_text(self, t)
        self.assertIn("01-600 Ketchikan No. 1", [u[0] for u in s["units_ballots_vary_by_contest"]])

    def test_duplicate_nonnumeric_malformed(self):
        lines = raw().splitlines(keepends=True)
        t = "".join(lines + [lines[1], "short,line\r\n"])
        t = edit_line(t, ['"01-610 Ketchikan No. 2"', '"Peltola, Mary"'], "total_under_votes", "x")
        rows, s, _ = parse_text(self, t)
        self.assertEqual(len(s["duplicate_entries"]), 1)
        self.assertEqual(len(s["malformed_lines"]), 1)
        self.assertTrue(s["non_numeric"])


if __name__ == "__main__":
    unittest.main()
