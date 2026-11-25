"""Cut Delaware test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_de_fixture PASS_RECORD OUT_DIR --contests "U.S. Senator,Attorney General" \
        --districts "01-01,02-27" --rds "01,02"

Writes OUT_DIR/de_<kind>.json and de_pass.json: statewide and county lines of the given contest titles,
district lines of those contests in the given election districts ("Election District <code>"), and
turnout rows of the given representative districts plus "ALL".
"""
import argparse
import json
import os


def _load(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def cut(record_path, out_dir, contests, districts, rds):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    names = {f"Election District {d}" for d in districts}
    out = {
        "statewide": [x for x in _load(paths["statewide"]) if x["Contest Title"] in contests],
        "district": [x for x in _load(paths["district"]) if x["Contest Title"] in contests and x["Election District"] in names],
        "county": [x for x in _load(paths["county"]) if x["Contest Title"] in contests],
        "turnout": [x for x in _load(paths["turnout"]) if x["Representative District"] in rds or x["Representative District"] == "ALL"],
    }
    os.makedirs(out_dir, exist_ok=True)
    for kind, obj in out.items():
        with open(os.path.join(out_dir, f"de_{kind}.json"), "w") as f:
            json.dump(obj, f)
    with open(os.path.join(out_dir, "de_pass.json"), "w") as f:
        json.dump(dict({k: v for k, v in rec.items() if k != "files"},
                       files=[{"kind": k, "path": f"de_{k}.json"} for k in out]), f)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--contests", required=True)
    p.add_argument("--districts", required=True)
    p.add_argument("--rds", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, set(a.contests.split(",")), a.districts.split(","), set(a.rds.split(",")))
