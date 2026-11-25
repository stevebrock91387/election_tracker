"""Cut Louisiana test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_la_fixture PASS_RECORD OUT_DIR --races 67997,70199 --parishes 05,17

Writes OUT_DIR/la_<kind>.json and la_pass.json: the races and votes files keep only the given races;
the parish and early files of those races keep only the given parishes.
"""
import argparse
import json
import os


def _load(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def cut(record_path, out_dir, races, parishes):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    out = {}
    for kind in ("races", "votes"):
        obj = _load(paths[kind])
        obj["Races"]["Race"] = [r for r in obj["Races"]["Race"] if r["ID"] in races]
        out[kind] = obj
    for r in [x for x in rec["races"] if x in races]:
        p = _load(paths[f"parish-{r}"])
        p["Parishes"]["Parish"] = [x for x in p["Parishes"]["Parish"] if x["ParishValue"] in parishes]
        out[f"parish-{r}"] = p
        e = _load(paths[f"early-{r}"])
        e["EarlyVoting"]["Parish"] = [x for x in e["EarlyVoting"]["Parish"] if x["ParishValue"] in parishes]
        out[f"early-{r}"] = e
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for kind, obj in out.items():
        with open(os.path.join(out_dir, f"la_{kind}.json"), "w") as f:
            json.dump(obj, f)
        files.append({"kind": kind, "path": f"la_{kind}.json"})
    with open(os.path.join(out_dir, "la_pass.json"), "w") as f:
        json.dump({"source_id": rec["source_id"], "state": rec["state"], "election_date": rec["election_date"],
                   "races": [x for x in rec["races"] if x in races], "parishes": rec["parishes"], "files": files}, f)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--races", required=True)
    p.add_argument("--parishes", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, set(a.races.split(",")), set(a.parishes.split(",")))
