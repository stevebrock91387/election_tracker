"""Fetch and/or parse Delaware results: the Department of Elections' ENR JSON files.

A fetch pass saves Election_StatewideResults_ID_<id>.json (<id>-statewide),
Election_ByElectionDistrict_ID_<id>.json (<id>-district), Election_ByCountyWithWilmington_ID_<id>.json
(<id>-county) and Election_VoterTurnout_ID_<id>.json (<id>-turnout), each with ?t=<unix ms> as the
results page does, through pipeline/fetch.py, request_gap_s apart. Any failure stops the pass.

    /opt/homebrew/bin/python3 -m pipeline.run_de fetch SOURCE_ID
"""
import argparse
import json
import os
import time
import tomllib

from pipeline.fetch import fetch

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_de.toml")
FILES = [("statewide", "StatewideResults"), ("district", "ByElectionDistrict"), ("county", "ByCountyWithWilmington"),
         ("turnout", "VoterTurnout")]


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None, sleep=time.sleep, clock=time.time):
    kw = dict(raw_dir=raw_dir, opener=opener, ext="json")
    if now is not None:
        kw["now"] = now
    iv, gap, base, eid = src["min_interval_s"], src["request_gap_s"], src["base_url"], src["election_id"]
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    stamp = int(clock() * 1000)
    files = []
    for i, (kind, name) in enumerate(FILES):
        if i:
            sleep(gap)
        files.append({"kind": kind, "path": fetch(f"{source_id}-{kind}", f"{base}Election_{name}_ID_{eid}.json?t={stamp}", iv, **kw)})
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    rec_path = os.path.join(out_dir, f"pass-{started}.json")
    with open(rec_path, "w") as f:
        json.dump({"source_id": source_id, "state": src["state"], "started_utc": started,
                   "exclude_title_prefixes": src["exclude_title_prefixes"],
                   "district_title_prefixes": src["district_title_prefixes"], "files": files}, f, indent=1)
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
