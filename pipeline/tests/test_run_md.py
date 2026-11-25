"""MD source list, the fetch pass (fake opener and sleep; no network) and the parse command."""
import contextlib
import csv
import glob
import io
import json
import os
import shutil
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_md import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
MD_ID = "md-2026-general"
BASE = "https://elections.maryland.gov/elections/2026/general_results/"


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[MD_ID]
        self.assertEqual((s["state"], s["base_url"], s["min_interval_s"], s["request_gap_s"]), ("MD", BASE, 120, 5))
        self.assertEqual(len(s["counties"]), 24)
        self.assertEqual((s["counties"]["16"], s["counties"]["3"]), ("Montgomery County", "Baltimore City"))
        self.assertEqual(sorted(s["office_pages"], key=int), [str(i) for i in range(1, 10)])
        self.assertEqual(set(s["office_pages"].values()), set(s["offices"]))
        self.assertEqual(set(s["question_pages"].values()), set(s["questions"]))
        self.assertEqual(s["per_county_offices"], ["Judge of the Circuit Court"])


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.raw)
        self.src = load_sources(DEFAULT_SOURCES)[MD_ID]

    def test_pass_record(self):
        seen, sleeps = [], []
        rec = fetch_pass(MD_ID, self.src, raw_dir=self.raw, opener=lambda u: (seen.append(u), (200, b"<html></html>"))[1],
                         sleep=sleeps.append)
        self.assertEqual(len(seen), 36)
        self.assertEqual((seen[0], seen[23], seen[24], seen[33], seen[35]),
                         (BASE + "gen_results_2026_by_county_1.html", BASE + "gen_results_2026_by_county_24.html",
                          BASE + "gen_results_2026_1.html", BASE + "gen_qresults_2026_1.html", BASE + "gen_qresults_2026_3.html"))
        self.assertEqual(sleeps, [5] * 35)
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([(x["kind"], x["number"]) for x in r["files"]][:2], [("county", "1"), ("county", "2")])
        self.assertTrue(all(x["path"].endswith(".html") for x in r["files"]))
        for k in ("counties", "offices", "questions", "per_county_offices", "office_pages", "question_pages"):
            self.assertEqual(r[k], self.src[k], k)

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(MD_ID, self.src, raw_dir=self.raw, opener=lambda u: (403, b"no"), sleep=lambda s: None)
        self.assertFalse(os.path.exists(os.path.join(self.raw, MD_ID)))


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", MD_ID, os.path.join(FX, "md_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, MD_ID, "*Z.csv"))
        self.assertEqual(glob.glob(os.path.join(out, MD_ID, "*-turnout.csv")), [])
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        self.assertIn("contests_not_checked:", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": MD_ID, "state": "MD", "files": []}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", MD_ID, rec, "--parsed-dir", d])
        self.assertIn("county_state_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
