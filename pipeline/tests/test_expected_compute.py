"""Step 4: expected vote per county from two comparable years (point, low, high)."""
import unittest

from pipeline.expected.compute import expected, norm_county


def b(year, votes, fips="29510", name="ST. LOUIS CITY", st="MO"):
    return {"state": st, "county_fips": fips, "county_name": name, "year": year, "top_office": "US SENATE",
            "votes": votes, "suppressed_rows": 0, "check": "passed", "checked_via": "",
            "medsl_source": "m", "fec_file_sha256": "f"}


class ComputeTest(unittest.TestCase):
    def test_raw_method_without_registration(self):
        rows, listed = expected(2026, (2018, 2022), {2018: [b(2018, 1000)], 2022: [b(2022, 1200)]}, {})
        (r,) = rows
        self.assertEqual((r["point"], r["low"], r["high"], r["method"]), (1200, 1000, 1200, "raw"))
        self.assertEqual(r["reason"], "no registration for 2018, 2022, 2026")
        self.assertEqual((r["years_used"], listed), ("2018 2022", []))

    def test_raw_names_only_missing_years(self):
        reg = {("MO", "saint louis city", 2026): 5000}
        (r,), _ = expected(2026, (2018, 2022), {2018: [b(2018, 1000)], 2022: [b(2022, 1200)]}, reg)
        self.assertEqual((r["method"], r["reason"]), ("raw", "no registration for 2018, 2022"))

    def test_rate_method(self):
        reg = {("MO", "saint louis city", 2018): 2000, ("MO", "saint louis city", 2022): 2400,
               ("MO", "saint louis city", 2026): 2500}
        (r,), _ = expected(2026, (2018, 2022), {2018: [b(2018, 1000)], 2022: [b(2022, 1200)]}, reg)
        self.assertEqual((r["point"], r["low"], r["high"], r["method"], r["reason"]),
                         (1250, 1250, 1250, "rate × registration", ""))

    def test_rate_method_range_and_rounding(self):
        reg = {("MO", "saint louis city", 2018): 3000, ("MO", "saint louis city", 2022): 2400,
               ("MO", "saint louis city", 2026): 2500}
        (r,), _ = expected(2026, (2018, 2022), {2018: [b(2018, 1001)], 2022: [b(2022, 1200)]}, reg)
        # rates 0.33367 and 0.5 -> 834.17 and 1250
        self.assertEqual((r["point"], r["low"], r["high"]), (1250, 834, 1250))

    def test_county_in_one_year_only(self):
        rows, _ = expected(2026, (2018, 2022), {2018: [], 2022: [b(2022, 1200, fips="09110", name="CAPITOL", st="CT")]}, {})
        (r,) = rows
        self.assertEqual((r["point"], r["low"], r["high"], r["method"], r["years_used"]), (1200, 1200, 1200, "one year", "2022"))
        self.assertEqual(r["reason"], "no 2018 baseline")

    def test_both_years_missing_listed(self):
        rows, listed = expected(2026, (2018, 2022), {2018: [], 2022: []}, {},
                                listed_in={2018: [("GA", "13001", "APPLING", "no eligible office (x)")],
                                           2022: [("GA", "13001", "APPLING", "no eligible office (y)")]})
        self.assertEqual(rows, [])
        self.assertEqual(listed, [("GA", "13001", "APPLING", "2018: no eligible office (x); 2022: no eligible office (y)")])

    def test_norm_county_rules(self):
        self.assertEqual(norm_county("St. Louis County"), norm_county("saint louis"))
        self.assertNotEqual(norm_county("Baltimore city"), norm_county("Baltimore County"))
        self.assertEqual(norm_county("  Acadia   Parish "), "acadia")
        self.assertEqual(norm_county("Ste. Genevieve County"), "sainte genevieve")
        self.assertEqual(norm_county("Juneau City and Borough"), "juneau")
        self.assertEqual(norm_county("Bethel Census Area"), "bethel")


if __name__ == "__main__":
    unittest.main()
