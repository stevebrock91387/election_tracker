"""Cut a Clarity county_json test fixture from a real pass: only the given contest keys.

    /opt/homebrew/bin/python3 -I pipeline/make_clarity_json_fixture.py PASS_RECORD OUT_DIR PREFIX KEY [KEY ...]

Run from the repository root (the pass record's paths are relative to it). Writes <PREFIX>_<kind>.json
(and <PREFIX>_type_<n>.json per vote type) plus <PREFIX>_pass.json, whose paths are relative to OUT_DIR.
Files are re-serialized JSON (not byte for byte): sum.json, vt.json and each area file keep only the
given contests (an area left with none is dropped); status.json is kept whole. Choice names after the
first "Write-In" choice of a contest are replaced by "Write-in name <n>": some counties list each
write-in name, often a private individual.
"""
import gzip
import json
import os
import sys


def load(path):
    with open(path, "rb") as f:
        data = f.read()
    return json.loads(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)


def redact(contest):
    names, n = [], None
    for name in contest["CH"]:
        if n is not None:
            n += 1
            names.append(f"Write-in name {n}")
            continue
        names.append(name)
        if name.lower().startswith("write-in"):
            n = 0
    contest["CH"] = names
    return contest


def trim_areas(doc, keys):
    out = []
    for a in doc["Contests"]:
        idx = [i for i, k in enumerate(a["C"]) if k in keys]
        if idx:
            out.append({"A": a["A"], "C": [a["C"][i] for i in idx], "V": [a["V"][i] for i in idx],
                        "T": [a["T"][i] for i in idx]})
    return dict(doc, Contests=out)


def main(record, out_dir, prefix, keys):
    keys = set(keys)
    with open(record) as f:
        rec = json.load(f)
    files, n_type = [], 0
    for x in rec["files"]:
        doc = load(x["path"])
        if x["kind"] == "sum":
            doc = dict(doc, Contests=[redact(c) for c in doc["Contests"] if c["K"] in keys])
        elif x["kind"] == "vt":
            doc = dict(doc, Contests=[c for c in doc["Contests"] if c["K"] in keys])
        elif x["kind"] in ("all", "type"):
            doc = trim_areas(doc, keys)
        name = f"{prefix}_{x['kind']}" + (f"_{n_type}" if x["kind"] == "type" else "") + ".json"
        n_type += x["kind"] == "type"
        with open(os.path.join(out_dir, name), "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        files.append(dict(x, path=name))
    with open(os.path.join(out_dir, f"{prefix}_pass.json"), "w") as f:
        json.dump(dict(rec, files=files), f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
