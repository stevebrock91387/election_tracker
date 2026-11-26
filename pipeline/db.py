"""Step 3 results database: every reader's parsed CSVs in one SQLite file.

Design: docs/superpowers/specs/2026-11-25-step3-checks-database-design.md.

A snapshot is one download (pass) of a source. Its time (first_seen_utc, kept as the column name) is when
the pass that the parse read was fetched: for each source_sha256 in the CSV, the latest fetched_utc of that
hash in the manifest at or before the parse's file name stamp (the earliest fetch if none is), then the
earliest of those. A download whose files are exactly those of the source's previous snapshot (nothing
changed) joins that snapshot (Steve, 2026-11-26, option B), so a reader fix's newer parse still replaces the
old one; content that comes back after a different download in between (a source reverting) is a new
snapshot that check 1 compares. Two parses with the same (source_id, first_seen_utc) are the same snapshot: the parse whose
file name stamp is newest wins (reader fixes take effect). Only the latest two snapshots per source keep
their result and turnout rows; older ones are marked pruned, and a CSV older than both kept snapshots isn't
loaded. Values are stored as the CSV has them, except votes: "" -> NULL, digits -> INTEGER.

    /opt/homebrew/bin/python3 -m pipeline.db load  [--db data/results.sqlite] [--parsed-dir data/parsed]
    /opt/homebrew/bin/python3 -m pipeline.db check [--db data/results.sqlite] [--source ID]
"""
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import tomllib

from pipeline.schema import COLUMNS

csv.field_size_limit(sys.maxsize)
DEFAULT_TURNOUT_MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turnout_map.toml")
KEEP = 2  # snapshots per source that keep their rows (Steve, 2026-11-25: option A)
STAMP = re.compile(r"^\d{8}T\d{6}Z\.csv$")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, state TEXT, first_seen_utc TEXT NOT NULL,
    csv_path TEXT, csv_sha256 TEXT, turnout_path TEXT, turnout_sha256 TEXT, loaded_utc TEXT,
    pruned INTEGER NOT NULL DEFAULT 0, source_hashes TEXT,
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
    if "source_hashes" not in [r[1] for r in conn.execute("PRAGMA table_info(snapshot)")]:
        conn.execute("ALTER TABLE snapshot ADD COLUMN source_hashes TEXT")  # a database built before it
    return conn


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _manifest_fetches(path):
    """{sha256: sorted fetched_utc list}."""
    fetches = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            fetches.setdefault(r["sha256"], []).append(r["fetched_utc"])
    for ts in fetches.values():
        ts.sort()
    return fetches


def _stamp_utc(path):
    """20261124T150546Z.csv -> 2026-11-24T15:05:46Z (the manifest's format)."""
    n = os.path.basename(path)
    return f"{n[0:4]}-{n[4:6]}-{n[6:8]}T{n[9:11]}:{n[11:13]}:{n[13:15]}Z"


def _snapshot_time(fetches, hashes, path):
    """Per hash, the latest fetch at or before the parse (else its earliest fetch); the earliest of those."""
    parsed = _stamp_utc(path)
    times = []
    for h in hashes:
        before = [t for t in fetches[h] if t <= parsed]
        times.append(before[-1] if before else fetches[h][0])
    return min(times)


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
    """Record a CSV as handled (loaded, or rejected for good) so later loads skip it after hashing it."""
    conn.execute("INSERT OR REPLACE INTO loaded_csv VALUES (?, ?)", (sha, path))


# A CSV that can't be read to the end (e.g. read while its reader was still writing it): noted, not loaded,
# not marked done, so the next load tries it again.
UNREADABLE = (csv.Error, ValueError, KeyError, AttributeError, TypeError, UnicodeDecodeError)


def _rows(reader):
    """DictReader rows, refusing short or long rows (a truncated or malformed file)."""
    for r in reader:
        if None in r or None in r.values():
            raise ValueError(f"line {reader.line_num}: wrong number of fields")
        yield r


