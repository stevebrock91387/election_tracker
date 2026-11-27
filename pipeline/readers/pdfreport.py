"""Parse county results-report PDFs: Camden and Sussex counties, NJ (docs/pdfreport.md).

The PDFs carry a text layer; pypdfium2 (PDFium) extracts it one line per printed line, numbers apart.
Everything after extraction works on text, so the parsers take a list of page strings.

Two layouts, each a dict below (the county whose 2026 general report looks like it):

- CAMDEN: one PDF. "Summary Results Report" pages hold county totals: per contest a vote-type header,
  "Vote For N", the contest name, then lines "<choice> (<party>) TOTAL t1 t2 t3 t4" (Write-In Totals,
  Total Votes Cast, Overvotes, Undervotes, Contest Totals included). "District Table Report" pages hold
  precinct totals: per page one contest, its name, "VOTE FOR N", the column labels (wrapped choice
  names), then "<precinct> v1 ... vk" and a "Totals" row; a "STATISTICS" table gives each precinct's
  registered voters and ballots cast. Other sections (municipality tables, write-in names) are not read.
- SUSSEX: two PDFs, a countywide summary and a precinct report (one unit per precinct, its name the
  first line of each of its pages). Per contest: the name, "Vote For N", the vote-type header, then
  "<PARTY> <choice> TOTAL PCT%" with the six vote types after the percent when the county publishes
  them; a choice line with no numbers at all is a withheld count (votes None).

Labels are matched on case-folded, space-collapsed text. Rows have no ids: contest_id is the contest
name, choice_id is empty; join on county + contest + choice. "No Nomination Made" / "No Petition Filed"
are ballot placeholders: dropped, counted, and listed if nonzero. Nothing is corrected or estimated;
every check below lists what differs.
"""
import hashlib
import json
import os
import re

from pipeline.schema import COLUMNS

CAMDEN = {
    "name": "camden", "county": "Camden",
    "vote_types": ["Early Voting", "Vote By Mail", "Election Day", "Provisional"],
    "header": "TOTAL Early Voting Vote By Mail Election Day Provisional", "header_position": "before",
    "percent": False, "party": "suffix", "contest_end": "contest totals",
    "summary_page": "Summary Results Report", "table_page": "District Table Report",
}
SUSSEX = {
    "name": "sussex", "county": "Sussex",
    "vote_types": ["Election Day", "Early Voting", "Mail-In", "Provisional", "Emergency", "Overseas"],
    "header": "TOTAL VOTE % Election Day Early Voting Mail-In Provisional Emergency Overseas",
    "header_position": "after", "percent": True, "party": "prefix", "contest_end": "total votes cast",
    "summary_page": "Summary Results Report", "precinct_page": "Precinct Results Report",
}
LAYOUTS = {x["name"]: x for x in (CAMDEN, SUSSEX)}

TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_name", "precinct_name", "registered_voters",
                   "ballots_cast"]

NUM = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)$")
PCT = re.compile(r"^\d+(?:\.\d+)?%$")
VOTE_FOR = re.compile(r"^vote for (\d+)$", re.I)
TOTAL_LABELS = {"total votes cast": "Total Votes Cast", "contest totals": "Contest Totals",
                "contest total": "Contest Totals"}
OU = {"overvotes": "Overvotes", "undervotes": "Undervotes"}
PLACEHOLDERS = {"no nomination made", "no petition filed"}
# Lines that close the text before a contest name (Sussex: the name is what follows the last of these).
RESET = [re.compile(p) for p in (r"Results Report$", r"^Voter Turnout - Total\b")]
# Page furniture that may fall inside a contest; never a choice.
NOISE = [re.compile(p) for p in (r"OFFICIAL RESULTS$", r"Results Report$", r"Page \d+ of ?\d+$", r"^General Election$",
                                 r"^Countywide$", r"^\d+ of \d+$", r"^November \d{1,2}, \d{4}\b")]
PLACEHOLDER_COLUMN = "placeholder "  # table column key prefix for a placeholder: checked, never a row
REPORT_TIME = re.compile(r" - (\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}[AP]M)\b")


