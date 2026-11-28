"""Step 4 command line: expected vote per county, and the dry-run score.

    /opt/homebrew/bin/python3 -m pipeline.expected.run fetch
    /opt/homebrew/bin/python3 -m pipeline.expected.run check YEAR       # MEDSL vs FEC, per state and office
    /opt/homebrew/bin/python3 -m pipeline.expected.run baseline YEAR    # top race per county
    /opt/homebrew/bin/python3 -m pipeline.expected.run registration     # 2026, from the step-3 database
    /opt/homebrew/bin/python3 -m pipeline.expected.run compute TARGET   # reads the two baselines + registration
    /opt/homebrew/bin/python3 -m pipeline.expected.run score TARGET     # reads expected-TARGET.csv + the database
    /opt/homebrew/bin/python3 -m pipeline.expected.run all TARGET       # every stage for TARGET's years

Options: --raw-dir (data/raw), --out-dir (data/expected), --db (data/results.sqlite). Outputs in --out-dir:
check-<year>.csv (state, office, passed, reason, differences as JSON), check-<year>-no-county.csv,
baseline-<year>.csv and
-listed.csv, registration-2026.csv and -listed.csv, expected-<target>.csv and -listed.csv,
actuals-<target>.csv and -listed.csv, score-<target>.csv, score-<target>-not-scored.csv and
score-<target>-summary.csv. Each stage prints a summary, including every fix applied and its row count.
"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import time

from pipeline.expected import inputs
from pipeline.expected.baseline import BASELINE_COLUMNS, baselines
from pipeline.expected.check import check
from pipeline.expected.compute import EXPECTED_COLUMNS, expected, norm_county
from pipeline.expected.fec import read_fec
from pipeline.expected.medsl import apply_fixes, county_totals, load_fixes, read_precincts
from pipeline.expected.registration import registration_2026
from pipeline.expected.score import actuals_2026, score

COMPARABLE = {2026: (2018, 2022)}


def _write(path, columns, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([r[c] for c in columns] if isinstance(r, dict) else list(r))


def _read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def stage_check(year, a, medsl=None):
    paths = (medsl or {}).get(year) or inputs.medsl_paths(year)
    applied = []
    totals, notes = county_totals(apply_fixes(read_precincts(paths, year), load_fixes(), applied, year))
    fec_path = inputs.latest_fec(year, a.raw_dir)
    fec_notes = {}
    checks = check(totals, read_fec(fec_path, year, fec_notes), year, notes)
    _write(os.path.join(a.out_dir, f"check-{year}.csv"), ["state", "office", "passed", "reason", "differences"],
           [(st, off, c["passed"], c["reason"], json.dumps(c["differences"])) for (st, off), c in sorted(checks.items())])
    passed = sum(c["passed"] for c in checks.values())
    named = sum(c["reason"] == "passed (named candidates)" for c in checks.values())
    print(f"check {year}: {passed}/{len(checks)} state-offices pass, {named} of them on named candidates only "
          f"(FEC {fec_path})")
    for st_off, c in sorted(checks.items()):
        if not c["passed"]:
            print(f"  {st_off[0]} {st_off[1]}: {c['reason']} ({len(c['differences'])} contest(s))")
    for fid, n in applied:
        print(f"  fix {fid}: {n} row(s) matched")
    print(f"  MEDSL rows with no county, by state: {dict(notes['blank_county'])} "
          f"(votes per pseudo-county in check-{year}-no-county.csv)")
    _write(os.path.join(a.out_dir, f"check-{year}-no-county.csv"), ["state", "county_fips", "county_name", "votes"],
           [k + (v,) for k, v in sorted(notes["no_county"].items())])
    print(f"  FEC unopposed (no votes): {fec_notes['unopposed']}")
    prov = {"medsl_source": inputs.config()["medsl_source"][str(year)], "fec_file_sha256": _sha256(fec_path)}
    return totals, checks, prov


def stage_baseline(year, a, medsl=None):
    totals, checks, prov = stage_check(year, a, medsl)
    rows, listed = baselines(totals, checks, year, prov)
    _write(os.path.join(a.out_dir, f"baseline-{year}.csv"), BASELINE_COLUMNS, rows)
    _write(os.path.join(a.out_dir, f"baseline-{year}-listed.csv"), ["state", "county_fips", "county_name", "reason"], listed)
    by = {}
    for r in rows:
        by[r["top_office"]] = by.get(r["top_office"], 0) + 1
    print(f"baseline {year}: {len(rows)} counties ({by}); {len(listed)} listed with no eligible office")
    ratios = sorted((r["governor_vs_federal"], r["state"], r["county_name"]) for r in rows if r["governor_vs_federal"] != "")
    if ratios:
        hi = [f"{st} {n} {x}" for x, st, n in ratios[-3:][::-1]]
        print(f"  Governor rows vs the county's larger federal office: {len(ratios)}, min {ratios[0][0]}, "
              f"max {ratios[-1][0]} ({'; '.join(hi)}); {sum(x > 1.25 for x, _, _ in ratios)} above 1.25")
    return rows, listed


def stage_registration(a):
    conn = sqlite3.connect(a.db)
    rows, listed = registration_2026(conn)
    conn.close()
    _write(os.path.join(a.out_dir, "registration-2026.csv"),
           ["state", "county_name", "year", "registered", "source_id", "snapshot_id"], [dict(r, year=2026) for r in rows])
    _write(os.path.join(a.out_dir, "registration-2026-listed.csv"), ["state", "source_id", "county_name", "reason"], listed)
    print(f"registration 2026: {len(rows)} counties in {len({r['state'] for r in rows})} states; {len(listed)} listed")
    return rows


def _baseline_rows(path):
    return [dict(r, votes=int(r["votes"]), year=int(r["year"])) for r in _read(path)]


def stage_compute(target, a):
    years = COMPARABLE[target]
    base = {y: _baseline_rows(os.path.join(a.out_dir, f"baseline-{y}.csv")) for y in years}
    listed_in = {y: [tuple(r.values()) for r in _read(os.path.join(a.out_dir, f"baseline-{y}-listed.csv"))] for y in years}
    reg = {}
    for r in _read(os.path.join(a.out_dir, "registration-2026.csv")):
        reg[(r["state"], norm_county(r["county_name"]), int(r["year"]))] = int(r["registered"])
    rows, listed = expected(target, years, base, reg, listed_in)
    _write(os.path.join(a.out_dir, f"expected-{target}.csv"), EXPECTED_COLUMNS, rows)
    _write(os.path.join(a.out_dir, f"expected-{target}-listed.csv"), ["state", "county_fips", "county_name", "reason"], listed)
    methods = {}
    for r in rows:
        methods[r["method"]] = methods.get(r["method"], 0) + 1
    print(f"expected {target}: {len(rows)} counties ({methods}); {len(listed)} listed with no baseline")
    return rows


def stage_score(target, a):
    exp = [dict(r, point=int(r["point"]), low=int(r["low"]), high=int(r["high"]))
           for r in _read(os.path.join(a.out_dir, f"expected-{target}.csv"))]
    conn = sqlite3.connect(a.db)
    actual, listed = actuals_2026(conn)
    conn.close()
    _write(os.path.join(a.out_dir, f"actuals-{target}.csv"),
           ["state", "county_name", "county_id", "top_office", "votes", "source_id", "withheld"], actual)
    _write(os.path.join(a.out_dir, f"actuals-{target}-listed.csv"), ["state", "source_id", "county_name", "reason"], listed)
    per, summary = score(exp, actual)
    _write(os.path.join(a.out_dir, f"score-{target}.csv"),
           ["state", "county", "county_fips", "actual", "point", "low", "high", "method", "inside", "miss",
            "miss_pct", "error_pct"], per)
    _write(os.path.join(a.out_dir, f"score-{target}-not-scored.csv"), ["state", "county", "reason"], summary["not_scored"])
    cols = ["scored", "inside_share", "median_abs_miss_pct", "p90_abs_miss_pct", "median_abs_error_pct"]
    states = [k for k in summary if k != "not_scored"]
    _write(os.path.join(a.out_dir, f"score-{target}-summary.csv"), ["state"] + cols,
           [[k] + [summary[k][c] for c in cols] for k in states])
    s = summary["ALL"]
    inside = sum(r["inside"] for r in per)
    print(f"score {target}: inside {inside}/{s['scored']}; median |miss| {s['median_abs_miss_pct']}, "
          f"p90 |miss| {s['p90_abs_miss_pct']}, median |actual-point|/point {s['median_abs_error_pct']}; "
          f"{len(summary['not_scored'])} not scored; {len(listed)} actual sources/counties listed")
    return per, summary


def main(argv=None, medsl=None):
    p = argparse.ArgumentParser(prog="pipeline.expected.run")
    p.add_argument("stage", choices=["fetch", "check", "baseline", "registration", "compute", "score", "all"])
    p.add_argument("year", nargs="?", type=int)
    p.add_argument("--raw-dir", default="data/raw")
    p.add_argument("--out-dir", default="data/expected")
    p.add_argument("--db", default="data/results.sqlite")
    a = p.parse_args(argv)
    if a.stage == "fetch":
        for i, y in enumerate(sorted(inputs.config()["fec"])):
            if i:
                time.sleep(2)
            print(inputs.fetch_fec(int(y), a.raw_dir))
    elif a.stage == "check":
        stage_check(a.year, a, medsl)
    elif a.stage == "baseline":
        stage_baseline(a.year, a, medsl)
    elif a.stage == "registration":
        stage_registration(a)
    elif a.stage == "compute":
        stage_compute(a.year, a)
    elif a.stage == "score":
        stage_score(a.year, a)
    else:
        for y in COMPARABLE[a.year]:
            stage_baseline(y, a, medsl)
        stage_registration(a)
        stage_compute(a.year, a)
        stage_score(a.year, a)


if __name__ == "__main__":
    main()