def load(conn, parsed_dir="data/parsed", manifest="data/raw/manifest.csv", turnout_map=None):
    """Load every new parsed CSV. Returns lists of CSV paths: loaded, skipped_known, replaced, not_loaded."""
    out = {"loaded": [], "skipped_known": [], "replaced": [], "not_loaded": []}
    if turnout_map is None:
        turnout_map = load_turnout_map()
    fetches = _manifest_fetches(manifest)
    known = {sha for (sha,) in conn.execute("SELECT csv_sha256 FROM loaded_csv")}
    fresh = set()  # snapshot ids loaded by this call
    # Pass 1: each new CSV's download time and file set.
    items = []
    for source_id, path in _parsed_csvs(parsed_dir):
        sha = _sha256(path)
        if sha in known:
            out["skipped_known"].append(path)
            continue
        try:
            with open(path, newline="") as f:
                hashes, state = set(), ""
                for row in _rows(csv.DictReader(f)):
                    hashes.add(row["source_sha256"])
                    state = state or row["state"]
        except UNREADABLE as e:
            _note(conn, path, "unreadable", str(e))
            out["not_loaded"].append(path)
            continue
        changed = _forget_changed(conn, path, sha)
        missing = sorted(h for h in hashes if h not in fetches)
        if missing or not hashes:
            _note(conn, path, "hash_not_in_manifest",
                  ",".join("empty source_sha256" if h == "" else h for h in missing) or "no rows")
            out["not_loaded"].append(path)
            continue
        items.append({"source_id": source_id, "t": _snapshot_time(fetches, hashes, path), "path": path,
                      "sha": sha, "state": state, "changed": changed, "hashes": ",".join(sorted(hashes))})
    # Pass 2: snapshot keys (identical back-to-back downloads share one); only the newest parse of a key is read.
    candidates = {}
    for it in sorted(_merge_unchanged(conn, items), key=lambda it: os.path.basename(it["path"])):
        key = (it["source_id"], it["t"])
        prev = candidates.get(key)
        if prev is not None:
            out["skipped_known"].append(prev["path"])  # an older parse of the same snapshot
            _done(conn, prev["sha"], prev["path"])
        candidates[key] = it
    for (source_id, t), c in sorted(candidates.items()):
        try:
            _load_one(conn, source_id, t, c, out, turnout_map, fresh)
        except UNREADABLE as e:  # the transaction for this CSV was rolled back
            _note(conn, c["path"], "unreadable", str(e))
            out["not_loaded"].append(c["path"])
    _refresh_turnout(conn, turnout_map)
    conn.commit()
    return out


def _merge_unchanged(conn, items):
    """Give each item the time of the snapshot it belongs to: walking a source's downloads (loaded snapshots
    and new parses) in time order, one whose file set equals the previous one's joins it. A group's time is
    its loaded snapshot's, else its earliest download's."""
    by_source = {}
    for it in items:
        by_source.setdefault(it["source_id"], []).append(it)
    for source_id, its in by_source.items():
        loaded = [(t, 0, h or "", None) for t, h in conn.execute(
            "SELECT first_seen_utc, source_hashes FROM snapshot WHERE source_id = ?", (source_id,))]
        entries = sorted(loaded + [(it["t"], 1, it["hashes"], it) for it in its], key=lambda e: (e[0], e[1]))
        groups = []
        for t, is_new, h, it in entries:
            if groups and h and groups[-1]["hashes"] == h:
                g = groups[-1]
            else:
                g = {"hashes": h, "time": t, "has_loaded": False, "new": []}
                groups.append(g)
            if is_new:
                g["new"].append(it)
            elif not g["has_loaded"]:
                g["time"], g["has_loaded"] = t, True  # a loaded snapshot keeps its time
        for g in groups:
            for it in g["new"]:
                it["t"] = g["time"]
    return items