def page_texts(path):
    """Each page's text, lines separated by "\\n" (pypdfium2).

    A district-table page printing several contests side by side (Camden: the County Question next to a
    municipal question) becomes one page per contest; see _split_side_by_side."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        out = []
        for i in range(len(pdf)):
            tp = pdf[i].get_textpage()
            text = tp.get_text_range()
            if CAMDEN["table_page"] in text and len(re.findall(r"VOTE FOR \d+", text)) >= 2:
                out.extend(_split_side_by_side(text, tp.get_charbox))
            else:
                out.append(text.replace("\r\n", "\n").replace("\r", "\n"))
        return out
    finally:
        pdf.close()


def _gap_middle(intervals, lo, hi):
    """Middle of the widest stretch in (lo, hi) that no interval covers; None if there is none."""
    edges = sorted((max(a, lo), min(b, hi)) for a, b in intervals if b > lo and a < hi)
    best, pos = None, lo
    for a, b in edges:
        if a > pos and (best is None or a - pos > best[1] - best[0]):
            best = (pos, a)
        pos = max(pos, b)
    if hi > pos and (best is None or hi - pos > best[1] - best[0]):
        best = (pos, hi)
    return None if best is None else (best[0] + best[1]) / 2


def _split_side_by_side(text, charbox):
    """One synthetic district-table page per contest printed side by side.

    PDFium's text keeps each printed line together (the precinct name, then both contests' values);
    each character's position across the page says which column band it sits in. Bands: the precinct
    names, then one per "VOTE FOR"; their borders are the middle of the widest uncovered stretch
    between neighbouring "VOTE FOR" centres (and, for the names, left of the first one). A precinct line
    becomes "<name> <that contest's values>" on each contest's page that has values for it; any other
    line goes to the band it sits in (the name band joins the first contest)."""
    starts = [m.start() for m in re.finditer(r"VOTE FOR \d+", text)]
    boxes = {i: charbox(i) for i in range(len(text)) if not text[i].isspace()}
    # Across-the-page axis: the one along which "VOTE FOR"'s letters advance (pages may be drawn rotated).
    l0, b0, _, _ = boxes[starts[0]]
    l1, b1, _, _ = boxes[starts[0] + 7]
    axis = (1, 3) if abs(b1 - b0) > abs(l1 - l0) else (0, 2)

    def span(i):
        a, b = boxes[i][axis[0]], boxes[i][axis[1]]
        return min(a, b), max(a, b)

    def centre(i):
        a, b = span(i)
        return (a + b) / 2

    lines, pos = [], 0
    for raw in text.split("\r\n"):
        lines.append((pos, raw))
        pos += len(raw) + 2
    marker = next(k for k, (_, s) in enumerate(lines) if CAMDEN["table_page"] in s)
    body = [(p, s) for p, s in lines[marker + 1:]
            if s.strip() and not (s.strip().startswith("OFFICIAL District Summary") or re.match(r"^\d+ of \d+$", s.strip()))]
    covered = [span(p + j) for p, s in body for j in range(len(s)) if (p + j) in boxes]
    vf = [(span(s)[0] + span(s + len(m) - 1)[1]) / 2
          for s, m in zip(starts, re.findall(r"VOTE FOR \d+", text))]
    left = min(a for a, _ in covered)
    # Between contests: each contest's labels end with "Contest Total" and the next contest's labels
    # follow it in the text; the border is midway between the two.
    ct = [m for m in re.finditer(r"Contest Totals?", text) if m.start() > starts[0]][:len(vf)]
    borders = [_gap_middle(covered, left, vf[0])]
    for k in range(len(vf) - 1):
        if k + 1 >= len(ct):
            borders.append(None)
            break
        a = max(span(i)[1] for i in range(ct[k].start(), ct[k].end()) if i in boxes)
        nxt = [span(i)[0] for i in range(ct[k].end(), ct[k + 1].start()) if i in boxes]
        borders.append((a + min(nxt)) / 2 if nxt and min(nxt) > a else None)
    if None in borders:
        return [text.replace("\r\n", "\n")]

    def band(i):
        return sum(centre(i) > x for x in borders)  # 0 = precinct names, k = contest k

    pages = [["OFFICIAL RESULTS District Table Report"] for _ in vf]
    for p, s in body:
        parts = [""] * (len(vf) + 1)
        last = 0
        for j, ch in enumerate(s):
            k = band(p + j) if (p + j) in boxes else last
            parts[k] += ch
            last = k
        parts = [" ".join(x.split()) for x in parts]
        values = parts[1:]
        is_row = parts[0] and any(values) and all(NUM.match(t) for v in values for t in v.split())
        for k, v in enumerate(values):
            if is_row:
                if v:
                    pages[k].append(f"{parts[0]} {v}")
            else:
                v = " ".join(x for x in (parts[0] if k == 0 else "", v) if x)
                if v:
                    pages[k].append(v)
    return ["\n".join(x) for x in pages]


def _norm(s):
    return " ".join(s.split()).casefold()


def _nospace(s):
    return "".join(s.split()).casefold()


def _int(tok):
    return int(tok.replace(",", ""))


def _trailing_numbers(tokens):
    n = 0
    while n < len(tokens) and NUM.match(tokens[-1 - n]):
        n += 1
    return n


def _page_lines(page):
    """Non-empty stripped lines. PDFium marks a hyphen printed at a line break as U+FFFE; read it as "-"."""
    return [x.strip() for x in page.replace("\ufffe", "-").split("\n") if x.strip()]


def _lines(pages):
    for p in pages:
        yield from _page_lines(p)


def _is_noise(line):
    return any(p.search(line) for p in NOISE)


def _split_party(label, layout):
    if _norm(label) in TOTAL_LABELS or _norm(label) in OU or _norm(label) == "write-in totals":
        return label, ""
    if layout["party"] == "suffix":
        m = re.match(r"^(.*\S)\s+\(([^()]{1,20})\)$", label)
    else:
        m = re.match(r"^([A-Z]{3})\s+(\S.*)$", label)
        if m:
            return m.group(2), m.group(1)
    return (m.group(1), m.group(2)) if m else (label, "")


def _choice_values(line, layout):
    """(label, values) for a choice line, or None if the line isn't one. values {vote type: int or None}."""
    tok = line.split()
    vts = layout["vote_types"]
    if layout["percent"]:
        n = _trailing_numbers(tok)
        if n == len(vts) and len(tok) > n + 2 and PCT.match(tok[-n - 1]) and NUM.match(tok[-n - 2]):
            vals = {"TOTAL": _int(tok[-n - 2])}
            vals.update({vt: _int(t) for vt, t in zip(vts, tok[-n:])})
            return " ".join(tok[:-n - 2]), vals
        if n == 0 and len(tok) > 2 and PCT.match(tok[-1]) and NUM.match(tok[-2]):
            return " ".join(tok[:-2]), {"TOTAL": _int(tok[-2])}
        if n == 0 and not any(PCT.match(t) for t in tok):
            return line, {"TOTAL": None}  # withheld: the label with no counts
        return None
    k = 1 + len(vts)
    if _trailing_numbers(tok) == k and len(tok) > k:
        vals = {"TOTAL": _int(tok[-k])}
        vals.update({vt: _int(t) for vt, t in zip(vts, tok[-k + 1:])})
        return " ".join(tok[:-k]), vals
    return None


