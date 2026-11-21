"""ResultsAjax source list and the fetch pass (fake opener and sleep; no network)."""
import json
import tempfile
import unittest

from pipeline.fetch import FetchError
from pipeline.readers.resultsajax import parse_page
from pipeline.run_resultsajax import DEFAULT_SOURCES, fetch_pass, load_sources

NM_ID = "resultsajax-NM-2026-general"
PAGE = (b"<input onclick=\"BuildCounty('FED', '11185', '180', '');\" />"
        b"<input onclick=\"BuildCounty('FED', '11185', '180', '');\" />"
        b"<input onclick=\"BuildCounty('FED', '11186', '190', '');\" />")


def nm_src(**kw):
    s = dict(load_sources(DEFAULT_SOURCES)[NM_ID])
    s.update(page_types=["FED"], media_types=["FED"])
    s.update(kw)
    return s


def opener_for(pages, record, fail=()):
    def opener(url):
        record.append(url)
        if any(f in url for f in fail):
            return 500, b"error"
        if "ResultsSW.aspx" in url:
            return 200, pages.get(url.split("type=")[1].split("&")[0], b"")
        if "resultsCSV.aspx" in url:
            return 200, b"RaceID,CandidateID\n"
        return 200, b'{"d": []}'
    return opener


class SourcesTest(unittest.TestCase):
    def test_sources_complete(self):
        src = load_sources(DEFAULT_SOURCES)
        self.assertEqual(len(src), 5)
        self.assertEqual({s["state"] for s in src.values()}, {"MT", "NE", "NM", "OR", "SD"})
        for sid, s in src.items():
            self.assertGreaterEqual(s["min_interval_s"], 120, sid)
            self.assertEqual(s["request_gap_s"], 10, sid)
            self.assertTrue(s["site"].endswith("/") and s["service_root"].endswith("/"), sid)


class ParsePageTest(unittest.TestCase):
    def test_parse_page(self):
        self.assertEqual(parse_page(PAGE.decode()), [("FED", "11185", "180", ""), ("FED", "11186", "190", "")])


class FetchPassTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()
        self.slept = []

    def run_pass(self, src, opener):
        return fetch_pass(NM_ID, src, raw_dir=self.raw, opener=opener, sleep=self.slept.append)

    def test_pass_order_and_urls(self):
        seen = []
        rec = self.run_pass(nm_src(), opener_for({"FED": PAGE}, seen))
        self.assertEqual(seen[0], "https://electionresults.sos.nm.gov/ResultsSW.aspx?type=FED&map=CTY")
        self.assertEqual(seen[1], "https://electionresults.sos.nm.gov/resultsCSV.aspx?text=All&type=FED&map=CTY")
        self.assertEqual(seen[2], "https://nmresultswebservice.azurewebsites.us/NMResultsAjax.svc/GetMapData"
                                  "?type=FED&category=CTY&raceID=11185&osn=180&county=0&party=0")
        self.assertTrue(seen[3].endswith("raceID=11186&osn=190&county=0&party=0"))
        self.assertEqual(len(seen), 4)
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([(x["kind"], x["race_id"]) for x in r["files"]],
                         [("page", ""), ("media", ""), ("race", "11185"), ("race", "11186")])
        self.assertEqual(r["failed_races"], [])

    def test_gap_between_requests(self):
        self.run_pass(nm_src(), opener_for({"FED": PAGE}, []))
        self.assertEqual(self.slept, [10, 10, 10])

    def test_duplicate_race_fetched_once(self):
        seen = []
        self.run_pass(nm_src(page_types=["FED", "SW"], media_types=[]),
                      opener_for({"FED": PAGE, "SW": b"BuildCounty('SW', '11185', '180', '')"}, seen))
        self.assertEqual(sum("raceID=11185" in u for u in seen), 1)

    def test_failed_race_continues(self):
        rec = self.run_pass(nm_src(), opener_for({"FED": PAGE}, [], fail=("raceID=11185",)))
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual([x["race_id"] for x in r["failed_races"]], ["11185"])
        self.assertIn("11186", [x["race_id"] for x in r["files"]])

    def test_page_failure_stops_pass(self):
        with self.assertRaises(FetchError):
            self.run_pass(nm_src(), opener_for({"FED": PAGE}, [], fail=("ResultsSW.aspx",)))


if __name__ == "__main__":
    unittest.main()
