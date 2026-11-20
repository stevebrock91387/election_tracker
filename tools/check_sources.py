#!/opt/homebrew/bin/python3
"""Check every URL in sources/registry.csv and record what came back.

Run on the Mac mini (the cloud workspace can't reach most state sites):
    /opt/homebrew/bin/python3 tools/check_sources.py sources/registry.csv checks/

Needs an SSL library with TLS 1.3: some state sites (e.g. MA) refuse TLS 1.2.
The Xcode/system python3 (LibreSSL 2.8.3) lacks it, so the script exits early
there rather than record false TLS errors.

Writes checks/check-<UTC timestamp>.csv with one row per URL:
abbr, column, url, http_status, final_url, content_type, bytes, sha256, error,
python, ssl (the interpreter and SSL library that made the request).
Standard library only. Read-only: it never edits the registry.
"""
import csv
import hashlib
import os
import platform
import ssl
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) election-tracker-source-check/0.1"
TIMEOUT = 20
URL_COLUMNS = ("results_url", "candidate_url")


def check(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            return {
                "http_status": resp.status,
                "final_url": resp.geturl(),
                "content_type": resp.headers.get("Content-Type", ""),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "error": "",
            }
    except urllib.error.HTTPError as e:
        return {"http_status": e.code, "final_url": url, "content_type": "",
                "bytes": 0, "sha256": "", "error": f"HTTPError {e.code}"}
    except Exception as e:  # DNS failure, timeout, TLS, etc.
        return {"http_status": "", "final_url": url, "content_type": "",
                "bytes": 0, "sha256": "", "error": f"{type(e).__name__}: {e}"}


def main(registry_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = os.path.join(out_dir, f"check-{stamp}.csv")
    fields = ["abbr", "column", "url", "http_status", "final_url",
              "content_type", "bytes", "sha256", "error", "python", "ssl"]
    env = {"python": platform.python_version(), "ssl": ssl.OPENSSL_VERSION}
    print(f"python {env['python']}, {env['ssl']}")
    with open(registry_path, newline="") as f, open(out_path, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for row in csv.DictReader(f):
            for col in URL_COLUMNS:
                url = (row.get(col) or "").strip()
                if not url:
                    continue
                result = check(url)
                writer.writerow({"abbr": row["abbr"], "column": col, "url": url, **result, **env})
                print(f"{row['abbr']:3} {col:14} {result['http_status'] or '---':>4} {url}"
                      + (f"  [{result['error']}]" if result["error"] else ""))
    print(f"\nWrote {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: check_sources.py <registry.csv> <out_dir>")
    if not ssl.HAS_TLSv1_3:
        sys.exit(f"{ssl.OPENSSL_VERSION} has no TLS 1.3; run with /opt/homebrew/bin/python3")
    main(sys.argv[1], sys.argv[2])