def _statistics(line, layout, stats):
    tok = line.split()
    if line.startswith("Registered Voters - Total") and _trailing_numbers(tok) >= 1:
        stats.setdefault("registered", _int(tok[-1]))
        return True
    if line.startswith("Ballots Cast - Total"):
        n = _trailing_numbers(tok)
        if n:
            names = ["TOTAL"] + layout["vote_types"]
            stats.setdefault("ballots", dict(zip(names, (_int(t) for t in tok[-n:]))))
        return True
    return False


def _blocks(lines, layout):
    """Contest blocks from summary-style text. Returns (contests, stats, issues)."""
    contests, stats = [], {}
    issues = {"header_mismatches": [], "unparsed_lines": []}
    header = _nospace(layout["header"])
    buf, cur, state, hdr = [], None, "idle", ""
    for line in lines:
        if state == "idle":
            if _statistics(line, layout, stats):
                buf = []
                continue
            m = VOTE_FOR.match(line)
            if not m:
                buf = [] if any(p.search(line) for p in RESET) else buf + [line]
                continue
            cur = {"name": "", "vote_for": m.group(1), "choices": [], "totals": {}, "placeholders": []}
            if layout["header_position"] == "before":
                if not _nospace(" ".join(buf)).endswith(header):
                    issues["header_mismatches"].append((len(contests), " ".join(buf[-8:])))
                state, names = "name", []
            else:
                cur["name"] = " ".join(x for x in buf if not _is_noise(x))
                state, hdr = "header", ""
            buf = []
            contests.append(cur)
            continue
        if state == "header":
            nxt = hdr + _nospace(line)
            if header.startswith(nxt):
                hdr = nxt
                if hdr == header:
                    state = "choices"
                continue
            issues["header_mismatches"].append((cur["name"], line))
            state = "choices"
        if state == "name":
            if _choice_values(line, layout) is None:
                names.append(line)
                continue
            cur["name"] = " ".join(names)
            state = "choices"
        if _is_noise(line):
            continue
        parsed = _choice_values(line, layout)
        if parsed is None:
            issues["unparsed_lines"].append((cur["name"], line))
            continue
        label, vals = parsed
        key = _norm(label)
        if key in TOTAL_LABELS:
            cur["totals"][TOTAL_LABELS[key]] = vals
            if key == layout["contest_end"]:
                state, buf = "idle", []
        elif key in PLACEHOLDERS:
            cur["placeholders"].append((label, vals))
        else:
            choice, party = _split_party(OU.get(key, label), layout)
            cur["choices"].append({"choice": choice, "party": party, "values": vals})
    if state != "idle" and cur is not None:
        issues["unparsed_lines"].append((cur["name"], "<contest not closed>"))
    return contests, stats, issues


