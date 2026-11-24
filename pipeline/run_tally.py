"""Fetch and/or parse Tally ENR results (AR, ND), county level.

A fetch pass saves election info (<id>-info), the contest list (<id>-list), then one
results file per contest type (<id>-results-<T>), through pipeline/fetch.py (which enforces
min_interval_s per source id), pausing request_gap_s between requests. Any failure stops
the pass: with four requests there is nothing worth salvaging. A completed pass writes a
record <raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_tally fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_tally parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_tally fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv (common columns) and prints the
summary: list lengths, plus the first 5 entries of every non-empty anomaly list.
"""
import argparse
import json
import os
import time
import tomllib
import urllib.parse

from pipeline.fetch import fetch
from pipeline.readers.tally import parse_pass
from pipeline.schema import write_csv

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


def parse_record(source_id, record_path, parsed_dir="data/parsed", base_dir="."):
    rows, summary = parse_pass(record_path, base_dir=base_dir)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".csv")
    n = write_csv(rows, out)
    print(f"{source_id}: {n} rows -> {out}")
    for k, v in summary.items():
        if isinstance(v, list):
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
