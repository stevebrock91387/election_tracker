"""Fetch and/or parse Massachusetts results: PD43+ list pages, then one precinct CSV per in-scope contest.

A fetch pass saves the contest list (<id>-search) and the question list (<id>-questions), selects the
contests whose office is in `offices` and the questions whose location is in `question_locations`,
then saves each CSV (<id>-c<election id>, <id>-q<question id>), `request_gap_s` apart, through
pipeline/fetch.py. A failure stops the pass.

    /opt/homebrew/bin/python3 -m pipeline.run_ma fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_ma parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_ma fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv, then prints the summary ("not checked"
for a check that could not run). The source has no turnout figures, so no turnout file is written.
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.ma import parse_pass, parse_questions, parse_search, select
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_ma.toml")
CONFIG_KEYS = ["offices", "question_locations"]


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener)
    if now is not None:
        kw["now"] = now
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base = src["base_url"]
    files, n = [], 0

    def get(sid, url, ext):
        nonlocal n
        if n:
            sleep(src["request_gap_s"])
        n += 1
        return fetch(sid, url, src["min_interval_s"], ext=ext, **kw)

    pages = {}
    for kind in ("search", "questions"):
        path = get(f"{source_id}-{kind}", base + src[f"{kind}_path"], "html")
        files.append({"kind": kind, "path": path})
        with open(path, "rb") as f:
            pages[kind] = f.read().decode("utf-8", "replace")
    contests, questions = parse_search(pages["search"]), parse_questions(pages["questions"])
    cids, qids = select(contests, questions, src["offices"], src["question_locations"])
    for cid in cids:
        path = get(f"{source_id}-c{cid}", base + src["contest_path"].format(id=cid), "csv")
        files.append({"kind": "contest", "id": cid, "path": path})
    for qid in qids:
        path = get(f"{source_id}-q{qid}", base + src["question_path"].format(id=qid), "csv")
        files.append({"kind": "question", "id": qid, "path": path})
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
