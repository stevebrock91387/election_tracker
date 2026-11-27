"""Statement-of-votes table PDFs: Bergen County, NJ's district report (docs/pdfreport.md, "Bergen").

Each page holds one contest: its title (top left, wrapping over up to three lines), then rotated column
labels (Registered Voters, Voters Cast, Turnout (%), one per choice, Write-ins, Total Votes), then one
line per unit and vote type: "<unit> <Early Voting|Election Day|Mail-In|Provisional|Total> <cells>".
Units are election districts ("Allendale 1"), a municipality's provisional unit ("Allendale
Provisional"), the municipality subtotal ("Allendale"), and the contest's county rows ("Total - Early
Voting" ... "Contest Total"). Empty cells are not printed; "***" marks a cell the county withheld.

Two stages:
- table_pages(path) (pypdfium2) places every character: a column label is the characters standing in
  one horizontal band of the header (rotated lines, read right to left, each top to bottom), and a
  cell's characters go to the first column whose right edge (+5 pt) they don't pass (numbers are
  right-aligned). This also rejoins numbers PDFium's text splits ("1 17" for 117).
- parse_pages(pages, ...) (text only) turns those cells into rows and checks.
"""
import re

ROW_KINDS = ["Early Voting", "Election Day", "Mail-In", "Provisional", "Total"]
ROW_RE = re.compile(r"^(.*?)\s*\b(Early Voting|Election Day|Mail-In|Provisional|Total)((?:\s+(?:\d+|\d+\.\d+%|\*\*\*))*)\s*$")
SLACK = 5.0  # pt a right-aligned number may pass its label's right edge
MERGE_GAP = 4.0  # pt between label lines of one column
LINE_TOL = 4.0  # pt: one rotated label line (lines are ~8 pt apart; a period sits ~2-3 pt off centre)


def _clusters(boxes):
    """Group header characters into columns: horizontal intervals closer than MERGE_GAP join."""
    spans = sorted(boxes, key=lambda b: b[0])
    cols = []
    for b in spans:
        if cols and b[0] - cols[-1]["right"] < MERGE_GAP:
            cols[-1]["chars"].append(b)
            cols[-1]["right"] = max(cols[-1]["right"], b[1])
        else:
            cols.append({"left": b[0], "right": b[1], "chars": [b]})
    return cols


def _label(col, text):
    """A column's label. Its rotated lines (characters sharing a horizontal centre) read right to left;
    within a line the characters keep PDFium's text order, with a space where the text has whitespace.
    (PDFium's own order across a column's lines is sometimes reversed: "COLELLA PHILIP S.")"""
    lines = []
    for l, r, b, t, j in sorted(col["chars"], key=lambda c: -(c[0] + c[1]) / 2):
        c = (l + r) / 2
        if lines and abs(lines[-1][0] - c) < LINE_TOL:
            lines[-1][1].append(j)
        else:
            lines.append([c, [j]])
    words = []
    for _, idx in lines:
        out = ""
        for j in sorted(idx):
            if out and text[j - 1].isspace():
                out += " "
            out += text[j]
        words.append(out)
    # PDFium marks a hyphen printed at a line break as U+FFFE ("O'CONNELL-" / "SORIANO")
    return re.sub("\ufffe\\s*", "-", " ".join(" ".join(words).split()))


