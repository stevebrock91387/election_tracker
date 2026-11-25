"""Parse Wyoming results: the Secretary of State's official results ZIP (three .xlsx workbooks).

Design: docs/superpowers/specs/2026-11-24-step2-wy-reader-design.md.

The ZIP holds PBP (one sheet per county: precinct results), TBC (one sheet per county: total ballots
cast per precinct) and SUMMARIES (statewide sheets with one row per county). Result sheets share a
block layout: row 3 names each contest at its block's first column, row 4 names each column's choice
("Harriet\\nHageman (R)", Write-Ins, Overvotes, Undervotes), data rows follow with the unit (precinct
or county) in column A, then a "Total" row. "-" means the contest is not on
that unit's ballot. Counts are numeric cells (the summaries workbook, a Google Sheets export, holds
cached formula values); names and "-" are strings. An .xlsx is a ZIP of XML parts, read here with the
stdlib only.
"""
import datetime
import hashlib
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

from pipeline.schema import COLUMNS

PBP = "2026 County General PbP - OFFICIAL.xlsx"
TBC = "2026 County General PbP TBC - OFFICIAL.xlsx"
SUMMARIES = "2026 General Results Summaries - OFFICIAL.xlsx"
MAX_MEMBER_BYTES = 50 * 1024 * 1024
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "precinct_id",
                   "precinct_name", "ballots_cast"]

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _blank(v):
    return v is None or not str(v).strip()


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read(z, name):
    info = z.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise ValueError(f"{name} is {info.file_size} bytes uncompressed (limit {MAX_MEMBER_BYTES})")
    return z.read(name)


BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(45, 48))
_TOKEN = re.compile(r'y+|m+|d+|\\.|"[^"]*"|[-/. ]')
_SIMPLE = {"yyyy", "yy", "mm", "m", "dd", "d"}  # mmm/dddd (names) and others are not rendered


def _date_like(code):
    """True when a format code shows dates (a d, m or y outside quotes and escapes)."""
    bare = re.sub(r'\\.|"[^"]*"', "", code)
    return bool(re.search(r"[dmy]", bare, re.I))


def render_date(raw, code, date1904):
    """Render an integer date serial with a simple m/d/y format code; None when either isn't simple."""
    if not re.fullmatch(r"\d+", raw or ""):
        return None
    serial = int(raw)
    try:
        if date1904:
            day = datetime.date(1904, 1, 1) + datetime.timedelta(days=serial)
        elif serial >= 61:  # serials below 61 straddle Excel's fictitious 1900-02-29
            day = datetime.date(1899, 12, 30) + datetime.timedelta(days=serial)
        else:
            return None
    except (OverflowError, ValueError):
        return None
    out, pos = [], 0
    for m in _TOKEN.finditer(code):
        if m.start() != pos:
            return None
        t, pos = m.group(), m.end()
        if t[0] in "ymd" and t not in _SIMPLE:
            return None
        out.append({"yyyy": f"{day.year:04d}", "yy": f"{day.year % 100:02d}", "mm": f"{day.month:02d}",
                    "m": str(day.month), "dd": f"{day.day:02d}", "d": str(day.day)}.get(
            t, t[1:] if t.startswith("\\") else t.strip('"') if t.startswith('"') else t))
    return "".join(out) if pos == len(code) else None


