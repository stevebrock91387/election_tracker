"""Step 4: each county's top race among the offices that passed the FEC check."""
import unittest

from pipeline.expected.baseline import BASELINE_COLUMNS, baselines

PROV = {"medsl_source": "medsl-2022 a8126c5790b8", "fec_file_sha256": "abc"}
OK = {"passed": True, "differences": [], "reason": "passed"}
BAD = {"passed": False, "differences": [{}], "reason": "differences"}


def t(office, cand, votes, fips="13001", district="STATEWIDE", special=False, writein=False, st="GA", supp=0):
    return {"state_po": st, "county_fips": fips, "county_name": "APPLING", "office": office, "district": district,
            "special": special, "candidate": cand, "writein": writein, "votes": votes, "suppressed_rows": supp}


def top(rows, checks):
    out, listed = baselines(rows, checks, 2022, PROV)
    return {r["county_fips"]: (r["top_office"], r["votes"], r["check"], r["checked_via"]) for r in out}, listed


class BaselineTest(unittest.TestCase):
    def test_top_race_is_largest_eligible(self):
        rows = [t("US SENATE", "A", 900), t("US HOUSE", "B", 950, district="001")]
        got, _ = top(rows, {("GA", "US SENATE"): BAD, ("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"], ("US HOUSE", 950, "passed", ""))
        got, _ = top(rows + [t("US SENATE", "W", 100, writein=True)], {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"], ("US SENATE", 1000, "passed", ""))  # write-ins count

    def test_check_column_names_a_named_candidates_pass(self):
        named = {"passed": True, "differences": [{}], "reason": "passed (named candidates)"}
        got, _ = top([t("US SENATE", "A", 900)], {("GA", "US SENATE"): named})
        self.assertEqual(got["13001"], ("US SENATE", 900, "passed (named candidates)", ""))

    def test_governor_row_carries_ratio_to_federal(self):
        # Governor isn't FEC-checked: its ratio to the county's larger federal office is reported
        rows = [t("GOVERNOR", "G", 1500), t("US SENATE", "A", 900), t("US HOUSE", "B", 1000, district="001")]
        out, _ = baselines(rows, {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): OK}, 2022, PROV)
        self.assertEqual(out[0]["governor_vs_federal"], 1.5)
        out, _ = baselines(rows[1:], {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): OK}, 2022, PROV)
        self.assertEqual(out[0]["governor_vs_federal"], "")

    def test_governor_needs_both_federal_offices(self):
        rows = [t("GOVERNOR", "G", 2000), t("US SENATE", "A", 900), t("US HOUSE", "B", 950, district="001")]
        got, _ = top(rows, {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): BAD})
        self.assertEqual(got["13001"][0], "US SENATE")
        got, _ = top(rows, {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"], ("GOVERNOR", 2000, "not checked", "federal rows"))
        # no Senate race in the state at all: House passing is enough
        got, _ = top([rows[0], rows[2]], {("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"][0], "GOVERNOR")

    def test_tie_order_senate_governor_house(self):
        rows = [t("GOVERNOR", "G", 900), t("US SENATE", "A", 900), t("US HOUSE", "B", 900, district="001")]
        got, _ = top(rows, {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"][0], "US SENATE")
        got, _ = top(rows[0::2], {("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"][0], "GOVERNOR")

    def test_house_summed_over_districts_in_county(self):
        rows = [t("US HOUSE", "A", 500, district="001"), t("US HOUSE", "B", 600, district="002"),
                t("US SENATE", "C", 1000)]
        got, _ = top(rows, {("GA", "US SENATE"): OK, ("GA", "US HOUSE"): OK})
        self.assertEqual(got["13001"], ("US HOUSE", 1100, "passed", ""))

    def test_two_senate_contests_larger_counts(self):
        rows = [t("US SENATE", "A", 700), t("US SENATE", "B", 800, special=True)]
        got, _ = top(rows, {("GA", "US SENATE"): OK})
        self.assertEqual(got["13001"][1], 800)

    def test_no_eligible_office_listed(self):
        rows = [t("US SENATE", "A", 900), t("US SENATE", "A", 5, fips="")]
        out, listed = baselines(rows, {("GA", "US SENATE"): BAD}, 2022, PROV)
        self.assertEqual(out, [])
        self.assertEqual(listed, [("GA", "13001", "APPLING", "no eligible office (US SENATE: differences)")])

    def test_row_columns_and_provenance(self):
        out, _ = baselines([t("US SENATE", "A", 900, supp=2)], {("GA", "US SENATE"): OK}, 2022, PROV)
        self.assertEqual(list(out[0]), BASELINE_COLUMNS)
        self.assertEqual((out[0]["suppressed_rows"], out[0]["medsl_source"], out[0]["fec_file_sha256"], out[0]["year"]),
                         (2, "medsl-2022 a8126c5790b8", "abc", 2022))


if __name__ == "__main__":
    unittest.main()
