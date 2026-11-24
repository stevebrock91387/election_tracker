"""Cut Texas test fixtures from a real statewide file and county file.

    /opt/homebrew/bin/python3 -m pipeline.make_tx_fixture ELECTION COUNTY OUT_PREFIX --races 5075,3579 --counties 1,2,3

Writes OUT_PREFIX_election.json and OUT_PREFIX_county.json. The statewide file keeps Version,
Home, Lookups.County (all counties; the other lookups are dropped) and the four result sections (Federal, StateWide, StateWideQ,
Districted) filtered to the given races; a section (or its Races) that decodes to null stays null. OfficeSummary,
Race, ReportList and ElementControl are dropped (unused by the reader). The county file keeps
the given county keys, each with only the given races. Values are re-encoded as base64 JSON.
"""
import argparse
import base64
import json

SECTIONS = ("Federal", "StateWide", "StateWideQ", "Districted")


def dec(v):
    return json.loads(base64.b64decode(v))


def enc(o):
    return base64.b64encode(json.dumps(o, ensure_ascii=False).encode("utf-8")).decode("ascii")


def cut(election_path, county_path, out_prefix, races, counties):
    with open(election_path) as f:
        el = json.load(f)
    out = {"Version": el["Version"], "Home": el["Home"], "Lookups": enc({"County": dec(el["Lookups"])["County"]})}
    for k in SECTIONS:
        sec = dec(el[k])
        if sec is not None and sec.get("Races") is not None:
            sec["Races"] = [r for r in sec["Races"] if r["id"] in races]
        out[k] = enc(sec)
    with open(county_path) as f:
        cty = dec(json.load(f)["upload"])
    cut_c = {}
    for key in counties:
        c = dict(cty[key])
        c["Races"] = {oid: r for oid, r in c["Races"].items() if int(oid) in races}
        cut_c[key] = c
    with open(out_prefix + "_election.json", "w") as f:
        json.dump(out, f)
    with open(out_prefix + "_county.json", "w") as f:
        json.dump({"upload": enc(cut_c)}, f)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("election")
    p.add_argument("county")
    p.add_argument("out_prefix")
    p.add_argument("--races", required=True)
    p.add_argument("--counties", required=True)
    a = p.parse_args()
    cut(a.election, a.county, a.out_prefix, {int(x) for x in a.races.split(",")}, a.counties.split(","))
