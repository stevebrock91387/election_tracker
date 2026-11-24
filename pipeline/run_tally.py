"""Fetch and/or parse Tally ENR results (AR, ND), county level.

A fetch pass saves election info (<id>-info), the contest list (<id>-list), then one
results file per contest type (<id>-results-<T>), through pipeline/fetch.py (which enforces
min_interval_s per source id), pausing request_gap_s between requests. Any failure stops
the pass: with four requests there is nothing worth salvaging. A completed pass writes a
record <raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_tally fetch SOURCE_ID
"""
import argparse
import json
import os
import time
import tomllib
import urllib.parse

from pipeline.fetch import fetch

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_tally.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _url(api, endpoint, **params):
    return f"{api}{endpoint}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener)
    if now is not None:
        kw["now"] = now
    api, cid, eid = src["api"], src["cid"], src["election_id"]
    iv, gap = src["min_interval_s"], src["request_gap_s"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    requests = [("info", "", f"{source_id}-info", _url(api, "Election/GetElectionInfo", cId=cid, electionID=eid)),
                ("list", "", f"{source_id}-list", _url(api, "Contest/GetContestSearchList", cid=cid, electionID=eid))]
    requests += [("results", t, f"{source_id}-results-{t}",
                  _url(api, "Contest/GetContestResults", cId=cid, electionID=eid, contestType=t))
                 for t in src["contest_types"]]
    files = []
    for i, (kind, t, sid, url) in enumerate(requests):
        if i:
            sleep(gap)
        files.append({"kind": kind, "type": t, "path": fetch(sid, url, iv, **kw)})

    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started,
                   "election_id": eid, "files": files}, f, indent=1)
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
