"""Cut the AL test fixture from the 2026 certified precinct ZIP: three county workbooks, bytes unchanged.

    .venv/bin/python -m pipeline.make_al_fixture SOURCE_ZIP

Bullock (registered voters all 0), Coosa (registered voters present) and Jackson (the "PROVSIONAL"
column). Writes pipeline/tests/fixtures/al_results.zip and al_pass.json.
"""
import json
import os
import sys
import zipfile

COUNTIES = ["BULLOCK", "COOSA", "JACKSON"]
FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures")


def main(src):
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(os.path.join(FX, "al_results.zip"), "w", zipfile.ZIP_DEFLATED) as out:
        for c in COUNTIES:
            name = f"2026_GENERAL_ELECTION-{c}.xls"
            out.writestr(name, z.read(name))
    with open(os.path.join(FX, "al_pass.json"), "w") as f:
        json.dump({"source_id": "al-2026-general", "state": "AL", "started_utc": "20261124T000000Z",
                   "files": [{"kind": "zip", "path": "al_results.zip"}]}, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
