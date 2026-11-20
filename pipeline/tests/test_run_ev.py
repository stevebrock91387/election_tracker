"""EV source list and the parse command."""
import csv
import glob
import os
import tempfile
import unittest

from pipeline.run_ev import DEFAULT_SOURCES, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures", "ev_az_greenlee.json")


class RunEvTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(len(src), 7)
        self.assertEqual({s["state"] for s in src.values()}, {"AZ", "GA", "UT", "WA", "VA", "RI", "ID"})
        for sid, s in src.items():
            self.assertGreaterEqual(s["min_interval_s"], 120, sid)
            self.assertTrue(s["url"].startswith("https://"), sid)
            self.assertTrue(s["url"].endswith(".json"), sid)

    def test_parse_command_writes_csv(self):
        out = tempfile.mkdtemp()
        main(["parse", FX, "ev-AZ-2026-general", "--parsed-dir", out])
        (path,) = glob.glob(os.path.join(out, "ev-AZ-2026-general", "*.csv"))
        with open(path, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)


if __name__ == "__main__":
    unittest.main()
