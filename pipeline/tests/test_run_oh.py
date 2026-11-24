"""OH source list and the fetch pass (fake opener; no network)."""
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_oh import fetch_pass, load_sources

OH_ID = "oh-2026-general"
XML_URL = "https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob"


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources()[OH_ID]
        self.assertEqual(src["state"], "OH")
        self.assertEqual(src["xml_url"], XML_URL)
        self.assertEqual(src["min_interval_s"], 120)


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.src = load_sources()[OH_ID]

    def test_pass_record(self):
        seen = []

        def opener(url):
            seen.append(url)
            return 200, b"<x/>"
        rec_path = fetch_pass(OH_ID, self.src, raw_dir=self.raw, opener=opener)
        self.assertEqual(seen, [XML_URL])
        with open(rec_path) as f:
            rec = json.load(f)
        self.assertEqual(rec["source_id"], OH_ID)
        self.assertEqual(rec["state"], "OH")
        self.assertEqual([x["kind"] for x in rec["files"]], ["xml"])
        path = rec["files"][0]["path"]
        self.assertTrue(path.endswith(".xml"))
        self.assertIn(os.sep + f"{OH_ID}-xml" + os.sep, path)

    def test_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            fetch_pass(OH_ID, self.src, raw_dir=self.raw, opener=lambda url: (403, b"blocked"))
        self.assertFalse(os.path.exists(os.path.join(self.raw, OH_ID)))


if __name__ == "__main__":
    unittest.main()
