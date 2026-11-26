"""Step 3 checks on the results database."""
import os
import tempfile
import unittest

from pipeline import db, db_checks
from pipeline.tests.test_db_load import row, write_manifest, write_parse


class CheckTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.parsed = os.path.join(self.tmp, "parsed")
        self.manifest = os.path.join(self.tmp, "manifest.csv")
        self.conn = db.connect(os.path.join(self.tmp, "r.sqlite"))
        self.entries = []

    def snap(self, source_id, day, rows, turnout=None):
        """One snapshot of source_id first seen on 2026-11-<day>; rows are row() dicts."""
        sha = f"{source_id}-{day}"
        self.entries.append((sha, f"2026-11-{day:02d}T00:00:00Z"))
        write_manifest(self.manifest, self.entries)
        write_parse(self.parsed, source_id, f"202611{day:02d}T000100Z",
                    [dict(r, source_sha256=sha) for r in rows], turnout)
        db.load(self.conn, self.parsed, self.manifest)


class DecreasesTest(CheckTestBase):
    def test_decrease_listed(self):
        self.snap("s1", 1, [row(votes="100")])
        self.snap("s1", 2, [row(votes="99")])
        exc, nc = db_checks.check_decreases(self.conn)
        self.assertEqual(len(exc), 1)
        self.assertEqual((exc[0]["kind"], exc[0]["old_votes"], exc[0]["new_votes"]), ("decrease", 100, 99))
        self.assertEqual(nc, [])

    def test_increase_not_listed(self):
        self.snap("s1", 1, [row(votes="100")])
        self.snap("s1", 2, [row(votes="101")])
        self.assertEqual(db_checks.check_decreases(self.conn), ([], []))

    def test_disappeared_row_listed(self):
        self.snap("s1", 1, [row(votes="100"), row(choice_id="11", votes="5")])
        self.snap("s1", 2, [row(votes="100")])
        exc, _ = db_checks.check_decreases(self.conn)
        self.assertEqual([(e["kind"], e["choice"], e["old_votes"], e["new_votes"]) for e in exc],
                         [("disappeared", "11", 5, None)])

    def test_null_on_either_side_skipped(self):
        self.snap("s1", 1, [row(votes="100"), row(choice_id="11", votes="")])
        self.snap("s1", 2, [row(votes=""), row(choice_id="11", votes="5")])
        self.assertEqual(db_checks.check_decreases(self.conn), ([], []))

    def test_one_snapshot_not_checked(self):
        self.snap("s1", 1, [row()])
        self.assertEqual(db_checks.check_decreases(self.conn),
                         ([], [{"source_id": "s1", "scope": "source", "reason": "one snapshot"}]))

    def test_names_used_where_ids_empty(self):
        self.snap("s1", 1, [row(choice_id="", choice="Alice", votes="10"), row(choice_id="", choice="Bob", votes="9")])
        self.snap("s1", 2, [row(choice_id="", choice="Alice", votes="10"), row(choice_id="", choice="Bob", votes="8")])
        exc, _ = db_checks.check_decreases(self.conn)
        self.assertEqual([(e["choice"], e["new_votes"]) for e in exc], [("Bob", 8)])

    def test_duplicate_key_listed_not_compared(self):
        self.snap("s1", 1, [row(votes="10"), row(votes="3")])
        self.snap("s1", 2, [row(votes="1")])
        exc, _ = db_checks.check_decreases(self.conn)
        self.assertEqual([e["kind"] for e in exc], ["duplicate_key"])

    def test_source_filter(self):
        self.snap("s1", 1, [row(votes="100")])
        self.snap("s1", 2, [row(votes="99")])
        self.snap("s2", 3, [row()])
        exc, nc = db_checks.check_decreases(self.conn, source_id="s2")
        self.assertEqual((exc, [n["source_id"] for n in nc]), ([], ["s2"]))



def st(v, **kw):
    return row(level="state", county_name="", votes=str(v), **kw)


def co(name, v, **kw):
    return row(level="county", county_name=name, votes=str(v), **kw)


def pr(county, name, v, **kw):
    return row(level="precinct", county_name=county, precinct_id=name, precinct_name=name, votes=str(v), **kw)


