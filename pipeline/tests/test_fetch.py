"""Rate-limited fetch: raw body saved and logged before return."""
import concurrent.futures
import csv
import hashlib
import json
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


def _fetch_many(raw, worker, n):
    """Worker for the concurrency test: n fetches under distinct source ids."""
    for i in range(n):
        fetch(f"w{worker}-s{i}", URL, 120, raw_dir=raw, opener=lambda url: (200, b"x" * (i % 7)))
    return n


class ConcurrentFetchTest(unittest.TestCase):
    def test_parallel_processes_keep_state_and_manifest_whole(self):
        raw, workers, n = tempfile.mkdtemp(), 6, 40
        with concurrent.futures.ProcessPoolExecutor(workers) as ex:
            list(ex.map(_fetch_many, [raw] * workers, range(workers), [n] * workers))
        with open(os.path.join(raw, ".last_fetch.json")) as f:
            state = json.load(f)
        self.assertEqual(len(state), workers * n)
        rows = manifest_rows(raw)
        self.assertEqual(len(rows), workers * n)
        self.assertEqual({r["source_id"] for r in rows}, set(state))


CROSS = os.path.join(os.path.dirname(__file__), "..", "certs", "godaddy-tls-root-r1-cross-g2.pem")
CROSS_SHA256 = "7BCB0F2F2D1031A6AF8D61BAA835D2835A3B8BCC26D94A3B048B1655FB81298C"


class CafileTest(unittest.TestCase):
    def test_cross_cert_fingerprint(self):
        import ssl
        with open(CROSS) as f:
            der = ssl.PEM_cert_to_DER_cert(f.read())
        self.assertEqual(hashlib.sha256(der).hexdigest().upper(), CROSS_SHA256)

    def test_cafile_context(self):
        import ssl
        from pipeline.fetch import _ssl_context
        c = _ssl_context(CROSS)
        self.assertEqual(c.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN, 0)
        self.assertEqual(c.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(c.check_hostname)
        cns = [(dict(x[0] for x in ca["subject"]).get("commonName"), dict(x[0] for x in ca["issuer"]).get("commonName"))
               for ca in c.get_ca_certs()]
        self.assertIn(("GoDaddy TLS Root CA - R1", "Go Daddy Root Certificate Authority - G2"), cns)
        self.assertIn(("Go Daddy Root Certificate Authority - G2", "Go Daddy Root Certificate Authority - G2"), cns)

    def test_fetch_passes_cafile(self):
        import pipeline.fetch as fm
        seen = []
        orig = fm._urllib_opener
        fm._urllib_opener = lambda url, context=None: (seen.append(context), (200, b"x"))[1]
        try:
            raw = tempfile.mkdtemp()
            fm.fetch("a", URL, 120, raw_dir=raw, now=lambda: 1000.0, cafile=CROSS)
            fm.fetch("b", URL, 120, raw_dir=raw, now=lambda: 1000.0)
        finally:
            fm._urllib_opener = orig
        self.assertIsNotNone(seen[0])
        self.assertIsNone(seen[1])


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.raw = tempfile.mkdtemp()

    def test_fetch_ext_override(self):
        url = "https://example.test/Api/v1/download?filename=X"
        op = opener_returning(200, b"<x/>")
        self.assertTrue(fetch("a", url, 120, raw_dir=self.raw, now=lambda: 1000.0, opener=op, ext="xml").endswith(".xml"))
        self.assertTrue(fetch("b", url, 120, raw_dir=self.raw, now=lambda: 1000.0, opener=op).endswith(".bin"))

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