def read_xlsx(data, notes=None, render_columns=(0,)):
    """Return [(sheet name, grid)] in workbook order. grid[i] is row i+1; cells are str or None.

    A numeric cell in `render_columns` (unit names) styled with a date format is rendered as the format
    displays it; elsewhere a date-styled numeric cell keeps its raw value and is listed; `notes` (a dict,
    optional) receives "date_formatted_cells" [(sheet, ref, raw, shown)] and "unrendered_formats"
    [(sheet, ref, raw, format code)].
    """
    notes = {} if notes is None else notes
    notes.setdefault("date_formatted_cells", [])
    notes.setdefault("unrendered_formats", [])
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        styles = {}  # cellXfs index -> format code of a date-like format
        if "xl/styles.xml" in names:
            st = ET.fromstring(_read(z, "xl/styles.xml"))
            codes = {int(f.get("numFmtId")): f.get("formatCode") or "" for f in st.iter(_M + "numFmt")}
            xfs = st.find(_M + "cellXfs")
            for i, xf in enumerate(xfs if xfs is not None else []):
                fid = int(xf.get("numFmtId") or 0)
                if fid in codes and _date_like(codes[fid]):
                    styles[i] = codes[fid]
                elif fid not in codes and fid in BUILTIN_DATE_FORMATS:
                    styles[i] = f"built-in {fid}"
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(_read(z, "xl/sharedStrings.xml")).iter(_M + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_M + "t")))
        wb = ET.fromstring(_read(z, "xl/workbook.xml"))
        pr = wb.find(_M + "workbookPr")
        date1904 = pr is not None and pr.get("date1904") in ("1", "true")
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(_read(z, "xl/_rels/workbook.xml.rels")).iter(_REL + "Relationship")}
        out = []
        for sheet in wb.iter(_M + "sheet"):
            target = rels[sheet.get(_R + "id")].lstrip("/")
            part = target if target.startswith("xl/") else "xl/" + target
            rows = {}
            for row in ET.fromstring(_read(z, part)).iter(_M + "row"):
                cells = {}
                for c in row.iter(_M + "c"):
                    v = c.find(_M + "v")
                    if c.get("t") == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(_M + "t"))
                    elif v is None:
                        continue
                    elif c.get("t") == "s":
                        val = shared[int(v.text)]
                    else:
                        val = v.text or ""
                        code = styles.get(int(c.get("s") or 0))
                        if code is not None and c.get("t") in (None, "n"):
                            col = _col(c.get("r"))
                            shown = None if code.startswith("built-in") or col not in render_columns \
                                else render_date(val, code, date1904)
                            if shown is None:
                                notes["unrendered_formats"].append((sheet.get("name"), c.get("r"), val, code))
                            else:
                                notes["date_formatted_cells"].append((sheet.get("name"), c.get("r"), val, shown))
                                val = shown
                    cells[_col(c.get("r"))] = val
                width = max(cells) + 1 if cells else 0
                rows[int(row.get("r"))] = [cells.get(i) for i in range(width)]
            out.append((sheet.get("name"), [rows.get(n, []) for n in range(1, max(rows, default=0) + 1)]))
        return out
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, ValueError, AttributeError, TypeError,
            OverflowError, EOFError, NotImplementedError, zlib.error) as e:
        raise ValueError(f"not a readable workbook: {e}") from e


def _cell(row, c):
    return row[c] if c < len(row) else None


