"""Parse Alabama results: the Secretary of State's certified precinct ZIP (one .xls per county).

Design: docs/superpowers/specs/2026-11-24-step2-al-reader-design.md.

The ZIP holds 67 workbooks named like 2026_GENERAL_ELECTION-ST._CLAIR.xls (legacy BIFF, read with
xlrd; see requirements.txt). Each has one sheet: row 0 is "Contest Title", "Party", "Candidate" and
then one column per counting unit (precincts, plus ABSENTEE / PROVISIONAL units); then rows for
registered voters, ballots cast and blank ballots; then one row per (contest, choice), Over Votes and
Under Votes included. Cells are floats or empty; an empty (contest, unit) block means the contest is
not on that unit's ballot. No ids, no vote types, no county or state totals.

Rows: level "precinct", county_id the filename token as published, county_name the token with "_"
read as a space, precinct_id = precinct_name = the column header, vote_type "TOTAL". Only state-level
contests (STRAIGHT PARTY, statewide offices and courts, US Senate and House, State Board of
Education, legislature, statewide amendments) are read; the rest are counted. The turnout table has
one row per unit: registered voters, ballots cast and blank ballots as published.

Nothing is corrected. The summary lists contests whose lines don't sum to the unit's ballots cast,
partly empty blocks, cells that aren't numbers or aren't whole, repeated lines and unit headers,
blank unit headers, real precincts that carry two districts of one office (split polling places:
each district's lines then fall short of the unit's ballots cast), counties whose registered voters are all 0, missing header rows, unreadable or
oversized workbooks, repeated counties, empty registered/ballots cells, counties whose balance check
couldn't run, out-of-scope titles that look state-level, extra sheets and ZIP members that aren't county workbooks. A missing or
unreadable ZIP leaves every check None.
"""
import hashlib
import io
import json
import os
import re
import zipfile

from pipeline.schema import COLUMNS

HEAD = ["Contest Title", "Party", "Candidate"]
REGISTERED, BALLOTS, BLANK = "REGISTERED VOTERS - TOTAL", "BALLOTS CAST - TOTAL", "BALLOTS CAST - BLANK"
HEADER_ROWS = [REGISTERED, BALLOTS, BLANK]
IN_SCOPE = re.compile(
    r"STRAIGHT PARTY|GOVERNOR|LIEUTENANT GOVERNOR|ATTORNEY GENERAL|SECRETARY OF STATE|STATE TREASURER"
    r"|STATE AUDITOR|COMMISSIONER OF AGRICULTURE AND INDUSTRIES|PUBLIC SERVICE COMMISSION, PLACE \d+"
    r"|CHIEF JUSTICE OF THE SUPREME COURT|ASSOCIATE JUSTICE OF THE SUPREME COURT, PLACE \d+"
    r"|COURT OF (CIVIL|CRIMINAL) APPEALS JUDGE, PLACE \d+|UNITED STATES SENATOR"
    r"|UNITED STATES REPRESENTATIVE, \d+(ST|ND|RD|TH) CONGRESSIONAL DISTRICT"
    r"|STATE BOARD OF EDUCATION MEMBER DISTRICT \d+|STATE SENATOR, DISTRICT \d+"
    r"|STATE REPRESENTATIVE, DISTRICT \d+|PROPOSED STATEWIDE AMENDMENT \d+")
DISTRICT_OFFICE = re.compile(r"UNITED STATES REPRESENTATIVE|STATE SENATOR|STATE REPRESENTATIVE|STATE BOARD OF EDUCATION MEMBER")
# Out-of-scope titles that look state-level are listed, so a renamed or new contest (e.g. President in
# 2028) is seen rather than silently dropped.
STATE_LIKE = re.compile(r"UNITED STATES|PRESIDENT|GOVERNOR|SENAT|REPRESENTATIVE|SUPREME|APPEALS|STATEWIDE"
                        r"|STATE BOARD|SECRETARY OF STATE|TREASURER|AUDITOR|ATTORNEY GENERAL|PUBLIC SERVICE"
                        r"|AGRICULTURE|STRAIGHT", re.I)
VIRTUAL = re.compile(r"\b(ABSENTEE|PROVISIONAL|PROVSIONAL)\b")
MEMBER = re.compile(r"(?:.*/)?[^/]*-([A-Z][A-Z_.]*)\.xls")
MAX_MEMBER_BYTES = 50 * 1024 * 1024
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "precinct_id",
                   "registered_voters", "ballots_cast", "ballots_blank"]
COUNTY_LISTS = ["ballot_balance_mismatches", "partial_blocks", "non_numeric", "non_integer", "duplicate_lines",
                "duplicate_units", "blank_units", "multi_district_units", "empty_header_cells", "missing_header_rows"]
