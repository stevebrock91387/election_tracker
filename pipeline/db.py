"""Step 3 results database: every reader's parsed CSVs in one SQLite file.

Design: docs/superpowers/specs/2026-11-25-step3-checks-database-design.md.

A snapshot is one downloaded state of a source. Its time (first_seen_utc) is when its content first
existed: for each source_sha256 in the CSV, the earliest fetched_utc of that hash in the manifest, then the
latest of those. Two parses with the same (source_id, first_seen_utc) are the same snapshot: the parse whose
file name stamp is newest wins (reader fixes take effect). Only the latest two snapshots per source keep
their result and turnout rows; older ones are marked pruned, and a CSV older than both kept snapshots isn't
loaded. Values are stored as the CSV has them, except votes: "" -> NULL, digits -> INTEGER.

    /opt/homebrew/bin/python3 -m pipeline.db load  [--db data/results.sqlite] [--parsed-dir data/parsed]
    /opt/homebrew/bin/python3 -m pipeline.db check [--db data/results.sqlite] [--source ID]
"""
import csv
import hashlib
import os
import re
import sqlite3
import sys
import time

from pipeline.schema import COLUMNS

csv.field_size_limit(sys.maxsize)
KEEP = 2  # snapshots per source that keep their rows (Steve, 2026-11-25: option A)
STAMP = re.compile(r"^\d{8}T\d{6}Z\.csv$")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, state TEXT, first_seen_utc TEXT NOT NULL,
    csv_path TEXT, csv_sha256 TEXT, turnout_path TEXT, loaded_utc TEXT, pruned INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, first_seen_utc));
CREATE TABLE IF NOT EXISTS result (snapshot_id INTEGER NOT NULL, {", ".join(
    c + (" INTEGER" if c == "votes" else " TEXT") for c in COLUMNS)});
CREATE INDEX IF NOT EXISTS result_snapshot ON result (snapshot_id, level, contest_id);
CREATE TABLE IF NOT EXISTS turnout (
    snapshot_id INTEGER NOT NULL, layout TEXT, county_id TEXT, county_name TEXT, precinct_id TEXT,
    precinct_name TEXT, contest_id TEXT, registered_voters INTEGER, ballots_cast INTEGER, raw TEXT);
