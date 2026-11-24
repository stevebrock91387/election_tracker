"""TX source list and the fetch pass (fake opener and sleep; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.tx import TURNOUT_COLUMNS
from pipeline.run_tx import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

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


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", TX_ID, os.path.join(FX, "tx_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, TX_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, TX_ID, "*-turnout.csv"))
        self.assertEqual(turnout, results[:-4] + "-turnout.csv")
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            r = csv.reader(f)
            self.assertEqual(next(r), TURNOUT_COLUMNS)
            self.assertEqual(sum(1 for _ in r), 3)
        text = buf.getvalue()
        self.assertIn("party_differences:", text)
        self.assertIn("version: enr/53815/117/", text)

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": TX_ID, "state": "TX",
                       "files": [{"kind": "election", "path": os.path.join(FX, "tx_election.json")}]}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", TX_ID, rec, "--parsed-dir", d])
        self.assertIn("mismatches_state_vs_county: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
