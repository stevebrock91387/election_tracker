"""Fetch and/or parse Clarity statewide results (county level).

A fetch pass reads <base>/current_ver.txt first and builds every data URL from
that one version, so the files of a pass belong together. Each file has its
own source id (<id>-ver, then <id> for the XML zip, or <id>-sum and <id>-all
for JSON), and pipeline/fetch.py enforces min_interval_s on each.
"""
import os
import re
import tomllib

from pipeline.fetch import FetchError, fetch
from pipeline.readers.clarity import read_body

DEFAULT_SOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources_clarity.toml")


def load_sources(path=DEFAULT_SOURCES):
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_pass(source_id, src, raw_dir="data/raw", now=None, opener=None):
    kw = dict(raw_dir=raw_dir, opener=opener)
    if now is not None:
        kw["now"] = now
    base, iv = src["base"], src["min_interval_s"]
    ver_path = fetch(f"{source_id}-ver", f"{base}/current_ver.txt", iv, **kw)
    version = read_body(ver_path).decode("utf-8", "replace").strip()
    if not re.fullmatch(r"\d+", version):
        raise FetchError(f"{source_id}: current_ver.txt is not a version number: {version[:60]!r} (saved to {ver_path})")
    if src["format"] == "xml":
        paths = {"xml": fetch(source_id, f"{base}/{version}/reports/detailxml.zip", iv, **kw)}
    elif src["format"] == "json":
        paths = {"sum": fetch(f"{source_id}-sum", f"{base}/{version}/json/sum.json", iv, **kw),
                 "all": fetch(f"{source_id}-all", f"{base}/{version}/json/ALL.json", iv, **kw)}
    else:
        raise ValueError(f"{source_id}: unknown format {src['format']!r}")
    return {"version": version, "paths": paths}
