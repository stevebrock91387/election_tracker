"""Fetch and/or parse Indiana results: the Indiana ENR category JSON plus the precinct CSV.

A fetch pass reads data/settings.json (<id>-settings) for the version letter, then
data/statewideElectionsC_<v>.json (<id>-elections), data/OffCatC_<category>_<v>.json per category
(<id>-offcat-<category>), data/statewideTurnout_<v>.json (<id>-turnout) and
download/AllOfficeResults.csv (<id>-csv), through pipeline/fetch.py, 10 s apart. A settings file
without a one-letter VersionType stops the pass (ValueError, no record); so does any fetch failure.

    /opt/homebrew/bin/python3 -m pipeline.run_in fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_in parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_in fetch-parse SOURCE_ID

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
from pipeline.readers.in_ import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_in.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _settings(path):
    with open(path, "rb") as f:
        root = json.loads(f.read().decode("utf-8-sig"))
    root = root.get("Root", root) if isinstance(root, dict) else {}
    v = root.get("VersionType") if isinstance(root, dict) else None
    if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z]", v):
        raise ValueError(f"settings.json: no one-letter VersionType: {v!r}")
    return v, str(root.get("VersionCode", ""))


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="json")
    if now is not None:
        kw["now"] = now
    iv, gap, base = src["min_interval_s"], src["request_gap_s"], src["base_url"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    spath = fetch(f"{source_id}-settings", base + "data/settings.json", iv, **kw)
    vtype, vcode = _settings(spath)
    requests = [("elections", f"data/statewideElectionsC_{vtype}.json", "json")]
    requests += [(f"offcat-{c}", f"data/OffCatC_{c}_{vtype}.json", "json") for c in src["categories"]]
    requests += [("turnout", f"data/statewideTurnout_{vtype}.json", "json"), ("csv", "download/AllOfficeResults.csv", "csv")]
    files = [{"kind": "settings", "path": spath}]
    for kind, path, ext in requests:
        sleep(gap)
        files.append({"kind": kind, "path": fetch(f"{source_id}-{kind}", base + path, iv, **dict(kw, ext=ext))})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started, "version_type": vtype,
                   "version_code": vcode, "categories": src["categories"], "files": files}, f, indent=1)
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
