"""AK source list and the fetch pass (fake opener; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.ak import TURNOUT_COLUMNS
from pipeline.run_ak import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

AK_ID = "ak-2026-general"
URL = "https://www.elections.alaska.gov/enr/26GENR/results/GA_ENR_Precinct_State_of_Alaska.csv"


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[AK_ID]
        self.assertEqual((s["state"], s["csv_url"], s["min_interval_s"]), ("AK", URL, 120))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.src = load_sources(DEFAULT_SOURCES)[AK_ID]

    def test_pass_record(self):
        seen = []
        rec = fetch_pass(AK_ID, self.src, raw_dir=self.raw, opener=lambda u: (seen.append(u), (200, b"x"))[1])
        self.assertEqual(seen, [URL])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["csv"])
        self.assertTrue(r["files"][0]["path"].endswith(".csv"))

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(AK_ID, self.src, raw_dir=self.raw, opener=lambda u: (403, b"no"))
        self.assertFalse(os.path.exists(os.path.join(self.raw, AK_ID)))


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", AK_ID, os.path.join(FX, "ak_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, AK_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, AK_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("writein_gap_by_contest:", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": AK_ID, "state": "AK", "files": []}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", AK_ID, rec, "--parsed-dir", d])
        self.assertIn("vote_type_sum_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
