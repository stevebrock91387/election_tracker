"""Tally source list and the fetch pass (fake opener and sleep; no network)."""
import csv
import glob
import json
import os
import tempfile
import unittest
import urllib.parse

from pipeline.fetch import FetchError
from pipeline.run_tally import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

ND_ID = "tally-ND-2026-general"
ND_API = "https://api.resultsnd.sos.nd.gov/"


def opener_for(record, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 500, b"error"
        return 200, b"{}"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(len(src), 2)
        self.assertEqual({s["state"] for s in src.values()}, {"AR", "ND"})
        for sid, s in src.items():
            self.assertGreaterEqual(s["min_interval_s"], 120, sid)
            self.assertEqual(s["request_gap_s"], 10, sid)
            self.assertTrue(s["api"].endswith("/"), sid)


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[ND_ID]

    def run_pass(self, src, opener):
        return fetch_pass(ND_ID, src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(self.src, opener_for(seen))
        self.assertEqual(seen, [
            ND_API + "Election/GetElectionInfo?cId=north-dakota&electionID=348",
            ND_API + "Contest/GetContestSearchList?cid=north-dakota&electionID=348",
            ND_API + "Contest/GetContestResults?cId=north-dakota&electionID=348&contestType=SW",
        ])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([(x["kind"], x["type"]) for x in r["files"]], [("info", ""), ("list", ""), ("results", "SW")])
        self.assertEqual((r["state"], r["election_id"]), ("ND", "348"))

    def test_contest_type_url_encoded(self):
        seen = []
        self.run_pass(dict(self.src, contest_types=["State Senate"]), opener_for(seen))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(seen[-1]).query)
        self.assertEqual(q["contestType"], ["State Senate"])
        self.assertNotIn(" ", seen[-1])

    def test_gap_between_requests(self):
        self.run_pass(self.src, opener_for([]))
        self.assertEqual(self.slept, [10, 10])

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(self.src, opener_for([], fail=("GetContestSearchList",)))
        self.assertFalse([p for p in os.listdir(os.path.join(self.raw, ND_ID)) if p.startswith("pass-")]
                         if os.path.isdir(os.path.join(self.raw, ND_ID)) else [])


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        main(["parse", "tally-ND-2026-general", os.path.join(FX, "tally_nd_pass.json"),
              "--base-dir", FX, "--parsed-dir", out])
        (path,) = glob.glob(os.path.join(out, "tally-ND-2026-general", "*.csv"))
        with open(path, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)


if __name__ == "__main__":
    unittest.main()
