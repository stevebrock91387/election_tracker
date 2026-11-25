"""AL source list, the fetch pass (fake opener; no network) and the parse command."""
import contextlib
import csv
import glob
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_al import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
AL_ID = "al-2026-general"
URL = ("https://www.sos.alabama.gov/sites/default/files/election-data/2026-11/"
       "2026GeneralElectionPrecinctResults.zip")
HAVE_XLRD = importlib.util.find_spec("xlrd") is not None


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[AL_ID]
        self.assertEqual((s["state"], s["zip_url"], s["min_interval_s"]), ("AL", URL, 120))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.raw)
        self.src = load_sources(DEFAULT_SOURCES)[AL_ID]

    def test_pass_record(self):
        seen = []
        rec = fetch_pass(AL_ID, self.src, raw_dir=self.raw, opener=lambda u: (seen.append(u), (200, b"PK"))[1])
        self.assertEqual(seen, [URL])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["state"], r["source_id"]), ("AL", AL_ID))
        self.assertEqual([x["kind"] for x in r["files"]], ["zip"])
        self.assertTrue(r["files"][0]["path"].endswith(".zip"))

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(AL_ID, self.src, raw_dir=self.raw, opener=lambda u: (403, b"no"))
        self.assertFalse(os.path.exists(os.path.join(self.raw, AL_ID)))


@unittest.skipUnless(HAVE_XLRD, "needs xlrd (.venv)")
class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        from pipeline.readers.al import TURNOUT_COLUMNS
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", AL_ID, os.path.join(FX, "al_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, AL_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, AL_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("ballot_balance_mismatches:", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": AL_ID, "state": "AL", "files": []}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", AL_ID, rec, "--parsed-dir", d])
        self.assertIn("ballot_balance_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
