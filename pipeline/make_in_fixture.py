"""Cut Indiana test fixtures from a real fetch pass.

    /opt/homebrew/bin/python3 -m pipeline.make_in_fixture PASS_RECORD OUT_DIR --counties Adams,Lake

Writes OUT_DIR/in_<kind>.json (in_csv.csv for the CSV) and in_pass.json. Category files keep only
races in the given counties (matched case-insensitively on the race's county) and statewide-summary
races whose office ids remain; regions left with no races are dropped. Turnout keeps those counties
and "Total". The CSV keeps rows of the record's categories (matched by name, case-insensitively) in
those counties. Settings and the category index are kept whole.
"""
import argparse
import csv
import io
import json
import os


def _L(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def _load(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8-sig"))


def cut(record_path, out_dir, counties):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: x["path"] for x in rec["files"]}
    keep = {c.casefold() for c in counties}
    out, cat_names = {}, set()
    for kind, p in paths.items():
        if kind == "csv":
            continue
        obj = _load(p)
        if kind.startswith("offcat-"):
            root = obj["Root"]
            cat_names.add(root["OfficeCategory"]["OFFICE_CATEGORY_NAME"].casefold())
            regions, offices = [], set()
            for reg in _L(root["OfficeCategory"]["Regions"]["Region"]):
                races = []
                for race in _L(reg["Races"]["Race"]):
                    name = race["Jurisdiction"]["JURISDICTION_NAME"]
                    if name == "Indiana":
                        name = reg["MAP_JURISDICTION_NAME"]
                    if name.casefold() in keep:
                        races.append(race)
                        offices.add(race["OFFICEID"])
                if races:
                    reg["Races"]["Race"] = races
                    regions.append(reg)
            root["OfficeCategory"]["Regions"]["Region"] = regions
            root["StatewideSummary"]["Race"] = [r for r in _L(root["StatewideSummary"]["Race"]) if r["OFFICEID"] in offices]
        elif kind == "turnout":
            obj["root"]["CountyTurnout"] = [t for t in obj["root"]["CountyTurnout"]
                                            if t["County"].casefold() in keep or t["County"] == "Total"]
        out[kind] = obj
    with open(paths["csv"], "rb") as f:
        text = f.read().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    head = rows[0]
    ci, ki = head.index("ReportingCountyName"), head.index("OfficeCategory")
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow(head)
    for r in rows[1:]:
        if r[ci].casefold() in keep and r[ki].casefold() in cat_names:
            w.writerow(r)
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for kind in [x["kind"] for x in rec["files"]]:
        name = "in_csv.csv" if kind == "csv" else f"in_{kind}.json"
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            f.write(buf.getvalue() if kind == "csv" else json.dumps(out[kind]))
        files.append({"kind": kind, "path": name})
    with open(os.path.join(out_dir, "in_pass.json"), "w") as f:
        json.dump(dict({k: v for k, v in rec.items() if k != "files"}, files=files), f, indent=1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("record")
    p.add_argument("out_dir")
    p.add_argument("--counties", required=True)
    a = p.parse_args()
    cut(a.record, a.out_dir, a.counties.split(","))
