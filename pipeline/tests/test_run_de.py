"""DE source list and the fetch pass (fake opener, sleep and clock; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.de import TURNOUT_COLUMNS
from pipeline.run_de import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

DE_ID = "de-2026-general"
B = "https://elections.delaware.gov/results/enr/"
FILES = ["StatewideResults", "ByElectionDistrict", "ByCountyWithWilmington", "VoterTurnout"]


def opener_for(record, fail=()):
    def opener(url):
        record.append(url)
        return (404, b"no") if any(f in url for f in fail) else (200, b"[]")
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[DE_ID]
        self.assertEqual((s["state"], s["base_url"], s["election_id"]), ("DE", B, "GE2026"))
        self.assertEqual(s["exclude_title_prefixes"], ["New Castle County", "Kent County", "Sussex County"])
        self.assertEqual(s["district_title_prefixes"], ["State Senator", "State Representative"])
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[DE_ID]

    def run_pass(self, opener):
        return fetch_pass(DE_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append, clock=lambda: 1700000000.25)

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [f"{B}Election_{f}_ID_GE2026.json?t=1700000000250" for f in FILES])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["statewide", "district", "county", "turnout"])
        self.assertEqual(self.slept, [10, 10, 10])

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], fail=("ByCounty",)))
        d = os.path.join(self.raw, DE_ID)
        self.assertFalse(os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", DE_ID, os.path.join(FX, "de_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, DE_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, DE_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("results_type: OFFICIAL RESULTS", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": DE_ID, "state": "DE", "exclude_title_prefixes": [], "district_title_prefixes": [],
                       "files": [{"kind": "district", "path": os.path.join(FX, "de_district.json")}]}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", DE_ID, rec, "--parsed-dir", d])
        self.assertIn("district_vs_state_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
