"""Cut Connecticut test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_ct_fixture PASS_RECORD OUT_DIR --offices 19663,19666 --towns 1,64

Writes OUT_DIR/ct_<kind>.json for every file in the pass, plus OUT_DIR/ct_pass.json. Keeps only the
given offices and towns. Lookupdata keeps election, townIds, counties, countyTowns and partyIds
whole, filters officeList and candidateIds to the kept offices, and drops pollingplaceIds,
townPollingPlaces and townParties. Every candidate's AD field (a home address) is removed. The
turnout file keeps its "Total" key.
"""
import argparse
import json
import os


def _load(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def cut(record_path, out_dir, offices, towns):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    data = {k: _load(p) for k, p in paths.items()}
    state = {o: v for o, v in data["state"].items() if o in offices}
    lines = {cid for lst in state.values() for e in lst for cid in e}
    lk = data["lookup"]
    out_lk = {k: lk[k] for k in ("election", "townIds", "counties", "countyTowns", "partyIds")}
    out_lk["officeList"] = [o for o in lk["officeList"] if next(iter(o)) in offices]
    out_lk["candidateIds"] = {cid: {k: v for k, v in c.items() if k != "AD"}
                              for cid, c in lk["candidateIds"].items() if cid in lines}
    out = {
        "version": data["version"],
        "lookup": out_lk,
        "state": state,
        "town": {t: {o: v for o, v in offs.items() if o in offices} for t, offs in data["town"].items() if t in towns},
        "townstatus": {t: v for t, v in data["townstatus"].items() if t in towns},
        "turnout": {t: v for t, v in data["turnout"].items() if t in towns or v.get("NM") == "Total"},
        "grouping": {o: v for o, v in data["grouping"].items() if o in offices},
        "officeprecincts": {o: v for o, v in data["officeprecincts"].items() if o in offices},
    }
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for kind, obj in out.items():
        with open(os.path.join(out_dir, f"ct_{kind}.json"), "w") as f:
            json.dump(obj, f, indent=0)
        files.append({"kind": kind, "path": f"ct_{kind}.json"})
    with open(os.path.join(out_dir, "ct_pass.json"), "w") as f:
        json.dump({"source_id": rec["source_id"], "state": rec["state"], "version": rec["version"],
                   "office_types": rec["office_types"], "files": files}, f, indent=1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--offices", required=True)
    p.add_argument("--towns", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, set(a.offices.split(",")), set(a.towns.split(",")))
