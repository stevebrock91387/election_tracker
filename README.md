# election-tracker

Own-source 2028 election tracking. Step 1 of 6: the source registry.

## sources/registry.csv

One row per state + DC.

- `status`
  - `verified`: the official results URL was confirmed from an official page or a 2026 source.
  - `partial`: the site exists, but its format or level isn't confirmed.
  - `unverified`: the `candidate_url` is a guess and hasn't been checked.
- `results_url` is filled only when the status is `verified` or `partial`.
- `statewide_live = no` means there is no statewide election-night feed, so each county has to be read separately (MI, NJ, WI).

## tools/check_sources.py

This runs on the Mac mini, because the cloud workspace can't reach most state sites.

    /opt/homebrew/bin/python3 tools/check_sources.py sources/registry.csv checks/

Use Homebrew's Python, not the system `python3`: the system one (Xcode's 3.9, LibreSSL 2.8.3) has no TLS 1.3, and some state sites (MA) refuse anything older. The script exits early if TLS 1.3 is missing, and each output row records the Python and SSL versions used.

It records the HTTP status, final URL, content type, size and hash for every URL, and never edits the registry. A 200 response only shows that the page exists. A row moves to `verified` only after someone looks at the page.