def parse_summary(pages, layout):
    """County totals from the summary pages: (contests, stats, issues)."""
    pages = [p for p in pages if layout["summary_page"] in p]
    return _blocks(_lines(pages), layout)


def parse_precinct_report(pages, layout):
    """Units of a precinct report (Sussex): ([{precinct, suppressed_label, registered, ballots, contests}], issues)."""
    groups = []
    for p in pages:
        lines = _page_lines(p)
        if not lines or layout["precinct_page"] not in p:
            continue
        head = lines[0]
        if not groups or groups[-1][0] != head:
            groups.append((head, []))
        groups[-1][1].extend(lines[1:])
    units, issues = [], {"header_mismatches": [], "unparsed_lines": []}
    for head, lines in groups:
        contests, stats, iss = _blocks(lines, layout)
        sup = head.endswith(" Suppressed")
        name = head[: -len(" Suppressed")] if sup else head
        units.append({"precinct": name, "suppressed_label": sup, "registered": stats.get("registered"),
                      "ballots": stats.get("ballots", {}), "contests": contests})
        for k in issues:
            issues[k].extend((name,) + tuple(x) for x in iss[k])
    return units, issues


def _labels(contest):
    """Canonical column labels of a contest, with the text each appears under in a table header."""
    out = []
    for c in contest["choices"]:
        name = c["choice"]
        shown = f"{name} ({c['party']})" if c["party"] else name
        out.append((name, [shown]))
    for i, (label, _) in enumerate(contest["placeholders"]):
        out.append((f"{PLACEHOLDER_COLUMN}{i}:{label}", [label]))
    out.append(("Total Votes Cast", ["Total Votes Cast"]))
    out.append(("Contest Totals", ["Contest Totals", "Contest Total"]))
    return out


def _segment(text, labels):
    """Split header text into labels (each used once, in any order); None if it can't be done exactly."""
    toks = _norm(text).split()
    opts = [(canon, _norm(s).split()) for canon, shows in labels for s in shows]

    def go(i, used):
        if i == len(toks):
            return []
        for canon, st in sorted(opts, key=lambda o: -len(o[1])):
            if canon not in used and toks[i:i + len(st)] == st:
                rest = go(i + len(st), used | {canon})
                if rest is not None:
                    return [canon] + rest
        return None

    return go(0, frozenset())


