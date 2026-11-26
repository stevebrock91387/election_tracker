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


if __name__ == "__main__":
    unittest.main()
