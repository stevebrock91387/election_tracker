"""Cut NC test fixtures from a real pass record (not run by the tests).

    /opt/homebrew/bin/python3 -m pipeline.make_nc_fixture PASS_RECORD OUT_PREFIX GROUPS COUNTIES

GROUPS and COUNTIES are comma-separated (contest group ids; county names as published).
Writes <prefix>.zip (the same member name, header, line endings and member timestamp, with
only the rows for those groups in those counties), <prefix>_dashboard.txt (the dashboard
rows for those groups, values unchanged) and <prefix>_pass.json (files listed by basename,
plus "_fixture_source_sha256").
"""
import hashlib
import json
import os
import sys
import zipfile


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make(record_path, prefix, groups, counties):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    with zipfile.ZipFile(paths["zip"]) as z:
        info = z.getinfo(rec["member"])
        lines = z.read(info).decode("utf-8").split("\r\n")
    keep = [lines[0]] + [l for l in lines[1:] if l and l.split("\t")[0] in counties and l.split("\t")[3] in groups]
    out_zip = f"{prefix}.zip"
    zi = zipfile.ZipInfo(rec["member"], date_time=info.date_time)
    zi.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(out_zip, "w") as z:
        z.writestr(zi, "\r\n".join(keep) + "\r\n")
    with open(paths["dashboard"]) as f:
        dash = [x for x in json.load(f) if x.get("gid") in groups]
    out_dash = f"{prefix}_dashboard.txt"
    with open(out_dash, "w") as f:
        json.dump(dash, f)
    files = [{"kind": "zip", "path": os.path.basename(out_zip)},
             {"kind": "dashboard", "path": os.path.basename(out_dash)}]
    shas = {os.path.basename(out_zip): _sha(paths["zip"]), os.path.basename(out_dash): _sha(paths["dashboard"])}
    with open(f"{prefix}_pass.json", "w") as f:
        json.dump(dict(rec, files=files, _fixture_source_sha256=shas), f, indent=1)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2], set(sys.argv[3].split(",")), set(sys.argv[4].split(",")))
