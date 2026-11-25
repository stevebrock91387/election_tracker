"""Fetch and/or parse Connecticut results: the CT EMS public-reporting static JSON.

A fetch pass reads <base_url>Version.json (source id <id>-version), then the seven data files
under <base_url><version>/ (source ids <id>-<kind>), through pipeline/fetch.py (which enforces
min_interval_s per source id), pausing request_gap_s between requests. Any failure stops the
pass, including a Version.json that isn't {"Version": <integer>}. Whether an old version's
folder stays online once Version.json moves on is unknown; if it doesn't, the pass fails with the
response saved and the next pass reads the new version. A completed pass writes a record
<raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_ct fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_ct parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_ct fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv (common columns) and
<UTC timestamp>-turnout.csv (TURNOUT_COLUMNS), then prints the summary: list lengths plus the
first 5 entries of every non-empty list; a check that could not run prints "not checked".
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.ct import TURNOUT_COLUMNS, parse_pass
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_ct.toml")
FILES = [("lookup", "Lookupdata.json"), ("state", "stateVotes_Electiondata.json"),
         ("town", "townVotes_Electiondata.json"), ("townstatus", "townStatus_Electiondata.json"),
         ("turnout", "voterTurnout_Electiondata.json"), ("grouping", "candidateGrouping_Electiondata.json"),
         ("officeprecincts", "officePrecincts_Electiondata.json")]


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _version(path):
    with open(path, "rb") as f:
        v = json.loads(f.read().decode("utf-8-sig")).get("Version")
    if not isinstance(v, int) or isinstance(v, bool):
        raise ValueError(f"Version.json has no integer Version: {v!r}")
    return v


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="json")
    if now is not None:
        kw["now"] = now
    iv, gap, base = src["min_interval_s"], src["request_gap_s"], src["base_url"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    vpath = fetch(f"{source_id}-version", base + "Version.json", iv, **kw)
    try:
        version = _version(vpath)
    except (ValueError, AttributeError, UnicodeDecodeError) as e:
        raise ValueError(f"{source_id}: unreadable Version.json ({vpath}): {e}") from e
    files = [{"kind": "version", "path": vpath}]
    for kind, name in FILES:
        sleep(gap)
        files.append({"kind": kind, "path": fetch(f"{source_id}-{kind}", f"{base}{version}/{name}", iv, **kw)})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started, "version": version,
                   "office_types": src["office_types"], "files": files}, f, indent=1)
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