LISTS = COUNTY_LISTS + ["balance_not_checked_counties", "out_of_scope_state_like", "counties_registered_all_zero",
                        "unreadable_workbooks", "duplicate_counties", "extra_sheets", "other_members"]
NEEDS_A_COUNTY = COUNTY_LISTS + ["balance_not_checked_counties", "out_of_scope_state_like", "counties_registered_all_zero",
                                 "extra_sheets", "units", "virtual_units", "contests", "contests_out_of_scope"]
COUNTS = ["counties", "units", "virtual_units", "contests", "contests_out_of_scope"]


def read_workbook(data):
    """One workbook's first sheet as a grid: str, float, or None for an empty cell; other cell types
    (booleans, errors) as a tagged string so they are listed as non-numeric. Also the sheet names."""
    import xlrd  # only this reader needs it; see requirements.txt
    book = xlrd.open_workbook(file_contents=data, logfile=io.StringIO(), verbosity=0)
    names = book.sheet_names()
    if not names:
        raise ValueError("no sheet")
    sh = book.sheet_by_index(0)
    grid = []
    for r in range(sh.nrows):
        row = []
        for c in range(sh.ncols):
            t, v = sh.cell_type(r, c), sh.cell_value(r, c)
            if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                row.append(None)
            elif t in (xlrd.XL_CELL_NUMBER, xlrd.XL_CELL_TEXT):
                row.append(v)
            else:
                row.append(f"#cell type {t}: {v!r}")
        grid.append(row)
    return grid, names


def _count(v, county, r, c, f):
    """int for a whole number; None for an empty cell; "" (and a listing) for anything else."""
    if v is None:
        return None
    if isinstance(v, float) and not isinstance(v, bool):
        if v == int(v):
            return int(v)
        f["non_integer"].append((county, r, c, v))
        return ""
    f["non_numeric"].append((county, r, c, v))
    return ""


def _text(v):
    return "" if v is None else str(v).strip()


def _contest_type(name):
    if name == "STRAIGHT PARTY":
        return "straight party"
    return "measure" if name.startswith("PROPOSED STATEWIDE AMENDMENT") else "candidate"


def parse_county(county, grid, base):
    f = {k: [] for k in COUNTY_LISTS}
    f.update(out_of_scope=set(), contests=set(), registered_all_zero=False, units=0, virtual_units=0)
    width = len(grid[0])
    units, seen_units = [], set()
    for j in range(3, width):
        name = _text(grid[0][j])
        if not name:
            f["blank_units"].append((county, j))
        elif name in seen_units:
            f["duplicate_units"].append((county, name))
        else:
            seen_units.add(name)
            units.append((j, name))
    f["units"] = len(units)
    f["virtual_units"] = sum(1 for _, n in units if VIRTUAL.search(n))

    def cell(r, j):
        return grid[r][j] if j < len(grid[r]) else None

    header, lines, seen_lines = {}, [], set()
    for r in range(1, len(grid)):
        title = _text(grid[r][0] if grid[r] else None)
        cand = _text(cell(r, 2))
        if title in HEADER_ROWS and title not in header:
            header[title] = r
            seen_lines.add((title, cand))
            continue
        if (title, cand) in seen_lines:
            f["duplicate_lines"].append((county, title, cand))
            continue
        seen_lines.add((title, cand))
        if IN_SCOPE.fullmatch(title):
            f["contests"].add(title)
            lines.append((r, title, _text(cell(r, 1)), cand))
        else:
            f["out_of_scope"].add(title)
    f["out_of_scope_state_like"] = sorted(n for n in f["out_of_scope"] - set(HEADER_ROWS) if STATE_LIKE.search(n))
    for name in HEADER_ROWS:
        if name not in header:
            f["missing_header_rows"].append((county, name))

    unit_values = {name: {} for name in HEADER_ROWS}
    for j, unit in units:
        for name in HEADER_ROWS:
            r = header.get(name)
            v = "" if r is None else _count(cell(r, j), county, r, j, f)
            if v is None:
                f["empty_header_cells"].append((county, unit, name))
                v = ""
            unit_values[name][j] = v
    reg = unit_values[REGISTERED]
    f["registered_all_zero"] = REGISTERED in header and bool(units) and all(reg[j] == 0 for j, _ in units)

    base = dict(dict.fromkeys(COLUMNS, ""), **base, level="precinct", county_id=county,
                county_name=county.replace("_", " "), contest_scope="statewide", vote_type="TOTAL")
    counts = {(r, j): _count(cell(r, j), county, r, j, f) for r, *_ in lines for j, _ in units}
    blocks = {}
    for r, title, party, cand in lines:
        blocks.setdefault(title, []).append(r)
    rows = []
    if BALLOTS not in header:
        f["ballot_balance_mismatches"] = None
    for j, unit in units:
        virtual = "Y" if VIRTUAL.search(unit) else "N"
        live = set()
        for title, rs in blocks.items():
            vals = [counts[(r, j)] for r in rs]
            if all(v is None for v in vals):
                continue
            live.add(title)
            if any(v is None for v in vals):
                f["partial_blocks"].append((county, unit, title))
            elif f["ballot_balance_mismatches"] is not None and all(isinstance(v, int) for v in vals):
                b = unit_values[BALLOTS][j]
                if isinstance(b, int) and sum(vals) != b:
                    f["ballot_balance_mismatches"].append((county, unit, title, sum(vals), b))
        if virtual == "N":
            fams = {}
            for title in live:
                m = DISTRICT_OFFICE.match(title)
                if m:
                    vals = [counts[(r, j)] for r in blocks[title]]
                    total = sum(vals) if all(isinstance(v, int) for v in vals) else None
                    fams.setdefault(m.group(0), []).append((title, total))
            for fam, entries in sorted(fams.items()):
                if len(entries) > 1:
                    f["multi_district_units"].append((county, unit, fam, sorted(entries)))
        for r, title, party, cand in lines:
            v = counts[(r, j)]
            if title in live and v is not None:
                rows.append(dict(base, precinct_id=unit, precinct_name=unit, precinct_is_virtual=virtual,
                                 contest_id=title, contest_name=title, contest_type=_contest_type(title),
                                 choice=cand, party=party, votes=v))
    turnout = [dict(state=base["state"], source_id=base["source_id"], source_sha256=base["source_sha256"],
                    county_id=county, county_name=base["county_name"], precinct_id=unit,
                    registered_voters=reg[j], ballots_cast=unit_values[BALLOTS][j],
                    ballots_blank=unit_values[BLANK][j]) for j, unit in units]
    return rows, turnout, f