def _forget_changed(conn, path, sha):
    """A CSV path already loaded with other content (it was read before its reader finished, or rewritten):
    drop the snapshot made from the old content, so the new content is loaded in its place. Returns whether
    one was dropped."""
    dropped = False
    for (sid,) in conn.execute("SELECT snapshot_id FROM snapshot WHERE csv_path = ? AND csv_sha256 != ?",
                               (path, sha)).fetchall():
        with conn:
            conn.execute("DELETE FROM result WHERE snapshot_id = ?", (sid,))
            conn.execute("DELETE FROM turnout WHERE snapshot_id = ?", (sid,))
            conn.execute("DELETE FROM snapshot WHERE snapshot_id = ?", (sid,))
            conn.execute("DELETE FROM loaded_csv WHERE csv_path = ?", (path,))
            _note(conn, path, "csv_changed", "reloaded")
        dropped = True
    return dropped


def _refresh_turnout(conn, turnout_map):
    """Load a kept snapshot's turnout table when it appeared or changed after the results were loaded."""
    for sid, source_id, csv_path, tpath, tsha in conn.execute(
            "SELECT snapshot_id, source_id, csv_path, turnout_path, turnout_sha256 FROM snapshot "
            "WHERE pruned = 0").fetchall():
        path = csv_path[:-4] + "-turnout.csv"
        if not os.path.exists(path):
            continue
        sha = _sha256(path)
        if path == tpath and sha == tsha:
            continue
        try:
            with conn:
                conn.execute("DELETE FROM turnout WHERE snapshot_id = ?", (sid,))
                _load_turnout(conn, sid, source_id, path, turnout_map)
                conn.execute("UPDATE snapshot SET turnout_path = ?, turnout_sha256 = ? WHERE snapshot_id = ?",
                             (path, sha, sid))
        except UNREADABLE as e:
            _note(conn, path, "unreadable", str(e))


def _load_one(conn, source_id, t, c, out, turnout_map, fresh):
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
    if existing and os.path.basename(path) < os.path.basename(existing[1]):
        out["skipped_known"].append(path)  # an older parse of a loaded snapshot
        _done(conn, c["sha"], path)
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with conn:
        if existing:
            sid = existing[0]
            conn.execute("DELETE FROM result WHERE snapshot_id = ?", (sid,))
            conn.execute("DELETE FROM turnout WHERE snapshot_id = ?", (sid,))
            conn.execute("UPDATE snapshot SET csv_path = ?, csv_sha256 = ?, turnout_path = '', turnout_sha256 = '', "
                         "loaded_utc = ?, source_hashes = ? WHERE snapshot_id = ?",
                         (path, c["sha"], now, c["hashes"], sid))
            _note(conn, path, "replaced_parse", existing[1])
        else:
            sid = conn.execute("INSERT INTO snapshot (source_id, state, first_seen_utc, csv_path, csv_sha256, "
                               "turnout_path, turnout_sha256, loaded_utc, source_hashes) "
                               "VALUES (?, ?, ?, ?, ?, '', '', ?, ?)",
                               (source_id, c["state"], t, path, c["sha"], now, c["hashes"])).lastrowid
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            missing = [k for k in COLUMNS if k not in (reader.fieldnames or [])]
            if missing:  # a parse written before a column was added: stored NULL, noted
                _note(conn, path, "columns_missing", ",".join(missing))
            conn.executemany(
                f"INSERT INTO result VALUES (?, {', '.join('?' * len(COLUMNS))})",
                ((sid, *(_votes(r[k]) if k == "votes" and k in r else r.get(k) for k in COLUMNS))
                 for r in _rows(reader)))
        _done(conn, c["sha"], path)
        fresh.add(sid)
        _prune(conn, source_id, fresh)
    out["replaced" if existing or c.get("changed") else "loaded"].append(path)


def load_turnout_map(path=DEFAULT_TURNOUT_MAP):
    """{layout name: layout}, in file order (the order layout_for tries them)."""
    with open(path, "rb") as f:
        return tomllib.load(f)["layout"]