def parse_blocks(grid):
    """Split a result sheet into contests: [{"name", "columns": [(col, header)], "units": [(row number,
    unit, {col: cell})], "total": {col: cell} or None}], plus problems found in the layout."""
    problems = {"blank_headers": [], "out_of_place_cells": [], "trailing_text": [], "layout": []}
    row3 = grid[2] if len(grid) > 2 else []
    row4 = grid[3] if len(grid) > 3 else []
    starts = [(c, v) for c, v in enumerate(row3) if not _blank(v)]
    if not starts:
        problems["layout"].append("no contest names in row 3")
        return [], problems
    total_at = next((i for i in range(4, len(grid)) if (_cell(grid[i], 0) or "").strip() == "Total"), None)
    body = grid[4:total_at] if total_at is not None else grid[4:]
    if total_at is None:
        problems["layout"].append("no Total row")
    width = max([len(row4)] + [len(r) for r in body])
    contests = []
    for i, (start, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else width
        columns = []
        for c in range(start, end):
            h = _cell(row4, c)
            if not _blank(h):
                columns.append((c, h))
            elif any(not _blank(_cell(r, c)) for r in body):
                problems["blank_headers"].append((name, c))
        contests.append({"name": name, "columns": columns, "units": [], "total": None})
    for n, row in enumerate(body, start=5):
        unit = (_cell(row, 0) or "").strip()
        if not unit:
            problems["out_of_place_cells"].extend((n, c, v) for c, v in enumerate(row) if c and not _blank(v))
            continue
        for ct in contests:
            ct["units"].append((n, unit, {c: _cell(row, c) for c, _ in ct["columns"]}))
    if total_at is not None:
        for ct in contests:
            ct["total"] = {c: _cell(grid[total_at], c) for c, _ in ct["columns"]}
        for n, row in enumerate(grid[total_at + 1:], start=total_at + 2):
            problems["trailing_text"].extend((n, v) for v in row if not _blank(v))
    return contests, problems


MEMBERS = {PBP: "PbP", TBC: "TBC", SUMMARIES: "Summaries"}
_MISSING = object()
BALLOTS = "Total Ballots Cast"
STATE_BALLOTS_SHEET = "Statewide Total Ballots Cast"
NON_CANDIDATE = {"Write-Ins", "Overvotes", "Undervotes"}
PARTY = re.compile(r"(.*?)\s*\((\w+)\)$")
LIST_KEYS = ["total_row_mismatches", "total_row_not_checked", "county_mismatches", "county_not_checked",
             "ballots_mismatches", "ballot_balance_mismatches", "non_numeric", "empty_cells", "empty_unit_rows",
             "duplicate_units", "duplicate_choices", "duplicate_contests", "blank_headers", "out_of_place_cells",
             "trailing_text", "units_not_on_any_ballot", "unmatched_tbc_precincts", "sheet_mismatches", "layout_problems",
             "date_formatted_cells", "unrendered_formats"]
NEEDS = {  # check -> members it needs
    "county_mismatches": (PBP, SUMMARIES), "county_not_checked": (PBP, SUMMARIES),
    "ballots_mismatches": (TBC, SUMMARIES), "ballot_balance_mismatches": (PBP, TBC),
    "unmatched_tbc_precincts": (PBP, TBC), "duplicate_units": (PBP,), "empty_cells": (PBP,),
    "empty_unit_rows": (PBP,), "units_not_on_any_ballot": (PBP,),
}


def _collapse(v):
    return " ".join((v or "").split())


def _choice(header):
    h = _collapse(header)
    m = PARTY.fullmatch(h)
    return (m.group(1), m.group(2)) if m else (h, "")


def _contest_type(choices):
    named = {c for c in choices if c not in NON_CANDIDATE}
    if named and named <= {"For", "Against"}:
        return "measure"
    if named and named <= {"Yes", "No"}:
        return "retention"
    return "candidate"


def _num(v):
    """int for a count, "-" for not on the ballot, None for empty, the text itself when non-numeric."""
    if _blank(v):
        return None
    t = str(v).strip()
    if t == "-":
        return "-"
    return int(t) if re.fullmatch(r"\d+", t) else t


def parse_single(grid):
    """A one-column ballots sheet: (units [(row number, unit, cell)], total cell or None, problems)."""
    head = next((i for i, r in enumerate(grid) if _collapse(_cell(r, 1)) == BALLOTS), None)
    if head is None:
        return [], None, [f"no '{BALLOTS}' header"]
    units, total, problems = [], None, []
    for i in range(head + 1, len(grid)):
        unit = _collapse(_cell(grid[i], 0))
        if unit == "Total":
            total = _cell(grid[i], 1)
            break
        if unit:
            units.append((i + 1, unit, _cell(grid[i], 1)))
        elif not _blank(_cell(grid[i], 1)):
            problems.append(f"value without a unit in row {i + 1}")
    else:
        problems.append("no Total row")
    return units, total, problems


def _results(summary, label, sheet, grid, emit, level_of_unit):
    """Parse one result sheet into rows (via emit) and return {(unit, contest, choice): value},
    {(contest, choice): Total-row value} and {(unit, contest): lines sum or None}."""
    contests, probs = parse_blocks(grid)
    summary["blank_headers"].extend((sheet, c, col) for c, col in probs["blank_headers"])
    summary["out_of_place_cells"].extend((sheet,) + x for x in probs["out_of_place_cells"])
    summary["trailing_text"].extend((sheet,) + x for x in probs["trailing_text"])
    summary["layout_problems"].extend((label, sheet, x) for x in probs["layout"])
    values, totals, lines, units = {}, {}, {}, set()
    if not contests:
        return values, totals, lines, units
    blank_rows = {n for n, _, _ in contests[0]["units"]
                  if all(_blank(v) for ct in contests for m, _, cells in ct["units"] if m == n for v in cells.values())}
    for n, unit, _ in contests[0]["units"]:
        if n in blank_rows:
            if level_of_unit == "precinct":
                summary["empty_unit_rows"].append((sheet, n, unit))
            continue
        units.add(unit)
        cells = [v for ct in contests for m, _, cl in ct["units"] if m == n for v in cl.values()]
        if level_of_unit == "precinct" and all(_blank(v) or str(v).strip() == "-" for v in cells):
            summary["units_not_on_any_ballot"].append((sheet, n, unit))
    seen_units, seen_contests = {}, set()
    for ct in contests:
        name = _collapse(ct["name"])
        if name in seen_contests:
            summary["duplicate_contests"].append((sheet, name))
            continue
        seen_contests.add(name)
        cols, seen_choices = [], set()
        for c, h in ct["columns"]:
            choice, party = _choice(h)
            if choice in seen_choices:
                summary["duplicate_choices"].append((sheet, name, choice))
                continue
            seen_choices.add(choice)
            cols.append((c, choice, party))
        ctype = _contest_type([ch for _, ch, _ in cols])
        sums = {ch: 0 for _, ch, _ in cols}
        for n, unit, cells in ct["units"]:
            if n in blank_rows:
                continue
            first = seen_units.setdefault(unit, n)
            if first != n:
                if level_of_unit == "precinct" and (sheet, unit) not in summary["duplicate_units"]:
                    summary["duplicate_units"].append((sheet, unit))
                continue
            line_sum = 0
            for c, choice, party in cols:
                v = _num(cells.get(c))
                if v is None:
                    if level_of_unit == "precinct":
                        summary["empty_cells"].append((sheet, unit, name, choice))
                    line_sum = None
                    continue
                if v == "-":
                    summary["not_on_ballot_cells"] += 1
                    line_sum = None if line_sum is None else line_sum
                    continue
                if not isinstance(v, int):
                    summary["non_numeric"].append((sheet, unit, name, choice, v))
                    sums[choice] = None
                    line_sum = None
                    emit(level_of_unit, sheet, unit, name, ctype, choice, party, "")
                    continue
                if sums[choice] is not None:
                    sums[choice] += v
                if line_sum is not None:
                    line_sum += v
                values[(unit, name, choice)] = v
                emit(level_of_unit, sheet, unit, name, ctype, choice, party, v)
            if any(_num(cells.get(c)) not in (None, "-") for c, _, _ in cols):
                lines[(unit, name)] = line_sum
            for c, choice, _ in cols:
                if _num(cells.get(c)) == "-" or _num(cells.get(c)) is None:
                    values.setdefault((unit, name, choice), _num(cells.get(c)))
                elif not isinstance(_num(cells.get(c)), int):
                    values[(unit, name, choice)] = _num(cells.get(c))
        for c, choice, party in cols:
            t = _num(ct["total"].get(c)) if ct["total"] is not None else None
            totals[(name, choice)] = t
            if level_of_unit == "county" and isinstance(t, int):
                emit("state", sheet, "", name, ctype, choice, party, t)
            all_dash = all(_num(cells.get(c)) in ("-", None) for n, _, cells in ct["units"] if n not in blank_rows)
            if t == "-" and all_dash:
                continue
            if not isinstance(t, int) or sums[choice] is None:
                summary["total_row_not_checked"].append((sheet, name, choice))
            elif t != sums[choice]:
                summary["total_row_mismatches"].append((sheet, name, choice, t, sums[choice]))
    return values, totals, lines, units


def parse_workbooks(base, books, notes=None):
    """books: {member: [(sheet, grid)]} for the members that could be read."""
    summary = {"sha256": base.get("source_sha256", ""), "counties": None, "precincts": None, "contests": None,
               "not_on_ballot_cells": 0, "other_members": [], "unreadable_members": [], "unreadable_files": [],
               "missing_files": [], "missing_members": [m for m in MEMBERS if m not in books]}
    summary.update({k: [] for k in LIST_KEYS})
    for m, n in (notes or {}).items():
        summary["date_formatted_cells"].extend((MEMBERS[m],) + x for x in n.get("date_formatted_cells", []))
        summary["unrendered_formats"].extend((MEMBERS[m],) + x for x in n.get("unrendered_formats", []))
    rows, turnout = [], []
    row_base = dict.fromkeys(COLUMNS, "")
    row_base.update(state=base["state"], source_id=base["source_id"], source_sha256=base.get("source_sha256", ""),
                    contest_scope="statewide", vote_type="TOTAL")

    def emit(level, sheet, unit, contest, ctype, choice, party, votes):
        r = dict(row_base, level=level, contest_id=contest, contest_name=contest, contest_type=ctype,
                 choice=choice, party=party, votes=votes)
        if level == "precinct":
            r.update(county_id=sheet, county_name=sheet, precinct_id=unit, precinct_name=unit, precinct_is_virtual="N")
        elif level == "county":
            r.update(county_id=unit, county_name=unit)
        rows.append(r)

    pbp_totals, pbp_lines, pbp_units, contests = {}, {}, {}, set()
    for sheet, grid in books.get(PBP, []):
        _, totals, lines, units = _results(summary, "PbP", sheet, grid, emit, "precinct")
        pbp_totals[sheet] = totals
        pbp_lines[sheet] = lines
        pbp_units[sheet] = units
        contests.update(c for c, _ in totals)
    summ_values, summ_ballots, summ_counties = {}, {}, set()
    for sheet, grid in books.get(SUMMARIES, []):
        if sheet == STATE_BALLOTS_SHEET:
            units, total, probs = parse_single(grid)
            summary["layout_problems"].extend(("Summaries", sheet, p) for p in probs)
            for _, county, cell in units:
                summ_ballots[county] = _num(cell)
                summ_counties.add(county)
            vals = [_num(c) for _, _, c in units]
            t = _num(total)
            if not isinstance(t, int) or not all(isinstance(v, int) for v in vals):
                summary["total_row_not_checked"].append((sheet, BALLOTS, ""))
            elif t != sum(vals):
                summary["total_row_mismatches"].append((sheet, BALLOTS, "", t, sum(vals)))
            continue
        values, _, _, _ = _results(summary, "Summaries", sheet, grid, emit, "county")
        summ_values.update(values)
        summ_counties.update(u for u, _, _ in values)
    tbc, tbc_units, tbc_bad = {}, {}, set()
    for sheet, grid in books.get(TBC, []):
        units, total, probs = parse_single(grid)
        if probs or not units:
            tbc_bad.add(sheet)
        summary["layout_problems"].extend(("TBC", sheet, p) for p in probs)
        seen = set()
        for _, unit, cell in units:
            if unit in seen:
                summary["duplicate_units"].append((f"TBC {sheet}", unit))
                continue
            seen.add(unit)
            v = _num(cell)
            tbc[(sheet, unit)] = v
            if not isinstance(v, int):
                summary["non_numeric"].append((f"TBC {sheet}", unit, BALLOTS, "", v))
            turnout.append(dict(state=base["state"], source_id=base["source_id"], source_sha256=base.get("source_sha256", ""),
                                county_id=sheet, county_name=sheet, precinct_id=unit, precinct_name=unit,
                                ballots_cast=v if v is not None else ""))
        tbc_units[sheet] = seen
        vals = [tbc[(sheet, u)] for u in seen]
        t = _num(total)
        if not isinstance(t, int) or not all(isinstance(v, int) for v in vals):
            summary["total_row_not_checked"].append((f"TBC {sheet}", BALLOTS, ""))
        elif t != sum(vals):
            summary["total_row_mismatches"].append((f"TBC {sheet}", BALLOTS, "", t, sum(vals)))

    have = set(books)
    if PBP in have and SUMMARIES in have:
        for county in sorted(set(pbp_totals) & summ_counties):
            keys = {(c, ch) for (u, c, ch) in summ_values if u == county} | set(pbp_totals[county])
            for contest, choice in sorted(keys):
                # Absent or "-" means not on that county's ballot; present but empty (None) means unreadable.
                s = summ_values.get((county, contest, choice), _MISSING)
                p = pbp_totals[county].get((contest, choice), _MISSING)
                s_absent, p_absent = s is _MISSING or s == "-", p is _MISSING or p == "-"
                if s_absent and p_absent:
                    continue
                if (not s_absent and not isinstance(s, int)) or (not p_absent and not isinstance(p, int)):
                    summary["county_not_checked"].append((county, contest, choice))
                elif s != p:
                    summary["county_mismatches"].append((county, contest, choice, None if s_absent else s, None if p_absent else p))
    if TBC in have and SUMMARIES in have:
        for county in sorted(set(tbc_units) & set(summ_ballots)):
            vals = [tbc[(county, u)] for u in tbc_units[county]]
            s = summ_ballots[county]
            if county in tbc_bad or not isinstance(s, int) or not all(isinstance(v, int) for v in vals):
                summary["county_not_checked"].append((county, BALLOTS, ""))
            elif s != sum(vals):
                summary["ballots_mismatches"].append((county, sum(vals), s))
    if PBP in have and TBC in have:
        for county in sorted(set(pbp_lines) & set(tbc_units)):
            for (unit, contest), total in sorted(pbp_lines[county].items()):
                b = tbc.get((county, unit))
                if isinstance(total, int) and isinstance(b, int) and total != b:
                    summary["ballot_balance_mismatches"].append((county, unit, contest, total, b))
            for unit in sorted(pbp_units[county] - tbc_units[county]):
                summary["unmatched_tbc_precincts"].append((county, unit, "pbp only"))
            for unit in sorted(tbc_units[county] - pbp_units[county]):
                summary["unmatched_tbc_precincts"].append((county, unit, "tbc only"))
    sets = {"pbp": set(pbp_totals) if PBP in have else None, "summaries": summ_counties if SUMMARIES in have else None,
            "tbc": set(tbc_units) if TBC in have else None}
    present = {k: v for k, v in sets.items() if v is not None}
    for county in sorted(set().union(*present.values()) if present else set()):
        inside = [k for k, v in present.items() if county in v]
        outside = [k for k, v in present.items() if county not in v]
        if outside:
            summary["sheet_mismatches"].append((county, ", ".join(inside), ", ".join(outside)))

    for k, needs in NEEDS.items():
        if not all(m in have for m in needs):
            summary[k] = None
    if len(have) < 2:
        summary["sheet_mismatches"] = None
    if PBP not in have:  # the precinct workbook is the data: without it no check stands (design)
        for k in LIST_KEYS:
            summary[k] = None
    if PBP in have:
        summary.update(counties=len(pbp_totals), precincts=sum(len(u) for u in pbp_units.values()), contests=len(contests))
    return rows, summary, turnout


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"])) for x in rec["files"]}
    base = {"state": rec["state"], "source_id": rec["source_id"], "source_sha256": ""}
    books, notes, problems = {}, {}, {"missing_files": [], "unreadable_files": [], "unreadable_members": [], "other_members": []}
    if "zip" not in paths:
        problems["missing_files"].append("zip")
    else:
        try:
            with open(paths["zip"], "rb") as f:
                data = f.read()
            base["source_sha256"] = hashlib.sha256(data).hexdigest()
            outer = zipfile.ZipFile(io.BytesIO(data))
            names = outer.namelist()
            problems["other_members"] = [n for n in names if n not in MEMBERS]
            for m in MEMBERS:
                if m not in names:
                    continue
                try:
                    notes[m] = {}
                    books[m] = read_xlsx(_read(outer, m), notes[m])
                except (ValueError, zipfile.BadZipFile, zlib.error, EOFError, OSError) as e:
                    problems["unreadable_members"].append((m, str(e)))
                    notes.pop(m)
        except (OSError, zipfile.BadZipFile) as e:
            problems["unreadable_files"].append(("zip", str(e)))
    rows, summary, turnout = parse_workbooks(base, books, notes)
    summary.update(problems)
    summary["missing_members"] = [] if problems["missing_files"] or problems["unreadable_files"] else \
        [m for m in MEMBERS if m not in books and m not in dict(problems["unreadable_members"])]
    return rows, summary, turnout
