"""Tally reader on fixtures cut from the real 2026 AR and ND downloads."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.tally import parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
SEN = "eafd140a-9378-43a2-bd6d-f8661524139b"
COTTON = "342d2707-ef1d-46e0-a6a5-a90c0ac9ac6d"
ND_HOUSE = "22055"


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def run(st):
    return parse_pass(os.path.join(FX, f"tally_{st}_pass.json"), base_dir=FX)


def variant(st, name, edit):
    """Copy a state's fixtures to a temp dir, apply edit(data) to one JSON file, parse."""
    d = tempfile.mkdtemp()
    for n in os.listdir(FX):
        if n.startswith(f"tally_{st}_"):
            shutil.copy(os.path.join(FX, n), d)
    p = os.path.join(d, name)
    with open(p) as f:
        data = json.load(f)
    edit(data)
    with open(p, "w") as f:
        json.dump(data, f)
    return parse_pass(os.path.join(d, f"tally_{st}_pass.json"), base_dir=d)


def senate(data):
    return data["response"]["contests"][SEN]


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {st: run(st) for st in ("ar", "nd")}

    def test_columns(self):
        for st, (rows, _) in self.res.items():
            self.assertTrue(rows, st)
            for r in rows:
                self.assertEqual(list(r), COLUMNS, st)

    def test_ar_values(self):
        rows, s = self.res["ar"]
        (r,) = find(rows, level="state", contest_id=SEN, choice_id=COTTON)
        self.assertEqual((r["choice"], r["party"], r["votes"], r["vote_type"], r["contest_name"]),
                         ("REP Tom Cotton", "Republican", 481495, "TOTAL", "U.S. Senate"))
        (r,) = find(rows, level="county", contest_id=SEN, choice_id=COTTON, county_id="05001")
        self.assertEqual((r["county_name"], r["votes"], r["reporting_status"]), ("Arkansas", 2506, "30/30 precincts"))
        self.assertEqual(r["election_date"], "2026-11-03")
        self.assertEqual(r["election_name"], "2026 General Election & Judical Runoff")
        self.assertTrue(r["source_created_at"].startswith("2026-11-23T"))
        self.assertEqual(r["contest_scope"], "statewide")

    def test_nd_house(self):
        rows, s = self.res["nd"]
        self.assertEqual(len({r["county_id"] for r in find(rows, level="county", contest_id=ND_HOUSE)}), 53)
        self.assertTrue(find(rows, level="state", contest_id=ND_HOUSE))

    def test_no_anomalies_on_real_fixtures(self):
        for st, (_, s) in self.res.items():
            self.assertEqual(len(s["version_ids"]), 1, st)
            self.assertTrue(all(s["is_official"].values()), st)
            for k in ("election_id_mismatches", "errors", "contests_missing_from_list", "choices_missing_from_list",
                      "unknown_party_ids", "unknown_location_ids", "mismatches_counties_vs_state", "write_ins",
                      "non_numeric_votes"):
                self.assertEqual(s[k], [], (st, k))


class AnomalyTest(unittest.TestCase):
    def test_version_mismatch_listed(self):
        _, s = variant("ar", "tally_ar_results_Statewide.json", lambda d: d.update(versionID="v999"))
        self.assertEqual(len(s["version_ids"]), 2)
        self.assertIn("v999", s["version_ids"])

    def test_election_id_mismatch_listed(self):
        _, s = variant("nd", "tally_nd_results_SW.json", lambda d: d.update(electionID="349"))
        self.assertEqual(s["election_id_mismatches"], [("results-SW", "349")])

    def test_error_message_listed(self):
        _, s = variant("nd", "tally_nd_list.json", lambda d: d.update(errorMessage="boom"))
        self.assertEqual(s["errors"], [("list", "boom")])

    def test_missing_names_listed(self):
        rows, s = variant("ar", "tally_ar_list.json", lambda d: d["response"]["contests"].pop(SEN))
        self.assertEqual(s["contests_missing_from_list"], [SEN])
        self.assertTrue(find(rows, contest_id=SEN))
        self.assertEqual({r["contest_name"] for r in find(rows, contest_id=SEN)}, {""})
        rows, s = variant("ar", "tally_ar_list.json", lambda d: senate(d)["choices"].pop(COTTON))
        self.assertEqual(s["choices_missing_from_list"], [(SEN, COTTON)])
        self.assertEqual({r["choice"] for r in find(rows, choice_id=COTTON)}, {""})

    def test_unknown_ids_listed(self):
        _, s = variant("ar", "tally_ar_info.json", lambda d: d["response"]["locations"].pop("05001"))
        self.assertIn((SEN, "05001"), s["unknown_location_ids"])

        def drop_rep(d):
            d["response"]["parties"].pop("4c1a540e-cfe4-4ba0-8435-1dd7c3eeb1e6")
        rows, s = variant("ar", "tally_ar_info.json", drop_rep)
        self.assertIn((SEN, COTTON, "4c1a540e-cfe4-4ba0-8435-1dd7c3eeb1e6"), s["unknown_party_ids"])
        (r,) = find(rows, level="state", choice_id=COTTON)
        self.assertEqual(r["party"], "")

    def test_blank_party_id_is_no_party(self):
        def blank(d):
            for ch in senate(d)["choices"]:
                ch["partyID"] = "   "
        rows, s = variant("ar", "tally_ar_results_Federal.json", blank)
        self.assertEqual(s["unknown_party_ids"], [])
        self.assertEqual({r["party"] for r in find(rows, level="state", contest_id=SEN)}, {""})

    def test_write_ins_listed(self):
        entry = {"choiceID": "w1", "totalVotes": 7}
        rows, s = variant("ar", "tally_ar_results_Federal.json", lambda d: senate(d)["writeInChoices"].append(entry))
        self.assertEqual(s["write_ins"], [(SEN, "", entry)])
        self.assertFalse(find(rows, choice_id="w1"))

        def county_write_in(d):
            senate(d)["locations"]["05001"]["writeinChoices"] = [entry]
        _, s = variant("ar", "tally_ar_results_Federal.json", county_write_in)
        self.assertEqual(s["write_ins"], [(SEN, "05001", entry)])

    def test_non_numeric_votes(self):
        def star(d):
            senate(d)["locations"]["05001"]["choices"][0]["totalVotes"] = "*"
        rows, s = variant("ar", "tally_ar_results_Federal.json", star)
        cand = [r for r in find(rows, level="county", contest_id=SEN, county_id="05001") if r["votes"] == ""]
        self.assertEqual(len(cand), 1)
        self.assertEqual(len(s["non_numeric_votes"]), 1)
        self.assertEqual(len(s["mismatches_counties_vs_state"]), 1)

    def test_county_sum_mismatch(self):
        def bump(d):
            senate(d)["locations"]["05001"]["choices"][0]["totalVotes"] += 1
        _, s = variant("ar", "tally_ar_results_Federal.json", bump)
        (m,) = s["mismatches_counties_vs_state"]
        self.assertEqual((m[0], m[3] - m[2]), (SEN, 1))


if __name__ == "__main__":
    unittest.main()
