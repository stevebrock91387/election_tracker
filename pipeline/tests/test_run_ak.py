"""AK source list and the fetch pass (fake opener; no network)."""
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_ak import DEFAULT_SOURCES, fetch_pass, load_sources

AK_ID = "ak-2026-general"
URL = "https://www.elections.alaska.gov/enr/26GENR/results/GA_ENR_Precinct_State_of_Alaska.csv"


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        s = load_sources(DEFAULT_SOURCES)[AK_ID]
        self.assertEqual((s["state"], s["csv_url"], s["min_interval_s"]), ("AK", URL, 120))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.src = load_sources(DEFAULT_SOURCES)[AK_ID]

    def test_pass_record(self):
        seen = []
        rec = fetch_pass(AK_ID, self.src, raw_dir=self.raw, opener=lambda u: (seen.append(u), (200, b"x"))[1])
        self.assertEqual(seen, [URL])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["kind"] for x in r["files"]], ["csv"])
        self.assertTrue(r["files"][0]["path"].endswith(".csv"))

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(AK_ID, self.src, raw_dir=self.raw, opener=lambda u: (403, b"no"))
        self.assertFalse(os.path.exists(os.path.join(self.raw, AK_ID)))


if __name__ == "__main__":
    unittest.main()
