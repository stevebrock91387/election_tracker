"""LA source list and the fetch pass (fake opener and sleep; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.la import TURNOUT_COLUMNS
from pipeline.run_la import DEFAULT_SOURCES, fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

LA_ID = "la-2026-general"
B = "https://voterportal.sos.la.gov/ElectionResults/ElectionResults/Data?blob="
RACES = json.dumps({"Races": {"WriteTime": "x", "Race": [
    {"ID": "67997", "OfficeLevel": "140"}, {"ID": "11111", "OfficeLevel": "210"}, {"ID": "13833", "OfficeLevel": "998"}]}}).encode()


def opener_for(record, races=RACES, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 404, b"no"
        return 200, races if "RacesCandidates_Multiparish" in url else b"{}"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [LA_ID])
        s = src[LA_ID]
        self.assertEqual((s["state"], s["base_url"], s["election_date"]), ("LA", B, "20261103"))
        self.assertEqual(s["office_levels"], ["140", "145", "160", "165", "205", "998"])
        self.assertEqual((len(s["parishes"]), s["parishes"]["01"], s["parishes"]["64"]), (64, "Acadia", "Winn"))
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[LA_ID]

    def run_pass(self, opener):
        return fetch_pass(LA_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def no_record(self):
        d = os.path.join(self.raw, LA_ID)
        return not (os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [B + "20261103/RacesCandidates_Multiparish.htm", B + "20261103/Votes_Multiparish.htm",
                                B + "20261103/VotesRaceByParish/Votes_67997.htm", B + "20261103/VotesEarly/Votes_67997.htm",
                                B + "20261103/VotesRaceByParish/Votes_13833.htm", B + "20261103/VotesEarly/Votes_13833.htm"])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual(r["races"], ["67997", "13833"])
        self.assertEqual([x["kind"] for x in r["files"]],
                         ["races", "votes", "parish-67997", "early-67997", "parish-13833", "early-13833"])
        self.assertEqual(self.slept, [10] * 5)

    def test_bad_races_file_stops_pass(self):
        with self.assertRaises(ValueError):
            self.run_pass(opener_for([], races=b"<html>no</html>"))
        self.assertTrue(self.no_record())

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], fail=("VotesEarly/Votes_13833",)))
        self.assertTrue(self.no_record())


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", LA_ID, os.path.join(FX, "la_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, LA_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, LA_ID, "*-turnout.csv"))
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            self.assertEqual(next(csv.reader(f)), TURNOUT_COLUMNS)
        self.assertIn("runoff_races: 1", buf.getvalue())

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": LA_ID, "state": "LA", "election_date": "20261103", "races": ["67997"],
                       "parishes": {}, "files": [{"kind": "races", "path": os.path.join(FX, "la_races.json")}]}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", LA_ID, rec, "--parsed-dir", d])
        self.assertIn("parish_vs_state_mismatches: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
