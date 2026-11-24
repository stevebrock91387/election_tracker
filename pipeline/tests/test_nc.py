"""NC reader: fixtures cut from the 2026 general (US Senate and US House 1 in Beaufort, Bertie
and Camden; dashboard rows for those two contests with their real statewide values), plus
synthetic variants written to a temporary directory for each listed anomaly."""
import csv
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile

from pipeline.readers.nc import parse_pass
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
MEMBER = "results_pct_20261103.txt"
HEADER = ["County", "Election Date", "Precinct", "Contest Group ID", "Contest Type", "Contest Name", "Choice",
          "Choice Party", "Vote For", "Election Day", "Early Voting", "Absentee by Mail", "Provisional",
          "Total Votes", "Real Precinct"]
METHODS = ["Election Day", "Early Voting", "Absentee by Mail", "Provisional"]

# Fixture ZIP sums per (contest group, choice): Election Day, Early Voting, Absentee by Mail, Provisional, Total.
ZIP_SUMS = {
    ("1383", "Roy Cooper"): [3887, 9610, 265, 91, 13853],
    ("1383", "Michael Whatley"): [7173, 9291, 111, 38, 16613],
    ("1383", "Shannon W. Bray"): [200, 274, 7, 6, 487],
    ("1383", "Michael Dublin"): [120, 109, 4, 1, 234],
    ("1369", "Don Davis"): [3707, 9410, 256, 93, 13466],
    ("1369", "Laurie Buckhout"): [7189, 9311, 120, 40, 16660],
    ("1369", "Tom Bailey"): [449, 548, 9, 5, 1011],
}


def real():
    return parse_pass(os.path.join(FX, "nc_pass.json"), base_dir=FX)


def line(county="BEAUFORT", prec="P1", gid="1383", ctype="S", cname="US SENATE", choice="Roy Cooper",
         party="DEM", vf="1", m=(1, 2, 3, 4), total=None, real_p="Y"):
    total = sum(m) if total is None else total
    return [county, "11/03/2026", prec, gid, ctype, cname, choice, party, vf, *map(str, m), str(total), real_p]


def dash_row(gid="1383", choice="Roy Cooper", party="DEM", vals=(10, 1, 2, 3, 4), cnm="US SENATE (VOTE FOR 1)"):
    vct, evc, ovc, avc, pvc = map(str, vals)
    return {"cid": "0", "cnm": cnm, "vfr": "1", "gid": gid, "lid": gid, "bnm": choice, "pty": party, "vct": vct,
            "evc": evc, "ovc": ovc, "avc": avc, "pvc": pvc, "prt": "2", "ptl": "2", "ogl": "FED"}


class Synthetic:
    """A pass in a temporary directory; zip_lines are raw lines (lists are joined with tabs)."""

    def __init__(self, zip_lines, dashboard, member=MEMBER, header=HEADER, dashboard_text=None, zip_bytes=None):
        self.dir = tempfile.mkdtemp()
        files = []
        if zip_lines is not None or zip_bytes is not None:
            p = os.path.join(self.dir, "x.zip")
            if zip_bytes is not None:
                with open(p, "wb") as f:
                    f.write(zip_bytes)
            else:
                body = "\r\n".join("\t".join(l) if isinstance(l, list) else l for l in [header] + zip_lines) + "\r\n"
                with zipfile.ZipFile(p, "w") as z:
                    z.writestr(member, body)
            files.append({"kind": "zip", "path": "x.zip"})
        if dashboard is not None or dashboard_text is not None:
            with open(os.path.join(self.dir, "d.txt"), "w") as f:
                f.write(dashboard_text if dashboard_text is not None else json.dumps(dashboard))
            files.append({"kind": "dashboard", "path": "d.txt"})
        self.rec = os.path.join(self.dir, "pass.json")
        with open(self.rec, "w") as f:
            json.dump({"source_id": "nc-2026-general", "state": "NC", "member": MEMBER, "files": files}, f)

    def parse(self):
        try:
            return parse_pass(self.rec, base_dir=self.dir)
        finally:
            shutil.rmtree(self.dir)


