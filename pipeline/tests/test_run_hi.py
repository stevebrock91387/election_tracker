"""HI source list and the fetch pass (fake opener; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.hi import TURNOUT_COLUMNS
from pipeline.run_hi import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

HI_ID = "hi-2026-general"
BASE = "https://elections.hawaii.gov/wp-content/results/2026%20General/"


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[HI_ID]
        self.assertEqual((s["state"], s["summary_url"], s["media_url"], s["min_interval_s"]),
                         ("HI", BASE + "summary.txt", BASE + "media.txt", 120))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.src = load_sources(DEFAULT_SOURCES)[HI_ID]

    def test_pass_record(self):
        seen = []
        rec = fetch_pass(HI_ID, self.src, raw_dir=self.raw, opener=lambda u: (seen.append(u), (200, b"x"))[1])
        self.assertEqual(seen, [BASE + "summary.txt", BASE + "media.txt"])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["summary", "media"])
        self.assertTrue(all(x["path"].endswith(".txt") for x in r["files"]))
        self.assertEqual(r["state"], "HI")

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(HI_ID, self.src, raw_dir=self.raw,
                       opener=lambda u: (200, b"x") if u.endswith("summary.txt") else (403, b"no"))
        self.assertFalse(os.path.exists(os.path.join(self.raw, HI_ID)))


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", HI_ID, os.path.join(FX, "hi_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, HI_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, HI_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("state_precinct_mismatches: 0", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": HI_ID, "state": "HI", "files": []}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", HI_ID, rec, "--parsed-dir", d])
        self.assertIn("state_precinct_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
