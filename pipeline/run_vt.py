"""Fetch and/or parse Vermont results: the SOS static JSON (one snapshot per pass).

A fetch pass reads <base_url>elections/<guid>.json (source id <id>-election), which names one
timestamped file per tab, then the files for the source's kinds (source ids <id>-<kind>), through
pipeline/fetch.py, 10 s apart. The pass stops (ValueError, no record) when a kind is missing or
disabled, when a path isn't a plain file under elections/, or when the paths carry different
timestamps; any fetch failure also stops it. A completed pass writes
<raw_dir>/<id>/pass-<UTC timestamp>.json with the snapshot timestamp.

    /opt/homebrew/bin/python3 -m pipeline.run_vt fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_vt parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_vt fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv and <UTC timestamp>-turnout.csv, then
prints the summary ("not checked" for a check that could not run).
"""
import argparse
import json
import os
import re
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.vt import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_vt.toml")
PATH = re.compile(r"elections/([0-9a-f-]+)-([a-z]+)-(\d{14})\.json")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _paths(election_path, guid, kinds):
    """{kind: relative path} from the election file, and the shared snapshot timestamp."""
    with open(election_path, "rb") as f:
        el = json.loads(f.read().decode("utf-8-sig"))
    out, stamps = {}, set()
    for kind in kinds:
        entry = el.get(kind) or {}
        path = (entry.get("path") or "").replace("\\", "/")
        m = PATH.fullmatch(path)
        if not entry.get("isEnable") or not m or m.group(1) != guid:
            raise ValueError(f"election file: unusable path for {kind}: {entry!r}")
        out[kind] = path
        stamps.add(m.group(3))
    if len(stamps) != 1:
        raise ValueError(f"election file: paths from different snapshots: {sorted(stamps)}")
    return out, stamps.pop()


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="json")
    if now is not None:
        kw["now"] = now
    iv, gap, base, guid = src["min_interval_s"], src["request_gap_s"], src["base_url"], src["election_guid"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    epath = fetch(f"{source_id}-election", f"{base}elections/{guid}.json", iv, **kw)
    paths, snapshot = _paths(epath, guid, src["kinds"])
    files = [{"kind": "election", "path": epath}]
    for kind in src["kinds"]:
        sleep(gap)
        files.append({"kind": kind, "path": fetch(f"{source_id}-{kind}", base + paths[kind], iv, **kw)})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started, "snapshot": snapshot,
                   "files": files}, f, indent=1)
    return rec_path


def parse_record(source_id, record_path, parsed_dir="data/parsed", base_dir="."):
    rows, summary, turnout = parse_pass(record_path, base_dir=base_dir)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    n = write_csv(rows, stem + ".csv")
    m = write_csv(turnout, stem + "-turnout.csv", TURNOUT_COLUMNS)
    print(f"{source_id}: {n} rows -> {stem}.csv; {m} turnout rows -> {stem}-turnout.csv")
    for k, v in summary.items():
        if v is None:
            print(f"  {k}: not checked")
        elif isinstance(v, list):
            print(f"  {k}: {len(v)}" + (f"  e.g. {v[:5]}" if v else ""))
        else:
            print(f"  {k}: {v}")
    return stem + ".csv"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["fetch", "parse", "fetch-parse"])
    p.add_argument("source_id")
    p.add_argument("record", nargs="?", help="pass record (parse only)")
    p.add_argument("--sources", default=DEFAULT_SOURCES)
    p.add_argument("--raw-dir", default="data/raw")
    p.add_argument("--parsed-dir", default="data/parsed")
    p.add_argument("--base-dir", default=".", help="directory that relative paths in the pass record start from")
    a = p.parse_args(argv)
    sources = load_sources(a.sources)
    if a.source_id not in sources:
        p.error(f"unknown source id {a.source_id!r}; known: {', '.join(sources)}")
    if a.command == "parse":
        if not a.record:
            p.error("parse needs a pass record")
        return parse_record(a.source_id, a.record, a.parsed_dir, a.base_dir)
    if a.record:
        p.error(f"{a.command} takes no pass record")
    rec = fetch_pass(a.source_id, sources[a.source_id], raw_dir=a.raw_dir)
    print(f"{a.source_id}: pass saved -> {rec}")
    if a.command == "fetch-parse":
        return parse_record(a.source_id, rec, a.parsed_dir)
    return rec


if __name__ == "__main__":
    main()
