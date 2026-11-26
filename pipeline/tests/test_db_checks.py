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


if __name__ == "__main__":
    unittest.main()
