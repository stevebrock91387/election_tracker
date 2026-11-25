"""IN source list and the fetch pass (fake opener and sleep; no network)."""
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_in import DEFAULT_SOURCES, fetch_pass, load_sources

IN_ID = "in-2026-general"
BASE = "https://enr.indianavoters.in.gov/site/"
CATS = ["1005", "1041", "1047", "1037", "1018", "1040"]


def opener_for(record, settings=b'{"Root": {"VersionType": "B", "VersionCode": "20261119_100058"}}', fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 403, b"no"
        return 200, settings if url.endswith("settings.json") else b"{}"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(list(src), [IN_ID])
        s = src[IN_ID]
        self.assertEqual((s["state"], s["base_url"], s["categories"]), ("IN", BASE, CATS))
        self.assertEqual((s["min_interval_s"], s["request_gap_s"]), (120, 10))


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []
        self.src = load_sources(DEFAULT_SOURCES)[IN_ID]

    def run_pass(self, opener):
        return fetch_pass(IN_ID, self.src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def no_record(self):
        d = os.path.join(self.raw, IN_ID)
        return not (os.path.isdir(d) and [p for p in os.listdir(d) if p.startswith("pass-")])

    def test_pass_urls_in_order(self):
        seen = []
        rec = self.run_pass(opener_for(seen))
        self.assertEqual(seen, [BASE + "data/settings.json", BASE + "data/statewideElectionsC_B.json"] +
                         [f"{BASE}data/OffCatC_{c}_B.json" for c in CATS] +
                         [BASE + "data/statewideTurnout_B.json", BASE + "download/AllOfficeResults.csv"])
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["version_type"], r["version_code"]), ("B", "20261119_100058"))
        self.assertEqual([x["kind"] for x in r["files"]],
                         ["settings", "elections"] + [f"offcat-{c}" for c in CATS] + ["turnout", "csv"])
        self.assertTrue(r["files"][-1]["path"].endswith(".csv"))
        self.assertEqual(self.slept, [10] * 9)

    def test_bad_version_stops_pass(self):
        with self.assertRaises(ValueError):
            self.run_pass(opener_for([], settings=b'{"Root": {"VersionType": "../x"}}'))
        self.assertTrue(self.no_record())

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(opener_for([], fail=("OffCatC_1018",)))
        self.assertTrue(self.no_record())


if __name__ == "__main__":
    unittest.main()
