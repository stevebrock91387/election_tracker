"""ResultsAjax reader on fixtures cut from the real 2026 MT, NE, NM, OR, SD downloads."""
import json
import os
import shutil
import tempfile
import unittest

from pipeline.readers.resultsajax import parse_media_csv, parse_pass, parse_race
from pipeline.schema import COLUMNS

FX = os.path.join(os.path.dirname(__file__), "fixtures")
MT_SEN, NE_SEN, NM_SEN, OR_SEN, SD_SEN = "450000000004069", "13224", "11185", "300038695", "14412"


def find(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def run(st):
    return parse_pass(os.path.join(FX, f"ra_{st}_pass.json"), base_dir=FX)


def variant(st, edit_record=None, edit_race=None, edit_text=None):
    """Copy a state's fixture set to a temp dir, optionally editing the pass record or one race JSON."""
    d = tempfile.mkdtemp()
    for name in os.listdir(FX):
        if name.startswith(f"ra_{st}_"):
            shutil.copy(os.path.join(FX, name), d)
    rec_path = os.path.join(d, f"ra_{st}_pass.json")
    with open(rec_path) as f:
        rec = json.load(f)
    if edit_record:
        edit_record(rec)
    with open(rec_path, "w") as f:
        json.dump(rec, f)
    if edit_race:
        name, fn = edit_race
        p = os.path.join(d, name)
        with open(p) as f:
            data = json.load(f)
        fn(data)
        with open(p, "w") as f:
            json.dump(data, f)
    if edit_text:
        name, fn = edit_text
        p = os.path.join(d, name)
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(fn(text))
    return parse_pass(rec_path, base_dir=d)


class RealFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {st: run(st) for st in ("mt", "ne", "nm", "or", "sd")}

    def test_columns(self):
        for st, (rows, _) in self.res.items():
            self.assertTrue(rows, st)
            for r in rows:
                self.assertEqual(list(r), COLUMNS, st)

    def test_mt_values(self):
        rows, s = self.res["mt"]
        (r,) = find(rows, level="county", contest_id=MT_SEN, choice_id="27099", county_name="BEAVERHEAD")
        self.assertEqual((r["votes"], r["party"], r["choice"], r["vote_type"], r["county_id"]),
                         (2805, "REP", "KURT ALME", "TOTAL", "01"))
        self.assertEqual(s["statewide_check"], "not available")
        self.assertFalse(find(rows, level="state"))

    def test_nm_strings_and_padding(self):
        rows, s = self.res["nm"]
        (r,) = find(rows, level="county", contest_id=NM_SEN, choice_id="19607", county_name="Santa Fe")
        self.assertEqual((r["county_id"], r["votes"]), ("01", 57862))
        self.assertEqual(s["statewide_check"], "media CSV")
        self.assertEqual(s["mismatches_counties_vs_media"], [])

    def test_or_kept_as_published(self):
        rows, s = self.res["or"]
        (r,) = find(rows, level="county", contest_id=OR_SEN, choice_id="300060094", county_name="Baker")
        self.assertEqual((r["party"], r["votes"], r["reporting_status"]), ("NON", 5755, "0/17 precincts"))
        self.assertEqual(s["statewide_check"], "not available")

    def test_ne_sd_checked_against_media(self):
        for st, race in (("ne", NE_SEN), ("sd", SD_SEN)):
            rows, s = self.res[st]
            self.assertEqual(s["statewide_check"], "media CSV", st)
            self.assertEqual(s["mismatches_counties_vs_media"], [], st)
            self.assertTrue(find(rows, level="state", contest_id=race, vote_type="TOTAL"), st)
            self.assertTrue(find(rows, level="county", contest_id=race), st)
        (r,) = find(self.res["ne"][0], level="county", contest_id=NE_SEN, choice_id="3012", county_name="Adams")
        self.assertEqual(r["votes"], 6696)

    def test_no_anomalies_on_real_fixtures(self):
        for st, (_, s) in self.res.items():
            for k in ("races_no_data", "races_unreadable", "failed_races", "duplicate_keys",
                      "non_numeric_votes", "media_problems"):
                self.assertEqual(s[k], [], (st, k))


class ParseFunctionsTest(unittest.TestCase):
    def test_parse_race_shapes(self):
        self.assertIsNone(parse_race(b'{"d": null}'))
        self.assertEqual(parse_race(b'{"d": []}'), [])
        self.assertEqual(parse_race(b'[{"RaceID": 1}]'), [{"RaceID": 1}])

    def test_parse_race_rejects_wrong_shapes(self):
        for body in (b"<html>bot check</html>", b"", b'{"d": "oops"}', b'{"d": [1, 2]}'):
            with self.assertRaises(ValueError, msg=body):
                parse_race(body)

    def test_media_bad_rows_listed_not_fatal(self):
        text = ('RaceID,CandidateID,CandidateVotes\n'
                '1,10,*\n'
                '1,11,1,234\n'
                '1,12\n'
                '1,13,5\n'
                '1,13,6\n')
        got, problems = parse_media_csv(text)
        self.assertEqual(got[("1", "10")]["votes"], "")
        self.assertEqual(got[("1", "13")]["votes"], 5)
        self.assertEqual([p[1] for p in problems],
                         ["non-numeric votes '*'", "unexpected field count", "missing CandidateID or votes",
                          "duplicate key"])

    def test_media_ids_match_as_strings(self):
        text = ('RaceID,RaceName,PartyCode,CandidateID,CandidateName,CandidateVotes,PrecinctsReporting\n'
                '14412,"US Senator","REP",24967,"Mike  Rounds ",184590,="671/671",\n')
        got, problems = parse_media_csv(text)
        self.assertEqual(problems, [])
        self.assertEqual(list(got), [("14412", "24967")])
        self.assertEqual((got[("14412", "24967")]["votes"], got[("14412", "24967")]["precincts"]), (184590, "671/671"))


class AnomalyTest(unittest.TestCase):
    def test_null_race_listed(self):
        rows, s = variant("mt", edit_race=(f"ra_mt_race_{MT_SEN}.json", lambda d: d.update(d=None)))
        self.assertEqual(s["races_no_data"], [MT_SEN])
        self.assertFalse(find(rows, contest_id=MT_SEN))

    def test_failed_race_in_summary(self):
        def edit(rec):
            rec["failed_races"] = [{"type": "FED", "race_id": "999", "error": "HTTP 500"}]
        _, s = variant("mt", edit_record=edit)
        self.assertEqual([f["race_id"] for f in s["failed_races"]], ["999"])

    def test_county_sum_mismatch(self):
        def bump(d):
            d["d"][0]["calcCandidateVotes"] += 1
        rows, s = variant("sd", edit_race=(f"ra_sd_race_{SD_SEN}.json", bump))
        (m,) = s["mismatches_counties_vs_media"]
        self.assertEqual((m[0], m[3] - m[2]), (SD_SEN, 1))

    def test_non_numeric_votes_kept_empty_and_listed(self):
        def star(d):
            d[0]["calcCandidateVotes"] = "*"
        rows, s = variant("nm", edit_race=(f"ra_nm_race_{NM_SEN}.json", star))
        cty, cand = None, None
        with open(os.path.join(FX, f"ra_nm_race_{NM_SEN}.json")) as f:
            first = json.load(f)[0]
        cty, cand = first["CountyID"].strip(), first["CandidateID"]
        (r,) = find(rows, level="county", contest_id=NM_SEN, county_id=cty, choice_id=cand)
        self.assertEqual(r["votes"], "")
        self.assertEqual(s["non_numeric_votes"], [(NM_SEN, cty, cand, "*")])
        self.assertEqual(len(s["mismatches_counties_vs_media"]), 1)

    def test_unreadable_race_listed(self):
        def html(rec):
            pass
        rows, s = variant("sd", edit_text=(f"ra_sd_race_{SD_SEN}.json", lambda t: "<html>error</html>"))
        self.assertEqual([r for r, _ in s["races_unreadable"]], [SD_SEN])
        self.assertFalse(find(rows, level="county", contest_id=SD_SEN))
        self.assertEqual(s["races_checked"], 0)

    def test_no_media_means_not_checked(self):
        _, s = run("mt")
        for k in ("mismatches_counties_vs_media", "media_races_not_on_pages", "page_races_not_in_media"):
            self.assertIsNone(s[k], k)
        self.assertIsNone(s["races_checked"])
        _, s = run("sd")
        self.assertEqual(s["races_checked"], 1)

    def test_duplicate_key_listed(self):
        rows, s = variant("sd", edit_race=(f"ra_sd_race_{SD_SEN}.json", lambda d: d["d"].append(d["d"][0])))
        self.assertEqual(len(s["duplicate_keys"]), 1)

    def test_media_orphans_listed(self):
        drop_page = ("ra_sd_page_SWR.html", lambda t: "")
        _, s = variant("sd", edit_text=drop_page)
        self.assertIn(SD_SEN, s["media_races_not_on_pages"])
        drop_media = ("ra_sd_media_SWR.csv", lambda t: t.splitlines(keepends=True)[0])
        _, s = variant("sd", edit_text=drop_media)
        self.assertIn(SD_SEN, s["page_races_not_in_media"])

if __name__ == "__main__":
    unittest.main()