class RealFixtureTest(unittest.TestCase):
    def test_columns(self):
        rows, _ = real()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(list(r), COLUMNS)

    def test_precinct_row_five_vote_types(self):
        rows, _ = real()
        got = {r["vote_type"]: r["votes"] for r in rows if r["level"] == "precinct" and r["county_name"] == "BEAUFORT"
               and r["precinct_id"] == "CHOCO" and r["contest_id"] == "1383" and r["choice"] == "Roy Cooper"}
        self.assertEqual(got, {"Election Day": 162, "Early Voting": 0, "Absentee by Mail": 0, "Provisional": 0,
                               "TOTAL": 162})
        r = next(r for r in rows if r["precinct_id"] == "CHOCO" and r["choice"] == "Roy Cooper")
        self.assertEqual((r["state"], r["source_id"], r["party"], r["contest_name"], r["contest_type"], r["vote_for"],
                          r["contest_scope"], r["election_date"], r["precinct_is_virtual"], r["choice_id"]),
                         ("NC", "nc-2026-general", "DEM", "US SENATE", "S", "1", "statewide", "11/03/2026", "N", ""))
        with open(os.path.join(FX, "nc.zip"), "rb") as f:
            import hashlib
            self.assertEqual(r["source_sha256"], hashlib.sha256(f.read()).hexdigest())

    def test_administrative_precinct_virtual(self):
        rows, _ = real()
        got = {r["vote_type"]: r["votes"] for r in rows if r["county_name"] == "BEAUFORT"
               and r["precinct_id"] == "ABSENTEE" and r["contest_id"] == "1383" and r["choice"] == "Roy Cooper"}
        self.assertEqual(got["Absentee by Mail"], 177)
        r = next(r for r in rows if r["precinct_id"] == "ABSENTEE")
        self.assertEqual(r["precinct_is_virtual"], "Y")

    def test_state_rows_from_dashboard(self):
        rows, _ = real()
        got = {r["vote_type"]: r["votes"] for r in rows if r["level"] == "state" and r["contest_id"] == "1383"
               and r["choice"] == "Roy Cooper"}
        self.assertEqual(got, {"TOTAL": 2480648, "Election Day": 658055, "Early Voting": 1728012,
                               "Absentee by Mail": 81799, "Provisional": 12782})
        r = next(r for r in rows if r["level"] == "state" and r["choice"] == "Roy Cooper")
        self.assertEqual((r["contest_name"], r["party"], r["reporting_status"], r["source_created_at"], r["vote_for"]),
                         ("US SENATE (VOTE FOR 1)", "DEM", "2626/2626 precincts", "", "1"))

    def test_counts(self):
        rows, s = real()
        self.assertEqual(sum(r["level"] == "precinct" for r in rows), 343 * 5)
        self.assertEqual(sum(r["level"] == "state" for r in rows), 7 * 5)
        self.assertEqual((s["contests"], s["counties"]), (2, 3))

    def test_real_senate_mismatch_listed(self):
        _, s = real()
        mm = s["mismatches_dashboard_vs_zip"]
        self.assertIn(("1383", "Roy Cooper", "TOTAL", 2480648, 13853), mm)
        self.assertIn(("1383", "Roy Cooper", "Provisional", 12782, 91), mm)
        self.assertIn(("1369", "Tom Bailey", "Early Voting", 5173, 548), mm)
        self.assertEqual(len(mm), 7 * 5)

    def test_clean_when_dashboard_equals_zip_sums(self):
        with open(os.path.join(FX, "nc_dashboard.txt")) as f:
            dash = json.load(f)
        for x in dash:
            ed, ev, ab, pv, tot = ZIP_SUMS[(x["gid"], x["bnm"])]
            x.update(vct=str(tot), evc=str(ed), ovc=str(ev), avc=str(ab), pvc=str(pv))
        with zipfile.ZipFile(os.path.join(FX, "nc.zip")) as z:
            body = z.read(MEMBER).decode()
        lines = [l.split("\t") for l in body.split("\r\n")[1:] if l]
        _, s = Synthetic(lines, dash).parse()
        self.assertEqual(s["mismatches_dashboard_vs_zip"], [])
        self.assertEqual(s["dashboard_rows_without_zip_match"], [])
        self.assertEqual(s["zip_contests_missing_from_dashboard"], [])
        self.assertEqual(s["zip_choices_missing_from_dashboard"], [])

    def test_real_fixture_clean_otherwise(self):
        _, s = real()
        for k in ("bad_sums", "non_numeric_votes", "wrong_field_count", "control_characters", "duplicate_keys",
                  "unexpected_header", "missing_member", "unreadable_files", "missing_files",
                  "dashboard_rows_without_zip_match", "zip_contests_missing_from_dashboard"):
            self.assertFalse(s[k], k)


