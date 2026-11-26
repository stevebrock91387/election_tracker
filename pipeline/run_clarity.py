"""Fetch and/or parse Clarity results: statewide files (county level) and, with format "county_xml" or
"county_json", one county's files (precinct level; New Jersey counties).

A fetch pass reads <base>/current_ver.txt first and builds every data URL from
that one version, so the files of a pass belong together. Each file has its
own source id (<id>-ver, then <id> for the XML zip, or <id>-sum and <id>-all
for JSON), and pipeline/fetch.py enforces min_interval_s on each.

A county_json pass reads sum.json, ALL.json, vt.json and status.json, then one precinct file per vote type
named in vt.json (<id>-sum, -all, -vt, -status, -type-<file stem>), and writes a pass record
<raw-dir>/<id>/pass-<UTC>.json that parse reads. A failure stops the pass.

    /opt/homebrew/bin/python3 -m pipeline.run_clarity fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_clarity parse SOURCE_ID ZIP          (xml, county_xml sources)
    /opt/homebrew/bin/python3 -m pipeline.run_clarity parse SOURCE_ID SUM ALL      (json sources)
    /opt/homebrew/bin/python3 -m pipeline.run_clarity parse SOURCE_ID PASS_RECORD  (county_json sources)
    /opt/homebrew/bin/python3 -m pipeline.run_clarity fetch-parse SOURCE_ID [--force]

fetch-parse remembers the last version it parsed (<raw-dir>/<id>/last-pass-version.txt, written only after
the parse succeeds) and, while current_ver.txt still says that version, fetches nothing else and parses
nothing; --force ignores it. fetch always fetches. county_xml rows are written to the CSV as they are made.

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv (common columns) and,
for XML, <UTC timestamp>-turnout.csv, then prints the summary counts.
"""
import argparse
import csv
import json
import os
import re
import time
import tomllib
import zlib

from pipeline.fetch import FetchError, fetch
from pipeline.readers.clarity import (COUNTY_TURNOUT_COLUMNS, TURNOUT_COLUMNS, parse_county_json, parse_county_xml,
                                      parse_json, parse_xml, read_body)
from pipeline.schema import COLUMNS, write_csv

LAST_VERSION_FILE = "last-pass-version.txt"  # in <raw-dir>/<source id>/; --force ignores it
DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_clarity.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def type_file_name(vote_type):
    """The county site's own rule (its JavaScript): whitespace and "/" become "_"."""
    return re.sub(r"\s", "_", vote_type).replace("/", "_") + ".json"


def _vote_types(path, source_id):
    """vt.json's Types: a list of non-empty strings, else the pass stops (the type files depend on it)."""
    try:
        types = json.loads(read_body(path))["Types"]
    except (ValueError, KeyError, TypeError, OSError, EOFError, zlib.error) as e:
        raise FetchError(f"{source_id}: vt.json has no readable Types ({e!r}; saved to {path})")
    if not isinstance(types, list) or not all(isinstance(t, str) and t for t in types):
        raise FetchError(f"{source_id}: vt.json Types is not a list of names: {str(types)[:80]!r} (saved to {path})")
    if len({type_file_name(t) for t in types}) != len(types):
        raise FetchError(f"{source_id}: vt.json Types repeat a name or a file name: {types!r} (saved to {path})")
    return types


def _county_json_pass(source_id, src, version, raw_dir, kw):
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    j, iv = f"{src['base']}/{version}/json", src["min_interval_s"]
    files = []
    types = None
    for kind, name in (("sum", "sum.json"), ("all", "ALL.json"), ("vt", "vt.json"), ("status", "status.json")):
        files.append({"kind": kind, "vote_type": "", "path": fetch(f"{source_id}-{kind}", f"{j}/{name}", iv, **kw)})
        if kind == "vt":
            types = _vote_types(files[-1]["path"], source_id)
    for t in types:
        name = type_file_name(t)
        files.append({"kind": "type", "vote_type": t,
                      "path": fetch(f"{source_id}-type-{name[:-5]}", f"{j}/{name}", iv, **kw)})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "county": src["county"], "version": version,
                   "started_utc": started, "files": files}, f, indent=1)
    return {"version": version, "record": rec_path}


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, last_version=None):
    """One pass. When current_ver.txt still says last_version, nothing else is fetched and the result is
    {"version", "unchanged": True}: every data URL carries the version, so the files are those of the last
    pass (assumed; Clarity uses the version as the cache key)."""
    kw = dict(raw_dir=raw_dir, opener=opener)
    if now is not None:
        kw["now"] = now
    base, iv = src["base"], src["min_interval_s"]
    ver_path = fetch(f"{source_id}-ver", f"{base}/current_ver.txt", iv, **kw)
    version = read_body(ver_path).decode("utf-8", "replace").strip()
    if not re.fullmatch(r"\d+", version):
        raise FetchError(f"{source_id}: current_ver.txt is not a version number: {version[:60]!r} (saved to {ver_path})")
    if last_version is not None and version == last_version:
        return {"version": version, "unchanged": True}
    if src["format"] == "county_json":
        return _county_json_pass(source_id, src, version, raw_dir, kw)
    if src["format"] in ("xml", "county_xml"):
        paths = {"xml": fetch(source_id, f"{base}/{version}/reports/detailxml.zip", iv, **kw)}
    elif src["format"] == "json":
        paths = {"sum": fetch(f"{source_id}-sum", f"{base}/{version}/json/sum.json", iv, **kw),
                 "all": fetch(f"{source_id}-all", f"{base}/{version}/json/ALL.json", iv, **kw)}
    else:
        raise ValueError(f"{source_id}: unknown format {src['format']!r}")
    return {"version": version, "paths": paths}


