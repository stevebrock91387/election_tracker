"""Connecticut reader on fixtures cut from the 2026 general files (pipeline/make_ct_fixture.py)."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.ct import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
KINDS = ["version", "lookup", "state", "town", "townstatus", "turnout", "grouping", "officeprecincts"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def load():
    out = {}
    for k in KINDS:
        with open(os.path.join(FX, f"ct_{k}.json")) as f:
            out[k] = json.load(f)
    return out


def parse_data(test, data, raw=None, kinds=KINDS):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    for k in kinds:
        with open(os.path.join(d, f"{k}.json"), "w") as f:
            if raw and k in raw:
                f.write(raw[k])
            else:
                json.dump(data[k], f)
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "ct-test", "state": "CT", "version": 56593, "office_types": ["SW", "C", "S", "A", "PD"],
                   "files": [{"kind": k, "path": f"{k}.json"} for k in kinds]}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "ct_pass.json"), base_dir=FX)

    def test_state_rows_party_lines(self):
        d, = find(self.rows, level="state", contest_id="19663", choice_id="44186")
        wf, = find(self.rows, level="state", contest_id="19663", choice_id="44299")
        self.assertEqual((d["votes"], d["party"], wf["votes"], wf["party"]), (742437, "D", 29820, "WF"))
        self.assertEqual(d["choice"], wf["choice"])
        self.assertEqual((d["election_date"], d["election_name"], d["contest_type"]),
                         ("11/03/2026", "2026 General Election", "SW"))

    def test_town_rows(self):
        r, = find(self.rows, level="town", contest_id="19666", choice_id="44188", county_id="64")
        self.assertEqual((r["votes"], r["county_name"], r["reporting_status"], r["contest_type"]),
                         (16135, "Hartford", "24 of 24 (100.00%)", "C"))
        self.assertEqual(r["choice"], "Luke Bronin")

    def test_out_of_scope_office_dropped(self):
        self.assertEqual(find(self.rows, contest_id="20014"), [])

    def test_unknown_party_listed(self):
        self.assertIn(("44432", "1060"), self.summary["unknown_parties"])
        r = find(self.rows, choice_id="44432")
        self.assertTrue(r)
        self.assertEqual({x["party"] for x in r}, {""})

    def test_multi_line_without_grouping(self):
        self.assertIn(("19898", "Matt Jalowiec"), self.summary["multi_line_names_without_grouping"])

    def test_turnout(self):
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        self.assertNotIn("Total", [t["county_name"] for t in self.turnout])
        h, = [t for t in self.turnout if t["county_id"] == "64"]
        self.assertEqual((h["registered_voters"], h["ballots"], h["precincts_reporting"], h["county"], h["abc"]),
                         (67292, 19447, "25 of 24 (104.17%)", "Hartford", 1319))

    def test_summary(self):
        s = self.summary
        self.assertEqual((s["version"], s["contests"], s["towns"]), (56593, 6, 6))
        self.assertIn(("19663", "44186", 742437), [m[:3] for m in s["mismatches_state_vs_town"]])
        for k in ("grouping_mismatches", "non_numeric_votes", "duplicate_lines",
                  "unknown_towns", "unknown_offices", "unknown_candidates", "unknown_office_types",
                  "in_scope_offices_without_state_entry", "unreadable_files", "missing_files",
                  "parties_without_code", "malformed_entries"):
            self.assertEqual(s[k], [], k)

    def test_every_row_and_no_addresses(self):
        self.assertTrue(self.rows)
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual({r["level"] for r in self.rows}, {"state", "town"})
        self.assertEqual({r["vote_type"] for r in self.rows}, {"TOTAL"})
        with open(os.path.join(FX, "ct_lookup.json")) as f:
            lk = json.load(f)
        self.assertFalse(any("AD" in c for c in lk["candidateIds"].values()))
        self.assertNotIn("Street", json.dumps([self.rows, self.summary, self.turnout]))


class SyntheticTest(unittest.TestCase):
    def setUp(self):
        self.d = load()

    def test_unreadable_town_file_not_checked(self):
        rows, s, _ = parse_data(self, self.d, raw={"town": "<!DOCTYPE html><html>blocked</html>"})
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["town"])
        self.assertEqual({r["level"] for r in rows}, {"state"})
        for k in ("mismatches_state_vs_town", "state_lines_missing_from_towns", "town_lines_missing_from_state"):
            self.assertIsNone(s[k], k)

    def test_unreadable_lookup_not_checked(self):
        rows, s, t = parse_data(self, self.d, raw={"lookup": '{"election": '})
        self.assertEqual(rows, [])
        self.assertIsNone(s["mismatches_state_vs_town"])
        self.assertIsNone(s["unknown_parties"])

    def test_unknown_town_listed(self):
        self.d["town"]["999"] = copy.deepcopy(self.d["town"]["1"])
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(s["unknown_towns"], ["999"])
        self.assertTrue(find(rows, level="town", county_id="999"))

    def test_turnout_total_row_checked(self):
        rows, s, _ = parse_data(self, self.d)
        self.assertTrue(s["turnout_total_mismatches"])
        total = next(k for k, v in self.d["turnout"].items() if v["NM"] == "Total")
        for f in ("EV", "VV", "ABR", "ABC", "EBR", "EBC", "EDR", "EDC"):
            self.d["turnout"][total][f] = str(sum(int(v[f]) for k, v in self.d["turnout"].items() if k != total))
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(s["turnout_total_mismatches"], [])

    def test_mismatch_listed(self):
        self.d["town"]["64"]["19666"][0]["44188"]["V"] = "16136"
        rows, s, _ = parse_data(self, self.d)
        self.assertIn(("19666", "44188", 170477), [m[:3] for m in s["mismatches_state_vs_town"]])

    def test_missing_lines_both_directions_listed(self):
        self.d["state"]["19826"] = [e for e in self.d["state"]["19826"] if "99999" not in e]
        self.d["town"]["64"]["19826"].append({"99999": {"V": "5", "TO": "0%"}})
        gone = next(iter(self.d["state"]["19663"].pop(0)))
        rows, s, _ = parse_data(self, self.d)
        self.assertIn(("19826", "99999"), s["town_lines_missing_from_state"])
        self.assertNotIn(("19663", gone), s["state_lines_missing_from_towns"])
        self.assertIn(("19663", gone), s["town_lines_missing_from_state"])

    def test_grouping_mismatch_listed(self):
        self.d["grouping"]["19663"][0]["44186"]["V"] = "1"
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual([g[:2] for g in s["grouping_mismatches"]], [("19663", "Ned Lamont and Susan Bysiewicz")])

    def test_non_numeric_votes_listed(self):
        self.d["town"]["64"]["19666"][0]["44188"]["V"] = "1,613"
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(s["non_numeric_votes"], [("town", "64", "19666", "44188", "1,613")])
        r, = find(rows, level="town", county_id="64", contest_id="19666", choice_id="44188")
        self.assertEqual(r["votes"], "")

    def test_duplicate_line_listed(self):
        self.d["state"]["19666"].append(copy.deepcopy(self.d["state"]["19666"][0]))
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(s["duplicate_lines"], [("state", "", "19666", "44188")])

    def test_unknown_office_type_listed(self):
        self.d["lookup"]["officeList"][0]["19663"]["OT"] = "XX"
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(s["unknown_office_types"], [("19663", "XX")])
        self.assertEqual(find(rows, contest_id="19663"), [])

    def test_offices_without_precinct_status_listed(self):
        oid = next(iter(self.d["officeprecincts"]))
        del self.d["officeprecincts"][oid]
        rows, s, _ = parse_data(self, self.d)
        self.assertIn(oid, s["offices_without_precinct_status"])

    def test_party_without_code_listed(self):
        self.d["lookup"]["partyIds"]["1"] = None
        rows, s, _ = parse_data(self, self.d)
        self.assertEqual(s["parties_without_code"], ["1"])

    def test_lookup_wrong_shape_unreadable(self):
        rows, s, _ = parse_data(self, self.d, raw={"lookup": '{"Message": "An error has occurred."}'})
        self.assertEqual(rows, [])
        self.assertEqual([x[0] for x in s["unreadable_files"]], ["lookup"])
        self.assertIsNone(s["mismatches_state_vs_town"])

    def test_non_numeric_grouping_listed(self):
        self.d["grouping"]["19663"][0]["44186"]["V"] = "n/a"
        rows, s, _ = parse_data(self, self.d)
        self.assertIn(("grouping", "", "19663", "44186", "n/a"), s["non_numeric_votes"])

    def test_malformed_entries_listed_not_fatal(self):
        oid = next(iter(self.d["officeprecincts"]))
        self.d["officeprecincts"][oid] = None
        self.d["townstatus"]["64"] = "oops"
        self.d["lookup"]["officeList"].append({"77777": None})
        self.d["state"]["19826"] = {"not": "a list"}
        rows, s, _ = parse_data(self, self.d)
        self.assertTrue(find(rows, level="town", county_id="64"))
        self.assertEqual(find(rows, level="town", county_id="64")[0]["reporting_status"], "")
        kinds = {m[0] for m in s["malformed_entries"]}
        self.assertEqual(kinds, {"officeprecincts", "townstatus", "lookup.officeList", "state"})

    def test_addresses_never_copied(self):
        for c in self.d["lookup"]["candidateIds"].values():
            c["AD"] = "MARKER-ADDRESS 1 Main Street"
        rows, s, t = parse_data(self, self.d)
        self.assertNotIn("MARKER-ADDRESS", json.dumps([rows, s, t]))

    def test_missing_file_listed(self):
        rows, s, _ = parse_data(self, self.d, kinds=[k for k in KINDS if k != "grouping"])
        self.assertEqual(s["missing_files"], ["grouping"])
        self.assertIsNone(s["grouping_mismatches"])


if __name__ == "__main__":
    unittest.main()
