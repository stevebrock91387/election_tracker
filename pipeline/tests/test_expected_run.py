"""Step 4 CLI: `all 2026` on tiny fixture inputs writes every stage's CSV."""
import contextlib
import csv
import io
import os
import tempfile
import unittest

from pipeline.db import connect
from pipeline.expected.run import main
from pipeline.tests.test_expected_check import FEC_HEADER, fec_row, xlsx
from pipeline.tests.test_expected_medsl import H2018, H2022, rec, write_zip


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class RunTest(unittest.TestCase):
    def test_all_on_fixture_inputs(self):
        d = tempfile.mkdtemp()
        raw, out = os.path.join(d, "raw"), os.path.join(d, "expected")
        medsl = {}
        for year, header, ada, canyon in ((2018, H2018, 1000, 400), (2022, H2022, 1200, 500)):
            rows = [rec("P1", "A", str(ada - 100), fips="16001", county="ADA"),
                    rec("P2", "B", "100", fips="16001", county="ADA"),
                    rec("P1", "A", str(canyon), fips="16027", county="CANYON"),
                    rec("P1", "A", "50", office="US HOUSE", district="001", fips="16001", county="ADA")]
            os.makedirs(os.path.join(d, str(year)))
            medsl[year] = [write_zip(os.path.join(d, str(year)), "id.zip", header, rows)]
            senate = [FEC_HEADER, fec_row("ID", "S", "A", "R", str(ada - 100 + canyon)), fec_row("ID", "S", "B", "D", "100")]
            house = [FEC_HEADER, fec_row("ID", "01", "A", "R", "49")]  # one vote off: US HOUSE fails
            os.makedirs(os.path.join(raw, f"fec-{year}-federalelections"))
            with open(os.path.join(raw, f"fec-{year}-federalelections", "20261127T000000Z.xlsx"), "wb") as f:
                f.write(xlsx([("x US Senate Results by State", senate), ("x US House Results by State", house)]))
        db = os.path.join(d, "r.sqlite")
        conn = connect(db)
        conn.execute("INSERT INTO snapshot (snapshot_id, source_id, state, first_seen_utc) VALUES (1, 'ev-ID', 'ID', 'x')")
        for county, v in (("Ada", 1150), ("Canyon", 700)):
            conn.execute("INSERT INTO result (snapshot_id, level, county_id, county_name, contest_name, choice, vote_type,"
                         " votes) VALUES (1, 'county', '001', ?, 'United States Senator', 'A', 'TOTAL', ?)", (county, v))
        conn.commit()
        conn.close()
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            main(["all", "2026", "--raw-dir", raw, "--out-dir", out, "--db", db], medsl=medsl)
        checks = {(r["state"], r["office"]): r["passed"] for r in read(os.path.join(out, "check-2022.csv"))}
        self.assertEqual(checks, {("ID", "US SENATE"): "True", ("ID", "US HOUSE"): "False"})
        self.assertEqual(len(read(os.path.join(out, "baseline-2018.csv"))), 2)
        exp = {r["county_name"]: (r["point"], r["low"], r["high"], r["method"]) for r in read(os.path.join(out, "expected-2026.csv"))}
        self.assertEqual(exp, {"ADA": ("1200", "1000", "1200", "raw"), "CANYON": ("500", "400", "500", "raw")})
        sc = {r["county"]: (r["inside"], r["miss"]) for r in read(os.path.join(out, "score-2026.csv"))}
        self.assertEqual(sc, {"ADA": ("True", "0"), "CANYON": ("False", "200")})
        self.assertIn("inside 1/2", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
