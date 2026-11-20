"""Swing arithmetic: two-party margin shift, regional swing, third-party draw."""
import unittest

from scenarios.engine import Scenario, ScenarioError, ThirdParty, apply
from scenarios.units import Unit, load_units


def margin(res):
    return (res.d - res.r) / (res.r + res.d)


def one(unit, **kw):
    return apply([unit], Scenario(name="t", r_name="R", d_name="D", **kw))[0]


class EngineTest(unittest.TestCase):
    def test_zero_scenario_returns_2024_votes(self):
        units = load_units()
        for u, res in zip(units, apply(units, Scenario(name="z", r_name="R", d_name="D"))):
            self.assertAlmostEqual(res.r, u.r, places=6)
            self.assertAlmostEqual(res.d, u.d, places=6)
            self.assertEqual(res.winner, "R" if u.r > u.d else "D")

    def test_margin_moves_by_swing(self):
        res = one(Unit("XX", "XX", 3, 600, 400, 0), national_swing=5.0)
        self.assertAlmostEqual(margin(res), -0.2 + 0.05, places=12)
        self.assertAlmostEqual(res.r + res.d, 1000, places=9)

    def test_regional_swing_adds_to_national(self):
        units = [Unit("PA", "PA", 19, 600, 400, 0), Unit("OH", "OH", 17, 600, 400, 0)]
        pa, oh = apply(units, Scenario(name="t", r_name="R", d_name="D",
                                       national_swing=1.0, regional_swing={"PA": 2.0}))
        self.assertAlmostEqual(margin(pa), -0.2 + 0.03, places=12)
        self.assertAlmostEqual(margin(oh), -0.2 + 0.01, places=12)

    def test_district_uses_state_regional_swing(self):
        res = one(Unit("NE-2", "NE", 1, 600, 400, 0), regional_swing={"NE": 4.0})
        self.assertAlmostEqual(margin(res), -0.2 + 0.04, places=12)

    def test_third_party_draw_split(self):
        res = one(Unit("XX", "XX", 3, 500, 500, 0),
                  third_party=(ThirdParty("Massie", 10.0, 0.7, 0.3),))
        self.assertAlmostEqual(res.r, 430, places=9)
        self.assertAlmostEqual(res.d, 470, places=9)
        self.assertAlmostEqual(res.third["Massie"], 100, places=9)
        self.assertEqual(res.winner, "D")

    def test_negative_votes_raise(self):
        with self.assertRaises(ScenarioError) as cm:
            one(Unit("WY", "WY", 3, 990, 10, 0), national_swing=-5.0)
        self.assertIn("WY", str(cm.exception))

    def test_third_party_can_win_unit(self):
        res = one(Unit("XX", "XX", 3, 400, 400, 200),
                  third_party=(ThirdParty("Ware", 45.0, 0.5, 0.5),))
        self.assertEqual(res.winner, "Ware")

    def test_exact_tie_reported(self):
        self.assertEqual(one(Unit("XX", "XX", 3, 500, 500, 0)).winner, "TIE")


if __name__ == "__main__":
    unittest.main()
