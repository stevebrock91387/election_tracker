"""VT source list and the fetch pass (fake opener and sleep; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.vt import TURNOUT_COLUMNS
from pipeline.run_vt import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

VT_ID = "vt-2026-general"
BASE = "https://static.electionresults.vermont.gov/"
GUID = "68d61e96-1d28-4210-8c1d-8e90512ae105"
SUFFIX = {"federal": "f", "stateWide": "s", "senate": "sn", "house": "h", "turnOut": "turnout"}


def election_body(stamp="20261117185828", odd=None):
    body = {k: {"isEnable": True, "path": f"elections\\{GUID}-{v}-{stamp}.json"} for k, v in SUFFIX.items()}
    if odd:
        body.update(odd)
    return json.dumps(body).encode()


def opener_for(record, body, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 403, b"no"
        return 200, body if url.endswith(GUID + ".json") else b"{}"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [VT_ID])
        s = src[VT_ID]
        self.assertEqual((s["state"], s["base_url"], s["election_guid"]), ("VT", BASE, GUID))
        self.assertEqual(s["kinds"], list(SUFFIX))
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[VT_ID]

    def run_pass(self, opener):
        return fetch_pass(VT_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def no_record(self):
        d = os.path.join(self.raw, VT_ID)
        return not (os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen, election_body()))
        self.assertEqual(seen, [f"{BASE}elections/{GUID}.json"] +
                         [f"{BASE}elections/{GUID}-{v}-20261117185828.json" for v in SUFFIX.values()])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["snapshot"], r["state"]), ("20261117185828", "VT"))
        self.assertEqual([x["kind"] for x in r["files"]], ["election"] + list(SUFFIX))
        self.assertEqual(self.slept, [10] * 5)

    def test_mixed_snapshot_stops_pass(self):
        for odd in ({"house": {"isEnable": True, "path": f"elections\\{GUID}-h-20261118000000.json"}},
                    {"house": {"isEnable": True, "path": "..\\other\\x.json"}},
                    {"house": {"isEnable": False}}):
            self.raw = tempfile.mkdtemp()  # a fresh folder: the fetch interval applies per raw dir
            with self.assertRaises(ValueError):
                self.run_pass(opener_for([], election_body(odd=odd)))
            self.assertTrue(self.no_record())

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], election_body(), fail=("-sn-",)))
        self.assertTrue(self.no_record())


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", VT_ID, os.path.join(FX, "vt_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, VT_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, VT_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("snapshot: 20261117185828", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": VT_ID, "state": "VT", "snapshot": "x",
                       "files": [{"kind": "election", "path": os.path.join(FX, "vt_election.json")}]}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", VT_ID, rec, "--parsed-dir", d])
        self.assertIn("turnout_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
