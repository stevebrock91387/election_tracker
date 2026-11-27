"""Fetch and/or parse county results-report PDFs (Camden, Sussex NJ; docs/pdfreport.md).

A fetch pass saves each configured file (<id>-<kind>) through pipeline/fetch.py, 5 s apart, and writes
a pass record. Camden: one request; Sussex: two. Needs pypdfium2 (requirements.txt, .venv).

    .venv/bin/python -m pipeline.run_pdfreport fetch SOURCE_ID
    .venv/bin/python -m pipeline.run_pdfreport parse SOURCE_ID PASS_RECORD
    .venv/bin/python -m pipeline.run_pdfreport fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv and -turnout.csv, and prints the summary
("not checked" for a check that could not run).
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.pdfreport import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_pdfreport.toml")
GAP_S = 5


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="pdf")
    if now is not None:
        kw["now"] = now
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    files = []
    for i, (kind, url) in enumerate(src["files"].items()):
        if i:
            sleep(GAP_S)
        files.append({"kind": kind, "path": fetch(f"{source_id}-{kind}", url, src["min_interval_s"], **kw)})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "county": src["county"], "layout": src["layout"],
                   "started_utc": started, "files": files}, f, indent=1)
    return rec_path


def parse_record(source_id, record_path, parsed_dir="data/parsed", base_dir="."):
    rows, summary, turnout = parse_pass(record_path, base_dir=base_dir)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    n = write_csv(rows, stem + ".csv")
    write_csv(turnout, stem + "-turnout.csv", TURNOUT_COLUMNS)
    print(f"{source_id}: {n} rows -> {stem}.csv (+ -turnout.csv, {len(turnout)} units)")
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
    src = sources[a.source_id]
    if a.command == "parse":
        if not a.record:
            p.error("parse needs a pass record")
        return parse_record(a.source_id, a.record, a.parsed_dir, a.base_dir)
    if a.record:
        p.error(f"{a.command} takes no pass record")
    rec = fetch_pass(a.source_id, src, raw_dir=a.raw_dir)
    print(f"{a.source_id}: pass saved -> {rec}")
    if a.command == "fetch-parse":
        return parse_record(a.source_id, rec, a.parsed_dir)
    return rec


if __name__ == "__main__":
    main()
