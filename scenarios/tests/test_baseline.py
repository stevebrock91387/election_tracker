"""Baseline units built from official 2024 totals (FEC + ME/NE certificates)."""
import csv
import os
import subprocess
import unittest

from scenarios.units import DEFAULT_DISTRICTS_CSV, DEFAULT_STATES_CSV, load_units


def state_rows():
    with open(DEFAULT_STATES_CSV, newline="") as f:
        return {r["state"]: r for r in csv.DictReader(f)}


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.units = load_units(DEFAULT_STATES_CSV, DEFAULT_DISTRICTS_CSV)

    def test_ev_total_538(self):
        self.assertEqual(sum(u.ev for u in self.units), 538)

    def test_unit_count(self):
        # 48 states (all but ME, NE) + DC + 2 at-large + 5 districts
        self.assertEqual(len(self.units), 56)
        ids = {u.id for u in self.units}
        self.assertNotIn("ME", ids)
        self.assertNotIn("NE", ids)
        self.assertTrue({"ME-AL", "NE-AL", "ME-1", "ME-2", "NE-1", "NE-2", "NE-3"} <= ids)

    def test_district_sums_match_state(self):
        rows = state_rows()
        for st, n in (("ME", 2), ("NE", 3)):
            districts = [u for u in self.units if u.id.startswith(st + "-") and u.id != st + "-AL"]
            self.assertEqual(len(districts), n)
            self.assertEqual(sum(u.r for u in districts), int(rows[st]["r"]))
            self.assertEqual(sum(u.d for u in districts), int(rows[st]["d"]))

    def test_2024_winners_match_fec_awards(self):
        rows = state_rows()
        won = {}
        for u in self.units:
            side = "r" if u.r > u.d else "d"
            won.setdefault(u.state, {"r": 0, "d": 0})[side] += u.ev
        for st, r in rows.items():
            self.assertEqual(won[st]["r"], int(r["ev_awarded_r"]), st)
            self.assertEqual(won[st]["d"], int(r["ev_awarded_d"]), st)
        self.assertEqual(sum(w["r"] for w in won.values()), 312)
        self.assertEqual(sum(w["d"] for w in won.values()), 226)

    def test_baseline_files_tracked_by_git(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for path in (DEFAULT_STATES_CSV, DEFAULT_DISTRICTS_CSV):
            r = subprocess.run(["git", "ls-files", "--error-unmatch", os.path.relpath(path, repo)],
                               cwd=repo, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{path} is not tracked by git")


if __name__ == "__main__":
    unittest.main()
