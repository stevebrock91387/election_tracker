"""Polite, recorded downloads: the raw body is saved and logged before anyone parses it.

fetch(source_id, url, min_interval_s) refuses (FetchTooSoon) when the same
source was fetched less than min_interval_s ago. The last-fetch time lives in
<raw_dir>/.last_fetch.json so separate runs respect it too. It never waits or
retries on its own.

Every attempt that reaches the network saves the body unchanged to
<raw_dir>/<source_id>/<UTC timestamp>.<ext> and appends a row to
<raw_dir>/manifest.csv (source_id, url, fetched_utc, http_status, bytes,
sha256, path) before returning. A non-200 response is saved and logged the
same way, then raises FetchError.

Run with Homebrew Python: some sources (e.g. Arizona) require TLS 1.3.
"""
import csv
import hashlib
import json
import os
import posixpath
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "election-tracker-fetch/0.1"
TIMEOUT = 120
FIELDS = ["source_id", "url", "fetched_utc", "http_status", "bytes", "sha256", "path"]


class FetchTooSoon(RuntimeError):
    pass


class FetchError(RuntimeError):
    pass


def _urllib_opener(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def fetch(source_id, url, min_interval_s, raw_dir="data/raw", now=time.time, opener=None):
    opener = opener or _urllib_opener
    os.makedirs(raw_dir, exist_ok=True)
    state_path = os.path.join(raw_dir, ".last_fetch.json")
    state = _load_state(state_path)
    t = now()
    last = state.get(source_id)
    if last is not None and t - last < min_interval_s:
        raise FetchTooSoon(f"{source_id}: last fetched {t - last:.0f}s ago; minimum is {min_interval_s}s")

    state[source_id] = t
    with open(state_path, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)

    status, body = opener(url)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t))
    ext = posixpath.splitext(urllib.parse.urlparse(url).path)[1].lstrip(".") or "bin"
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{stamp}.{ext}")
    with open(path, "wb") as f:
        f.write(body)

    manifest = os.path.join(raw_dir, "manifest.csv")
    new = not os.path.exists(manifest)
    with open(manifest, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"source_id": source_id, "url": url,
                    "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                    "http_status": status, "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(), "path": path})

    if status != 200:
        raise FetchError(f"{source_id}: HTTP {status} from {url} (saved to {path})")
    return path