class PartsTest(CheckTestBase):
    def check(self):
        return db_checks.check_parts(self.conn)

    def test_county_sum_mismatch_listed(self):
        self.snap("s1", 1, [co("A", 10), co("B", 20), st(31)])
        exc, _ = self.check()
        self.assertEqual([(e["pair"], e["part_sum"], e["whole"]) for e in exc], [("county>state", 30, 31)])

    def test_clean_sum_no_exception(self):
        self.snap("s1", 1, [co("A", 10), co("B", 20), st(30), pr("A", "p1", 4), pr("A", "p2", 6),
                            pr("B", "p3", 20)])
        self.assertEqual(self.check(), ([], []))

    def test_null_part_not_checked(self):
        self.snap("s1", 1, [co("A", 10), row(level="county", county_name="B", votes=""), st(30)])
        exc, nc = self.check()
        self.assertEqual(exc, [])
        self.assertEqual([(n["scope"], n["reason"]) for n in nc],
                         [("pair", "precinct>county: no precinct rows"), ("line", "empty count")])

    def test_missing_state_level_not_checked(self):
        self.snap("s1", 1, [co("A", 10), pr("A", "p1", 10)])
        exc, nc = self.check()
        self.assertEqual(exc, [])
        self.assertEqual([(n["scope"], n["reason"]) for n in nc], [("pair", "county>state: no state rows")])

    def test_party_lines_kept_apart(self):
        self.snap("s1", 1, [row(level="town", county_id="1", votes="5", party="D"),
                            row(level="town", county_id="2", votes="7", party="D"),
                            row(level="town", county_id="1", votes="1", party="WF"),
                            st(12, party="D"), st(1, party="WF")])
        exc, nc = self.check()
        self.assertEqual(exc, [])
        self.assertEqual([n["reason"] for n in nc], ["precinct>county: no precinct rows"])

    def test_local_contest_joins_within_county(self):
        self.snap("s1", 1, [co("A", 10, contest_scope="local"), co("B", 3, contest_scope="local"),
                            pr("A", "p1", 10, contest_scope="local"), pr("B", "p2", 4, contest_scope="local")])
        exc, _ = self.check()
        self.assertEqual([(e["county"], e["part_sum"], e["whole"]) for e in exc], [("B", 4, 3)])

    def test_precinct_rows_without_county_not_checked(self):
        self.snap("s1", 1, [co("A", 10), pr("", "p1", 10), st(10)])
        exc, nc = self.check()
        self.assertEqual(exc, [])
        self.assertEqual([n["reason"] for n in nc], ["precinct>county: 1 precinct rows have no county",
                                                     "no precinct rows"])



MAP = db.load_turnout_map(db.DEFAULT_TURNOUT_MAP)


def turnout(layout, rows):
    header = MAP[layout]["header"]
    return header, [dict(dict.fromkeys(header, ""), **r) for r in rows]


def ak(p, v, choice="10", vote_for="1", **kw):
    return row(level="precinct", county_name="", precinct_id=p, precinct_name=p, choice_id=choice,
               vote_for=vote_for, votes=str(v), **kw)


