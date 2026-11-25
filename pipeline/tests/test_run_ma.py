"""MA source list, list parsers and the fetch pass (fake opener; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.ma import parse_questions, parse_search, select
from pipeline.run_ma import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
MA_ID = "ma-2026-general"
BASE = "https://electionstats.state.ma.us"


def fx(name, mode="rb"):
    with open(os.path.join(FX, name), mode) as f:
        return f.read()


class ListParserTest(unittest.TestCase):
    def test_search(self):
        got = parse_search(fx("ma_search.html").decode("utf-8"))
        self.assertEqual(sorted(got), ["171923", "173531", "173571", "173595", "173668"])
        sen = got["173531"]
        self.assertEqual((sen["office"], sen["district"], sen["stage"], sen["year"]),
                         ("U.S. Senate", "Statewide", "General Election", "2026"))
        self.assertEqual(sen["candidates"][:2], [("Edward J. Markey", "Democratic", "1,718,276"),
                                                 ("John Deaton", "Republican", "855,969")])
        self.assertEqual(sen["candidates"][-3:], [("All Others", "", "3,811"), ("Blanks", "", "51,371"),
                                                  ("Total Votes Cast", "", "2,749,609")])
        self.assertEqual(got["173571"]["candidates"][0][:2], ("James P. McGovern", "Democratic"))
        self.assertEqual((got["173668"]["office"], got["173668"]["district"]), ("State Representative", "1st Barnstable"))

    def test_questions(self):
        got = parse_questions(fx("ma_questions.html").decode("utf-8"))
        self.assertEqual((got["11789"]["number"], got["11789"]["location"], got["11789"]["type"]),
                         ("1", "Statewide", "Initiative Petition"))
        self.assertEqual(got["11758"]["location"], "1st Bristol")
        self.assertEqual([c[0] for c in got["11789"]["candidates"]], ["Yes", "No", "Blanks", "Total Votes Cast"])

    def test_select(self):
        src = load_sources(DEFAULT_SOURCES)[MA_ID]
        contests = parse_search(fx("ma_search.html").decode("utf-8"))
        questions = parse_questions(fx("ma_questions.html").decode("utf-8"))
        self.assertEqual(got["171923"]["stage"] if (got := contests) else None, "Special General Election")
        self.assertEqual(select(contests, questions, src["offices"], src["question_locations"], src["stages"]),
                         (["173531", "173571", "173668"], ["11789"]))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.src = load_sources(DEFAULT_SOURCES)[MA_ID]

    def opener(self, seen):
        pages = {BASE + self.src["search_path"]: fx("ma_search.html"),
                 BASE + self.src["questions_path"]: fx("ma_questions.html")}
        return lambda u: (seen.append(u), (200, pages.get(u, b"csv")))[1]

    def test_pass_record(self):
        seen, gaps = [], []
        rec = fetch_pass(MA_ID, self.src, raw_dir=self.raw, opener=self.opener(seen), sleep=gaps.append)
        self.assertEqual(seen, [BASE + self.src["search_path"], BASE + self.src["questions_path"]]
                         + [BASE + f"/elections/download/{i}/precincts_include:1/" for i in ("173531", "173571", "173668")]
                         + [BASE + "/ballot_questions/download/11789/precincts_include:1/"])
        self.assertEqual(gaps, [5] * 5)
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([(x["kind"], x.get("id")) for x in r["files"]],
                         [("search", None), ("questions", None), ("contest", "173531"), ("contest", "173571"),
                          ("contest", "173668"), ("question", "11789")])
        self.assertEqual((r["offices"], r["question_locations"], r["stages"]),
                         (self.src["offices"], ["Statewide"], ["General Election"]))
        self.assertEqual({k: r["files"][2][k] for k in ("office", "district", "stage")},
                         {"office": "U.S. Senate", "district": "Statewide", "stage": "General Election"})
        self.assertEqual((r["files"][5]["number"], r["files"][5]["location"]), ("1", "Statewide"))

    def test_list_page_without_rows_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(MA_ID, self.src, raw_dir=self.raw, sleep=lambda s: None,
                       opener=lambda u: (200, b"<html>Radware bot check</html>"))
        self.assertFalse(os.path.exists(os.path.join(self.raw, MA_ID)))

    def test_list_page_bad_utf8_stops_pass(self):
        seen = []
        ok = self.opener(seen)
        with self.assertRaises(UnicodeDecodeError):
            fetch_pass(MA_ID, self.src, raw_dir=self.raw, sleep=lambda s: None,
                       opener=lambda u: (200, fx("ma_search.html") + b"\xff") if u.endswith("stage:General") else ok(u))

    def test_failure_stops_pass(self):
        seen = []
        ok = self.opener(seen)
        with self.assertRaises(FetchError):
            fetch_pass(MA_ID, self.src, raw_dir=self.raw, sleep=lambda s: None,
                       opener=lambda u: (403, b"no") if "173571" in u else ok(u))
        self.assertFalse(os.path.exists(os.path.join(self.raw, MA_ID)))


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", MA_ID, os.path.join(FX, "ma_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, MA_ID, "*Z.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        self.assertIn("list_mismatches: 0", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": MA_ID, "state": "MA", "offices": [], "question_locations": [], "files": []}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", MA_ID, rec, "--parsed-dir", d])
        self.assertIn("list_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
