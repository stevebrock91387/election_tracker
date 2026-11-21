"""Cut ResultsAjax test fixtures from a real pass record (not run by the tests).

    /opt/homebrew/bin/python3 -m pipeline.make_resultsajax_fixture PASS_RECORD OUT_PREFIX RACE_ID [RACE_ID ...]

Writes, next to OUT_PREFIX (e.g. pipeline/tests/fixtures/ra_mt):
- <prefix>_page_<TYPE>.html: only the BuildCounty(...) calls for the chosen races
- <prefix>_race_<RACE_ID>.json: the race JSON exactly as saved
- <prefix>_media_<TYPE>.csv: header plus the rows for the chosen races
- <prefix>_pass.json: a pass record listing those files by basename, plus
  "_fixture_source_sha256" giving each source file's hash.
"""
import hashlib
import json
import os
import sys

from pipeline.readers.resultsajax import parse_page


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make(record_path, prefix, race_ids):
    with open(record_path) as f:
        rec = json.load(f)
    files, shas = [], {}
    for x in rec["files"]:
        src = x["path"]
        if x["kind"] == "page":
            with open(src, "rb") as f:
                races = [r for r in parse_page(f.read().decode("utf-8", "replace")) if r[1] in race_ids]
            if not races:
                continue
            out = f"{prefix}_page_{x['type']}.html"
            with open(out, "w") as f:
                f.write("\n".join(f"<input onclick=\"BuildCounty('{t}', '{r}', '{o}', '{p}');\" />"
                                  for t, r, o, p in races) + "\n")
        elif x["kind"] == "media":
            out = f"{prefix}_media_{x['type']}.csv"
            with open(src, "rb") as f:
                lines = f.read().decode("utf-8", "replace").splitlines(keepends=True)
            with open(out, "w", newline="") as f:
                f.write(lines[0])
                f.writelines(ln for ln in lines[1:] if ln.split(",", 1)[0] in race_ids)
        elif x["race_id"] in race_ids:
            out = f"{prefix}_race_{x['race_id']}.json"
            with open(src, "rb") as f, open(out, "wb") as g:
                g.write(f.read())
        else:
            continue
        files.append(dict(x, path=os.path.basename(out)))
        shas[os.path.basename(out)] = _sha(src)
    with open(f"{prefix}_pass.json", "w") as f:
        json.dump(dict(rec, files=files, failed_races=[], _fixture_source_sha256=shas), f, indent=1)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2], set(sys.argv[3:]))