def parse_files(source_id, src, paths, parsed_dir="data/parsed", base_dir="."):
    """paths: [zip] for xml sources, [sum, all] for json sources, [pass record] for county_json (its file
    paths are relative to base_dir). Returns the output paths."""
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    if src["format"] == "xml":
        (zip_path,) = paths
        rows, summary, turnout = parse_xml(zip_path, src["state"], source_id)
        write_csv(turnout, stem + "-turnout.csv", TURNOUT_COLUMNS)
        outs = [stem + ".csv", stem + "-turnout.csv"]
    elif src["format"] == "county_xml":
        (zip_path,) = paths
        with open(stem + ".csv", "w", newline="") as f:  # streamed: a county can be over a million rows
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            n = 0

            def sink(row):
                nonlocal n
                w.writerow(row)
                n += 1
            rows, summary, turnout = parse_county_xml(zip_path, src["state"], src["county"], source_id, sink=sink)
        write_csv(turnout, stem + "-turnout.csv", COUNTY_TURNOUT_COLUMNS)
        outs = [stem + ".csv", stem + "-turnout.csv"]
    elif src["format"] == "county_json":
        (record,) = paths
        rows, summary, turnout = parse_county_json(record, base_dir=base_dir)
        write_csv(turnout, stem + "-turnout.csv", COUNTY_TURNOUT_COLUMNS)
        outs = [stem + ".csv", stem + "-turnout.csv"]
    else:
        sum_path, all_path = paths
        rows, summary = parse_json(sum_path, all_path, src["state"], source_id)
        outs = [stem + ".csv"]
    if src["format"] != "county_xml":
        n = write_csv(rows, stem + ".csv")
    print(f"{source_id}: {n} rows -> {', '.join(outs)}")
    for k, v in summary.items():
        if v is None:
            print(f"  {k}: not checked")
        elif isinstance(v, list) and k != "vote_types":
            print(f"  {k}: {len(v)}" + (f"  e.g. {v[:3]}" if v else ""))
        else:
            print(f"  {k}: {v}")
    return outs


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["fetch", "parse", "fetch-parse"])
    p.add_argument("source_id")
    p.add_argument("paths", nargs="*")
    p.add_argument("--sources", default=DEFAULT_SOURCES)
    p.add_argument("--raw-dir", default="data/raw")
    p.add_argument("--parsed-dir", default="data/parsed")
    p.add_argument("--base-dir", default=".", help="county_json: directory the pass record's paths start from")
    p.add_argument("--force", action="store_true",
                   help="fetch-parse: fetch and parse even if the version is the one last parsed")
    a = p.parse_args(argv)
    sources = load_sources(a.sources)
    if a.source_id not in sources:
        p.error(f"unknown source id {a.source_id!r}; known: {', '.join(sources)}")
    src = sources[a.source_id]
    if a.command == "parse":
        need = 2 if src["format"] == "json" else 1
        if len(a.paths) != need:
            p.error(f"{a.source_id} is {src['format']}: parse needs {need} path(s)")
        return parse_files(a.source_id, src, a.paths, a.parsed_dir, a.base_dir)
    if a.paths:
        p.error(f"{a.command} takes no paths")
    state_path = os.path.join(a.raw_dir, a.source_id, LAST_VERSION_FILE)
    last = None
    if a.command == "fetch-parse" and not a.force and os.path.exists(state_path):
        with open(state_path) as f:
            last = f.read().strip() or None
    r = fetch_pass(a.source_id, src, raw_dir=a.raw_dir, last_version=last)
    if r.get("unchanged"):
        print(f"{a.source_id}: version {r['version']} unchanged since the last pass; nothing else fetched or parsed")
        return r
    if src["format"] == "county_json":
        print(f"{a.source_id}: version {r['version']}, pass saved -> {r['record']}")
        out = parse_files(a.source_id, src, [r["record"]], a.parsed_dir) if a.command == "fetch-parse" else r
    else:
        print(f"{a.source_id}: version {r['version']}, saved {r['paths']}")
        order = ["xml"] if src["format"] in ("xml", "county_xml") else ["sum", "all"]
        out = (parse_files(a.source_id, src, [r["paths"][k] for k in order], a.parsed_dir)
               if a.command == "fetch-parse" else r)
    if a.command == "fetch-parse":
        _record_version(state_path, r["version"])  # only after the pass and its parse succeeded
    return out


def _record_version(path, version):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(version + "\n")
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
