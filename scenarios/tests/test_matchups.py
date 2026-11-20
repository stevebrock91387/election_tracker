"""matchups.toml loading and validation."""
import os
import tempfile
import unittest

from scenarios.engine import ScenarioError, apply
from scenarios.matchups import DEFAULT_MATCHUPS, load_matchups
from scenarios.units import load_units

STATES = {u.state for u in load_units()}


def load_text(text):
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(text)
    try:
        return load_matchups(f.name, STATES)
    finally:
        os.unlink(f.name)


BASE = '''
[[matchup]]
name = "t"
r_name = "R"
d_name = "D"
national_swing = 0.0
'''


class MatchupsTest(unittest.TestCase):
    def test_loads_shipped_file(self):
        ms = load_matchups(DEFAULT_MATCHUPS, STATES)
        self.assertEqual(len(ms), 4)
        self.assertEqual([m.name for m in ms][0], "vance-vs-shapiro")
        for m in ms:
            self.assertEqual(m.national_swing, 0.0)
            self.assertEqual(m.regional_swing, {})
            self.assertTrue(all(tp.share == 0.0 for tp in m.third_party))

    def test_bad_split_rejected(self):
        bad = BASE + '[[matchup.third_party]]\nname = "X"\nshare = 1.0\nfrom_r = 0.6\nfrom_d = 0.6\n'
        with self.assertRaises(ScenarioError):
            load_text(bad)

    def test_unknown_region_rejected(self):
        bad = BASE + '[matchup.regional_swing]\nXX = 1.0\n'
        with self.assertRaises(ScenarioError):
            load_text(bad)

    def test_shipped_matchups_reproduce_2024(self):
        units = load_units()
        for m in load_matchups(DEFAULT_MATCHUPS, STATES):
            res = apply(units, m)
            self.assertEqual(sum(r.ev for r in res if r.winner == "R"), 312, m.name)
            self.assertEqual(sum(r.ev for r in res if r.winner == "D"), 226, m.name)

    def test_negative_share_rejected(self):
        with self.assertRaises(ScenarioError):
            load_text(BASE + '[[matchup.third_party]]\nname = "X"\nshare = -10.0\nfrom_r = 0.5\nfrom_d = 0.5\n')

    def test_split_outside_0_1_rejected(self):
        with self.assertRaises(ScenarioError):
            load_text(BASE + '[[matchup.third_party]]\nname = "X"\nshare = 1.0\nfrom_r = 1.5\nfrom_d = -0.5\n')

    def test_non_finite_numbers_rejected(self):
        with self.assertRaises(ScenarioError):
            load_text(BASE.replace("national_swing = 0.0", "national_swing = nan"))
        with self.assertRaises(ScenarioError):
            load_text(BASE + '[matchup.regional_swing]\nPA = inf\n')
        with self.assertRaises(ScenarioError):
            load_text(BASE + '[[matchup.third_party]]\nname = "X"\nshare = inf\nfrom_r = 0.5\nfrom_d = 0.5\n')


if __name__ == "__main__":
    unittest.main()
