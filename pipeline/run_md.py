"""Fetch and/or parse Maryland results: the State Board of Elections' live results pages.

A fetch pass saves the 24 county pages, then the office pages and statewide question pages, each
through pipeline/fetch.py under its own id (<id>-county-<n>, <id>-office-<n>, <id>-question-<n>),
request_gap_s apart. A failure stops the pass.

    /opt/homebrew/bin/python3 -m pipeline.run_md fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_md parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_md fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv (no turnout file: the pages carry no
turnout), then prints the summary ("not checked" for a check that could not run).
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.md import parse_pass
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_md.toml")
CONFIG_KEYS = ["counties", "offices", "questions", "office_pages", "question_pages"]


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="html")
    if now is not None:
        kw["now"] = now
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    requests = ([("county", n, src["county_page"]) for n in sorted(src["counties"], key=int)]
                + [("office", n, src["office_page"]) for n in sorted(src["office_pages"], key=int)]
                + [("question", n, src["question_page"]) for n in sorted(src["question_pages"], key=int)])
    files = []
    for i, (kind, n, template) in enumerate(requests):
        if i:
            sleep(src["request_gap_s"])
        path = fetch(f"{source_id}-{kind}-{n}", src["base_url"] + template.format(n=n), src["min_interval_s"], **kw)
        files.append({"kind": kind, "number": n, "path": path})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump(dict({"source_id": source_id, "state": src["state"], "started_utc": started},
                       **{k: src[k] for k in CONFIG_KEYS}, files=files), f, indent=1)
    return rec_path


def parse_record(source_id, record_path, parsed_dir="data/parsed", base_dir="."):
    rows, summary, _ = parse_pass(record_path, base_dir=base_dir)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    n = write_csv(rows, stem + ".csv")
    print(f"{source_id}: {n} rows -> {stem}.csv")
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