def parse_pass(record_path, base_dir="."):
    with open(record_path) as fh:
        rec = json.load(fh)
    summary = {k: [] for k in LISTS}
    summary.update({k: 0 for k in COUNTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"])) for x in rec["files"]}
    summary["missing_files"] = [k for k in ("zip",) if k not in paths]

    def unread(reason=None):
        if reason:
            summary["unreadable_files"].append(("zip", reason))
        for k in LISTS + COUNTS:
            summary[k] = None
        return [], summary, []

    if "zip" not in paths:
        return unread()
    try:
        with open(paths["zip"], "rb") as fh:
            body = fh.read()
        z = zipfile.ZipFile(io.BytesIO(body))
        infos = z.infolist()
    except (OSError, zipfile.BadZipFile) as e:
        return unread(str(e))
    members = []
    for info in infos:
        if info.is_dir():
            continue
        m = MEMBER.fullmatch(info.filename)
        if m:
            members.append((info, m.group(1)))
        else:
            summary["other_members"].append(info.filename)
    if not members:
        return unread("no county workbooks in the ZIP")

    base = {"state": rec["state"], "source_id": rec["source_id"], "source_sha256": hashlib.sha256(body).hexdigest()}
    rows, turnout, contests, out, seen, state_like = [], [], set(), set(), set(), set()
    for info, county in members:
        if county in seen:
            summary["duplicate_counties"].append((info.filename, county))
            continue
        if info.file_size > MAX_MEMBER_BYTES:
            summary["unreadable_workbooks"].append((info.filename, f"too large: {info.file_size} bytes"))
            continue
        try:
            grid, names = read_workbook(z.read(info))
        except Exception as e:  # xlrd raises many types on malformed input; the workbook is listed, not fatal
            summary["unreadable_workbooks"].append((info.filename, f"{type(e).__name__}: {e}"))
            continue
        first = [_text(v) for v in grid[0][:3]] if grid else []
        if first != HEAD:
            summary["unreadable_workbooks"].append((info.filename, f"first row is {first}, not {HEAD}"))
            continue
        if len(names) > 1:
            summary["extra_sheets"].append((info.filename, names[1:]))
        seen.add(county)
        r, t, f = parse_county(county, grid, base)
        rows += r
        turnout += t
        for k in COUNTY_LISTS:
            if f[k] is not None:
                summary[k] += f[k]
        if f["ballot_balance_mismatches"] is None:
            summary["balance_not_checked_counties"].append(county)
        if f["registered_all_zero"]:
            summary["counties_registered_all_zero"].append(county)
        summary["units"] += f["units"]
        summary["virtual_units"] += f["virtual_units"]
        contests |= f["contests"]
        state_like |= set(f["out_of_scope_state_like"])
        out |= f["out_of_scope"]
    if not seen:  # no county could be read: no check ran
        for k in NEEDS_A_COUNTY:
            summary[k] = None
        return rows, summary, turnout
    out -= set(HEADER_ROWS)
    summary["out_of_scope_state_like"] = sorted(state_like)
    summary.update(counties=len(seen), contests=len(contests), contests_out_of_scope=len(out))
    return rows, summary, turnout
