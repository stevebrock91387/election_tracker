"""Fetch and/or parse Enhanced Voting exports.

    /opt/homebrew/bin/python3 -m pipeline.run_ev fetch SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_ev parse PATH SOURCE_ID
    /opt/homebrew/bin/python3 -m pipeline.run_ev fetch-parse SOURCE_ID

fetch respects each source's min_interval_s (see pipeline/fetch.py). parse
writes <parsed-dir>/<source_id>/<UTC timestamp>.csv and prints the summary.
"""
import argparse
import os
import time
import tomllib

from pipeline.fetch import fetch
from pipeline.readers.enhanced_voting import parse
from pipeline.schema import write_csv

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _parse(path, source_id, state, parsed_dir):
    rows, summary = parse(path, state, source_id)
    out_dir = os.path.join(parsed_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".csv")
    n = write_csv(rows, out)
    print(f"{source_id}: {n} rows -> {out}")
    for k in ("election_name", "created_at", "counties", "has_precincts", "has_vote_types"):
        print(f"  {k}: {summary[k]}")
    print(f"  statewide vs counties: {summary['pairs_compared']} pairs compared, "
          f"{len(summary['mismatches_state_vs_counties'])} mismatches, "
          f"{len(summary['options_only_in_counties'])} county options with no statewide match")
    print(f"  vote-type groups vs total: {len(summary['mismatches_groups_vs_total'])} mismatches, "
          f"{len(summary['groups_not_published'])} with null group counts")
    return out, summary


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["fetch", "parse", "fetch-parse"])
    p.add_argument("args", nargs="+")
    p.add_argument("--sources", default=DEFAULT_SOURCES)
    p.add_argument("--raw-dir", default="data/raw")
    p.add_argument("--parsed-dir", default="data/parsed")
    a = p.parse_args(argv)
    sources = load_sources(a.sources)
    if a.command == "parse":
        path, source_id = a.args
        return _parse(path, source_id, sources[source_id]["state"], a.parsed_dir)
    (source_id,) = a.args
    s = sources[source_id]
    path = fetch(source_id, s["url"], s["min_interval_s"], raw_dir=a.raw_dir)
    print(f"{source_id}: saved {path}")
    if a.command == "fetch-parse":
        return _parse(path, source_id, s["state"], a.parsed_dir)
    return path


if __name__ == "__main__":
    main()
