"""Fetch and/or parse Florida results: the Division of Elections' pipe-delimited files plus the
tab-delimited file (for party).

A fetch pass saves the informational file (<id>-info), the votes file (<id>-votes) and the tab file
(<id>-tab) through pipeline/fetch.py, 10 s apart, each URL with ?v=<unix seconds> appended as the
site's own links do. The source's cafile (relative to the repository root) is passed to fetch for
every request. Any failure stops the pass. A completed pass writes a record
<raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_fl fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_fl parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_fl fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv (common columns) and prints the summary:
list lengths plus the first 5 entries of every non-empty list; a check that could not run prints
"not checked".
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.fl import parse_pass
from pipeline.schema import write_csv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_SOURCES = os.path.join(HERE, "sources_fl.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep, clock=time.time):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="txt", cafile=os.path.join(REPO, src["cafile"]))
    if now is not None:
        kw["now"] = now
    iv, gap = src["min_interval_s"], src["request_gap_s"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    stamp = int(clock())
    files = []
    for i, kind in enumerate(("info", "votes", "tab")):
        if i:
            sleep(gap)
        files.append({"kind": kind, "path": fetch(f"{source_id}-{kind}", f"{src[kind + '_url']}?v={stamp}", iv, **kw)})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started, "files": files}, f, indent=1)
    return rec_path


def parse_record(source_id, record_path, parsed_dir="data/parsed", base_dir="."):
    rows, summary = parse_pass(record_path, base_dir=base_dir)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".csv")
    n = write_csv(rows, out)
    print(f"{source_id}: {n} rows -> {out}")
    for k, v in summary.items():
        if v is None:
            print(f"  {k}: not checked")
        elif isinstance(v, list):
            print(f"  {k}: {len(v)}" + (f"  e.g. {v[:5]}" if v else ""))
        else:
            print(f"  {k}: {v}")
    return out


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