def table_pages(path):
    """[{title, labels, rows: [(left text, [cell per column])], unparsed, refreshed}] per page."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    out = []
    try:
        for i in range(len(pdf)):
            tp = pdf[i].get_textpage()
            text = tp.get_text_range()
            out.append(_page(text, tp.get_charbox))
    finally:
        pdf.close()
    return out


def _page(text, charbox):
    page = {"title": None, "labels": [], "rows": [], "unparsed": [], "refreshed": None}
    h = text.find("Registered Voters")
    if h < 0:
        # a page holding only the footnote and footer (page 712 of 2026) is not a table page
        if any(ROW_RE.match(x.strip()) and ROW_RE.match(x.strip()).group(3).strip() for x in text.split("\r\n")):
            page["unparsed"].append(("no header", text[:80]))
        return page
    page["title"] = " ".join(text[:h].split())
    lines, pos = [], 0
    for raw in text.split("\r\n"):
        lines.append((pos, raw))
        pos += len(raw) + 2
    first = next((k for k, (p, s) in enumerate(lines) if p > h and (m := ROW_RE.match(s.strip())) and m.group(3).strip()), None)
    if first is None:
        page["unparsed"].append(("no rows", page["title"]))
        return page
    hdr_end = lines[first][0]
    # A unit name wrapped from the previous page can sit between the labels and the first row; it lies
    # left of the first label ("Registered Voters"), so it is a name fragment, not a label.
    label_left = min(charbox(j)[0] for j in range(h, h + len("Registered Voters")) if not text[j].isspace()) - 2
    boxes, pending = [], []
    for p, s in lines:
        if p + len(s) <= h or p >= hdr_end:
            continue
        idx = [j for j in range(max(p, h), p + len(s)) if not text[j].isspace()]
        if idx and all(charbox(j)[2] < label_left for j in idx):
            pending.append(s.strip())
            continue
        for j in idx:
            l, b, r, t = charbox(j)
            boxes.append((l, r, b, t, j))
    cols = _clusters(boxes)
    page["labels"] = [_label(c, text) for c in cols]
    edges = [c["right"] + SLACK for c in cols]
    for p, s in lines[first:]:
        st = s.strip()
        if not st:
            continue
        if st.startswith("Data Refreshed:"):
            m = re.match(r"Data Refreshed:\s*(.*?)\s+Page \d+ of \d+", st)
            page["refreshed"] = m.group(1) if m else st
            break
        m = ROW_RE.match(st)
        if not m or not m.group(3).strip():
            # every row prints at least its registered voters, so a line with no cells is part of a
            # wrapped unit name ("Hasbrouck Heights" / "Provisional" / "Early Voting 0 0")
            if st.startswith("***"):
                continue
            if any(ch.isdigit() for ch in st) and not m:
                page["unparsed"].append(("line", st))
            else:
                pending.append(st)
            continue
        left = " ".join(pending + [f"{m.group(1)} {m.group(2)}".strip()]).strip()
        pending = []
        start = p + (len(s) - len(s.lstrip())) + m.start(3)
        cells = [""] * len(cols)
        for j in range(start, p + len(s)):
            ch = text[j]
            if ch.isspace():
                continue
            l, b, r, t = charbox(j)
            c = (l + r) / 2
            k = next((n for n, e in enumerate(edges) if c <= e), None)
            if k is None:
                page["unparsed"].append(("cell right of the last column", st))
                break
            cells[k] += ch
        page["rows"].append((left, cells))
    if pending:
        page["unparsed"].append(("name with no row", " ".join(pending)))
    return page


STATS = ["Registered Voters", "Voters Cast", "Turnout (%)"]
WRITE_IN, TOTAL_VOTES = "Write-ins", "Total Votes"
VOTE_TYPES = ["Early Voting", "Election Day", "Mail-In", "Provisional"]


def _cell(s):
    """"" (not printed) -> 0, "***" (withheld) -> None, else the integer; percents are not counts."""
    if s == "":
        return 0
    if s == "***":
        return None
    return int(s)


def _split_unit(left):
    kind = next(k for k in ROW_KINDS if left.endswith(k))
    unit = left[: -len(kind)].strip()
    if left == "Contest Total":
        return "COUNTY", "Total"
    if unit == "Total -":
        return "COUNTY", kind
    return unit, kind


def parse_pages(pages):
    """Contests from table_pages output.

    Returns (contests, issues). contests: {title: {"choices": [label...], "units": {unit: {"type",
    "kinds": {kind: {label: value}}}}}}, unit type "district" (an election district or a municipality's
    provisional unit), "municipality" (the subtotal of the units before it) or "county"."""
    contests, issues = {}, {"label_conflicts": [], "cell_conflicts": [], "unit_type_conflicts": [], "unparsed": []}
    block, last_title = [], None
    for n, p in enumerate(pages, 1):
        issues["unparsed"] += [(n,) + tuple(u) for u in p["unparsed"]]
        if not p["title"]:
            continue
        title = re.sub(r"^\d+\s+", "", p["title"])
        c = contests.setdefault(title, {"choices": [], "units": {}})
        if title != last_title:
            block, last_title = [], title
        labels = p["labels"]
        if labels[:3] != STATS:
            issues["label_conflicts"].append((n, title, labels[:3]))
            continue
        for lab in labels[3:]:
            if lab not in (WRITE_IN, TOTAL_VOTES) and lab not in c["choices"]:
                c["choices"].append(lab)
        for left, cells in p["rows"]:
            unit, kind = _split_unit(left)
            if unit == "COUNTY":
                utype = "county"
            elif unit in c["units"]:
                utype = c["units"][unit]["type"]
            elif block and all(b.startswith(unit + " ") for b in block):
                utype, block = "municipality", []
            else:
                utype = "district"
                if unit not in block:
                    block.append(unit)
            u = c["units"].setdefault(unit, {"type": utype, "kinds": {}})
            if u["type"] != utype:
                issues["unit_type_conflicts"].append((title, unit, u["type"], utype))
            vals = u["kinds"].setdefault(kind, {})
            for lab, s in zip(labels, cells):
                if lab == "Turnout (%)":
                    continue
                v = _cell(s)
                if lab in vals and vals[lab] != v:
                    issues["cell_conflicts"].append((title, unit, kind, lab, vals[lab], v))
                    continue
                vals[lab] = v
    return contests, issues


def check(contests):
    """Lists of what doesn't add up (blank cells count as 0; a withheld cell skips its sum)."""
    out = {"row_sums": [], "unattributed": {}, "vote_types_vs_total": [], "units_vs_municipality": [], "municipalities_vs_county": [],
           "withheld": 0, "registered_differs_by_type": [], "missing_columns": []}

    def add(vals):
        return None if None in vals else sum(vals)

    for title, c in contests.items():
        cols = c["choices"] + [WRITE_IN]
        for unit, u in c["units"].items():
            for kind, vals in u["kinds"].items():
                out["withheld"] += sum(1 for v in vals.values() if v is None)
                missing = [x for x in cols + [TOTAL_VOTES, "Voters Cast", "Registered Voters"] if x not in vals]
                if missing:
                    out["missing_columns"].append((title, unit, kind, missing))
                    continue
                # Total Votes also counts votes in no printed column (2026: the county remainder equals
                # LiveVoterTurnout's "Personal Choice" line); a negative remainder is an error
                s = add([vals[x] for x in cols])
                if s is not None and vals[TOTAL_VOTES] is not None:
                    if s > vals[TOTAL_VOTES]:
                        out["row_sums"].append((title, unit, kind, vals[TOTAL_VOTES], s))
                    elif unit == "COUNTY" and kind == "Total":
                        out["unattributed"][title] = vals[TOTAL_VOTES] - s
            kinds = u["kinds"]
            if "Total" in kinds and all(k in kinds for k in VOTE_TYPES):
                for lab in cols + [TOTAL_VOTES, "Voters Cast"]:
                    s = add([kinds[k].get(lab, 0) for k in VOTE_TYPES])
                    t = kinds["Total"].get(lab)
                    if s is not None and t is not None and s != t:
                        out["vote_types_vs_total"].append((title, unit, lab, t, s))
                regs = {kinds[k].get("Registered Voters") for k in kinds}
                if len(regs) > 1:
                    out["registered_differs_by_type"].append((title, unit, sorted(regs, key=str)))
        # districts -> municipality subtotal -> county, in document order
        order = list(c["units"].items())
        groups, cur = [], []
        for unit, u in order:
            if u["type"] == "district":
                cur.append(unit)
            elif u["type"] == "municipality":
                groups.append((unit, cur))
                cur = []
        if cur:
            out["units_vs_municipality"].append((title, "<districts after the last subtotal>", len(cur)))
        county = c["units"].get("COUNTY")
        labs = cols + [TOTAL_VOTES, "Voters Cast", "Registered Voters"]
        for kind in ROW_KINDS:
            for lab in labs:
                if lab == "Registered Voters" and kind != "Total":
                    continue
                msum = []
                for m, members in groups:
                    mv = c["units"][m]["kinds"].get(kind, {}).get(lab)
                    s = add([c["units"][x]["kinds"].get(kind, {}).get(lab, 0) for x in members])
                    if s is not None and mv is not None and s != mv:
                        out["units_vs_municipality"].append((title, m, kind, lab, mv, s))
                    msum.append(mv)
                cv = county["kinds"].get(kind, {}).get(lab) if county else None
                s = add(msum)
                if county is None:
                    continue
                if s is not None and cv is not None and s != cv:
                    out["municipalities_vs_county"].append((title, kind, lab, cv, s))
        if county is None:
            out["municipalities_vs_county"].append((title, "<no county rows>"))
    return out


