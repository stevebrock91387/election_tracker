"""Fetch and/or parse Florida results: the Division of Elections' pipe-delimited files plus the
tab-delimited file (for party).

A fetch pass saves the informational file (<id>-info), the votes file (<id>-votes) and the tab file
(<id>-tab) through pipeline/fetch.py, 10 s apart, each URL with ?v=<unix seconds> appended as the
site's own links do. The source's cafile (relative to the repository root) is passed to fetch for
every request. Any failure stops the pass. A completed pass writes a record
<raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_fl fetch SOURCE_ID
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch

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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["fetch"])
    p.add_argument("source_id")
    p.add_argument("--sources", default=DEFAULT_SOURCES)
    p.add_argument("--raw-dir", default="data/raw")
    a = p.parse_args(argv)
    sources = load_sources(a.sources)
    if a.source_id not in sources:
        p.error(f"unknown source id {a.source_id!r}; known: {', '.join(sources)}")
    rec = fetch_pass(a.source_id, sources[a.source_id], raw_dir=a.raw_dir)
    print(f"{a.source_id}: pass saved -> {rec}")
    return rec


if __name__ == "__main__":
    main()
