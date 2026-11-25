"""Cut DC test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_dc_fixture PASS_RECORD OUT_DIR --contests -2,-1,4,5 --precincts 1,20

Writes OUT_DIR/dc_info.json, dc_csv.csv, dc_citywide.json and dc_pass.json. The CSV keeps rows of the
given contests in the given precincts (bytes of kept lines unchanged); the citywide JSON keeps the
given contests; the info file is kept whole.
"""
import argparse
import csv
import io
import json
import os


def cut(record_path, out_dir, contests, precincts):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    with open(paths["csv"], "rb") as f:
        lines = f.read().decode("utf-8-sig").splitlines(keepends=True)
    head = next(csv.reader([lines[0]]))
    ci, pi = head.index("ContestNumber"), head.index("PrecinctNumber")
    kept = [lines[0]] + [l for l in lines[1:] if l.strip() and (lambda r: r[ci] in contests and r[pi] in precincts)(
        next(csv.reader([l])))]
    with open(paths["citywide"], "rb") as f:
        city = [c for c in json.loads(f.read().decode("utf-8-sig")) if str(c.get("ContestNumber")) in contests]
    os.makedirs(out_dir, exist_ok=True)
    with open(paths["info"], "rb") as f, open(os.path.join(out_dir, "dc_info.json"), "wb") as g:
        g.write(f.read())
    with open(os.path.join(out_dir, "dc_csv.csv"), "w", newline="") as f:
        f.write("".join(kept))
    with open(os.path.join(out_dir, "dc_citywide.json"), "w") as f:
        json.dump(city, f)
    with open(os.path.join(out_dir, "dc_pass.json"), "w") as f:
        json.dump({"source_id": rec["source_id"], "state": rec["state"], "csv_link": rec["csv_link"],
                   "files": [{"kind": k, "path": f"dc_{k}.{'csv' if k == 'csv' else 'json'}"} for k in ("info", "csv", "citywide")]}, f)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--contests", required=True)
    p.add_argument("--precincts", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, set(a.contests.split(",")), set(a.precincts.split(",")))
