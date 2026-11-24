"""NC source list and the fetch pass (fake opener and sleep; no network)."""
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_nc import DEFAULT_SOURCES, fetch_pass, load_sources

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


if __name__ == "__main__":
    unittest.main()
