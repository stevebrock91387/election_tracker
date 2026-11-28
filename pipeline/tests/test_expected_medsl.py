"""Step 4: MEDSL precincts summed to county candidate totals, with recorded fixes."""
import csv
import io
import os
import tempfile
import unittest
import zipfile

from pipeline.expected.medsl import apply_fixes, county_totals, load_fixes, read_precincts

H2022 = ["precinct", "office", "party_detailed", "party_simplified", "mode", "votes", "county_name", "county_fips",
         "jurisdiction_name", "jurisdiction_fips", "candidate", "district", "dataverse", "year", "stage", "state",
         "special", "writein", "state_po", "state_fips", "state_cen", "state_ic", "date", "readme_check", "magnitude"]
# 2018 (GitHub copy): same names, different order
H2018 = ["precinct", "office", "party_detailed", "party_simplified", "mode", "votes", "county_name", "county_fips",
         "jurisdiction_name", "jurisdiction_fips", "candidate", "district", "magnitude", "dataverse", "year", "stage",
         "state", "special", "writein", "state_po", "state_fips", "state_cen", "state_ic", "date", "readme_check"]


def rec(precinct, candidate, votes, mode="TOTAL", office="US SENATE", county="ADA", fips="16001", party="DEMOCRAT",
        st="ID", district="STATEWIDE", special="FALSE", writein="FALSE", stage="GEN"):
    return {"precinct": precinct, "office": office, "party_detailed": party, "party_simplified": party, "mode": mode,
            "votes": votes, "county_name": county, "county_fips": fips, "jurisdiction_name": county,
            "jurisdiction_fips": fips, "candidate": candidate, "district": district, "dataverse": "SENATE",
            "year": "2022", "stage": stage, "state": "X", "special": special, "writein": writein, "state_po": st,
            "state_fips": "16", "state_cen": "", "state_ic": "", "date": "2022-11-08", "readme_check": "FALSE",
            "magnitude": "1"}


def write_zip(d, name, header, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    w.writerows(rows)
    path = os.path.join(d, name)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name.replace(".zip", ".csv"), buf.getvalue())
    return path


def totals(rows, year=2022, header=H2022):
    d = tempfile.mkdtemp()
    return county_totals(read_precincts([write_zip(d, "x.zip", header, rows)], year))


def by_candidate(t):
    return {(r["county_fips"], r["candidate"]): r for r in t}