CREATE INDEX IF NOT EXISTS turnout_snapshot ON turnout (snapshot_id);
CREATE TABLE IF NOT EXISTS load_note (csv_path TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS loaded_csv (csv_sha256 TEXT PRIMARY KEY, csv_path TEXT);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _manifest_first_seen(path):
    first = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t, sha = r["fetched_utc"], r["sha256"]
            if sha not in first or t < first[sha]:
                first[sha] = t
    return first


def _votes(v):
    if v == "":
        return None
    return int(v) if v.isascii() and v.isdigit() else v


def _parsed_csvs(parsed_dir):
    """(source_id, path) of every results CSV, oldest parse first within a source."""
    out = []
    for source_id in sorted(os.listdir(parsed_dir)):
        d = os.path.join(parsed_dir, source_id)
        if os.path.isdir(d):
            out += [(source_id, os.path.join(d, n)) for n in sorted(os.listdir(d)) if STAMP.match(n)]
    return out


def _note(conn, path, kind, detail=""):
    if not conn.execute("SELECT 1 FROM load_note WHERE csv_path = ? AND kind = ?", (path, kind)).fetchone():
        conn.execute("INSERT INTO load_note VALUES (?, ?, ?)", (path, kind, detail))


def _done(conn, sha, path):
    """Record a CSV as handled (loaded, or rejected for good) so later loads skip it unread."""
    conn.execute("INSERT OR REPLACE INTO loaded_csv VALUES (?, ?)", (sha, path))


def load(conn, parsed_dir="data/parsed", manifest="data/raw/manifest.csv", turnout_map=None):
    """Load every new parsed CSV. Returns lists of CSV paths: loaded, skipped_known, replaced, not_loaded."""
    out = {"loaded": [], "skipped_known": [], "replaced": [], "not_loaded": []}
    first_seen = _manifest_first_seen(manifest)
    known = {sha for (sha,) in conn.execute("SELECT csv_sha256 FROM loaded_csv")}
    # Pass 1: each new CSV's snapshot key; within one load only the newest parse of a key is read.
    candidates = {}
    for source_id, path in _parsed_csvs(parsed_dir):
        sha = _sha256(path)
        if sha in known:
            out["skipped_known"].append(path)
            continue
        with open(path, newline="") as f:
            r = csv.DictReader(f)
            hashes, state = set(), ""
            for row in r:
                hashes.add(row["source_sha256"])
                state = state or row["state"]
        missing = sorted(h for h in hashes if h not in first_seen)
        if missing or not hashes:
            _note(conn, path, "hash_not_in_manifest", ",".join(missing) or "no rows")
            out["not_loaded"].append(path)
            continue
        key = (source_id, max(first_seen[h] for h in hashes))
        prev = candidates.get(key)
        if prev is not None:
            out["skipped_known"].append(prev["path"])  # an older parse of the same snapshot
            _done(conn, prev["sha"], prev["path"])
        candidates[key] = {"path": path, "sha": sha, "state": state}
    for (source_id, t), c in sorted(candidates.items()):
        _load_one(conn, source_id, t, c, out, turnout_map)
    conn.commit()
    return out


def _load_one(conn, source_id, t, c, out, turnout_map):
    path = c["path"]
    kept = [r[0] for r in conn.execute(
        "SELECT first_seen_utc FROM snapshot WHERE source_id = ? AND pruned = 0", (source_id,))]
    existing = conn.execute("SELECT snapshot_id, csv_path, pruned FROM snapshot WHERE source_id = ? AND "
                            "first_seen_utc = ?", (source_id, t)).fetchone()
    if (existing and existing[2]) or (not existing and len(kept) >= KEEP and t < min(kept)):
        _note(conn, path, "older_than_kept", t)
        _done(conn, c["sha"], path)
        out["not_loaded"].append(path)
        return
    if existing and os.path.basename(path) <= os.path.basename(existing[1]):
        out["skipped_known"].append(path)  # an older parse of a loaded snapshot
        _done(conn, c["sha"], path)
        return
    turnout_path = path[:-4] + "-turnout.csv"
    turnout_path = turnout_path if os.path.exists(turnout_path) else ""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with conn:
        if existing:
            sid = existing[0]
            conn.execute("DELETE FROM result WHERE snapshot_id = ?", (sid,))
            conn.execute("DELETE FROM turnout WHERE snapshot_id = ?", (sid,))
            conn.execute("UPDATE snapshot SET csv_path = ?, csv_sha256 = ?, turnout_path = ?, loaded_utc = ? "
                         "WHERE snapshot_id = ?", (path, c["sha"], turnout_path, now, sid))
            _note(conn, path, "replaced_parse", existing[1])
            out["replaced"].append(path)
        else:
            sid = conn.execute("INSERT INTO snapshot (source_id, state, first_seen_utc, csv_path, csv_sha256, "
                               "turnout_path, loaded_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (source_id, c["state"], t, path, c["sha"], turnout_path, now)).lastrowid
            out["loaded"].append(path)
        with open(path, newline="") as f:
            conn.executemany(
                f"INSERT INTO result VALUES (?, {', '.join('?' * len(COLUMNS))})",
                ((sid, *(_votes(r[k]) if k == "votes" else r[k] for k in COLUMNS)) for r in csv.DictReader(f)))
        if turnout_path:
            _load_turnout(conn, sid, source_id, turnout_path, turnout_map)
        _done(conn, c["sha"], path)
        _prune(conn, source_id)


def _load_turnout(conn, sid, source_id, path, turnout_map):
    pass  # Task 2


def _prune(conn, source_id):
    ids = [r[0] for r in conn.execute("SELECT snapshot_id FROM snapshot WHERE source_id = ? AND pruned = 0 "
                                      "ORDER BY first_seen_utc DESC", (source_id,))]
    for sid in ids[KEEP:]:
        conn.execute("DELETE FROM result WHERE snapshot_id = ?", (sid,))
        conn.execute("DELETE FROM turnout WHERE snapshot_id = ?", (sid,))
        conn.execute("UPDATE snapshot SET pruned = 1 WHERE snapshot_id = ?", (sid,))
