"""Cut Vermont test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_vt_fixture PASS_RECORD OUT_DIR \
        --offices federal:4,stateWide:5,senate:CHI CT 1,house:CHI 20 --towns 16,50,63

Writes OUT_DIR/vt_<kind>.json and vt_pass.json. Each results file keeps only the named offices
(statewide and federal by oid, senate and house by district code dc) and, in them, only the given
towns' entries plus the total entry (tid 0). The election file keeps towns and townDistricts for
the given towns. The turnout file keeps those towns without their per-office lists (hl).
Write-in names (isWriteIn true) are replaced by "WRITE-IN <cid>": they name people who received a
write-in vote, many apparently private individuals.
"""
import argparse
import json
import os


def _load(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def _scrub(entry):
    for w in entry.get("wc") or []:
        if w.get("isWriteIn"):
            w["cn"] = f"WRITE-IN {w.get('cid')}"
    return entry


def cut(record_path, out_dir, offices, towns):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    out = {}
    el = _load(paths["election"])
    el["towns"] = [t for t in el.get("towns", []) if t["townId"] in towns]
    el["townDistricts"] = [t for t in el.get("townDistricts", []) if t["townId"] in towns]
    out["election"] = el
    for kind, keep in offices.items():
        data = _load(paths[kind])
        for block in data["d"]:
            kept = []
            for o in block.get("o") or []:
                key = str(o["oid"]) if kind in ("federal", "stateWide") else o.get("dc")
                if key in keep:
                    o["cs"] = [_scrub(c) for c in o["cs"] if c["tid"] == 0 or c["tid"] in towns]
                    o.pop("cd", None)
                    kept.append(o)
            block["o"] = kept
            if "dist" in block:
                block["dist"] = [x for x in block["dist"] if x.get("dc") in keep]
        out[kind] = data
    t = _load(paths["turnOut"])
    t["d"] = [{k: v for k, v in x.items() if k != "hl"} for x in t["d"] if x["tid"] in towns]
    out["turnOut"] = t
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for kind, obj in out.items():
        with open(os.path.join(out_dir, f"vt_{kind}.json"), "w") as f:
            json.dump(obj, f)
        files.append({"kind": kind, "path": f"vt_{kind}.json"})
    with open(os.path.join(out_dir, "vt_pass.json"), "w") as f:
        json.dump({"source_id": rec["source_id"], "state": rec["state"], "snapshot": rec["snapshot"], "files": files},
                  f, indent=1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--offices", required=True, help="kind:key,... (oid for federal/stateWide, dc for senate/house)")
    p.add_argument("--towns", required=True)
    a = p.parse_args()
    offices = {}
    for part in a.offices.split(","):
        kind, key = part.split(":", 1)
        offices.setdefault(kind, set()).add(key)
    cut(a.record, a.out_dir, offices, {int(x) for x in a.towns.split(",")})
