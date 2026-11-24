"""Cut Tally test fixtures from a real pass record (not run by the tests).

    /opt/homebrew/bin/python3 -m pipeline.make_tally_fixture PASS_RECORD OUT_PREFIX CONTEST_ID [CONTEST_ID ...]

Writes <prefix>_info.json, <prefix>_list.json, <prefix>_results_<TYPE>.json and
<prefix>_pass.json (files listed by basename, plus "_fixture_source_sha256"). Every
response keeps its envelope (versionID, electionID, lastUpdated, isOfficial, ...).
Results and list keep only the chosen contests; info keeps only the parties those
contests use and the counties, with each county's nested precinct list emptied.
"""
import hashlib
import json
import os
import sys


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make(record_path, prefix, contest_ids):
    with open(record_path) as f:
        rec = json.load(f)
    loaded = {}
    for x in rec["files"]:
        with open(x["path"]) as f:
            loaded[(x["kind"], x["type"])] = json.load(f)
    parties = set()
    files, shas = [], {}
    for x in rec["files"]:
        d = loaded[(x["kind"], x["type"])]
        if x["kind"] == "results":
            cs = {k: v for k, v in d["response"]["contests"].items() if k in contest_ids}
            if not cs:
                continue
            d["response"]["contests"] = cs
            for c in cs.values():
                parties.update(ch["partyID"] for ch in c["choices"] if ch.get("partyID"))
            out = f"{prefix}_results_{x['type']}.json"
        elif x["kind"] == "list":
            d["response"]["contests"] = {k: v for k, v in d["response"]["contests"].items() if k in contest_ids}
            d["response"]["searchList"] = []
            out = f"{prefix}_list.json"
        else:
            continue
        with open(out, "w") as f:
            json.dump(d, f)
        files.append(dict(x, path=os.path.basename(out)))
        shas[os.path.basename(out)] = _sha(x["path"])
    for x in rec["files"]:
        if x["kind"] == "info":
            d = loaded[("info", "")]
            r = d["response"]
            r["parties"] = {k: v for k, v in r["parties"].items() if k in parties}
            r["locations"] = {k: dict(v, locations={}) for k, v in r["locations"].items()}
            r["districts"] = {}
            out = f"{prefix}_info.json"
            with open(out, "w") as f:
                json.dump(d, f)
            files.insert(0, dict(x, path=os.path.basename(out)))
            shas[os.path.basename(out)] = _sha(x["path"])
    with open(f"{prefix}_pass.json", "w") as f:
        json.dump(dict(rec, files=files, _fixture_source_sha256=shas), f, indent=1)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2], set(sys.argv[3:]))
