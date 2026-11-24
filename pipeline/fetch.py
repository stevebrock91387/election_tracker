"""Polite, recorded downloads: the raw body is saved and logged before anyone parses it.

fetch(source_id, url, min_interval_s) refuses (FetchTooSoon) when the same
source was fetched less than min_interval_s ago. The last-fetch time lives in
<raw_dir>/.last_fetch.json so separate runs respect it too. It never waits or
retries on its own.

Every attempt that gets an HTTP response saves the body unchanged to
<raw_dir>/<source_id>/<UTC timestamp>.<ext> (ext: the URL path's extension, else
"bin", unless the caller passes ext) and appends a row to
<raw_dir>/manifest.csv (source_id, url, fetched_utc, http_status, bytes,
sha256, path) before returning. A non-200 response is saved and logged the
same way, then raises FetchError. An exception before any response (timeout,
DNS failure) still uses up the interval and saves nothing.

Safe for concurrent runs (several processes sharing one raw_dir): the interval check and
state update, and the manifest append, each happen under an exclusive lock on
<raw_dir>/.fetch.lock, and the state file is replaced atomically (written to a temporary
file, then renamed). The lock is not held during the download itself.

Run with Homebrew Python: some sources (e.g. Arizona) require TLS 1.3.
"""
import contextlib
import csv
import fcntl
import hashlib
import json
import os
import tempfile
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


@contextlib.contextmanager
def _locked(raw_dir):
    with open(os.path.join(raw_dir, ".fetch.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write_state(path, state):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".last_fetch.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def fetch(source_id, url, min_interval_s, raw_dir="data/raw", now=time.time, opener=None, ext=None):
    opener = opener or _urllib_opener
    os.makedirs(raw_dir, exist_ok=True)
    state_path = os.path.join(raw_dir, ".last_fetch.json")
    with _locked(raw_dir):
        state = _load_state(state_path)
        t = now()
        last = state.get(source_id)
        if last is not None and t - last < min_interval_s:
            raise FetchTooSoon(f"{source_id}: last fetched {t - last:.0f}s ago; minimum is {min_interval_s}s")
        state[source_id] = t
        _write_state(state_path, state)

    status, body = opener(url)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t))
    if ext is None:
        ext = posixpath.splitext(urllib.parse.urlparse(url).path)[1].lstrip(".") or "bin"
    out_dir = os.path.join(raw_dir, source_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{stamp}.{ext}")
    with open(path, "wb") as f:
        f.write(body)

    manifest = os.path.join(raw_dir, "manifest.csv")
    with _locked(raw_dir), open(manifest, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if f.tell() == 0:
            w.writeheader()
        w.writerow({"source_id": source_id, "url": url,
                    "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                    "http_status": status, "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(), "path": path})

    if status != 200:
        raise FetchError(f"{source_id}: HTTP {status} from {url} (saved to {path})")
    return path
