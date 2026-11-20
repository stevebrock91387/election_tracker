"""Cut a small test fixture from a real Enhanced Voting export. Values are copied, never changed.

    /opt/homebrew/bin/python3 -m pipeline.make_ev_fixture SRC OUT --county "Greenlee County" --contests AZ-6,AZ-10

Keeps the top-level fields, statewide ballot items for the listed contests,
and only the named county (with its items filtered to the same contests).
Adds "_fixture_source_sha256" with the SHA-256 of SRC.
"""
import argparse
import hashlib
import json


def make_fixture(src, out, county, contests):
    with open(src, "rb") as f:
        raw = f.read()
    d = json.loads(raw)
    keep = set(contests)
    fx = {k: v for k, v in d.items() if k not in ("results", "localResults")}
    fx["_fixture_source_sha256"] = hashlib.sha256(raw).hexdigest()
    res = dict(d["results"])
    res["ballotItems"] = [b for b in d["results"]["ballotItems"] if b["id"] in keep]
    fx["results"] = res
    locs = []
    for c in d.get("localResults") or []:
        if c["name"] == county:
            c = dict(c)
            c["ballotItems"] = [b for b in c["ballotItems"] if b["id"] in keep]
            locs.append(c)
    if not locs:
        raise SystemExit(f"county {county!r} not found in {src}")
    fx["localResults"] = locs
    with open(out, "w") as f:
        json.dump(fx, f, indent=1, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--county", required=True)
    p.add_argument("--contests", required=True)
    a = p.parse_args()
    make_fixture(a.src, a.out, a.county, a.contests.split(","))
