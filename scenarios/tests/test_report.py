"""Totals, tipping point, flip swing, sensitivity and rendering."""
import dataclasses
import unittest

from scenarios.engine import Scenario, ThirdParty, apply
from scenarios.matchups import DEFAULT_MATCHUPS, load_matchups
from scenarios.report import (LABEL, ev_totals, flip_swing, render_csv, render_markdown,
                              sensitivity, tipping_point)
from scenarios.units import Unit, load_units

UNITS = load_units()
VS = load_matchups(DEFAULT_MATCHUPS, {u.state for u in UNITS})[0]


def winner_at(national):
    return ev_totals(apply(UNITS, dataclasses.replace(VS, national_swing=national)))["winner"]


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.results = apply(UNITS, VS)
        self.totals = ev_totals(self.results)

    def test_label_first_line(self):
        tp = tipping_point(self.results)
        md = render_markdown(VS, self.results, self.totals, tp, flip_swing(UNITS, VS), sensitivity(UNITS, VS))
        self.assertEqual(md.splitlines()[0], LABEL)
        self.assertEqual(render_csv(VS, self.results).splitlines()[0], "# " + LABEL)

    def test_2024_totals_and_tipping_point(self):
        self.assertEqual(self.totals["R"], 312)
        self.assertEqual(self.totals["D"], 226)
        self.assertEqual(self.totals["winner"], "R")
        self.assertFalse(self.totals["tie"])
        tp = tipping_point(self.results)
        won = [r for r in self.results if r.winner == "R"]
        won.sort(key=lambda r: (r.r - r.d) / (r.r + r.d + sum(r.third.values()) + r.other), reverse=True)
        cum = 0
        for r in won:
            cum += r.ev
            if cum >= 270:
                self.assertEqual(tp, r.id)
                break

    def test_flip_swing_flips(self):
        flip = flip_swing(UNITS, VS)
        self.assertIsNotNone(flip)
        step = 0.01 if flip > 0 else -0.01
        self.assertEqual(winner_at(flip - step), "R")
        self.assertNotEqual(winner_at(flip + step), "R")

    def test_sensitivity_shape(self):
        rows = sensitivity(UNITS, VS)
        self.assertEqual(len(rows), 41)
        self.assertEqual(rows[0][0], -10.0)
        self.assertEqual(rows[-1][0], 10.0)
        for swing, r_ev, d_ev, note in rows:
            self.assertLessEqual(r_ev + d_ev, 538)
            self.assertEqual(note, "")
        self.assertEqual({sw: (r, d) for sw, r, d, _ in rows}[0.0], (312, 226))

    def test_tie_reported(self):
        units = [Unit("AA", "AA", 269, 600, 400, 0), Unit("BB", "BB", 269, 400, 600, 0)]
        s = Scenario(name="tie", r_name="R", d_name="D")
        res = apply(units, s)
        totals = ev_totals(res)
        self.assertTrue(totals["tie"])
        self.assertIsNone(totals["winner"])
        md = render_markdown(s, res, totals, tipping_point(res), None, [])
        self.assertIn("No majority: House decides", md)

    def test_sensitivity_survives_invalid_rows(self):
        s = dataclasses.replace(VS, third_party=(ThirdParty("X", 5.0, 0.5, 0.5),))
        rows = sensitivity(UNITS, s)
        self.assertEqual(len(rows), 41)
        bad = [row for row in rows if row[1] is None]
        self.assertTrue(bad, "expected some swings to be not computable")
        self.assertIn("DC", bad[0][3])
        res = apply(UNITS, s)
        md = render_markdown(s, res, ev_totals(res), tipping_point(res), flip_swing(UNITS, s), rows)
        self.assertIn("not computable", md)

    def test_flip_line_shows_threshold(self):
        s = dataclasses.replace(VS, national_swing=3.0)
        res = apply(UNITS, s)
        flip = flip_swing(UNITS, s)
        md = render_markdown(s, res, ev_totals(res), tipping_point(res), flip, sensitivity(UNITS, s))
        self.assertAlmostEqual(3.0 + flip, 1.726, places=3)
        self.assertIn(f"at a national swing of {3.0 + flip:+.3f}", md)

    def test_unit_tables_show_shares(self):
        md = render_markdown(VS, self.results, self.totals, tipping_point(self.results), None, [])
        self.assertIn("| R % | D % |", md)
        self.assertIn("Other (2024)", md)
        header = render_csv(VS, self.results).splitlines()[1]
        self.assertIn("r_pct", header)
        self.assertIn("d_pct", header)


if __name__ == "__main__":
    unittest.main()