def layout_for(turnout_map, source_id, header):
    """(name, layout) of the first layout matching the source id prefix and the exact header, else None."""
    for name, layout in turnout_map.items():
        if any(source_id.startswith(p) for p in layout["prefixes"]) and layout["header"] == header:
            return name, layout
    return None


def _count(v):
    return int(v) if v is not None and v.isascii() and v.isdigit() else None


TURNOUT_UNIT_COLUMNS = ["county_id", "county_name", "precinct_id", "precinct_name", "contest_id"]


def _load_turnout(conn, sid, source_id, path, turnout_map):
    """Turnout rows: unit columns copied when the CSV has them, registered voters and ballots cast from the
    columns the layout names, and the whole row as JSON. No layout: raw only, noted."""
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        found = layout_for(turnout_map, source_id, r.fieldnames or [])
        if found is None:
            _note(conn, path, "turnout_layout_unknown", ",".join(r.fieldnames or []))
        name, layout = found or (None, {})
        reg, bal = layout.get("registered"), layout.get("ballots")
        conn.executemany(
            "INSERT INTO turnout VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ((sid, name, *(row.get(c) if found else None for c in TURNOUT_UNIT_COLUMNS),
              _count(row.get(reg)) if reg else None, _count(row.get(bal)) if bal else None, json.dumps(row))
             for row in r))


def _prune(conn, source_id, fresh=()):
    """Keep rows for the latest KEEP snapshots. A snapshot pruned in the same load that brought it in was never
    compared by check 1: noted (pruned_unchecked)."""
    rows = conn.execute("SELECT snapshot_id, csv_path FROM snapshot WHERE source_id = ? AND pruned = 0 "
                        "ORDER BY first_seen_utc DESC", (source_id,)).fetchall()
    for sid, path in rows[KEEP:]:
        if sid in fresh:
            _note(conn, path, "pruned_unchecked", "check 1 never saw it as the newer side")
        conn.execute("DELETE FROM result WHERE snapshot_id = ?", (sid,))
        conn.execute("DELETE FROM turnout WHERE snapshot_id = ?", (sid,))
        conn.execute("UPDATE snapshot SET pruned = 1 WHERE snapshot_id = ?", (sid,))


def main(argv=None):
    import argparse
    from collections import Counter
    from pipeline import db_checks
    p = argparse.ArgumentParser(prog="python3 -m pipeline.db")
    p.add_argument("command", choices=["load", "check"])
    p.add_argument("--db", default="data/results.sqlite")
    p.add_argument("--parsed-dir", default="data/parsed")
    p.add_argument("--manifest", default="data/raw/manifest.csv")
    p.add_argument("--source", help="check: one source id")
    p.add_argument("--reports-dir", default="data/reports")
    a = p.parse_args(argv)
    conn = connect(a.db)
    if a.command == "load":
        t0 = time.time()
        out = load(conn, a.parsed_dir, a.manifest)
        for k, v in out.items():
            print(f"{k}: {len(v)}")
        notes = conn.execute("SELECT kind, COUNT(*) FROM load_note GROUP BY kind").fetchall()
        print(f"notes: {dict(notes)}  ({time.time() - t0:.0f} s)")
        return out
    out_dir = os.path.join(a.reports_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    counts = db_checks.run_checks(conn, out_dir, a.source)
    for name, (n_exc, n_nc) in counts.items():
        print(f"{name}: {n_exc} exceptions, {n_nc} not checked")
        with open(os.path.join(out_dir, f"{name}-not-checked.csv"), newline="") as f:
            reasons = Counter((r["scope"], r["reason"]) for r in csv.DictReader(f) if r["scope"] != "line")
        for (scope, reason), n in sorted(reasons.items()):
            print(f"  not checked ({scope}): {reason}" + (f" x{n}" if n > 1 else ""))
    print(f"reports -> {out_dir}")
    return counts


if __name__ == "__main__":
    main()
