"""Cut Florida test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_fl_fixture PASS_RECORD OUT_DIR --races 120000,160000 --units 12001,12003

Writes OUT_DIR/fl_info.txt, fl_votes.txt, fl_tab.txt and fl_pass.json. Keeps the r and c records of
the given races, the u records of the given units, and the p and V records of both; the tab file
keeps its header and the rows whose county is one of the units and whose race name equals a kept
race's name or the part after its first colon (stripped). Line endings and bytes are kept as is.
"""
import argparse
import json
import os


def _lines(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8").splitlines(keepends=True)


def _fields(line):
    return line.strip().strip("[]").split("|")


def cut(record_path, out_dir, races, units):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    info = _lines(paths["info"])
    keep, names, counties = [], set(), set()
    for line in info:
        f = _fields(line)
        if (f[0] == "r" and f[5] in races) or (f[0] == "c" and f[3] in races) or \
           (f[0] == "p" and f[3] in races and f[4] in units) or (f[0] == "u" and f[4] in units):
            keep.append(line)
        if f[0] == "r" and f[5] in races:
            names |= {f[3].strip(), f[3].split(":", 1)[-1].strip()}
        if f[0] == "u" and f[4] in units:
            counties.add(f[3].strip())
    votes = [l for l in _lines(paths["votes"]) if _fields(l)[4] in races and _fields(l)[5] in units]
    tab = _lines(paths["tab"])
    head = tab[0].rstrip("\r\n").split("\t")
    ri, ci = head.index("RaceName"), head.index("CountyName")
    tab = tab[:1] + [l for l in tab[1:] if l.split("\t")[ri].strip() in names and l.split("\t")[ci].strip() in counties]
    os.makedirs(out_dir, exist_ok=True)
    for kind, lines in (("info", keep), ("votes", votes), ("tab", tab)):
        with open(os.path.join(out_dir, f"fl_{kind}.txt"), "wb") as f:
            f.write("".join(lines).encode("utf-8"))
    with open(os.path.join(out_dir, "fl_pass.json"), "w") as f:
        json.dump({"source_id": rec["source_id"], "state": rec["state"],
                   "files": [{"kind": k, "path": f"fl_{k}.txt"} for k in ("info", "votes", "tab")]}, f, indent=1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--races", required=True)
    p.add_argument("--units", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, set(a.races.split(",")), set(a.units.split(",")))