class AnomalyTest(unittest.TestCase):
    def test_orphans_listed(self):
        rows, s = Synthetic(
            [line(), line(gid="1369", cname="US HOUSE 01", choice="Don Davis"), line(choice="Michael Whatley")],
            [dash_row(), dash_row(gid="9999", choice="Nobody")]).parse()
        self.assertEqual(s["dashboard_rows_without_zip_match"], [("9999", "Nobody")])
        self.assertEqual(s["zip_contests_missing_from_dashboard"], ["1369"])
        self.assertEqual(s["zip_choices_missing_from_dashboard"], [("1383", "Michael Whatley")])
        self.assertTrue(any(r["level"] == "state" and r["contest_id"] == "9999" for r in rows))

    def test_type_c_out_of_scope(self):
        rows, s = Synthetic([line(), line(gid="760011", ctype="C", cname="CITY COUNCIL", choice="X")],
                            [dash_row(), dash_row(gid="760011", choice="X")]).parse()
        self.assertFalse(any(r["contest_id"] == "760011" for r in rows))
        self.assertEqual(s["dashboard_rows_out_of_scope"], 1)
        self.assertEqual(s["dashboard_rows_without_zip_match"], [])

    def test_control_characters_listed(self):
        rows, s = Synthetic([line(choice="\x00"), line(choice="Ann\x07e")], [dash_row()]).parse()
        self.assertEqual(s["control_characters"], [("BEAUFORT", "P1", "1383", "Choice", "\x00"),
                                                   ("BEAUFORT", "P1", "1383", "Choice", "Ann\x07e")])
        self.assertIn("\x00", {r["choice"] for r in rows})
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=COLUMNS)
        w.writerows(rows)  # a NUL choice must still be writable

    def test_bad_rows_listed(self):
        rows, s = Synthetic([
            line(prec="SUM", total=99),
            ["BEAUFORT", "11/03/2026", "NUM", "1383", "S", "US SENATE", "Roy Cooper", "DEM", "1", "1", "x", "0", "0", "1", "Y"],
            ["BEAUFORT", "11/03/2026", "SHORT", "1383", "S"],
        ], [dash_row()]).parse()
        self.assertEqual(s["bad_sums"], [("BEAUFORT", "SUM", "1383", "Roy Cooper", [1, 2, 3, 4], 99)])
        self.assertEqual(s["non_numeric_votes"], [("zip", "BEAUFORT", "NUM", "1383", "Roy Cooper", "Early Voting", "x")])
        self.assertEqual(s["wrong_field_count"], [(4, 5)])
        num = {r["vote_type"]: r["votes"] for r in rows if r["precinct_id"] == "NUM"}
        self.assertEqual(num["Early Voting"], "")
        self.assertEqual(num["TOTAL"], 1)
        self.assertFalse(any(r["precinct_id"] == "SHORT" for r in rows))

    def test_duplicate_keys_listed(self):
        _, s = Synthetic([line(), line()], [dash_row()]).parse()
        self.assertEqual(s["duplicate_keys"], [("BEAUFORT", "P1", "1383", "Roy Cooper")])

    def test_blank_party_is_no_party(self):
        rows, _ = Synthetic([line(party=" ")], [dash_row(party="")]).parse()
        self.assertEqual({r["party"] for r in rows}, {""})

    def test_unexpected_header_listed(self):
        rows, s = Synthetic([line()], [dash_row()], header=HEADER[:-1] + ["Real Pct"]).parse()
        self.assertEqual(s["unexpected_header"], [tuple(HEADER[:-1] + ["Real Pct"])])
        self.assertFalse(any(r["level"] == "precinct" for r in rows))
        self.assertIsNone(s["mismatches_dashboard_vs_zip"])
        self.assertTrue(any(r["level"] == "state" for r in rows))

    def test_reordered_header_read_by_name(self):
        hdr = HEADER[1:] + HEADER[:1]
        l = line()
        rows, s = Synthetic([l[1:] + l[:1]], [dash_row()], header=hdr).parse()
        self.assertEqual(s["unexpected_header"], [tuple(hdr)])
        self.assertEqual({r["votes"] for r in rows if r["level"] == "precinct" and r["vote_type"] == "TOTAL"}, {10})

    def test_missing_member_listed(self):
        rows, s = Synthetic([line()], [dash_row()], member="other.txt").parse()
        self.assertEqual(s["missing_member"], [MEMBER])
        self.assertIsNone(s["mismatches_dashboard_vs_zip"])
        self.assertIsNone(s["dashboard_rows_without_zip_match"])
        self.assertTrue(any(r["level"] == "state" for r in rows))

    def test_unreadable_zip_listed(self):
        _, s = Synthetic(None, [dash_row()], zip_bytes=b"not a zip").parse()
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["zip"])
        self.assertIsNone(s["mismatches_dashboard_vs_zip"])

    def test_unreadable_dashboard_not_checked(self):
        for text in ("{not json", '{"a": 1}'):
            rows, s = Synthetic([line()], None, dashboard_text=text).parse()
            self.assertEqual([u[0] for u in s["unreadable_files"]], ["dashboard"], text)
            self.assertIsNone(s["mismatches_dashboard_vs_zip"])
            self.assertIsNone(s["zip_contests_missing_from_dashboard"])
            self.assertTrue(any(r["level"] == "precinct" for r in rows))

    def test_missing_files_listed(self):
        _, s = Synthetic([line()], None).parse()
        self.assertEqual(s["missing_files"], ["dashboard"])
        self.assertIsNone(s["mismatches_dashboard_vs_zip"])

    def test_dashboard_non_numeric_listed(self):
        rows, s = Synthetic([line()], [dash_row(vals=(10, 1, 2, "", 4))]).parse()
        self.assertIn(("dashboard", "", "", "1383", "Roy Cooper", "Absentee by Mail", ""), s["non_numeric_votes"])
        self.assertEqual(next(r["votes"] for r in rows if r["level"] == "state" and r["vote_type"] == "Absentee by Mail"), "")
        self.assertFalse(any(m[2] == "Absentee by Mail" for m in s["mismatches_dashboard_vs_zip"]))


