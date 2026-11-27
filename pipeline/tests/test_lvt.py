"""LiveVoterTurnout reader on fixtures cut from the 2026 general summary XML of Bergen and Salem counties, NJ.

Bergen: races 1-3 (U.S. Senate, House 5 and 9), 138 (Maywood Board of Education, off by one vote in the
ballot balance) and 150. Salem: races 1-3; the named write-ins after each "Write-In" line are replaced by
"WRITE-IN NAME n" (private individuals).
"""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.lvt import parse_pass

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8-sig") as f:
        return f.read()


def parse_text(test, text=None, county="Bergen", files=True):
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d)
    if text is not None:
        with open(os.path.join(d, "s.xml"), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(d, "pass.json"), "w") as f:
        json.dump({"source_id": "lvt-test", "state": "NJ", "county": county,
                   "files": [{"kind": "summary_xml", "path": "s.xml"}] if files else []}, f)
    return parse_pass(os.path.join(d, "pass.json"), base_dir=d)


def parse_fixture(test, name, county):
    return parse_text(test, raw(name), county)


class BergenTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.s = parse_fixture(self, "lvt_bergen_summary.xml", "Bergen")

    def test_total_row(self):
        (r,) = find(self.rows, contest_id="1", choice_id="2", vote_type="TOTAL")
        self.assertEqual((r["level"], r["state"], r["county_name"], r["contest_name"], r["choice"], r["party"],
                          r["votes"], r["vote_for"], r["contest_scope"], r["source_created_at"], r["source_id"]),
                         ("county", "NJ", "Bergen", "UNITED STATES SENATOR", "CORY BOOKER", "DEM", 193707, "1",
                          "local", "2026-11-18T11:13:38.434-05:00", "lvt-test"))
        self.assertEqual(len(r["source_sha256"]), 64)

    def test_vote_type_rows_keep_source_names(self):
        got = {r["vote_type"]: r["votes"] for r in find(self.rows, contest_id="1", choice_id="1")}
        self.assertEqual(got, {"EarlyVotingVotes": 19999, "VotebyMailBallotsVotes": 13061,
                               "ElectionDayVotes": 81002, "ProvisionalVotes": 1052, "TOTAL": 115114})

    def test_over_and_under_votes_are_contest_rows(self):
        (o,) = find(self.rows, contest_id="1", choice="OverVotes")
        (u,) = find(self.rows, contest_id="1", choice="UnderVotes")
        self.assertEqual((o["votes"], o["choice_id"], o["vote_type"], u["votes"]), (794, "", "TOTAL", 5529))

    def test_personal_choice_is_an_ordinary_choice(self):
        (r,) = find(self.rows, contest_id="1", choice="Personal Choice", vote_type="TOTAL")
        self.assertEqual(r["votes"], 317)

    def test_summary(self):
        s = self.s
        self.assertEqual((s["contests"], s["generated"], s["registered_voters"], s["ballots_cast"]),
                         (5, "2026-11-18T11:13:38.434-05:00", 678327, 323766))
        self.assertEqual(s["vote_types"], ["EarlyVotingVotes", "VotebyMailBallotsVotes", "ElectionDayVotes",
                                           "ProvisionalVotes"])
        self.assertEqual(s["ballot_balance_differences"], [("138", "MAYWOOD BOARD OF EDUCATION", 7160, 7159)])
        for k in ("vote_type_sum_mismatches", "race_fields_vary", "duplicate_choices", "non_numeric",
                  "write_in_breakdown_mismatches", "unknown_vote_fields", "nonzero_unused_fields",
                  "withdrawn", "unreadable_files", "missing_files"):
            self.assertEqual(s[k], [], k)
        self.assertEqual(s["write_in_names_dropped"], 0)


class SalemTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.s = parse_fixture(self, "lvt_salem_summary.xml", "Salem")

    def test_write_in_total_kept_names_dropped(self):
        self.assertEqual(find(self.rows, contest_id="1", choice="Write-In", vote_type="TOTAL")[0]["votes"], 25)
        self.assertEqual([r for r in self.rows if r["choice"].startswith("WRITE-IN NAME")], [])
        self.assertEqual(self.s["write_in_names_dropped"], 81)
        self.assertEqual(self.s["write_in_breakdown_mismatches"], [])

    def test_custom_votes_and_no_county_header(self):
        got = {r["vote_type"]: r["votes"] for r in find(self.rows, contest_id="1", choice_id="1")}
        self.assertEqual(got["CustomVotes"], 4)
        self.assertEqual((self.s["generated"], self.s["registered_voters"]), (None, None))
        self.assertEqual(find(self.rows, contest_id="1", choice_id="1")[0]["source_created_at"], "")

    def test_ballot_balance(self):
        self.assertEqual(self.s["ballot_balance_differences"],
                         [("3", "Salem County Commissioner- 3 Year Term", 21410, 21409)])


