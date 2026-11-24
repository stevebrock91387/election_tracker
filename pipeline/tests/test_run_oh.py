"""OH source list and the fetch pass (fake opener; no network)."""
import contextlib
import csv
import glob
import io
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.oh import TURNOUT_COLUMNS
from pipeline.run_oh import fetch_pass, load_sources, main
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")

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


class ParseCommandTest(unittest.TestCase):
    def test_parse_command(self):
        out = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", OH_ID, os.path.join(FX, "oh_pass.json"), "--base-dir", FX, "--parsed-dir", out])
        (results,) = glob.glob(os.path.join(out, OH_ID, "*Z.csv"))
        (turnout,) = glob.glob(os.path.join(out, OH_ID, "*-turnout.csv"))
        self.assertEqual(turnout, results[:-4] + "-turnout.csv")
        with open(results, newline="") as f:
            self.assertEqual(next(csv.reader(f)), COLUMNS)
        with open(turnout, newline="") as f:
            r = csv.reader(f)
            self.assertEqual(next(r), TURNOUT_COLUMNS)
            self.assertEqual(sum(1 for _ in r), 88)
        text = buf.getvalue()
        self.assertIn("unreferenced_county_units: 88", text)
        self.assertIn("absentee_exceeds_total: 88", text)
        self.assertIn("election_status: UnofficialComplete", text)

    def test_parse_prints_not_checked(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "pass.json")
        with open(rec, "w") as f:
            json.dump({"source_id": OH_ID, "state": "OH", "files": []}, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["parse", OH_ID, rec, "--parsed-dir", d])
        self.assertIn("bad_sums: not checked", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