def parse_district_table(pages, contests):
    """Precinct values from the district-table pages (Camden).

    Returns (table {contest: {precinct (or "Totals"): {label: int}}}, turnout {precinct: (registered,
    ballots)}, issues)."""
    by_name = {_norm(c["name"]): c for c in contests}
    table, turnout = {}, {}
    issues = {"unmatched_headers": [], "unknown_contests": [], "truncated_names": [], "placeholders_nonzero": [],
              "unparsed_lines": [], "duplicate_cells": []}
    for p in pages:
        if CAMDEN["table_page"] not in p:
            continue
        lines = _page_lines(p)
        i = next(j for j, x in enumerate(lines) if CAMDEN["table_page"] in x) + 1
        body = [x for x in lines[i:] if not (x.startswith("OFFICIAL District Summary") or re.match(r"^\d+ of \d+$", x))]
        if body and body[0] == "STATISTICS":
            # registered voters and ballots per precinct, ending at its "Totals" row (a contest may follow)
            j = 1
            while j < len(body) and not body[j].startswith("Totals "):
                m = re.match(r"^(.*\S)\s+(\S+)\s+(\S+)\s+(\S+%)$", body[j])
                if m and NUM.match(m.group(2)) and NUM.match(m.group(3)):
                    turnout[m.group(1)] = (_int(m.group(2)), _int(m.group(3)))
                elif any(ch.isdigit() for ch in body[j]):
                    issues["unparsed_lines"].append(("STATISTICS", body[j]))
                j += 1
            body = body[j + 1:]
        k = next((j for j, x in enumerate(body) if VOTE_FOR.match(x)), None)
        if k is None:
            if body:
                issues["unparsed_lines"] += [("page", x) for x in body]
            continue
        name = " ".join(body[:k])
        contest = by_name.get(_norm(name))
        if contest is None:
            # a name the table header cut short: accept the one summary contest it begins
            cands = [c for n, c in by_name.items() if n.startswith(_norm(name) + " ")]
            if len(cands) == 1:
                contest = cands[0]
                if (name, contest["name"]) not in issues["truncated_names"]:
                    issues["truncated_names"].append((name, contest["name"]))
        if contest is None:
            issues["unknown_contests"].append(name)
            continue
        name = contest["name"]
        r = k + 1
        while r < len(body) and not (body[r].split() and NUM.match(body[r].split()[-1])):
            r += 1
        header = " ".join(body[k + 1:r])
        cols = _segment(header, _labels(contest))
        if cols is None:
            issues["unmatched_headers"].append((name, header))
            continue
        cells = table.setdefault(name, {})
        for x in body[r:]:
            tok = x.split()
            n = len(cols)
            if _trailing_numbers(tok) < n or len(tok) == n:
                issues["unparsed_lines"].append((name, x))
                continue
            unit = " ".join(tok[:-n])
            row = cells.setdefault(unit, {})
            for col, t in zip(cols, tok[-n:]):
                if col in row:
                    issues["duplicate_cells"].append((name, unit, col))
                    continue
                if col.startswith(PLACEHOLDER_COLUMN):
                    if _int(t) and unit != "Totals":
                        issues["placeholders_nonzero"].append((name, unit, col.split(":", 1)[1], _int(t)))
                    continue
                row[col] = _int(t)
    return table, turnout, issues


def check_sums(contests, layout, unit=""):
    """Totals that don't equal their parts: (unit, contest, vote type or "vote types", label, published, computed)."""
    out = []
    vts = ["TOTAL"] + layout["vote_types"]
    for c in contests:
        cands = [x for x in c["choices"] if x["choice"] not in OU.values()]
        ou = [x for x in c["choices"] if x["choice"] in OU.values()]
        tvc, ct = c["totals"].get("Total Votes Cast", {}), c["totals"].get("Contest Totals", {})
        for vt in vts:
            vals = [x["values"].get(vt) for x in cands]
            if vt in tvc and tvc[vt] is not None and vals and None not in vals and sum(vals) != tvc[vt]:
                out.append((unit, c["name"], vt, "Total Votes Cast", tvc[vt], sum(vals)))
            parts = [tvc.get(vt)] + [x["values"].get(vt) for x in ou]
            if vt in ct and ct[vt] is not None and None not in parts and sum(parts) != ct[vt]:
                out.append((unit, c["name"], vt, "Contest Totals", ct[vt], sum(parts)))
        for x in c["choices"] + [{"choice": k, "values": v} for k, v in c["totals"].items()]:
            v = x["values"]
            types = [v[t] for t in layout["vote_types"] if t in v]
            if len(types) == len(layout["vote_types"]) and None not in types and v.get("TOTAL") is not None \
                    and sum(types) != v["TOTAL"]:
                out.append((unit, c["name"], "vote types", x["choice"], v["TOTAL"], sum(types)))
    return out