class SyntheticTest(unittest.TestCase):
    def test_vote_type_sum_mismatch_listed(self):
        text = raw("lvt_bergen_summary.xml").replace("<EarlyVotingVotes>19999<", "<EarlyVotingVotes>19998<", 1)
        rows, s = parse_text(self, text)
        self.assertEqual(s["vote_type_sum_mismatches"], [("1", "1", 115113, 115114)])
        self.assertEqual(find(rows, contest_id="1", choice_id="1", vote_type="EarlyVotingVotes")[0]["votes"], 19998)

    def test_write_in_breakdown_mismatch_listed(self):
        text = raw("lvt_salem_summary.xml").replace("<TotalVotes>25</TotalVotes>", "<TotalVotes>26</TotalVotes>", 1)
        _, s = parse_text(self, text, "Salem")
        self.assertEqual(s["write_in_breakdown_mismatches"], [("1", 26, 25)])

    def test_non_numeric_votes_empty_and_listed(self):
        text = raw("lvt_bergen_summary.xml").replace("<TotalVotes>115114<", "<TotalVotes>x<", 1)
        rows, s = parse_text(self, text)
        self.assertEqual(find(rows, contest_id="1", choice_id="1", vote_type="TOTAL")[0]["votes"], "")
        self.assertIn(("1", "1", "TotalVotes", "x"), s["non_numeric"])
        self.assertEqual(s["vote_type_sum_mismatches"], [])  # not computable for that choice

    def test_race_fields_vary_listed(self):
        text = raw("lvt_bergen_summary.xml").replace("<OverVotes>794<", "<OverVotes>795<", 1)
        _, s = parse_text(self, text)
        self.assertEqual(s["race_fields_vary"], [("1", "OverVotes", ["794", "795"])])

    def test_unknown_vote_field_and_nonzero_votes_listed(self):
        text = raw("lvt_bergen_summary.xml").replace("<Votes>0</Votes>", "<Votes>3</Votes><MysteryVotes>1</MysteryVotes>", 1)
        _, s = parse_text(self, text)
        self.assertEqual(s["unknown_vote_fields"], ["MysteryVotes"])
        self.assertEqual(s["nonzero_unused_fields"], [("1", "1", "Votes", "3")])

    def test_duplicate_choice_listed_first_kept(self):
        text = raw("lvt_bergen_summary.xml")
        i = text.index("<Table>")
        j = text.index("</Table>") + len("</Table>")
        rows, s = parse_text(self, text[:j] + text[i:j] + text[j:])
        self.assertEqual(s["duplicate_choices"], [("1", "1")])
        self.assertEqual(len(find(rows, contest_id="1", choice_id="1", vote_type="TOTAL")), 1)

    def test_unreadable_and_missing(self):
        rows, s = parse_text(self, "<NewDataSet><Table>")
        self.assertEqual((rows, s["contests"], s["vote_type_sum_mismatches"]), ([], None, None))
        self.assertEqual(len(s["unreadable_files"]), 1)
        rows, s = parse_text(self, files=False)
        self.assertEqual((rows, s["missing_files"]), ([], ["summary_xml"]))


class RunnerTest(unittest.TestCase):
    def test_fetch_pass_records_the_file(self):
        from pipeline import run_lvt

        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        src = {"state": "NJ", "county": "Bergen", "xml_url": "https://example.test/summary_20.xml",
               "min_interval_s": 120}
        rec = run_lvt.fetch_pass("lvt-x", src, raw_dir=d, opener=lambda url: (200, b"<NewDataSet/>"))
        with open(rec) as f:
            r = json.load(f)
        self.assertEqual((r["county"], [x["kind"] for x in r["files"]]), ("Bergen", ["summary_xml"]))
        self.assertTrue(r["files"][0]["path"].endswith(".xml"))


if __name__ == "__main__":
    unittest.main()
