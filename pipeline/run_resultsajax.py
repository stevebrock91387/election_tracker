"""Fetch and/or parse ResultsAjax-engine state results (MT, NE, NM, OR, SD), county level.

A fetch pass reads each configured results page for its race list, then each media
CSV (statewide totals, where the state publishes one), then one county JSON per race.
Every file goes through pipeline/fetch.py under its own source id (<id>-page-<T>,
<id>-media-<T>, <id>-race-<raceID>), which enforces min_interval_s per source id; the
pass also pauses request_gap_s between consecutive requests. A failed page or media CSV
stops the pass; a failed race is listed and the pass goes on. The pass writes a record
<raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_resultsajax fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_resultsajax parse SOURCE_ID PASS_RECORD
    /opt/homebrew/bin/python3 -m pipeline.run_resultsajax fetch-parse SOURCE_ID

parse writes <parsed-dir>/<source_id>/<UTC timestamp>.csv (common columns) and prints the
summary: list lengths, plus the first 5 entries of every non-empty anomaly list.
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import FetchError, fetch
from pipeline.readers.resultsajax import parse_page, parse_pass
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_resultsajax.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep):
    kw = dict(raw_dir=raw_dir, opener=opener)
    if now is not None:
        kw["now"] = now
    iv, gap = src["min_interval_s"], src["request_gap_s"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    n = 0

    def get(sid, url):
        nonlocal n
        if n:
            sleep(gap)
        n += 1
        return fetch(sid, url, iv, **kw)

    files, failed, races = [], [], []
    for t in src["page_types"]:
        path = get(f"{source_id}-page-{t}", f"{src['site']}ResultsSW.aspx?type={t}&map=CTY")
        files.append({"kind": "page", "type": t, "race_id": "", "osn": "", "party": "", "path": path})
        with open(path, "rb") as f:
            for race in parse_page(f.read().decode("utf-8", "replace")):
                if race[1] not in [r[1] for r in races]:
                    races.append(race)
    for t in src["media_types"]:
        path = get(f"{source_id}-media-{t}", f"{src['site']}resultsCSV.aspx?text=All&type={t}&map=CTY")
        files.append({"kind": "media", "type": t, "race_id": "", "osn": "", "party": "", "path": path})
    for t, race_id, osn, party in races:
        url = (f"{src['service_root']}{src['service']}/GetMapData?type={t}&category=CTY"
               f"&raceID={race_id}&osn={osn}&county=0&party={party or 0}")
        try:
            path = get(f"{source_id}-race-{race_id}", url)
        except FetchError as e:
            failed.append({"type": t, "race_id": race_id, "error": str(e)})
            continue
        files.append({"kind": "race", "type": t, "race_id": race_id, "osn": osn, "party": party, "path": path})

    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started,
                   "files": files, "failed_races": failed}, f, indent=1)
    return rec_path


def parse_record(source_id, record_path, parsed_dir="data/parsed", base_dir="."):
    rows, summary = parse_pass(record_path, base_dir=base_dir)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".csv")
    n = write_csv(rows, out)
    print(f"{source_id}: {n} rows -> {out}")
    for k, v in summary.items():
        if k == "counties_per_race":
            counts = sorted(v.values())
            print(f"  {k}: {len(v)} races, {counts[0] if counts else 0}-{counts[-1] if counts else 0} counties")
        elif isinstance(v, list):
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
    with open(rec) as f:
        r = json.load(f)
    print(f"{a.source_id}: {len(r['files'])} files saved, {len(r['failed_races'])} races failed -> {rec}")
    if a.command == "fetch-parse":
        return parse_record(a.source_id, rec, a.parsed_dir)
    return rec


if __name__ == "__main__":
    main()