class RegisteredTest(CheckTestBase):
    def check(self):
        return db_checks.check_registered(self.conn)

    def kinds(self):
        exc, _ = self.check()
        return [(e["kind"], e["unit"], e.get("votes")) for e in exc]

    def test_ballots_over_registered(self):
        self.snap("ak-t", 1, [ak("p1", 50)], turnout("ak", [{"precinct_id": "p1", "registered_voters": "100",
                                                              "ballots": "101"}]))
        self.assertEqual(self.kinds(), [("ballots_over_registered", "p1", None)])

    def test_contest_over_registered_uses_vote_for(self):
        t = turnout("ak", [{"precinct_id": "p1", "registered_voters": "100", "ballots": "100"}])
        self.snap("ak-t", 1, [ak("p1", 120, vote_for="2"), ak("p1", 70, "11", vote_for="2")], t)
        self.assertEqual(self.kinds(), [])
        self.snap("ak-u", 2, [ak("p1", 120, vote_for="2"), ak("p1", 90, "11", vote_for="2")], t)
        self.assertEqual(self.kinds(), [("contest_over_registered", "p1", 210)])

    def test_blank_vote_for_counts_as_one_and_is_listed(self):
        t = turnout("ak", [{"precinct_id": "p1", "registered_voters": "100", "ballots": "90"}])
        self.snap("ak-t", 1, [ak("p1", 80, vote_for="")], t)
        self.assertEqual(self.kinds(), [("blank_vote_for", "", None)])

    def test_zero_registered_listed_not_compared(self):
        self.snap("ak-t", 1, [ak("p1", 50)], turnout("ak", [{"precinct_id": "p1", "registered_voters": "0",
                                                              "ballots": "60"}]))
        self.assertEqual(self.kinds(), [("zero_registered", "p1", None)])

    def test_units_that_dont_meet_listed(self):
        self.snap("ak-t", 1, [ak("p1", 5), ak("p2", 5)],
                  turnout("ak", [{"precinct_id": "p1", "registered_voters": "100", "ballots": "9"},
                                 {"precinct_id": "p3", "registered_voters": "100", "ballots": "9"}]))
        self.assertEqual(self.kinds(), [("result_unit_without_turnout", "p2", None),
                                        ("turnout_unit_without_results", "p3", None)])

    def test_hi_vsc_units_rolled_up(self):
        def hi(name, v):
            return row(level="precinct", county_name="", precinct_id=name, precinct_name=name, vote_for="1",
                       votes=str(v))
        t = turnout("hi", [{"precinct_id": "1", "precinct_name": "01-01", "registered_voters": "100", "ballots": "40"},
                           {"precinct_id": "2", "precinct_name": "01-01 VSC", "registered_voters": "0",
                            "ballots": "30"}])
        self.snap("hi-t", 1, [hi("01-01", 40), hi("01-01 VSC", 30)], t)
        self.assertEqual(self.check(), ([], []))

    def test_vt_town_parts_summed(self):
        def part(p, v):
            return row(level="town", county_id="5", county_name="T", precinct_id=p, vote_for="1", votes=str(v))
        t = turnout("vt", [{"county_id": "5", "county_name": "T", "registered_voters": "100", "ballots": "100"}])
        self.snap("vt-t", 1, [part("a", 60), part("b", 50)], t)
        self.assertEqual(self.kinds(), [("contest_over_registered", "5", 110)])

    def test_de_not_joinable(self):
        self.snap("de-t", 1, [ak("p1", 5)], turnout("de", [{"representative_district": "1",
                                                             "registered_voters": "9", "ballots_cast": "9"}]))
        exc, nc = self.check()
        self.assertEqual((exc, [n["reason"] for n in nc]), ([], [MAP["de"]["not_joinable"]]))

    def test_wy_no_registered_not_checked(self):
        self.snap("wy-t", 1, [ak("p1", 5)], turnout("wy", [{"county_id": "A", "precinct_id": "p1",
                                                             "ballots_cast": "9"}]))
        exc, nc = self.check()
        self.assertEqual((exc, [n["reason"] for n in nc]), ([], ["no registered voters"]))

    def test_no_turnout_table_not_checked(self):
        self.snap("ak-t", 1, [ak("p1", 5)])
        self.assertEqual([n["reason"] for n in self.check()[1]], ["no turnout table"])

    def test_wv_uses_election_day_total(self):
        def wv(t, v):
            return row(level="county", county_name="Ohio", vote_for="1", vote_type=t, votes=str(v))
        t = turnout("clarity_wv", [{"county_name": "Ohio", "registered_voters": "100", "ballots_cast": "50"}])
        self.snap("clarity-WV-t", 1, [wv("Election Day", 101)], t)
        self.assertEqual(self.kinds(), [("contest_over_registered", "Ohio", 101)])

    def test_turnout_total_row_ignored(self):
        t = turnout("clarity_county", [{"county_name": "A", "precinct_name": "p1", "registered_voters": "100",
                                        "ballots_cast": "50"},
                                       {"county_name": "A", "precinct_name": "", "registered_voters": "100",
                                        "ballots_cast": "50"}])
        self.snap("clarity-NJ-t", 1, [ak("p1", 50)], t)
        self.assertEqual(self.check(), ([], []))


if __name__ == "__main__":
    unittest.main()