class ReviewFixTest(unittest.TestCase):
    def test_nul_party_listed(self):
        rows, s = Synthetic([line(party="\x00")], [dash_row()]).parse()
        self.assertEqual(s["control_characters"], [("BEAUFORT", "P1", "1383", "Choice Party", "\x00")])
        self.assertIn("\x00", {r["party"] for r in rows})

    def test_zip_checks_not_checked_when_zip_unread(self):
        for kw in ({"member": "other.txt"}, {"header": ["a", "b"]}):
            _, s = Synthetic([line()], [dash_row()], **kw).parse()
            for k in ("bad_sums", "wrong_field_count", "control_characters", "duplicate_keys", "contests",
                      "choices", "counties", "precincts", "unknown_contest_types", "mixed_contest_types",
                      "unexpected_real_precinct"):
                self.assertIsNone(s[k], (kw, k))

    def test_duplicate_dashboard_rows_listed(self):
        _, s = Synthetic([line()], [dash_row(), dash_row()]).parse()
        self.assertEqual(s["duplicate_dashboard_keys"], [("1383", "Roy Cooper")])

    def test_corrupt_zip_stream_listed(self):
        p = os.path.join(FX, "nc.zip")
        with open(p, "rb") as f:
            b = bytearray(f.read())
        with zipfile.ZipFile(p) as z:
            info = z.getinfo(MEMBER)
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        b[start + 20:start + 80] = b"\xff" * 60  # inside the deflated member data
        rows, s = Synthetic(None, [dash_row()], zip_bytes=bytes(b)).parse()
        self.assertEqual([u[0] for u in s["unreadable_files"]], ["zip"])
        self.assertIsNone(s["mismatches_dashboard_vs_zip"])
        self.assertTrue(any(r["level"] == "state" for r in rows))

    def test_unknown_and_mixed_contest_types_listed(self):
        rows, s = Synthetic([line(), line(gid="5", ctype="F", choice="Q"),
                             line(gid="7", choice="A"), line(gid="7", ctype="C", prec="P2", choice="A")],
                            [dash_row(), dash_row(gid="5", choice="Q")]).parse()
        self.assertEqual(s["unknown_contest_types"], [("5", "F")])
        self.assertEqual(s["mixed_contest_types"], [("7", ["C", "S"])])
        self.assertFalse(any(r["contest_id"] == "5" for r in rows))

    def test_unexpected_real_precinct_listed(self):
        rows, s = Synthetic([line(real_p="")], [dash_row()]).parse()
        self.assertEqual(s["unexpected_real_precinct"], [("BEAUFORT", "P1", "")])
        self.assertEqual({r["precinct_is_virtual"] for r in rows if r["level"] == "precinct"}, {""})


if __name__ == "__main__":
    unittest.main()
