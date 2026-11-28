"""Step 4 inputs: the FEC workbook is saved through pipeline.fetch."""
import csv
import os
import tempfile
import time
import unittest

from pipeline.expected.inputs import fetch_fec, latest_fec


class InputsTest(unittest.TestCase):
    def test_fetch_fec_saves_through_fetch(self):
        raw = tempfile.mkdtemp()
        path = fetch_fec(2022, raw, opener=lambda url: (200, b"PK"))
        self.assertTrue(path.endswith(".xlsx"))
        with open(os.path.join(raw, "manifest.csv"), newline="") as f:
            (m,) = list(csv.DictReader(f))
        self.assertEqual((m["source_id"], m["url"]),
                         ("fec-2022-federalelections", "https://www.fec.gov/documents/5676/federalelections2022.xlsx"))
        self.assertEqual(latest_fec(2022, raw), path)

    def test_latest_fec_missing_says_fetch(self):
        with self.assertRaisesRegex(FileNotFoundError, "run `fetch`"):
            latest_fec(2018, tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
