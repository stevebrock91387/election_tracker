"""Run every matchup and write Markdown and CSV reports.

    /opt/homebrew/bin/python3 -m scenarios.run [--matchups PATH] [--out DIR]
"""
import argparse
import os

from scenarios.engine import apply
from scenarios.matchups import DEFAULT_MATCHUPS, load_matchups
from scenarios.report import (LABEL, ev_totals, flip_swing, render_csv, render_markdown,
                              sensitivity, tipping_point)
from scenarios.units import load_units

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def main(argv=None):
    p = argparse.ArgumentParser(description=LABEL)
    p.add_argument("--matchups", default=DEFAULT_MATCHUPS)
    p.add_argument("--out", default=DEFAULT_OUT)
    a = p.parse_args(argv)
    units = load_units()
    os.makedirs(a.out, exist_ok=True)
    print(LABEL)
    for s in load_matchups(a.matchups, {u.state for u in units}):
        results = apply(units, s)
        totals = ev_totals(results)
        md = render_markdown(s, results, totals, tipping_point(results),
                             flip_swing(units, s), sensitivity(units, s))
        for ext, text in (("md", md), ("csv", render_csv(s, results))):
            with open(os.path.join(a.out, f"{s.name}.{ext}"), "w") as f:
                f.write(text)
        print(f"{s.name}: R {totals['R']} D {totals['D']} winner {totals['winner']}")


if __name__ == "__main__":
    main()
