"""CT source list and the fetch pass (fake opener and sleep; no network)."""
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_ct import DEFAULT_SOURCES, fetch_pass, load_sources

CT_ID = "ct-2026-general"
BASE = "https://ctemspublic.tgstg.net/ng-app/data/election/108/"
FILES = ["Lookupdata.json", "stateVotes_Electiondata.json", "townVotes_Electiondata.json",
         "townStatus_Electiondata.json", "voterTurnout_Electiondata.json", "candidateGrouping_Electiondata.json",
         "officePrecincts_Electiondata.json"]
KINDS = ["version", "lookup", "state", "town", "townstatus", "turnout", "grouping", "officeprecincts"]


def opener_for(record, version_body=b'{"Version":56592}\r\n', fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 404, b"not found"
        return 200, version_body if url.endswith("Version.json") else b"{}"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [CT_ID])
        s = src[CT_ID]
        self.assertEqual((s["state"], s["base_url"], s["office_types"]), ("CT", BASE, ["SW", "C", "S", "A", "PD"]))
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[CT_ID]

    def run_pass(self, opener):
        return fetch_pass(CT_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def no_record(self):
        d = os.path.join(self.raw, CT_ID)
        return not (os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [BASE + "Version.json"] + [BASE + "56592/" + f for f in FILES])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["source_id"], r["state"], r["version"]), (CT_ID, "CT", 56592))
        self.assertEqual(r["office_types"], ["SW", "C", "S", "A", "PD"])
        self.assertEqual([x["kind"] for x in r["files"]], KINDS)
        for x in r["files"]:
            self.assertTrue(x["path"].endswith(".json"))
            self.assertIn(os.sep + f"{CT_ID}-{x['kind']}" + os.sep, x["path"])

    def test_gap_between_requests(self):
        self.run_pass(opener_for([]))
        self.assertEqual(self.slept, [10] * 7)

    def test_bad_version_stops_pass(self):
        with self.assertRaises(ValueError):
            self.run_pass(opener_for([], version_body=b"<html>"))
        self.assertTrue(self.no_record())

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], fail=("townVotes",)))
        self.assertTrue(self.no_record())


if __name__ == "__main__":
    unittest.main()
