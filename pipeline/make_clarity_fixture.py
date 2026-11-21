"""Cut small test fixtures from real Clarity downloads. Values are copied, never changed.

    /opt/homebrew/bin/python3 -m pipeline.make_clarity_fixture xml SRC_ZIP OUT_ZIP --contests 20
    /opt/homebrew/bin/python3 -m pipeline.make_clarity_fixture json SUM ALL OUT_SUM OUT_ALL --contests 1000

XML: keeps the header elements and ElectionVoterTurnout whole, and only the
listed contests (with all their counties), in OUT_ZIP/detail.xml, preceded by
a comment giving the SHA-256 of SRC_ZIP.
JSON: keeps the listed contests in sum.json and in every ALL.json area
(including "-1"), written un-gzipped, with "_fixture_source_sha256" =
[sha of SUM, sha of ALL].
"""
import argparse
import hashlib
import io
import json
import xml.etree.ElementTree as ET
import zipfile


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_xml_fixture(src_zip, out_zip, contest_keys):
    keep = set(contest_keys)
    with zipfile.ZipFile(src_zip) as z:
        root = ET.fromstring(z.read("detail.xml"))
    for c in list(root.findall("Contest")):
        if c.get("key") not in keep:
            root.remove(c)
    found = {c.get("key") for c in root.findall("Contest")}
    if found != keep:
        raise SystemExit(f"contests not found in {src_zip}: {sorted(keep - found)}")
    root.insert(0, ET.Comment(f" fixture source sha256 {_sha(src_zip)} "))
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("detail.xml", buf.getvalue())


def make_json_fixture(sum_src, all_src, out_sum, out_all, contest_keys):
    from pipeline.readers.clarity import read_body
    keep = set(contest_keys)
    s = json.loads(read_body(sum_src))
    a = json.loads(read_body(all_src))
    s["Contests"] = [c for c in s["Contests"] if c["K"] in keep]
    if {c["K"] for c in s["Contests"]} != keep:
        raise SystemExit(f"contests not found in {sum_src}")
    for area in a["Contests"]:
        idx = [i for i, k in enumerate(area["C"]) if k in keep]
        for f in ("C", "V", "T"):
            area[f] = [area[f][i] for i in idx]
    shas = [_sha(sum_src), _sha(all_src)]
    for d, out in ((s, out_sum), (a, out_all)):
        d["_fixture_source_sha256"] = shas
        with open(out, "w") as f:
            json.dump(d, f, ensure_ascii=False)
            f.write("\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["xml", "json"])
    p.add_argument("paths", nargs="+")
    p.add_argument("--contests", required=True)
    a = p.parse_args()
    keys = a.contests.split(",")
    if a.kind == "xml":
        make_xml_fixture(*a.paths, keys)
    else:
        make_json_fixture(*a.paths, keys)
