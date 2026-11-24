"""Texas reader on fixtures cut from the 2026 general and 2025 amendment files (pipeline/make_tx_fixture.py)."""
import base64
import copy
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.tx import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
SENATE, GOV, REP5, REP19, HD8 = 5075, 3579, 5070, 5048, 4984
PAXTON, BROWN = "42424", "33528"


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def dec(v):
    return json.loads(base64.b64decode(v))


def enc(o):
    return base64.b64encode(json.dumps(o).encode("utf-8")).decode("ascii")


def load(prefix):
    with open(os.path.join(FX, prefix + "_election.json")) as f:
        el = json.load(f)
    with open(os.path.join(FX, prefix + "_county.json")) as f:
        cty = dec(json.load(f)["upload"])
    return {k: (v if k == "Version" else dec(v)) for k, v in el.items()}, cty


def parse_edited(test, election, county, election_raw=None, county_raw=None, files=("election", "county")):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    with open(os.path.join(d, "e.json"), "w") as f:
        if election_raw is not None:
            f.write(election_raw)
        else:
            json.dump({k: (v if k == "Version" else enc(v)) for k, v in election.items()}, f)
    with open(os.path.join(d, "c.json"), "w") as f:
        f.write(county_raw if county_raw is not None else json.dumps({"upload": enc(county)}))
    paths = {"election": "e.json", "county": "c.json"}
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "tx-test", "state": "TX", "files": [{"kind": k, "path": paths[k]} for k in files]}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "tx_pass.json"), base_dir=FX)

    def test_state_rows(self):
        tot, = find(self.rows, level="state", contest_id="5075", choice_id=PAXTON, vote_type="TOTAL")
        ev, = find(self.rows, level="state", contest_id="5075", choice_id=PAXTON, vote_type="Early Votes")
        self.assertEqual((tot["votes"], ev["votes"]), (4249373, 3232667))
        self.assertEqual((tot["choice"], tot["party"], tot["contest_type"], tot["contest_name"]),
                         ("KEN PAXTON", "REP", "FEDERAL OFFICES", "U. S. SENATOR "))
        self.assertEqual((tot["source_created_at"], tot["election_date"], tot["county_id"], tot["reporting_status"]),
                         ("Nov 04, 2026 22:48:37", "11032026", "", ""))

    def test_county_rows(self):
        tot, = find(self.rows, level="county", contest_id="5075", choice_id=PAXTON, county_id="48001", vote_type="TOTAL")
        ev, = find(self.rows, level="county", contest_id="5075", choice_id=PAXTON, county_id="48001",
                   vote_type="Early Votes")
        self.assertEqual((tot["votes"], ev["votes"]), (10930, 7529))
        self.assertEqual((tot["county_name"], tot["reporting_status"], tot["source_created_at"], tot["contest_type"]),
                         ("ANDERSON", "23/23 precincts", "", "FEDERAL OFFICES"))
        self.assertEqual(tot["election_date"], "11032026")

    def test_party_as_published_per_file(self):
        st, = find(self.rows, level="state", contest_id="5075", choice_id=BROWN, vote_type="TOTAL")
        co, = find(self.rows, level="county", contest_id="5075", choice_id=BROWN, county_id="48001", vote_type="TOTAL")
        self.assertEqual((st["party"], co["party"]), ("LIB", "L"))
        self.assertEqual([x for x in self.summary["party_differences"] if x[1] == BROWN], [(SENATE, BROWN, "LIB", "L")])

    def test_mismatches_listed(self):
        m = self.summary["mismatches_state_vs_county"]
        self.assertIn((SENATE, PAXTON, "TOTAL", 4249373, 31279), m)
        self.assertIn((SENATE, PAXTON, "Early Votes", 3232667, 22249), m)

    def test_no_mismatch_when_state_equals_county_sum(self):
        el, cty = load("tx")
        sums = {}
        for c in cty.values():
            for oid, r in c["Races"].items():
                for cand in r["C"].values():
                    s = sums.setdefault((int(oid), cand["id"]), [0, 0])
                    s[0] += cand["V"]
                    s[1] += cand["EV"]
        for sec in ("Federal", "StateWide", "Districted"):
            for r in el[sec]["Races"]:
                for cand in r["Candidates"]:
                    cand["V"], cand["EV"] = sums[(r["id"], cand["ID"])]
        rows, s, _ = parse_edited(self, el, cty)
        self.assertEqual(s["mismatches_state_vs_county"], [])

    def test_turnout(self):
        self.assertEqual(len(self.turnout), 3)
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        a, = [t for t in self.turnout if t["county_id"] == "48001"]
        self.assertEqual((a["county_name"], a["registered_voters"], a["voters"], a["precincts_reporting"],
                          a["polling_locations_reporting"], a["polling_locations_total"]),
                         ("ANDERSON", 31222, 15290, 23, 23, 23))

    def test_summary(self):
        s = self.summary
        self.assertIn(("PrecinctsReporting", 202, 200), s["home_reported_exceeds_total"])
        self.assertEqual((s["version"], s["last_updated"]), ("enr/53815/117/", "Nov 04, 2026 22:48:37"))
        self.assertEqual((s["contests"], s["counties"]), (5, 3))
        self.assertEqual(s["null_choice_ids"], 0)
        self.assertEqual(s["party_codes"]["W"], 8)
        for k in ("state_choices_missing_from_county", "county_choices_missing_from_state", "unknown_counties",
                  "early_exceeds_total", "non_numeric_votes", "duplicate_choices", "office_in_two_sections",
                  "unreadable_sections", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual({r["vote_type"] for r in self.rows}, {"TOTAL", "Early Votes"})
        self.assertEqual({r["contest_scope"] for r in self.rows}, {"statewide"})
        self.assertEqual({r["state"] for r in self.rows}, {"TX"})


class PropositionTest(unittest.TestCase):
    def test_propositions_join_by_name(self):
        rows, s, _ = parse_pass(os.path.join(FX, "tx2025_pass.json"), base_dir=FX)
        f, = find(rows, level="state", contest_id="87", choice="FOR", vote_type="TOTAL")
        a, = find(rows, level="state", contest_id="87", choice="AGAINST", vote_type="TOTAL")
        self.assertEqual((f["choice_id"], f["votes"], a["votes"]), ("", 2041859, 916217))
        self.assertEqual(f["contest_type"], "STATEWIDE PROPOSITIONS")
        self.assertEqual(f["party"], "")
        cf = find(rows, level="county", contest_id="87", choice="FOR", vote_type="TOTAL")
        self.assertEqual({r["choice_id"] for r in cf}, {"8701"})
        self.assertEqual((s["state_choices_missing_from_county"], s["county_choices_missing_from_state"]), ([], []))
        self.assertEqual(s["null_choice_ids"], 2)
        self.assertIn((87, "FOR", "TOTAL", 2041859, sum(r["votes"] for r in cf)), s["mismatches_state_vs_county"])


class SyntheticTest(unittest.TestCase):
    def setUp(self):
        self.el, self.cty = load("tx")

    def test_unreadable_county_file_not_checked(self):
        rows, s, t = parse_edited(self, self.el, None, county_raw="<!DOCTYPE html><html>Just a moment...</html>")
        self.assertEqual(len(s["unreadable_files"]), 1)
        self.assertEqual({r["level"] for r in rows}, {"state"})
        self.assertEqual(t, [])
        for k in ("mismatches_state_vs_county", "state_choices_missing_from_county",
                  "county_choices_missing_from_state", "party_differences", "home_vs_county_summary"):
            self.assertIsNone(s[k], k)

    def test_bad_section_listed(self):
        raw = {k: (v if k == "Version" else enc(v)) for k, v in self.el.items()}
        raw["StateWide"] = "not base64 json!"
        rows, s, _ = parse_edited(self, None, self.cty, election_raw=json.dumps(raw))
        self.assertEqual([x[0] for x in s["unreadable_sections"]], ["StateWide"])
        self.assertTrue(find(rows, level="state", contest_id="5075"))
        self.assertFalse(find(rows, level="state", contest_id="3579"))

    def test_unknown_county_listed(self):
        self.cty["999"] = copy.deepcopy(self.cty["2"])
        rows, s, t = parse_edited(self, self.el, self.cty)
        self.assertEqual(s["unknown_counties"], [("999", "ANDREWS")])
        r = find(rows, level="county", county_name="ANDREWS", contest_id="5075", choice_id=PAXTON, vote_type="TOTAL")
        self.assertEqual(sorted(x["county_id"] for x in r), ["", "48002"])

    def test_race_in_some_counties_not_listed(self):
        rows, s, _ = parse_edited(self, self.el, self.cty)
        self.assertNotIn(str(REP5), self.cty["2"]["Races"])
        self.assertEqual((s["state_choices_missing_from_county"], s["county_choices_missing_from_state"]), ([], []))

    def test_missing_choice_both_directions_listed(self):
        del self.cty["1"]["Races"][str(HD8)]
        self.cty["1"]["Races"][str(SENATE)]["C"]["77777"] = dict(self.cty["1"]["Races"][str(SENATE)]["C"][PAXTON],
                                                                  id=77777, N="NOBODY")
        rows, s, _ = parse_edited(self, self.el, self.cty)
        self.assertEqual(sorted(s["state_choices_missing_from_county"]), [(HD8, "39573"), (HD8, "41321")])
        self.assertEqual(s["county_choices_missing_from_state"], [(SENATE, "77777")])

    def test_early_exceeds_total_listed(self):
        self.cty["1"]["Races"][str(SENATE)]["C"][PAXTON]["EV"] = 99999
        rows, s, _ = parse_edited(self, self.el, self.cty)
        self.assertEqual(s["early_exceeds_total"], [("county", "48001", SENATE, PAXTON, 99999, 10930)])

    def test_non_numeric_votes_listed(self):
        self.cty["1"]["Races"][str(SENATE)]["C"][PAXTON]["V"] = "n/a"
        rows, s, _ = parse_edited(self, self.el, self.cty)
        self.assertEqual(s["non_numeric_votes"], [("county", "48001", SENATE, PAXTON, "TOTAL", "n/a")])
        r, = find(rows, level="county", county_id="48001", contest_id="5075", choice_id=PAXTON, vote_type="TOTAL")
        self.assertEqual(r["votes"], "")
        self.assertIn((SENATE, PAXTON, "TOTAL", 4249373, 2913 + 17436), s["mismatches_state_vs_county"])

    def test_duplicate_choice_listed(self):
        sen = [r for r in self.el["Federal"]["Races"] if r["id"] == SENATE][0]
        sen["Candidates"].append(dict(sen["Candidates"][0]))
        rows, s, _ = parse_edited(self, self.el, self.cty)
        self.assertEqual(s["duplicate_choices"], [("state", "", SENATE, str(sen["Candidates"][0]["ID"]))])

    def test_office_in_two_sections_listed(self):
        gov = [r for r in self.el["StateWide"]["Races"] if r["id"] == GOV][0]
        self.el["Districted"]["Races"].append(copy.deepcopy(gov))
        rows, s, _ = parse_edited(self, self.el, self.cty)
        self.assertEqual(s["office_in_two_sections"], [(GOV, ["StateWide", "Districted"])])

    def test_missing_file_listed(self):
        rows, s, t = parse_edited(self, self.el, self.cty, files=("election",))
        self.assertEqual(s["missing_files"], ["county"])
        self.assertIsNone(s["mismatches_state_vs_county"])


if __name__ == "__main__":
    unittest.main()
