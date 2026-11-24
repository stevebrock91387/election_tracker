"""NC source list and the fetch pass (fake opener and sleep; no network)."""
import csv
import glob
import io
import json
import os
import tempfile
import contextlib
import unittest

from pipeline.fetch import FetchError
from pipeline.run_nc import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

NC_ID = "nc-2026-general"
ZIP_URL = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_11_03/results_pct_20261103.zip"
DASH_URL = "https://er.ncsbe.gov/enr/20261103/data/results_0.txt"


def opener_for(record, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 500, b"error"
        return 200, b"x"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [NC_ID])
        s = src[NC_ID]
        self.assertEqual(s["state"], "NC")
        self.assertEqual(s["zip_url"], ZIP_URL)
        self.assertEqual(s["member"], "results_pct_20261103.txt")
        self.assertEqual(s["dashboard_url"], DASH_URL)
        self.assertGreaterEqual(s["min_interval_s"], 120)
        self.assertEqual(s["request_gap_s"], 10)


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[NC_ID]

    def run_pass(self, opener):
        return fetch_pass(NC_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [ZIP_URL, DASH_URL])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["zip", "dashboard"])
        self.assertEqual((r["state"], r["member"]), ("NC", "results_pct_20261103.txt"))
        for x in r["files"]:
            self.assertTrue(os.path.exists(x["path"]))

    def test_gap_between_requests(self):
        self.run_pass(opener_for([]))
        self.assertEqual(self.slept, [10])

    def test_failure_stops_pass(self):
        seen = []
        with self.assertRaises(FetchError):
            self.run_pass(opener_for(seen, fail=(".zip",)))
        self.assertEqual(seen, [ZIP_URL])
        d = os.path.join(self.raw, NC_ID)
        self.assertFalse(os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", NC_ID, os.path.join(FX, "nc_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (path,) = glob.glob(os.path.join(out, NC_ID, "*.csv"))
        with open(path, newline="") as f:
            r = csv.reader(f)
            self.assertEqual(next(r), COLUMNS)
            self.assertEqual(sum(1 for _ in r), 343 * 5 + 7 * 5)
        self.assertIn("mismatches_dashboard_vs_zip: 35", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": NC_ID, "state": "NC", "member": "m.txt",
                       "files": [{"kind": "dashboard", "path": os.path.join(FX, "nc_dashboard.txt")}]}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", NC_ID, rec, "--parsed-dir", d])
        self.assertIn("mismatches_dashboard_vs_zip: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
