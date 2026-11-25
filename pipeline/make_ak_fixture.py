"""Cut Alaska test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_ak_fixture PASS_RECORD OUT_DIR --contests 6,5 --units "01-600 Ketchikan No. 1,District 1 - Absentee"

Writes OUT_DIR/ak_csv.csv (the header and the lines of the given Contest_Ids in the given unit names,
bytes unchanged) and ak_pass.json.
"""
import argparse
import csv
import json
import os


def cut(record_path, out_dir, contests, units):
    with open(record_path) as f:
        rec = json.load(f)
    path = next(x["path"] for x in rec["files"] if x["kind"] == "csv")
    with open(path, "rb") as f:
        lines = f.read().decode("utf-8-sig").splitlines(keepends=True)
    head = next(csv.reader([lines[0]]))
    ni, ci = head.index("Precinct_name"), head.index("Contest_Id")
    kept = [lines[0]] + [l for l in lines[1:] if l.strip() and (lambda r: r[ni] in units and r[ci] in contests)(next(csv.reader([l])))]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "ak_csv.csv"), "w", newline="") as f:
        f.write("".join(kept))
    with open(os.path.join(out_dir, "ak_pass.json"), "w") as f:
        json.dump({"source_id": rec["source_id"], "state": rec["state"], "files": [{"kind": "csv", "path": "ak_csv.csv"}]}, f)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--contests", required=True)
    p.add_argument("--units", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, set(a.contests.split(",")), set(a.units.split(",")))
