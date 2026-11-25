"""Clarity source list, the version-first fetch pass, and body reading."""
import csv
import glob
import gzip
import json
import os
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.clarity import COUNTY_TURNOUT_COLUMNS, TURNOUT_COLUMNS
from pipeline.run_clarity import DEFAULT_SOURCES, fetch_pass, load_sources, main, read_body, type_file_name
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
        county_json = {k: s for k, s in src.items() if s["format"] == "county_json"}
        self.assertEqual((len(statewide), len(county), len(county_json), len(src)), (4, 8, 7, 19))
        self.assertEqual({s["county"] for s in county_json.values()},
                         {"Cumberland", "Gloucester", "Middlesex", "Monmouth", "Morris", "Passaic", "Somerset"})
        self.assertEqual({s["state"] for s in statewide.values()}, {"CO", "IA", "SC", "WV"})
        self.assertEqual({s["state"] for s in county.values()}, {"NJ"})
        for sid, s in src.items():
            self.assertGreaterEqual(s["min_interval_s"], 120, sid)
            self.assertTrue(s["base"].startswith("https://"), sid)
            self.assertFalse(s["base"].endswith("/"), sid)
            allowed = {"IA": ("json",), "NJ": ("county_xml", "county_json")}.get(s["state"], ("xml",))
            self.assertIn(s["format"], allowed, sid)


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


def json_opener(record, types_body=b'{"Types": ["Early Voting", "State/Fed"], "Contests": []}'):
    def opener(url):
        record.append(url)
        if url.endswith("/current_ver.txt"):
            return 200, b"387114\r\n"
        if url.endswith("/vt.json"):
            return 200, types_body
        return 200, b'{"Contests": []}'
    return opener


class CountyJsonFetchTest(unittest.TestCase):
    def setUp(self):
        self.src = load_sources(DEFAULT_SOURCES)
        self.sid = "clarity-NJ-Morris-2026-general"
        self.s = self.src[self.sid]
        self.raw = tempfile.mkdtemp()

    def test_type_file_name_follows_site_rule(self):
        self.assertEqual(type_file_name("State/Fed"), "State_Fed.json")
        self.assertEqual(type_file_name("Early Voting"), "Early_Voting.json")
        self.assertEqual(type_file_name("Vote-by-Mail"), "Vote-by-Mail.json")

    def test_pass_order_and_record(self):
        seen = []
        out = fetch_pass(self.sid, self.s, raw_dir=self.raw, opener=json_opener(seen))
        j = self.s["base"] + "/387114/json/"
        self.assertEqual(seen, [self.s["base"] + "/current_ver.txt", j + "sum.json", j + "ALL.json", j + "vt.json",
                                j + "status.json", j + "Early_Voting.json", j + "State_Fed.json"])
        with open(out["record"]) as f:
            rec = json.load(f)
        self.assertEqual((rec["source_id"], rec["state"], rec["county"], rec["version"]),
                         (self.sid, "NJ", "Morris", "387114"))
        self.assertEqual([(x["kind"], x["vote_type"]) for x in rec["files"]],
                         [("sum", ""), ("all", ""), ("vt", ""), ("status", ""), ("type", "Early Voting"),
                          ("type", "State/Fed")])
        for x in rec["files"]:
            self.assertTrue(os.path.exists(x["path"]), x)

    def test_no_vote_types_no_type_requests(self):
        seen = []
        fetch_pass(self.sid, self.s, raw_dir=self.raw, opener=json_opener(seen, b'{"Types": [], "Contests": []}'))
        self.assertEqual(len(seen), 5)

    def test_unreadable_vt_stops_pass(self):
        for body in (b"<html>busy</html>", b'{"Contests": []}', b'{"Types": "Early Voting"}', b'{"Types": [""]}'):
            seen = []
            with self.assertRaises(FetchError, msg=body):
                fetch_pass(self.sid, self.s, raw_dir=tempfile.mkdtemp(), opener=json_opener(seen, body))
            self.assertEqual(len(seen), 4, body)


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

    def test_parse_command_county_json(self):
        out = tempfile.mkdtemp()
        main(["parse", "clarity-NJ-Cumberland-2026-general", os.path.join(FX, "nj_cumberland_pass.json"),
              "--base-dir", FX, "--parsed-dir", out])
        files = sorted(glob.glob(os.path.join(out, "clarity-NJ-Cumberland-2026-general", "*.csv")))
        (turnout,) = [f for f in files if f.endswith("-turnout.csv")]
        (rows,) = [f for f in files if not f.endswith("-turnout.csv")]
        self.assertEqual(header(rows), COLUMNS)
        self.assertEqual(header(turnout), COUNTY_TURNOUT_COLUMNS)
        with open(rows) as f:
            self.assertEqual(sum(1 for _ in f), 11083)

    def test_fetch_parse_county_json(self):
        raw, out = tempfile.mkdtemp(), tempfile.mkdtemp()
        import pipeline.run_clarity as rc
        real = rc.fetch_pass
        rc.fetch_pass = lambda sid, src, raw_dir: real(sid, src, raw_dir=raw_dir, opener=json_opener([]))
        try:
            main(["fetch-parse", "clarity-NJ-Morris-2026-general", "--raw-dir", raw, "--parsed-dir", out])
        finally:
            rc.fetch_pass = real
        self.assertEqual(len(glob.glob(os.path.join(out, "clarity-NJ-Morris-2026-general", "*.csv"))), 2)


if __name__ == "__main__":
    unittest.main()
