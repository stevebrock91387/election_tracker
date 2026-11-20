"""Rate-limited fetch: raw body saved and logged before return."""
import csv
import hashlib
import os
import tempfile
import unittest

from pipeline.fetch import FetchError, FetchTooSoon, fetch

URL = "https://example.test/cdn/results/X/export-1.json"


def opener_returning(status, body):
    return lambda url: (status, body)


def manifest_rows(raw):
    with open(os.path.join(raw, "manifest.csv"), newline="") as f:
        return list(csv.DictReader(f))


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()

    def test_saves_body_and_manifest_before_return(self):
        body = b'{"a": 1}'
        path = fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 1000.0,
                     opener=opener_returning(200, body))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), body)
        self.assertTrue(path.endswith(".json"))
        row = manifest_rows(self.raw)[-1]
        self.assertEqual(row["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(int(row["bytes"]), len(body))
        self.assertEqual(row["http_status"], "200")
        self.assertEqual(row["path"], path)

    def test_too_soon_raises(self):
        op = opener_returning(200, b"x")
        fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 1000.0, opener=op)
        with self.assertRaises(FetchTooSoon):
            fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 1119.0, opener=op)
        fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 1120.0, opener=op)
        self.assertEqual(len(manifest_rows(self.raw)), 2)

    def test_interval_survives_new_process(self):
        op = opener_returning(200, b"x")
        fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 5000.0, opener=op)
        self.assertTrue(os.path.exists(os.path.join(self.raw, ".last_fetch.json")))
        with self.assertRaises(FetchTooSoon):
            fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 5060.0, opener=op)

    def test_other_source_not_blocked(self):
        op = opener_returning(200, b"x")
        fetch("a", URL, 120, raw_dir=self.raw, now=lambda: 1000.0, opener=op)
        fetch("b", URL, 120, raw_dir=self.raw, now=lambda: 1001.0, opener=op)

    def test_http_error_saved_then_raises(self):
        with self.assertRaises(FetchError):
            fetch("src", URL, 120, raw_dir=self.raw, now=lambda: 1000.0,
                  opener=opener_returning(404, b"nope"))
        row = manifest_rows(self.raw)[-1]
        self.assertEqual(row["http_status"], "404")
        with open(row["path"], "rb") as f:
            self.assertEqual(f.read(), b"nope")


if __name__ == "__main__":
    unittest.main()
