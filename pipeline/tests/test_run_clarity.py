"""Clarity source list, the version-first fetch pass, and body reading."""
import csv
import glob
import gzip
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.clarity import TURNOUT_COLUMNS
from pipeline.run_clarity import DEFAULT_SOURCES, fetch_pass, load_sources, main, read_body
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def opener_for(version_body, record):
    def opener(url):
        record.append(url)
        if url.endswith("/current_ver.txt"):
            return 200, version_body
        return 200, b"PK\x03\x04 not really a zip"
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        statewide = {k: s for k, s in src.items() if s["format"] in ("xml", "json")}
        county = {k: s for k, s in src.items() if s["format"] == "county_xml"}
        self.assertEqual((len(statewide), len(county), len(src)), (4, 15, 19))
        self.assertEqual({s["state"] for s in statewide.values()}, {"CO", "IA", "SC", "WV"})
        self.assertEqual({s["state"] for s in county.values()}, {"NJ"})
        for sid, s in src.items():
            self.assertGreaterEqual(s["min_interval_s"], 120, sid)
            self.assertTrue(s["base"].startswith("https://"), sid)
            self.assertFalse(s["base"].endswith("/"), sid)
            self.assertEqual(s["format"], {"IA": "json", "NJ": "county_xml"}.get(s["state"], "xml"), sid)


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.src = load_sources(DEFAULT_SOURCES)
        self.raw = tempfile.mkdtemp()

    def test_xml_pass_reads_version_first(self):
        seen = []
        s = self.src["clarity-CO-2026-general"]
        out = fetch_pass("clarity-CO-2026-general", s, raw_dir=self.raw, opener=opener_for(b"387376\r\n", seen))
        self.assertEqual(seen, [s["base"] + "/current_ver.txt", s["base"] + "/387376/reports/detailxml.zip"])
        self.assertEqual(out["version"], "387376")
        self.assertTrue(os.path.exists(out["paths"]["xml"]))

    def test_json_pass_fetches_sum_and_all(self):
        seen = []
        s = self.src["clarity-IA-2026-general"]
        out = fetch_pass("clarity-IA-2026-general", s, raw_dir=self.raw, opener=opener_for(b"387368", seen))
        self.assertEqual(seen, [s["base"] + "/current_ver.txt", s["base"] + "/387368/json/sum.json",
                                s["base"] + "/387368/json/ALL.json"])
        self.assertEqual(set(out["paths"]), {"sum", "all"})

    def test_bad_version_stops_pass(self):
        seen = []
        s = self.src["clarity-WV-2026-general"]
        with self.assertRaises(FetchError):
            fetch_pass("clarity-WV-2026-general", s, raw_dir=self.raw, opener=opener_for(b"<html>oops</html>", seen))
        self.assertEqual(seen, [s["base"] + "/current_ver.txt"])


class ReadBodyTest(unittest.TestCase):
    def test_read_body_gunzips(self):
        d = tempfile.mkdtemp()
        gz, plain = os.path.join(d, "a.json"), os.path.join(d, "b.json")
        with open(gz, "wb") as f:
            f.write(gzip.compress(b'{"a":1}'))
        with open(plain, "wb") as f:
            f.write(b'{"a":1}')
        self.assertEqual(read_body(gz), b'{"a":1}')
        self.assertEqual(read_body(plain), b'{"a":1}')


def header(path):
    with open(path, newline="") as f:
        return next(csv.reader(f))


class ParseCommandTest(unittest.TestCase):
    def test_parse_command_xml(self):
        out = tempfile.mkdtemp()
        main(["parse", "clarity-CO-2026-general", os.path.join(FX, "clarity_co.zip"), "--parsed-dir", out])
        files = sorted(glob.glob(os.path.join(out, "clarity-CO-2026-general", "*.csv")))
        (turnout,) = [f for f in files if f.endswith("-turnout.csv")]
        (rows,) = [f for f in files if not f.endswith("-turnout.csv")]
        self.assertEqual(header(rows), COLUMNS)
        self.assertEqual(header(turnout), TURNOUT_COLUMNS)

    def test_parse_command_json(self):
        out = tempfile.mkdtemp()
        main(["parse", "clarity-IA-2026-general", os.path.join(FX, "clarity_ia_sum.json"),
              os.path.join(FX, "clarity_ia_all.json"), "--parsed-dir", out])
        (path,) = glob.glob(os.path.join(out, "clarity-IA-2026-general", "*.csv"))
        self.assertEqual(header(path), COLUMNS)


if __name__ == "__main__":
    unittest.main()
