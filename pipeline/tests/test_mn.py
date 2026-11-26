"""Minnesota reader on a fixture cut from the 2026 general allracesbycounty.txt (counties 01 and 02)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.mn import parse_pass

FX = os.path.join(os.path.dirname(__file__), "fixtures")
RANGES = [["0102", "0111"], ["0121", "0351"], ["7000", "7099"]]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def raw():
    with open(os.path.join(FX, "mn_allracesbycounty.txt"), "rb") as f:
        return f.read().decode("latin-1")


def parse_text(test, text=None, files=True, ranges=RANGES):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    if text is not None:
        with open(os.path.join(d, "mn.txt"), "wb") as f:
            f.write(text.encode("latin-1"))
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "mn-test", "state": "MN",
                   "files": [{"kind": "txt", "path": "mn.txt"}] if files else []}, f)
    return parse_pass(os.path.join(d, "pass.json"), ranges, base_dir=d)


def edit(text, match, index, value):
    """Set field `index` (0-based) on the first line containing every string in `match`."""
    lines = text.split("\r\n")
    i = next(n for n, l in enumerate(lines) if all(m in l for m in match))
    f = lines[i].split(";")
    f[index] = value
    lines[i] = ";".join(f)
    return "\r\n".join(lines)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, d)
        shutil.copy(os.path.join(FX, "mn_allracesbycounty.txt"), os.path.join(d, "mn.txt"))
        with open(os.path.join(d, "pass.json"), "w") as f:
            json.dump({"source_id": "mn-test", "state": "MN", "files": [{"kind": "txt", "path": "mn.txt"}]}, f)
        cls.rows, cls.summary = parse_pass(os.path.join(d, "pass.json"), RANGES, base_dir=d)

    def test_county_row(self):
        (r,) = find(self.rows, county_id="02", contest_id="0102", choice_id="0403")
        self.assertEqual((r["level"], r["contest_name"], r["choice"], r["party"], r["votes"], r["vote_type"],
                          r["reporting_status"], r["contest_scope"], r["state"], r["source_id"]),
                         ("county", "U.S. Senator", "Peggy Flanagan", "DFL", 90031, "TOTAL", "128/128", "statewide",
                          "MN", "mn-test"))
        self.assertEqual(len(r["source_sha256"]), 64)

    def test_district_contest_reporting_is_its_own(self):
        (r,) = find(self.rows, county_id="02", contest_id="0108", choice_id="0401")
        self.assertEqual((r["contest_name"], r["reporting_status"], r["votes"]),
                         ("U.S. Representative District 5", "21/21", 15480))

    def test_write_in_and_estimated_blanks_kept(self):
        self.assertEqual(find(self.rows, county_id="01", contest_id="0102", choice_id="9901")[0]["votes"], 8)
        self.assertEqual(find(self.rows, county_id="01", contest_id="0351", choice_id="9003")[0]["choice"],
                         "ESTIMATED BLANKS")

    def test_scope(self):
        got = {r["contest_id"] for r in self.rows}
        self.assertEqual(got, {"0102", "0108", "0111", "0127", "0200", "0241", "0331", "0351", "7002"})
        self.assertEqual(self.summary["out_of_scope_offices"],
                         [("0404", "County Sheriff"), ("0431", "Soil and Water Supervisor District 1"),
                          ("9101", "Judge - 9th District Court 2")])

    def test_summary_clean(self):
        s = self.summary
        self.assertEqual((s["lines"], s["rows"], s["counties"], s["contests"]), (53, len(self.rows), 2, 9))
        for k in ("office_total_mismatches", "reporting_varies", "reporting_over_total", "duplicate_entries",
                  "non_numeric", "malformed_lines", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)


class SyntheticTest(unittest.TestCase):
    def test_office_total_mismatch_listed(self):
        rows, s = parse_text(self, edit(raw(), [";01;;0102;", "Tafoya"], 13, "5690"))
        self.assertEqual(s["office_total_mismatches"], [("01", "0102", 8954, 8953)])
        self.assertEqual(find(rows, county_id="01", contest_id="0102", choice_id="0304")[0]["votes"], 5690)

    def test_reporting_varies_and_over_total(self):
        _, s = parse_text(self, edit(raw(), [";02;;0102;", "Whiting"], 11, "127"))
        self.assertEqual(s["reporting_varies"], [("02", "0102", ["127/128", "128/128"])])
        _, s = parse_text(self, edit(raw(), [";02;;0102;", "Whiting"], 11, "129"))
        self.assertEqual(s["reporting_over_total"], [("02", "0102", "1102", 129, 128)])

    def test_non_numeric_votes_empty_and_listed(self):
        rows, s = parse_text(self, edit(raw(), [";01;;0102;", "Tafoya"], 13, "x"))
        self.assertEqual(find(rows, county_id="01", contest_id="0102", choice_id="0304")[0]["votes"], "")
        self.assertEqual(s["non_numeric"], [("01", "0102", "0304", "votes", "x")])
        self.assertEqual(s["office_total_mismatches"], [])  # can't be computed for that office

    def test_duplicate_and_malformed(self):
        text = raw()
        line = next(l for l in text.split("\r\n") if ";01;;0102;" in l)
        rows, s = parse_text(self, text + "\r\n" + line + "\r\nMN;01;bad")
        self.assertEqual(s["duplicate_entries"], [("01", "0102", "1001")])
        self.assertEqual(s["malformed_lines"], [(56, 3)])
        self.assertEqual(len(find(rows, county_id="01", contest_id="0102", choice_id="1001")), 1)

    def test_unreadable_and_missing(self):
        rows, s = parse_text(self, "")
        self.assertEqual((rows, s["lines"], s["office_total_mismatches"]), ([], None, None))
        self.assertEqual(len(s["unreadable_files"]), 1)
        rows, s = parse_text(self, files=False)
        self.assertEqual((rows, s["missing_files"]), ([], ["txt"]))

    def test_other_state_refused(self):
        rows, s = parse_text(self, raw().replace("MN;02;", "WI;02;", 1))
        self.assertEqual(s["malformed_lines"][0][1], "state WI")


class RunnerTest(unittest.TestCase):
    def test_fetch_pass_records_the_file(self):
        from pipeline import run_mn

        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        src = {"state": "MN", "txt_url": "https://example.test/allracesbycounty.txt", "min_interval_s": 120,
               "office_ranges": RANGES}
        rec = run_mn.fetch_pass("mn-x", src, raw_dir=d, opener=lambda url: (200, b"MN;01;;0102;U.S. Senator;;1001;A;;;IND;1;1;1;100.00;1\r\n"))
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["txt"])
        self.assertTrue(r["files"][0]["path"].endswith(".txt"))


if __name__ == "__main__":
    unittest.main()
