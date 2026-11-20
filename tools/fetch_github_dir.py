#!/opt/homebrew/bin/python3
"""Download every file in one directory of a public GitHub repo, pinned to a commit.

    /opt/homebrew/bin/python3 tools/fetch_github_dir.py OWNER/REPO DIR OUT_DIR MANIFEST_DIR

Resolves the default branch to a commit SHA, lists DIR at that commit, and saves
each file to OUT_DIR/<name> unchanged (archives are not extracted). Appends one
row per file to MANIFEST_DIR/fetch-<UTC timestamp>.csv:
repo, commit, path, url, fetched_utc, http_status, bytes, expected_bytes, git_sha, sha256, error.

`git_sha` is GitHub's blob hash for the file; `sha256` is computed here over the
bytes received. A row whose `bytes` differs from `expected_bytes` is a failed or
truncated download. Standard library only; unauthenticated API (60 calls/hour).
"""
import csv
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request

UA = "election-tracker-fetch/0.1"
TIMEOUT = 120


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, resp.read()


def get_json(url):
    return json.loads(get(url)[1])


def git_blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def main(repo, dir_path, out_dir, manifest_dir):
    info = get_json(f"https://api.github.com/repos/{repo}")
    branch = info["default_branch"]
    commit = get_json(f"https://api.github.com/repos/{repo}/commits/{branch}")["sha"]
    listing = get_json(f"https://api.github.com/repos/{repo}/contents/{dir_path}?ref={commit}")
    files = [f for f in listing if f["type"] == "file" and not f["name"].startswith(".")]

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(manifest_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    manifest = os.path.join(manifest_dir, f"fetch-{stamp}.csv")
    fields = ["repo", "commit", "path", "url", "fetched_utc", "http_status", "bytes",
              "expected_bytes", "git_sha", "sha256", "error"]
    print(f"{repo} @ {commit[:12]} ({branch}): {len(files)} files in {dir_path}")
    failures = 0
    with open(manifest, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for f in files:
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{f['path']}"
            row = {"repo": repo, "commit": commit, "path": f["path"], "url": url,
                   "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "expected_bytes": f["size"], "http_status": "", "bytes": 0,
                   "git_sha": "", "sha256": "", "error": ""}
            try:
                status, data = get(url)
                with open(os.path.join(out_dir, f["name"]), "wb") as fh:
                    fh.write(data)
                row.update(http_status=status, bytes=len(data), git_sha=git_blob_sha(data),
                           sha256=hashlib.sha256(data).hexdigest())
                if len(data) != f["size"] or row["git_sha"] != f["sha"]:
                    row["error"] = "size or git hash mismatch with GitHub listing"
            except Exception as e:
                row["error"] = f"{type(e).__name__}: {e}"
            failures += bool(row["error"])
            writer.writerow(row)
            print(f"  {f['name']:40} {row['bytes']:>10}" + (f"  [{row['error']}]" if row["error"] else ""))
    print(f"\nWrote {manifest}; {failures} failure(s)")
    return failures


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit("usage: fetch_github_dir.py OWNER/REPO DIR OUT_DIR MANIFEST_DIR")
    if not ssl.HAS_TLSv1_3:
        sys.exit(f"{ssl.OPENSSL_VERSION} has no TLS 1.3; run with /opt/homebrew/bin/python3")
    sys.exit(1 if main(*sys.argv[1:]) else 0)