def _choice(label):
    m = re.match(r"^([A-Z]{2,4}) - (.+)$", label)
    return (m.group(2), m.group(1)) if m else (label, "")


def parse_pass(rec, path, sha, pages_fn=table_pages):
    """(rows, summary, turnout) for one Bergen district-report PDF; rec is the pass record."""
    from pipeline.schema import COLUMNS

    pages = pages_fn(path)
    contests, issues = parse_pages(pages)
    chk = check(contests)
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], source_sha256=sha, county_name=rec["county"],
                contest_scope="local")
    rows, turnout = [], []
    for title, c in contests.items():
        cols = c["choices"] + [WRITE_IN]
        for unit, u in c["units"].items():
            if u["type"] == "municipality":
                continue
            lvl = dict(base, contest_id=title, contest_name=title)
            if u["type"] == "county":
                lvl["level"] = "county"
            else:
                lvl.update(level="precinct", precinct_id=unit, precinct_name=unit)
            for kind, vals in u["kinds"].items():
                vt = "TOTAL" if kind == "Total" else kind
                for col in cols:
                    if col not in vals:
                        continue
                    choice, party = _choice(col)
                    v = vals[col]
                    rows.append(dict(lvl, choice=choice, party=party, vote_type=vt, votes="" if v is None else v))
    # turnout from the first contest every district appears in (registered voters and ballots repeat)
    seen = set()
    for title, c in contests.items():
        for unit, u in c["units"].items():
            if u["type"] != "district" or unit in seen or "Total" not in u["kinds"]:
                continue
            seen.add(unit)
            t = u["kinds"]["Total"]
            turnout.append({"state": rec["state"], "source_id": rec["source_id"], "source_sha256": sha,
                            "county_name": rec["county"], "precinct_name": unit,
                            "registered_voters": "" if t.get("Registered Voters") is None else t["Registered Voters"],
                            "ballots_cast": "" if t.get("Voters Cast") is None else t["Voters Cast"]})
    summary = {k: v for k, v in issues.items()}
    summary.update({k: v for k, v in chk.items() if k != "unattributed"})
    summary["contests"] = len(contests)
    summary["districts"] = len(seen)
    summary["unattributed_votes"] = sum(chk["unattributed"].values())
    summary["unattributed_by_contest"] = sorted(chk["unattributed"].items())
    summary["report_times"] = sorted({p["refreshed"] for p in pages if p["refreshed"]})
    return rows, summary, turnout
