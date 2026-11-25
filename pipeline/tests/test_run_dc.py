"""DC source list and the fetch pass (fake opener and sleep; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.dc import TURNOUT_COLUMNS
from pipeline.run_dc import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

DC_ID = "dc-2026-general"
B = "https://electionresults.dcboe.org/"
CSV = B + "Downloads/Reports/November_3_2026_General_Election_Pre-certified_Results.csv"


def opener_for(record, link=CSV, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 403, b"no"
        return 200, json.dumps({"CsvLink": link}).encode() if "getElectionInfo" in url else b"x"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[DC_ID]
        self.assertEqual((s["state"], s["base_url"], s["election_slug"]), ("DC", B, "2026-General-Election"))
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[DC_ID]

    def run_pass(self, opener):
        return fetch_pass(DC_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def no_record(self):
        d = os.path.join(self.raw, DC_ID)
        return not (os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [B + "electionResults/getElectionInfo/2026-General-Election", CSV,
                                B + "cityWide/getCityWide/2026-General-Election"])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["info", "csv", "citywide"])
        self.assertTrue(r["files"][1]["path"].endswith(".csv"))
        self.assertEqual(self.slept, [10, 10])

    def test_bad_csvlink_stops_pass(self):
        for link in ("https://evil.example/x.csv", B + "../x.csv", None):
            self.raw = tempfile.mkdtemp()
            with self.assertRaises(ValueError):
                self.run_pass(opener_for([], link=link))
            self.assertTrue(self.no_record())

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], fail=("getCityWide",)))
        self.assertTrue(self.no_record())


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", DC_ID, os.path.join(FX, "dc_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, DC_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, DC_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("results_type: Pre-certified Results", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": DC_ID, "state": "DC", "files": [{"kind": "csv", "path": os.path.join(FX, "dc_csv.csv")}]}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", DC_ID, rec, "--parsed-dir", d])
        self.assertIn("precinct_vs_citywide_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