def check_precincts(contests, table):
    """Camden: district-table precinct sums and Totals rows against the summary's county TOTALs."""
    out = {"precinct_vs_county": [], "table_totals_vs_county": [], "table_totals_vs_precincts": [],
           "contests_without_precincts": []}
    for c in contests:
        if c["name"] not in table:
            out["contests_without_precincts"].append(c["name"])
            continue
        rows = table[c["name"]]
        county = {x["choice"]: x["values"]["TOTAL"] for x in c["choices"]}
        county.update({k: v["TOTAL"] for k, v in c["totals"].items()})
        for label, cv in county.items():
            vals = [r.get(label) for u, r in rows.items() if u != "Totals"]
            s = None if None in vals else sum(vals)
            if s != cv:
                out["precinct_vs_county"].append((c["name"], label, cv, s))
            tot = rows.get("Totals", {}).get(label)
            if tot != cv:
                out["table_totals_vs_county"].append((c["name"], label, cv, tot))
            if tot is not None and s != tot:
                out["table_totals_vs_precincts"].append((c["name"], label, tot, s))
    return out


def check_units(contests, units):
    """Sussex: precinct-report sums against the summary's county TOTALs; withheld cells skip their check."""
    out = {"precinct_vs_county": [], "contests_not_in_summary": [], "contests_without_precincts": [],
           "withheld": [], "not_checked_withheld": []}
    by_name = {c["name"]: c for c in contests}
    sums, seen = {}, set()
    for u in units:
        for c in u["contests"]:
            if c["name"] not in by_name:
                out["contests_not_in_summary"].append((u["precinct"], c["name"]))
            seen.add(c["name"])
            items = [(x["choice"], x["values"]["TOTAL"]) for x in c["choices"]]
            items += [(k, v["TOTAL"]) for k, v in c["totals"].items()]
            n = sum(1 for x in c["choices"] if x["values"]["TOTAL"] is None)
            if n:
                out["withheld"].append((u["precinct"], c["name"], n))
            for label, v in items:
                key = (c["name"], label)
                sums[key] = None if v is None or sums.get(key, 0) is None else sums.get(key, 0) + v
    for c in contests:
        if c["name"] not in seen:
            out["contests_without_precincts"].append(c["name"])
            continue
        items = [(x["choice"], x["values"]["TOTAL"]) for x in c["choices"]]
        items += [(k, v["TOTAL"]) for k, v in c["totals"].items()]
        for label, cv in items:
            key = (c["name"], label)
            if key not in sums:
                out["precinct_vs_county"].append((c["name"], label, cv, None))
            elif sums[key] is None:
                out["not_checked_withheld"].append((c["name"], label))
            elif sums[key] != cv:
                out["precinct_vs_county"].append((c["name"], label, cv, sums[key]))
    return out


