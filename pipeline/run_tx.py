"""Fetch and/or parse Texas results: the Civix ENR statewide file plus its county file.

A fetch pass saves the statewide file (<id>-election), then the county file (<id>-county),
through pipeline/fetch.py (which enforces min_interval_s per source id), pausing
request_gap_s between them. Any failure stops the pass. The URLs have no file extension, so
files are saved as .json. A completed pass writes a record <raw_dir>/<id>/pass-<UTC timestamp>.json
that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_tx fetch SOURCE_ID
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_tx.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="json")
    if now is not None:
        kw["now"] = now
    iv, gap = src["min_interval_s"], src["request_gap_s"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    requests = [("election", f"{source_id}-election", src["election_url"]),
                ("county", f"{source_id}-county", src["county_url"])]
    files = []
    for i, (kind, sid, url) in enumerate(requests):
        if i:
            sleep(gap)
        files.append({"kind": kind, "path": fetch(sid, url, iv, **kw)})

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
