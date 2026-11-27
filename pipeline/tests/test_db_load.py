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

    def test_snapshot_time_is_the_download_the_parse_read(self):
        # Per file, the latest fetch at or before the parse; the snapshot is the earliest of those.
        write_manifest(self.manifest, [("A", "2026-11-24T15:00:00Z"), ("B", "2026-11-24T15:00:10Z"),
                                       ("A", "2026-11-26T03:07:35Z"), ("C", "2026-11-26T03:07:46Z")])
        write_parse(self.parsed, "s1", "20261124T150100Z", [row(source_sha256="A"), row(source_sha256="B")])
        write_parse(self.parsed, "s1", "20261126T030800Z", [row(source_sha256="A"), row(source_sha256="C")])
        self.load()
        self.assertEqual(self.q("SELECT first_seen_utc FROM snapshot ORDER BY first_seen_utc"),
                         [("2026-11-24T15:00:00Z",), ("2026-11-26T03:07:35Z",)])

    def test_reversion_to_earlier_content_is_a_new_snapshot(self):
        write_manifest(self.manifest, [("A", "2026-11-21T00:00:00Z"), ("B", "2026-11-22T00:00:00Z"),
                                       ("A", "2026-11-23T00:00:00Z")])
        write_parse(self.parsed, "s1", "20261121T000100Z", [row(source_sha256="A", votes="5")])
        write_parse(self.parsed, "s1", "20261122T000100Z", [row(source_sha256="B", votes="9")])
        write_parse(self.parsed, "s1", "20261123T000100Z", [row(source_sha256="A", votes="5")])
        self.load()
        self.assertEqual(self.q("SELECT first_seen_utc, pruned FROM snapshot ORDER BY first_seen_utc"),
                         [("2026-11-21T00:00:00Z", 1), ("2026-11-22T00:00:00Z", 0), ("2026-11-23T00:00:00Z", 0)])
        self.assertEqual(sorted(self.q("SELECT votes FROM result")), [(5,), (9,)])

    def test_identical_back_to_back_downloads_are_one_snapshot(self):
        # Steve, 2026-11-26 (option B): nothing changed, so one snapshot; the newest parse wins (reader fixes).
        write_manifest(self.manifest, [("A", "2026-11-21T00:00:00Z"), ("A", "2026-11-22T00:00:00Z")])
        write_parse(self.parsed, "s1", "20261121T000100Z", [row(source_sha256="A", votes="1")])
        new = write_parse(self.parsed, "s1", "20261122T000100Z", [row(source_sha256="A", votes="2")])
        self.load()
        self.assertEqual(self.q("SELECT first_seen_utc, csv_path FROM snapshot"), [("2026-11-21T00:00:00Z", new)])
        self.assertEqual(self.q("SELECT votes FROM result"), [(2,)])

    def test_identical_back_to_back_download_in_a_later_load_replaces(self):
        write_manifest(self.manifest, [("A", "2026-11-21T00:00:00Z"), ("A", "2026-11-22T00:00:00Z")])
        write_parse(self.parsed, "s1", "20261121T000100Z", [row(source_sha256="A", votes="1")])
        self.load()
        new = write_parse(self.parsed, "s1", "20261122T000100Z", [row(source_sha256="A", votes="2")])
        out = self.load()
        self.assertEqual(out["replaced"], [new])
        self.assertEqual(self.q("SELECT first_seen_utc, csv_path FROM snapshot"), [("2026-11-21T00:00:00Z", new)])

    def test_late_parse_of_earlier_identical_download_joins_loaded_snapshot(self):
        write_manifest(self.manifest, [("A", "2026-11-21T00:00:00Z"), ("A", "2026-11-22T00:00:00Z")])
        kept = write_parse(self.parsed, "s1", "20261122T000100Z", [row(source_sha256="A", votes="2")])
        self.load()
        old = write_parse(self.parsed, "s1", "20261121T000100Z", [row(source_sha256="A", votes="1")])
        out = self.load()
        self.assertIn(old, out["skipped_known"])
        self.assertEqual(self.q("SELECT first_seen_utc, csv_path FROM snapshot"), [("2026-11-22T00:00:00Z", kept)])

    def test_reparse_of_older_pass_replaces_that_pass(self):
        # File X didn't change between passes, so the re-parse's own time (Y1's fetch, 5 s after pass 1's) is
        # off; its files equal pass 1's, the snapshot just before it, so it joins pass 1. Pass 2 is untouched.
        write_manifest(self.manifest, [("X", "2026-11-21T00:00:00Z"), ("Y1", "2026-11-21T00:00:05Z"),
                                       ("X", "2026-11-22T00:00:00Z"), ("Y2", "2026-11-22T00:00:05Z")])
        write_parse(self.parsed, "s1", "20261121T000100Z", [row(source_sha256="X"), row(source_sha256="Y1", votes="1")])
        p2 = write_parse(self.parsed, "s1", "20261122T000100Z",
                         [row(source_sha256="X"), row(source_sha256="Y2", votes="2")])
        self.load()
        new = write_parse(self.parsed, "s1", "20261125T000000Z",
                          [row(source_sha256="X"), row(source_sha256="Y1", votes="7")])
        out = self.load()
        self.assertEqual(out["replaced"], [new])
        self.assertEqual(self.q("SELECT first_seen_utc, csv_path, pruned FROM snapshot ORDER BY first_seen_utc"),
                         [("2026-11-21T00:00:00Z", new, 0), ("2026-11-22T00:00:00Z", p2, 0)])

    def test_parse_stamped_before_every_fetch_uses_earliest_fetch(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z"), ("A", "2026-11-25T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T010000Z", [row(source_sha256="A")])
        self.load()
        self.assertEqual(self.q("SELECT first_seen_utc FROM snapshot"), [("2026-11-24T15:02:22Z",)])

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

    def test_csv_missing_a_column_loads_it_empty_and_notes(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        d = os.path.join(self.parsed, "s1")
        os.makedirs(d)
        cols = [c for c in COLUMNS if c != "contest_scope"]
        path = os.path.join(d, "20261124T150300Z.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerow(row(source_sha256="A", source_id="s1"))
        out = self.load()
        self.assertEqual(out["loaded"], [path])
        self.assertEqual(self.q("SELECT contest_scope, votes FROM result"), [(None, 5)])
        self.assertEqual(self.q("SELECT kind, detail FROM load_note"), [("columns_missing", "contest_scope")])

    def test_rewritten_csv_same_name_replaces(self):
        """A CSV read while its reader was still writing it is replaced once the finished file differs."""
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "s1", "20261124T150300Z", [row(source_sha256="A")])
        self.load()
        path = write_parse(self.parsed, "s1", "20261124T150300Z",
                           [row(source_sha256="A"), row(source_sha256="A", choice_id="11")])
        out = self.load()
        self.assertEqual(out["replaced"], [path])
        self.assertEqual(self.q("SELECT COUNT(*) FROM result"), [(2,)])

    def test_turnout_arriving_after_results_is_loaded(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        path = write_parse(self.parsed, "hi-2026-general", "20261124T150300Z", [row(source_sha256="A")])
        self.load()
        header = db.load_turnout_map()["hi"]["header"]
        with open(path[:-4] + "-turnout.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerow(dict.fromkeys(header, "1"))
        self.load()
        self.assertEqual(self.q("SELECT COUNT(*) FROM turnout"), [(1,)])
        self.assertEqual(self.q("SELECT turnout_path FROM snapshot"), [(path[:-4] + "-turnout.csv",)])

    def test_truncated_csv_noted_and_others_still_load(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z"), ("B", "2026-11-24T15:02:22Z")])
        bad = write_parse(self.parsed, "a1", "20261124T150300Z", [row(source_sha256="A")] * 3)
        with open(bad) as f:
            text = f.read()
        with open(bad, "w") as f:
            f.write(text[: text.rindex("\n", 0, len(text) - 1) + 12])  # cut mid-line
        good = write_parse(self.parsed, "b1", "20261124T150300Z", [row(source_sha256="B")])
        out = self.load()
        self.assertEqual(out["loaded"], [good])
        self.assertIn(bad, out["not_loaded"])
        self.assertIn(("unreadable",), self.q("SELECT kind FROM load_note WHERE csv_path = ?", bad))
        self.assertEqual(self.q("SELECT COUNT(*) FROM snapshot WHERE source_id = 'a1'"), [(0,)])

    def test_empty_hash_noted_as_such(self):
        write_manifest(self.manifest, [])
        write_parse(self.parsed, "s1", "20261124T150300Z", [row(source_sha256="")])
        self.load()
        self.assertEqual(self.q("SELECT kind, detail FROM load_note"), [("hash_not_in_manifest", "empty source_sha256")])

    def test_snapshot_pruned_unchecked_in_same_load_noted(self):
        self.snapshots(3)
        self.load()
        self.assertIn(("pruned_unchecked",), self.q("SELECT kind FROM load_note"))

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



HI_HEADER = ["state", "source_id", "source_sha256", "precinct_id", "precinct_name", "registered_voters", "ballots",
             "reporting"]


class TurnoutTest(LoadTestBase):
    def load(self):
        return db.load(self.conn, self.parsed, self.manifest, db.load_turnout_map(db.DEFAULT_TURNOUT_MAP))

    def test_map_covers_every_reader_layout(self):
        import importlib, pkgutil
        import pipeline.readers as readers
        headers = [l["header"] for l in db.load_turnout_map(db.DEFAULT_TURNOUT_MAP).values()]
        n = 0
        for m in pkgutil.iter_modules(readers.__path__):
            mod = importlib.import_module(f"pipeline.readers.{m.name}")
            for name in ("TURNOUT_COLUMNS", "COUNTY_TURNOUT_COLUMNS"):
                if hasattr(mod, name):
                    n += 1
                    self.assertIn(getattr(mod, name), headers, f"{m.name}.{name}")
        self.assertEqual(n, 15)

    def test_turnout_loaded_with_mapped_columns(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        trow = {"state": "HI", "source_id": "hi-2026-general", "source_sha256": "A", "precinct_id": "1",
                "precinct_name": "01-01", "registered_voters": "6555", "ballots": "3046", "reporting": "1"}
        write_parse(self.parsed, "hi-2026-general", "20261124T150300Z", [row(source_sha256="A")],
                    turnout=(HI_HEADER, [trow]))
        self.load()
        got = self.q("SELECT layout, precinct_id, precinct_name, county_id, registered_voters, ballots_cast, raw "
                     "FROM turnout")
        self.assertEqual(got[0][:6], ("hi", "1", "01-01", None, 6555, 3046))
        import json
        self.assertEqual(json.loads(got[0][6]), trow)

    def test_unknown_turnout_header(self):
        write_manifest(self.manifest, [("A", "2026-11-24T15:02:22Z")])
        write_parse(self.parsed, "hi-2026-general", "20261124T150300Z", [row(source_sha256="A")],
                    turnout=(["state", "odd"], [{"state": "HI", "odd": "1"}]))
        self.load()
        self.assertEqual(self.q("SELECT layout, registered_voters, ballots_cast, raw FROM turnout"),
                         [(None, None, None, '{"state": "HI", "odd": "1"}')])
        self.assertIn(("turnout_layout_unknown",), self.q("SELECT kind FROM load_note"))

    def test_layout_needs_prefix_and_header(self):
        m = db.load_turnout_map(db.DEFAULT_TURNOUT_MAP)
        header = m["clarity_state"]["header"]
        self.assertEqual(db.layout_for(m, "clarity-WV-2026-general", header)[0], "clarity_state")
        self.assertEqual(db.layout_for(m, "clarity-NJ-Essex-2026-general", m["clarity_county"]["header"])[0],
                         "clarity_county")
        self.assertIsNone(db.layout_for(m, "zz-2026", header))


if __name__ == "__main__":
    unittest.main()
