"""Clarity source list, the version-first fetch pass, and body reading."""
import gzip
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.run_clarity import DEFAULT_SOURCES, fetch_pass, load_sources, read_body


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
        self.assertEqual(len(src), 4)
        self.assertEqual({s["state"] for s in src.values()}, {"CO", "IA", "SC", "WV"})
        for sid, s in src.items():
            self.assertGreaterEqual(s["min_interval_s"], 120, sid)
            self.assertTrue(s["base"].startswith("https://"), sid)
            self.assertFalse(s["base"].endswith("/"), sid)
            self.assertEqual(s["format"], "json" if s["state"] == "IA" else "xml", sid)


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


if __name__ == "__main__":
    unittest.main()