LISTS = ["sum_mismatches", "precinct_vs_county", "table_totals_vs_county", "table_totals_vs_precincts",
         "unmatched_headers", "unknown_contests", "truncated_names", "unparsed_lines", "header_mismatches",
         "duplicate_cells", "contests_without_precincts", "contests_not_in_summary", "withheld", "not_checked_withheld",
         "placeholders_nonzero", "turnout_vs_county", "parties"]


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def parse_pass(record_path, base_dir=".", text_pages=page_texts):
    """(rows, summary, turnout rows) for one pass record (layout and file kinds per docs/pdfreport.md)."""
    with open(record_path) as f:
        rec = json.load(f)
    layout = LAYOUTS[rec["layout"]]
    kinds = ["report_pdf"] if layout is CAMDEN else ["summary_pdf", "precinct_pdf"]
    summary = {k: [] for k in LISTS}
    summary.update(contests=None, placeholders_dropped=0, report_times=[], unreadable_files=[], missing_files=[])
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"]))
             for x in rec["files"]}
    texts, shas = {}, {}
    for k in kinds:
        if k not in paths:
            summary["missing_files"].append(k)
            continue
        try:
            texts[k], shas[k] = text_pages(paths[k]), _sha(paths[k])
        except Exception as e:  # a damaged or non-PDF download: listed, the pass yields no rows
            summary["unreadable_files"].append((k, f"{type(e).__name__}: {e}"))
    if summary["missing_files"] or summary["unreadable_files"]:
        for k in LISTS:
            summary[k] = None
        return [], summary, []

    summary_pages = texts[kinds[0]]
    contests, stats, iss = parse_summary(summary_pages, layout)
    summary["contests"] = len(contests)
    summary["header_mismatches"] += [("county",) + tuple(x) for x in iss["header_mismatches"]]
    summary["unparsed_lines"] += [("county",) + tuple(x) for x in iss["unparsed_lines"]]
    summary["sum_mismatches"] += check_sums(contests, layout)
    for t in kinds:
        for p in texts[t]:
            m = REPORT_TIME.search(p)
            if m and (t, m.group(1)) not in summary["report_times"]:
                summary["report_times"].append((t, m.group(1)))

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], county_name=rec["county"], contest_scope="local")
    rows, turnout_units = [], []
    parties = set()

    def placeholders(unit, c):
        summary["placeholders_dropped"] += len(c["placeholders"])
        for label, v in c["placeholders"]:
            if any(x not in (0, None) for x in v.values()):
                summary["placeholders_nonzero"].append((unit, c["name"], label, v))

    for c in contests:
        placeholders("county", c)
        crow = dict(base, source_sha256=shas[kinds[0]], level="county", contest_id=c["name"], contest_name=c["name"],
                    vote_for=c["vote_for"])
        for x in c["choices"]:
            parties.add(x["party"])
            for vt, v in x["values"].items():
                rows.append(dict(crow, choice=x["choice"], party=x["party"], vote_type=vt,
                                 votes="" if v is None else v))

    if layout is CAMDEN:
        table, tturnout, tiss = parse_district_table(summary_pages, contests)
        for k in ("unmatched_headers", "unknown_contests", "truncated_names", "duplicate_cells", "placeholders_nonzero"):
            summary[k] += tiss[k]
        summary["unparsed_lines"] += [("table",) + tuple(x) for x in tiss["unparsed_lines"]]
        chk = check_precincts(contests, table)
        for k, v in chk.items():
            summary[k] += v
        by_name = {c["name"]: c for c in contests}
        for name, units in table.items():
            c = by_name[name]
            party = {x["choice"]: x["party"] for x in c["choices"]}
            prow = dict(base, source_sha256=shas["report_pdf"], level="precinct", contest_id=name, contest_name=name,
                        vote_for=c["vote_for"])
            for unit, vals in units.items():
                if unit == "Totals":
                    continue
                for label, v in vals.items():
                    if label in party:
                        rows.append(dict(prow, precinct_id=unit, precinct_name=unit, choice=label,
                                         party=party[label], vote_type="TOTAL", votes=v))
        turnout_units = [(u, reg, bal) for u, (reg, bal) in tturnout.items()]
    else:
        units, uiss = parse_precinct_report(texts["precinct_pdf"], layout)
        summary["header_mismatches"] += uiss["header_mismatches"]
        summary["unparsed_lines"] += uiss["unparsed_lines"]
        for u in units:
            summary["sum_mismatches"] += check_sums(u["contests"], layout, unit=u["precinct"])
            for c in u["contests"]:
                placeholders(u["precinct"], c)
                prow = dict(base, source_sha256=shas["precinct_pdf"], level="precinct", contest_id=c["name"],
                            contest_name=c["name"], vote_for=c["vote_for"], precinct_id=u["precinct"],
                            precinct_name=u["precinct"])
                for x in c["choices"]:
                    parties.add(x["party"])
                    for vt, v in x["values"].items():
                        rows.append(dict(prow, choice=x["choice"], party=x["party"], vote_type=vt,
                                         votes="" if v is None else v))
            turnout_units.append((u["precinct"], u["registered"], u["ballots"].get("TOTAL")))
        chk = check_units(contests, units)
        for k, v in chk.items():
            summary[k] += v

    for field, county, i in (("registered", stats.get("registered"), 1),
                             ("ballots", stats.get("ballots", {}).get("TOTAL"), 2)):
        vals = [t[i] for t in turnout_units]
        s = None if None in vals or not vals else sum(vals)
        if s != county:
            summary["turnout_vs_county"].append((field, county, s))
    summary["parties"] = sorted(parties - {""})
    summary["registered_voters"] = stats.get("registered")
    summary["ballots_cast"] = stats.get("ballots", {}).get("TOTAL")
    precinct_sha = shas[kinds[-1]]
    turnout = [{"state": rec["state"], "source_id": rec["source_id"], "source_sha256": precinct_sha,
                "county_name": rec["county"], "precinct_name": u, "registered_voters": "" if reg is None else reg,
                "ballots_cast": "" if bal is None else bal} for u, reg, bal in turnout_units]
    return rows, summary, turnout
