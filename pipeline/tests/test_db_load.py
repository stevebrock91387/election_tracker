"""Step 3 database: loading parsed CSVs (snapshot identity, re-parses, retention)."""
import csv
import os
import tempfile
import unittest

from pipeline import db
from pipeline.schema import COLUMNS


def row(**kw):
    r = dict.fromkeys(COLUMNS, "")
    r.update(state="XX", source_id="s1", level="county", county_name="A", contest_id="1", contest_scope="statewide",
             choice="Alice", choice_id="10", vote_type="TOTAL", votes="5")
    r.update(kw)
    return r


def write_parse(parsed_dir, source_id, stamp, rows, turnout=None):
    """rows: list of dicts (row()); turnout: (header, list of dicts) written as <stamp>-turnout.csv."""
    d = os.path.join(parsed_dir, source_id)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{stamp}.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(dict(r, source_id=source_id))
    if turnout is not None:
        header, trows = turnout
        with open(os.path.join(d, f"{stamp}-turnout.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for r in trows:
                w.writerow(r)
    return path


def write_manifest(path, entries):
    """entries: (sha256, fetched_utc)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_id", "url", "fetched_utc", "http_status", "bytes", "sha256", "path"])
        for sha, t in entries:
            w.writerow(["x", "u", t, 200, 1, sha, "p"])


class LoadTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.parsed = os.path.join(self.tmp, "parsed")
        self.manifest = os.path.join(self.tmp, "manifest.csv")
        self.conn = db.connect(os.path.join(self.tmp, "r.sqlite"))

    def load(self):
        return db.load(self.conn, self.parsed, self.manifest)

    def q(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()


class ResultLoadTest(LoadTestBase):
    def test_load_one_csv(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        path = write_parse(self.parsed, "s1", "20261124T150300Z", [
            row(source_sha256="A", votes="12"), row(source_sha256="A", choice_id="11", votes=""),
            row(source_sha256="A", choice_id="12", votes="0")])
        out = self.load()
        self.assertEqual(out["loaded"], [path])
        self.assertEqual(self.q("SELECT source_id, first_seen_utc FROM snapshot"), [("s1", "2026-11-24T15:02:22Z")])
        self.assertEqual(sorted(self.q("SELECT choice_id, votes FROM result"), key=lambda x: x[0]),
                         [("10", 12), ("11", None), ("12", 0)])

    def test_same_csv_twice_is_skipped(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        path = write_parse(self.parsed, "s1", "20261124T150300Z", [row(source_sha256="A")] * 3)
        self.load()
        out = self.load()
        self.assertEqual(out["skipped_known"], [path])
        self.assertEqual(self.q("SELECT COUNT(*) FROM result"), [(3,)])

    def test_newer_parse_of_same_snapshot_replaces(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T010000Z", [row(source_sha256="A", votes="1")])
        self.load()
        new = write_parse(self.parsed, "s1", "20261124T020000Z", [row(source_sha256="A", votes="2")])
        out = self.load()
        self.assertEqual(out["replaced"], [new])
        self.assertEqual(self.q("SELECT COUNT(*) FROM snapshot"), [(1,)])
        self.assertEqual(self.q("SELECT votes FROM result"), [(2,)])
        self.assertEqual(self.q("SELECT kind FROM load_note"), [("replaced_parse",)])

    def test_older_parse_of_same_snapshot_is_skipped(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T020000Z", [row(source_sha256="A", votes="2")])
        self.load()
        old = write_parse(self.parsed, "s1", "20261124T010000Z", [row(source_sha256="A", votes="1")])
        out = self.load()
        self.assertIn(old, out["skipped_known"])
        self.assertEqual(self.q("SELECT votes FROM result"), [(2,)])

    def test_both_parses_in_one_load_newest_wins(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T010000Z", [row(source_sha256="A", votes="1")])
        write_parse(self.parsed, "s1", "20261124T020000Z", [row(source_sha256="A", votes="2")])
        self.load()
        self.assertEqual(self.q("SELECT votes FROM result"), [(2,)])

    def test_unchanged_file_keeps_first_fetch_time(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:00:00Z"), ("B", "2026-11-24T15:00:10Z"),
                                       ("A", "2026-11-26T03:07:35Z"), ("C", "2026-11-26T03:07:46Z")])
        write_parse(self.parsed, "s1", "20261124T150100Z", [row(source_sha256="A"), row(source_sha256="B")])
        write_parse(self.parsed, "s1", "20261126T030800Z", [row(source_sha256="A"), row(source_sha256="C")])
        self.load()
        self.assertEqual(self.q("SELECT first_seen_utc FROM snapshot ORDER BY first_seen_utc"),
                         [("2026-11-24T15:00:10Z",), ("2026-11-26T03:07:46Z",)])

    def test_hash_not_in_manifest(self):
        write_manifest(self.manifest, [])
        path = write_parse(self.parsed, "s1", "20261124T150300Z", [row(source_sha256="Z")])
        out = self.load()
        self.assertEqual(out["not_loaded"], [path])
        self.assertEqual(self.q("SELECT kind FROM load_note"), [("hash_not_in_manifest",)])
        self.assertEqual(self.q("SELECT COUNT(*) FROM snapshot"), [(0,)])

    def test_notes_not_repeated_on_reload(self):
        write_manifest(self.manifest, [])
        write_parse(self.parsed, "s1", "20261124T150300Z", [row(source_sha256="Z")])
        self.load()
        self.load()
        self.assertEqual(self.q("SELECT COUNT(*) FROM load_note"), [(1,)])

    def test_skipped_older_parse_not_reread(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T020000Z", [row(source_sha256="A", votes="2")])
        old = write_parse(self.parsed, "s1", "20261124T010000Z", [row(source_sha256="A", votes="1")])
        self.load()
        self.assertEqual(self.q("SELECT COUNT(*) FROM loaded_csv WHERE csv_path = ?", old), [(1,)])

    def snapshots(self, n):
        write_manifest(self.manifest, [(f"H{i}", f"2026-11-2{i}T00:00:00Z") for i in range(1, n + 1)])
        return [write_parse(self.parsed, "s1", f"2026112{i}T000100Z", [row(source_sha256=f"H{i}", votes=str(i))])
                for i in range(1, n + 1)]

    def test_retention_keeps_latest_two(self):
        self.snapshots(3)
        self.load()
        self.assertEqual(self.q("SELECT first_seen_utc, pruned FROM snapshot ORDER BY first_seen_utc"),
                         [("2026-11-21T00:00:00Z", 1), ("2026-11-22T00:00:00Z", 0), ("2026-11-23T00:00:00Z", 0)])
        self.assertEqual(sorted(self.q("SELECT votes FROM result")), [(2,), (3,)])

    def test_late_older_snapshot_not_loaded(self):
        p1, p2, p3 = self.snapshots(3)
        os.rename(p1, p1 + ".hold")
        self.load()
        os.rename(p1 + ".hold", p1)
        out = self.load()
        self.assertEqual(out["not_loaded"], [p1])
        self.assertIn(("older_than_kept",), self.q("SELECT kind FROM load_note"))
        self.assertEqual(sorted(self.q("SELECT votes FROM result")), [(2,), (3,)])

    def test_turnout_csv_not_loaded_as_results(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T150300Z", [row(source_sha256="A")],
                    turnout=(["state", "x"], [{"state": "XX", "x": "1"}]))
        out = self.load()
        self.assertEqual(len(out["loaded"]), 1)
        self.assertEqual(self.q("SELECT COUNT(*) FROM result"), [(1,)])


if __name__ == "__main__":
    unittest.main()
