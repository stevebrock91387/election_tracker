"""TX source list and the fetch pass (fake opener and sleep; no network)."""
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_tx import DEFAULT_SOURCES, fetch_pass, load_sources

TX_ID = "tx-2026-general"
ELECTION_URL = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/53815"
COUNTY_URL = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/countyInfo/53815"


def opener_for(record, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 403, b"blocked"
        return 200, b"{}"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [TX_ID])
        s = src[TX_ID]
        self.assertEqual((s["state"], s["election_url"], s["county_url"]), ("TX", ELECTION_URL, COUNTY_URL))
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[TX_ID]

    def run_pass(self, opener):
        return fetch_pass(TX_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [ELECTION_URL, COUNTY_URL])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["source_id"], r["state"]), (TX_ID, "TX"))
        self.assertEqual([x["kind"] for x in r["files"]], ["election", "county"])
        for x, sid in zip(r["files"], ("election", "county")):
            self.assertTrue(os.path.exists(x["path"]))
            self.assertTrue(x["path"].endswith(".json"))
            self.assertIn(os.sep + f"{TX_ID}-{sid}" + os.sep, x["path"])

    def test_gap_between_requests(self):
        self.run_pass(opener_for([]))
        self.assertEqual(self.slept, [10])

    def test_failure_stops_pass(self):
        seen = []
        with self.assertRaises(FetchError):
            self.run_pass(opener_for(seen, fail=("countyInfo",)))
        self.assertEqual(seen, [ELECTION_URL, COUNTY_URL])
        d = os.path.join(self.raw, TX_ID)
        self.assertFalse(os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])


if __name__ == "__main__":
    unittest.main()