class MedslTest(unittest.TestCase):
    def test_total_mode_preferred_and_star_counted(self):
        t, notes = totals([rec("P1", "A", "10"), rec("P1", "A", "6", mode="ELECTION DAY"),
                           rec("P2", "A", "3", mode="ELECTION DAY"), rec("P2", "A", "2", mode="MAIL"),
                           rec("P3", "A", "*")])
        a = by_candidate(t)[("16001", "A")]
        self.assertEqual((a["votes"], a["suppressed_rows"]), (15, 1))
        self.assertEqual(notes["suppressed"][("ID", "US SENATE")], 1)

    def test_non_candidates_dropped(self):
        t, _ = totals([rec("P1", "A", "10"), rec("P1", "UNDERVOTES", "4")])
        self.assertEqual([r["candidate"] for r in t], ["A"])

    def test_step4_tallies_dropped_blank_flag_allowed(self):
        # VT 2022 publishes BLANK VOTES / OVERVOTES with an empty writein flag; tallies are never votes
        t, _ = totals([rec("P1", "A", "10"), rec("P1", "BLANK VOTES", "3", writein=""),
                       rec("P1", "TIMES BLANK VOTED", "2"), rec("P1", "REGISTERED VOTERS", "900")])
        self.assertEqual([r["candidate"] for r in t], ["A"])

    def test_nyc_ballot_counts_dropped(self):
        # NYC election districts in MEDSL 2018 and 2022: ballot counts by type filed as candidates
        lines = ["PUBLIC COUNTER", "ABSENTEE / MILITARY", "AFFIDAVIT", "FEDERAL", "MANUALLY COUNTED EMERGENCY"]
        t, _ = totals([rec("P1", "A", "10")] + [rec("P1", n, "500") for n in lines])
        self.assertEqual([r["candidate"] for r in t], ["A"])

    def test_blank_writein_on_a_candidate_raises(self):
        with self.assertRaisesRegex(ValueError, "writein"):
            totals([rec("P1", "A", "10", writein="")])

    def test_other_offices_and_stages_skipped(self):
        t, _ = totals([rec("P1", "A", "10"), rec("P1", "B", "4", office="STATE HOUSE"),
                       rec("P1", "C", "4", stage="PRI")])
        self.assertEqual([r["candidate"] for r in t], ["A"])

    def test_blank_county_rows_listed_not_assigned(self):
        t, notes = totals([rec("P1", "A", "10", st="AK", county="", fips="")])
        self.assertEqual([(r["county_fips"], r["votes"]) for r in t], [("", 10)])
        self.assertEqual(notes["blank_county"]["AK"], 1)
        self.assertEqual(dict(notes["no_county"]), {("AK", "", ""): 10})

    def test_four_digit_fips_padded(self):
        # MEDSL 2022 AL, AR, CA publish "1001"; 2018 publishes "01001"
        t, _ = totals([rec("P1", "A", "10", st="AL", fips="1001", county="AUTAUGA")])
        self.assertEqual([r["county_fips"] for r in t], ["01001"])

    def test_pseudo_counties_are_no_county(self):
        # ME 2018 "23000" STATE UOCAVA, MO "36000" KANSAS CITY, RI "NAN" / "NA": in the state check, no baseline
        t, notes = totals([rec("P1", "A", "10", st="ME", fips="23000", county="STATE UOCAVA"),
                           rec("P1", "A", "5", st="RI", fips="NAN", county=""),
                           rec("P1", "A", "7", st="RI", fips="44001", county="BRISTOL")])
        self.assertEqual(sorted((r["state_po"], r["county_fips"], r["votes"]) for r in t),
                         [("ME", "", 10), ("RI", "", 5), ("RI", "44001", 7)])
        self.assertEqual(dict(notes["no_county"]), {("ME", "23000", "STATE UOCAVA"): 10, ("RI", "NAN", ""): 5})

    def test_party_lines_kept_apart_for_mode_choice(self):
        # a fusion candidate: DEM line by TOTAL, WOR line only by split modes -> both lines count
        t, _ = totals([rec("P1", "A", "10", party="DEM"), rec("P1", "A", "2", mode="ABSENTEE", party="WOR"),
                       rec("P1", "A", "1", mode="ELECTION DAY", party="WOR")])
        self.assertEqual(by_candidate(t)[("16001", "A")]["votes"], 13)

    def test_special_and_writein_normalized(self):
        t, _ = totals([rec("P1", "A", "10", special="True", writein="TRUE"), rec("P1", "B", "1", special="false")])
        flags = {r["candidate"]: (r["special"], r["writein"]) for r in t}
        self.assertEqual(flags, {"A": (True, True), "B": (False, False)})

    def test_writein_line_of_a_named_candidate_kept_apart(self):
        # VT 2018: one precinct also has a write-in vote recorded under "BERNIE SANDERS"; the county's named
        # votes must stay named
        t, _ = totals([rec("P1", "S", "100", party="INDEPENDENT"), rec("P2", "S", "50", party="INDEPENDENT"),
                       rec("P2", "S", "1", party="", writein="TRUE")])
        self.assertEqual(sorted((r["candidate"], r["writein"], r["votes"]) for r in t), [("S", False, 150), ("S", True, 1)])

    def test_unreadable_votes_raise(self):
        with self.assertRaisesRegex(ValueError, "votes"):
            totals([rec("P1", "A", "ten")])

    def test_drop_fix_applied_and_recorded(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fixes.toml")
        with open(path, "w") as f:
            f.write('[[fix]]\nid = "NJ-2022-1"\nstate = "NJ"\nyear = 2022\noffice = "US HOUSE"\naction = "drop"\n'
                    'change = "drop a county total stored as a precinct"\nevidence = "x"\nbefore = "x"\nafter = "x"\n'
                    '[fix.match]\nprecinct = "COUNTY TOTAL"\ncounty_name = "ADA"\n')
        fixes = load_fixes(path)
        applied = []
        rows = [rec("P1", "A", "10", st="NJ", office="US HOUSE", district="002"),
                rec("COUNTY TOTAL", "A", "10", st="NJ", office="US HOUSE", district="002")]
        src = read_precincts([write_zip(d, "x.zip", H2022, rows)], 2022)
        t, _ = county_totals(apply_fixes(src, fixes, applied))
        self.assertEqual(by_candidate(t)[("16001", "A")]["votes"], 10)
        self.assertEqual(applied, [("NJ-2022-1", 1)])

    def _fixes(self, d, body):
        path = os.path.join(d, "fixes.toml")
        with open(path, "w") as f:
            f.write('[[fix]]\nid = "F-1"\nstate = "NJ"\nyear = 2022\noffice = "US HOUSE"\nchange = "c"\n'
                    'evidence = "e"\nbefore = "b"\nafter = "a"\n' + body)
        return load_fixes(path)

    def test_match_list_drops_any_listed_value(self):
        d = tempfile.mkdtemp()
        fixes = self._fixes(d, 'action = "drop"\n[fix.match]\nprecinct = ["Atlantic Totals", "District 1 Totals"]\n')
        rows = [rec(p, "A", "10", st="NJ", office="US HOUSE", district="002")
                for p in ("P1", "Atlantic Totals", "District 1 Totals")]
        applied = []
        t, _ = county_totals(apply_fixes(read_precincts([write_zip(d, "x.zip", H2022, rows)], 2022), fixes, applied))
        self.assertEqual(([r["votes"] for r in t], applied), ([10], [("F-1", 2)]))

    def test_set_fix_changes_fields_and_keeps_row(self):
        # MEDSL 2022 VT flags a ballot candidate (Redic, LIB) as a write-in
        d = tempfile.mkdtemp()
        fixes = self._fixes(d, 'action = "set"\n[fix.match]\ncandidate = "B"\n[fix.set]\nwritein = false\n')
        rows = [rec("P1", "A", "10", st="NJ", office="US HOUSE"), rec("P1", "B", "4", st="NJ", office="US HOUSE", writein="TRUE")]
        applied = []
        t, _ = county_totals(apply_fixes(read_precincts([write_zip(d, "x.zip", H2022, rows)], 2022), fixes, applied))
        self.assertEqual({r["candidate"]: (r["writein"], r["votes"]) for r in t}, {"A": (False, 10), "B": (False, 4)})
        self.assertEqual(applied, [("F-1", 1)])

    def test_set_fix_needs_known_fields(self):
        d = tempfile.mkdtemp()
        with self.assertRaisesRegex(ValueError, "set"):
            self._fixes(d, 'action = "set"\n[fix.match]\ncandidate = "B"\n')
        with self.assertRaisesRegex(ValueError, "votes"):
            self._fixes(d, 'action = "set"\n[fix.match]\ncandidate = "B"\n[fix.set]\nvotes = "9"\n')

    def test_fix_without_required_field_rejected(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fixes.toml")
        with open(path, "w") as f:
            f.write('[[fix]]\nid = "X-1"\nstate = "NJ"\nyear = 2022\noffice = "US HOUSE"\naction = "drop"\n'
                    '[fix.match]\nprecinct = "P"\n')
        with self.assertRaisesRegex(ValueError, "evidence"):
            load_fixes(path)

    def test_2018_columns_mapped(self):
        rows = [rec("P1", "A", "10"), rec("P2", "A", "5")]
        self.assertEqual(totals(rows, 2018, H2018), totals(rows, 2022, H2022))

    def test_macosx_metadata_member_skipped(self):
        # 2022 WV's zip also holds __MACOSX/._2022-wv-local-precinct-general.csv (AppleDouble bytes, not UTF-8)
        d = tempfile.mkdtemp()
        path = write_zip(d, "x.zip", H2022, [rec("P1", "A", "10")])
        with zipfile.ZipFile(path, "a") as z:
            z.writestr("__MACOSX/._x.csv", b"\x00\x05\x16\x07\xb4")
        t, _ = county_totals(read_precincts([path], 2022))
        self.assertEqual([r["votes"] for r in t], [10])

    def test_repo_fixes_file_loads(self):
        self.assertIsInstance(load_fixes(), list)


if __name__ == "__main__":
    unittest.main()
