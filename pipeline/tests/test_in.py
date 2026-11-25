"""Indiana reader on fixtures cut from the 2026 general files (pipeline/make_in_fixture.py)."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.in_ import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
CATS = ["1005", "1041", "1047", "1037", "1018", "1040"]
KINDS = ["settings", "elections"] + [f"offcat-{c}" for c in CATS] + ["turnout", "csv"]


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def fname(kind):
    return "in_csv.csv" if kind == "csv" else f"in_{kind}.json"


def raw(kind):
    with open(os.path.join(FX, fname(kind)), "rb") as f:
        return f.read().decode("utf-8")


def parse_texts(test, texts=None, kinds=KINDS):
    texts = texts or {}
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    for k in kinds:
        with open(os.path.join(d, fname(k)), "w", newline="") as f:
            f.write(texts.get(k, raw(k)))
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "in-test", "state": "IN", "version_type": "B", "categories": CATS,
                   "files": [{"kind": k, "path": fname(k)} for k in kinds]}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.turnout = parse_pass(os.path.join(FX, "in_pass.json"), base_dir=FX)

    def test_state_row(self):
        r, = find(self.rows, level="state", contest_id="2258", choice_id="5486")
        self.assertEqual((r["votes"], r["party"], r["contest_type"]), (1007815, "D", "Secretary of State"))
        self.assertEqual((r["election_name"], r["election_date"]), ("2026 General Election", "11/03/2026"))

    def test_county_rows(self):
        a, = find(self.rows, level="county", contest_id="2258", choice_id="2361", county_id="18001")
        self.assertEqual((a["votes"], a["county_name"]), (5188, "Adams"))
        l, = find(self.rows, level="county", contest_id="2258", choice_id="5486", county_id="18089")
        self.assertEqual(l["votes"], 92103)
        m, = find(self.rows, level="county", contest_id="4912", choice_id="4046", county_id="18089")
        self.assertEqual(m["votes"], 95679)

    def test_precinct_rows_joined(self):
        p = find(self.rows, level="precinct", contest_id="2258", choice_id="5486", county_id="18089")
        self.assertTrue(p)
        self.assertEqual(sum(r["votes"] for r in p), 92103)
        self.assertTrue(all(r["precinct_name"] for r in p))
        self.assertEqual({r["reporting_status"] for r in p}, {""})
        self.assertNotIn(len({r["party"] for r in p}), (0,))

    def test_summary(self):
        s = self.summary
        for k in ("precinct_vs_county_mismatches", "unmatched_precinct_rows", "county_lines_without_precincts",
                  "statewide_without_id", "duplicate_entries", "non_numeric", "counties_without_fips",
                  "malformed_entries", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)
        self.assertGreater(s["precinct_units"], 0)

    def test_turnout(self):
        for t in self.turnout:
            self.assertEqual(list(t), TURNOUT_COLUMNS)
        a, = [t for t in self.turnout if t["county_name"] == "Adams"]
        self.assertEqual((a["county_id"], a["registered_voters"]), ("18001", 19761))

    def test_every_row(self):
        for r in self.rows:
            self.assertEqual(list(r), COLUMNS)
        self.assertEqual({r["level"] for r in self.rows}, {"state", "county", "precinct"})


class SyntheticTest(unittest.TestCase):
    def test_unreadable_category(self):
        rows, s, _ = parse_texts(self, {"offcat-1041": "<html>no</html>"})
        self.assertIn("offcat-1041", [x[0] for x in s["unreadable_files"]])
        self.assertFalse(find(rows, level="county", contest_type="Secretary of State"))
        p = [r for r in rows if r["level"] == "precinct" and r["contest_name"].casefold() == "secretary of state"]
        self.assertTrue(p)
        self.assertEqual({r["contest_id"] for r in p}, {""})
        self.assertIsNone(s["precinct_vs_county_mismatches"])

    def test_csv_missing(self):
        rows, s, _ = parse_texts(self, kinds=[k for k in KINDS if k != "csv"])
        self.assertEqual(s["missing_files"], ["csv"])
        self.assertTrue(find(rows, level="county"))
        self.assertIsNone(s["precinct_vs_county_mismatches"])

    def test_county_name_case_joined(self):
        t = raw("csv").replace('"Lake"', '"LAKE"')
        rows, s, _ = parse_texts(self, {"csv": t})
        self.assertEqual(s["unmatched_precinct_rows"], [])
        self.assertEqual(s["precinct_vs_county_mismatches"], [])

    def test_uncovered_category_listed(self):
        el = json.loads(raw("elections"))
        el["Root"]["List"][0]["Items"]["Item"].append({"OFFICECATEGORYID": "1001", "OFFICE_CATEGORY_NAME": "US Senator"})
        rows, s, _ = parse_texts(self, {"elections": json.dumps(el)})
        self.assertEqual(s["uncovered_categories"], [("1001", "US Senator")])

    def test_precinct_mismatch_and_unmatched_listed(self):
        lines = raw("csv").split("\r\n")
        i = next(n for n, l in enumerate(lines) if '"Lake"' in l and '"Beau Bayh"' in l)
        f = lines[i].split('","')
        f[-1] = str(int(f[-1].rstrip('"')) + 1) + '"'
        lines[i] = '","'.join(f)
        j = next(n for n, l in enumerate(lines) if '"Adams"' in l and '"Max Engling"' in l)
        lines[j] = lines[j].replace('"Max Engling"', '"Nobody Here"')
        rows, s, _ = parse_texts(self, {"csv": "\r\n".join(lines)})
        self.assertEqual([m[:3] for m in s["precinct_vs_county_mismatches"] if m[0] == "2258" and m[2] == "5486"],
                         [("2258", "18089", "5486")])
        self.assertTrue(any("nobody here" in str(u).casefold() for u in s["unmatched_precinct_rows"]))

    def test_non_numeric_listed(self):
        lines = raw("csv").split("\r\n")
        i = next(n for n, l in enumerate(lines) if '"Adams"' in l and '"Beau Bayh"' in l)
        f = lines[i].split('","')
        f[-1] = 'n/a"'
        lines[i] = '","'.join(f)
        rows, s, _ = parse_texts(self, {"csv": "\r\n".join(lines)})
        self.assertEqual(len(s["non_numeric"]), 1)

    def test_turnout_total_mismatch_listed(self):
        t = json.loads(raw("turnout"))
        rows_ = t["root"]["CountyTurnout"]
        total = next(c for c in rows_ if c["County"] == "Total")
        for f in ("REGISTERED_VOTERS", "VotersVoting", "InPerson", "Absentee"):
            total[f] = sum(c[f] for c in rows_ if c["County"] != "Total")
        self.assertEqual(parse_texts(self, {"turnout": json.dumps(t)})[1]["turnout_total_mismatches"], [])
        total["REGISTERED_VOTERS"] += 1
        rows, s, _ = parse_texts(self, {"turnout": json.dumps(t)})
        self.assertEqual([m[0] for m in s["turnout_total_mismatches"]], ["REGISTERED_VOTERS"])


if __name__ == "__main__":
    unittest.main()
