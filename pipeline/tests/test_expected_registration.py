"""Step 4: 2026 registered voters per county from the step-3 database's turnout tables."""
import os
import tempfile
import unittest

from pipeline.db import connect
from pipeline.expected.registration import registration_2026


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(os.path.join(tempfile.mkdtemp(), "r.sqlite"))
        self.sid = 0

    def snap(self, source, state, seen="2026-11-20T00:00:00Z", pruned=0):
        self.sid += 1
        self.conn.execute("INSERT INTO snapshot (snapshot_id, source_id, state, first_seen_utc, pruned) VALUES (?,?,?,?,?)",
                          (self.sid, source, state, seen, pruned))
        return self.sid

    def unit(self, sid, layout, county, reg, precinct="", contest=""):
        self.conn.execute("INSERT INTO turnout (snapshot_id, layout, county_id, county_name, precinct_id, precinct_name,"
                          " contest_id, registered_voters) VALUES (?,?,?,?,?,?,?,?)",
                          (sid, layout, "", county, "", precinct, contest, reg))

    def regs(self):
        rows, listed = registration_2026(self.conn)
        return {(r["state"], r["county_name"]): r["registered"] for r in rows}, listed

    def test_precinct_turnout_summed_to_county(self):
        s = self.snap("clarity-NJ-Atlantic-2026-general", "NJ")
        self.unit(s, "clarity_county", "Atlantic", 1287, "Absecon W1 D1")
        self.unit(s, "clarity_county", "Atlantic", 1511, "Absecon W1 D2")
        got, _ = self.regs()
        self.assertEqual(got, {("NJ", "Atlantic"): 2798})

    def test_latest_snapshot_only(self):
        old = self.snap("tx-2026-general", "TX", "2026-11-05T00:00:00Z")
        new = self.snap("tx-2026-general", "TX", "2026-11-10T00:00:00Z")
        self.unit(old, "tx", "NOLAN", 8000)
        self.unit(new, "tx", "NOLAN", 8835)
        got, _ = self.regs()
        self.assertEqual(got, {("TX", "NOLAN"): 8835})

    def test_town_layout_listed_not_summed(self):
        s = self.snap("ct-2026-general", "CT")
        self.unit(s, "ct", "Andover", 2500)
        got, listed = self.regs()
        self.assertEqual(got, {})
        self.assertEqual(listed, [("CT", "ct-2026-general", "", "towns (layout ct)")])

    def test_two_sources_same_county_listed(self):
        for src in ("a-2026", "b-2026"):
            self.unit(self.snap(src, "NJ"), "clarity_county", "Bergen", 100)
        got, listed = self.regs()
        self.assertEqual(got, {})
        self.assertEqual(listed, [("NJ", "a-2026 b-2026", "Bergen", "two sources")])

    def test_null_or_zero_registration_listed(self):
        s = self.snap("al-2026-general", "AL")
        self.unit(s, "al", "Autauga", None, "P1")
        self.unit(s, "al", "Autauga", 100, "P2")
        self.unit(s, "al", "Baldwin", 0, "P1")
        got, listed = self.regs()
        self.assertEqual(got, {})
        self.assertEqual(listed, [("AL", "al-2026-general", "Autauga", "registered voters missing for 1 unit(s)"),
                                  ("AL", "al-2026-general", "Baldwin", "registered voters 0")])

    def test_blank_county_name_listed(self):
        s = self.snap("hi-2026-general", "HI")
        self.unit(s, "hi", "", 900, "01-01")
        got, listed = self.regs()
        self.assertEqual((got, listed), ({}, [("HI", "hi-2026-general", "", "no county names")]))

    def test_contest_keyed_units_use_statewide_contests(self):
        # LA: one turnout row per (race, parish); a district race covers part of a parish
        s = self.snap("la-2026-general", "LA")
        for c in ("SEN", "AMD1"):
            self.unit(s, "la", "Acadia", 40000, contest=c)
            self.unit(s, "la", "Allen", 15000, contest=c)
        self.unit(s, "la", "Acadia", 12000, contest="HD42")
        self.unit(s, "la", "Caddo", 150000, contest="SEN")
        self.unit(s, "la", "Caddo", 151000, contest="AMD1")
        got, listed = self.regs()
        self.assertEqual(got, {("LA", "Acadia"): 40000, ("LA", "Allen"): 15000})
        self.assertEqual(listed, [("LA", "la-2026-general", "Caddo", "registered voters differ by contest: 150000, 151000")])


if __name__ == "__main__":
    unittest.main()
