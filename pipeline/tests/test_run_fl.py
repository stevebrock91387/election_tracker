"""FL source list and the fetch pass (fake opener, sleep and clock; no network)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import pipeline.run_fl as run_fl
from pipeline.fetch import FetchError
from pipeline.run_fl import DEFAULT_SOURCES, fetch_pass, load_sources

FL_ID = "fl-2026-general"
B = "https://flelectionfiles.floridados.gov/enightfilespublic/"
URLS = [B + "20261103_ElecResultsFL_PipeDlm_Info.txt", B + "20261103_ElecResultsFL_PipeDlm_Votes.txt",
        B + "20261103_ElecResultsFL.txt"]


def opener_for(record, fail=()):
    def opener(url):
        record.append(url)
        return (403, b"blocked") if any(f in url for f in fail) else (200, b"[x]")
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [FL_ID])
        s = src[FL_ID]
        self.assertEqual((s["state"], s["info_url"], s["votes_url"], s["tab_url"]), ("FL", *URLS))
        self.assertEqual(s["cafile"], "pipeline/certs/godaddy-tls-root-r1-cross-g2.pem")
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[FL_ID]

    def run_pass(self, opener):
        return fetch_pass(FL_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append,
                          clock=lambda: 1700000000.5)

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [u + "?v=1700000000" for u in URLS])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["info", "votes", "tab"])
        for x in r["files"]:
            self.assertTrue(x["path"].endswith(".txt"))
            self.assertIn(os.sep + f"{FL_ID}-{x['kind']}" + os.sep, x["path"])

    def test_gap_between_requests(self):
        self.run_pass(opener_for([]))
        self.assertEqual(self.slept, [10, 10])

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], fail=("Votes",)))
        d = os.path.join(self.raw, FL_ID)
        self.assertFalse(os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])

    def test_cafile_passed(self):
        calls = []
        with mock.patch.object(run_fl, "fetch", side_effect=lambda *a, **k: (calls.append(k), "x.txt")[1]):
            fetch_pass(FL_ID, self.src, raw_dir=self.raw, sleep=lambda s: None, clock=lambda: 1.0)
        self.assertTrue(calls)
        for k in calls:
            self.assertTrue(k["cafile"].endswith("pipeline/certs/godaddy-tls-root-r1-cross-g2.pem"))
            self.assertTrue(os.path.isabs(k["cafile"]))


if __name__ == "__main__":
    unittest.main()
