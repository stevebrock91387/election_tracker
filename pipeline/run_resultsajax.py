"""Fetch and/or parse ResultsAjax-engine state results (MT, NE, NM, OR, SD), county level.

A fetch pass reads each configured results page for its race list, then each media
CSV (statewide totals, where the state publishes one), then one county JSON per race.
Every file goes through pipeline/fetch.py under its own source id (<id>-page-<T>,
<id>-media-<T>, <id>-race-<raceID>), which enforces min_interval_s per source id; the
pass also pauses request_gap_s between consecutive requests. A failed page or media CSV
stops the pass; a failed race is listed and the pass goes on. The pass writes a record
<raw_dir>/<id>/pass-<UTC timestamp>.json that the parse step reads.

    /opt/homebrew/bin/python3 -m pipeline.run_resultsajax fetch SOURCE_ID
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import FetchError, fetch
from pipeline.readers.resultsajax import parse_page

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
    with open(rec) as f:
        r = json.load(f)
    print(f"{a.source_id}: {len(r['files'])} files saved, {len(r['failed_races'])} races failed -> {rec}")
    return rec


if __name__ == "__main__":
    main()
