"""Parse Massachusetts results: the PD43+ archive's list pages and per-contest precinct CSVs.

Design: docs/superpowers/specs/2026-11-24-step2-ma-reader-design.md.

The contest list (`/elections/search/...`) has one `<tr id="election-id-<id>">` per contest with year,
office, district and stage cells and a candidates table (name, party label, statewide votes; then All
Others, Blanks, Total Votes Cast). The question list (`/ballot_questions/search/...`) has one
`<tr id="bq-id-<id>">` per question with year, number, text, type and location. Each contest's CSV:
`City/Town, Ward, Pct, <candidates…>, All Others, Blanks, Total Votes Cast`, a party row, one line per
precinct, then TOTALS; a question's CSV starts `Locality, Ward, Pct, Yes, No, Blanks, Total Votes
Cast` and has no party row.
"""
import csv
import hashlib
import io
import json
import os
import re
from html.parser import HTMLParser

from pipeline.schema import COLUMNS

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    def text(self):
        out = []
        for c in self.children:
            out.append(c if isinstance(c, str) else c.text())
        return "".join(out)

    def find_all(self, tag, pred=lambda n: True):
        for c in self.children:
            if isinstance(c, _Node):
                if c.tag == tag and pred(c):
                    yield c
                yield from c.find_all(tag, pred)

    def kids(self, tag):
        return [c for c in self.children if isinstance(c, _Node) and c.tag == tag]

    def classes(self):
        return (self.attrs.get("class") or "").split()


class _Tree(HTMLParser):
    """A tolerant element tree: an end tag closes the nearest open element of that name, if any."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(html):
    t = _Tree()
    t.feed(html)
    t.close()
    return t.root


def _clean(s):
    return " ".join(s.replace("\xa0", " ").split())


def _candidates(row):
    """[(name, party label, votes text)] from a list row's candidates table (body rows only)."""
    out = []
    for table in row.find_all("table", lambda n: "candidates" in n.classes()):
        for body in table.kids("tbody"):
            for tr in body.find_all("tr"):
                cells = tr.kids("td")
                if not cells or "candidate" not in cells[0].classes():
                    continue
                name_div = next(cells[0].find_all("div", lambda n: "name" in n.classes()), None)
                party_div = next(cells[0].find_all("div", lambda n: "party" in n.classes()), None)
                name = _clean(name_div.text() if name_div is not None else cells[0].text())
                votes = next((_clean(c.text()) for c in cells[1:] if "number" in c.classes()), "")
                out.append((name, _clean(party_div.text()) if party_div is not None else "", votes))
        break
    return out


def parse_search(html):
    """{election id: {"year", "office", "district", "stage", "candidates"}} from the contest list."""
    out = {}
    for tr in _tree(html).find_all("tr", lambda n: (n.attrs.get("id") or "").startswith("election-id-")):
        cells = [_clean(td.text()) for td in tr.kids("td")]
        eid = tr.attrs["id"][len("election-id-"):]
        out[eid] = {"year": cells[0] if cells else "", "office": cells[1] if len(cells) > 1 else "",
                    "district": cells[2] if len(cells) > 2 else "", "stage": cells[3] if len(cells) > 3 else "",
                    "candidates": _candidates(tr)}
    return out


def parse_questions(html):
    """{question id: {"year", "number", "type", "location", "candidates"}} from the question list."""
    out = {}
    for tr in _tree(html).find_all("tr", lambda n: (n.attrs.get("id") or "").startswith("bq-id-")):
        by_class = {}
        for td in tr.kids("td"):
            for c in td.classes() or [""]:
                by_class.setdefault(c, _clean(td.text()))
        tds = tr.kids("td")
        out[tr.attrs["id"][len("bq-id-"):]] = {
            "year": by_class.get("year", ""), "number": _clean(tds[1].text()) if len(tds) > 1 else "",
            "type": by_class.get("bq_types", ""), "location": by_class.get("bq_location", ""),
            "candidates": _candidates(tr)}
    return out


def select(contests, questions, offices, locations):
    """The ids to fetch: contests whose office is in scope, questions whose location is (list order)."""
    return ([i for i, c in contests.items() if c["office"] in offices],
            [i for i, q in questions.items() if q["location"] in locations])


HEADS = {"contest": ["City/Town", "Ward", "Pct"], "question": ["Locality", "Ward", "Pct"]}
TOTAL = "Total Votes Cast"
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
LISTS = ["totals_row_mismatches", "totals_row_not_checked", "list_mismatches", "list_not_checked",
         "total_votes_mismatches", "total_votes_not_checked", "party_label_differences", "non_numeric",
         "malformed_lines", "duplicate_precincts", "duplicate_choices", "contests_without_file", "files_not_in_list",
         "unexpected_headers", "unreadable_files", "missing_files"]
LIST_CHECKS = ["list_mismatches", "list_not_checked", "party_label_differences", "contests_without_file",
               "files_not_in_list"]


def _number(v):
    """int for a count as published ("1,401" -> 1401), else the text unchanged."""
    t = (v or "").strip()
    return int(t.replace(",", "")) if NUMBER.fullmatch(t) else v


def parse_csv(text, kind):
    """{"header", "choices", "parties", "lines": [(record no, town, ward, {column: value}, pct)],
    "totals": {column: value} or None, "malformed": [(record no, fields)], "duplicates": [column]}."""
    recs = list(csv.reader(io.StringIO(text, newline="")))
    if not recs or recs[0][:3] != HEADS[kind] or recs[0][-1] != TOTAL:
        raise ValueError(f"unexpected header: {recs[0][:4] if recs else []}")
    header = recs[0]
    columns, dups = [], []
    for i, name in enumerate(header[3:], start=3):
        if name in [n for _, n in columns]:
            dups.append(name)
        else:
            columns.append((i, name))
    out = {"header": header, "choices": [n for _, n in columns if n != TOTAL], "parties": {}, "lines": [],
           "totals": None, "malformed": [], "duplicates": dups}
    start = 1
    if kind == "contest" and len(recs) > 1 and recs[1][:3] == ["", "", ""]:
        out["parties"] = {header[i]: p for i, p in enumerate(recs[1]) if i >= 3 and p}
        start = 2
    for n, f in enumerate(recs[start:], start=start + 1):
        if not f or f == [""]:
            continue
        if len(f) != len(header):
            out["malformed"].append((n, len(f)))
            continue
        values = {name: _number(f[i]) for i, name in columns}
        if f[0] == "TOTALS":
            out["totals"] = values
        else:
            out["lines"].append((n, f[0], f[1], values, f[2]))
    return out


def _name(info, kind, fid):
    if info is None:
        return f"{kind} {fid}"
    if kind == "question":
        return f"Question {info['number']}"
    return info["office"] if info["district"] == "Statewide" else f"{info['office']} {info['district']}"


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"contests": 0, "questions": 0, "out_of_scope_offices": None, "out_of_scope_questions": None}
    summary.update({k: [] for k in LISTS})
    lists, lists_ok = {}, True
    for kind, parser in (("search", parse_search), ("questions", parse_questions)):
        entry = next((x for x in rec["files"] if x["kind"] == kind), None)
        if entry is None:
            summary["missing_files"].append(kind)
            lists_ok = False
            continue
        path = entry["path"] if os.path.isabs(entry["path"]) else os.path.join(base_dir, entry["path"])
        try:
            with open(path, "rb") as f:
                lists[kind] = parser(f.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, AssertionError) as e:
            summary["unreadable_files"].append((kind, str(e)))
            lists_ok = False
    contests, questions = lists.get("search", {}), lists.get("questions", {})
    offices, locations = rec.get("offices", []), rec.get("question_locations", [])
    if "search" in lists:
        oos = {}
        for c in contests.values():
            if c["office"] not in offices:
                oos[c["office"]] = oos.get(c["office"], 0) + 1
        summary["out_of_scope_offices"] = dict(sorted(oos.items()))
    if "questions" in lists:
        oos = {}
        for q in questions.values():
            if q["location"] not in locations:
                oos[q["location"]] = oos.get(q["location"], 0) + 1
        summary["out_of_scope_questions"] = dict(sorted(oos.items()))

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide", vote_type="TOTAL")
    rows, read = [], set()
    for x in rec["files"]:
        kind = x["kind"]
        if kind not in ("contest", "question"):
            continue
        fid, label = x["id"], f"{kind} {x['id']}"
        info = (contests if kind == "contest" else questions).get(fid)
        if lists_ok and info is None:
            summary["files_not_in_list"].append((kind, fid))
        name = _name(info, kind, fid)
        path = x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"])
        try:
            with open(path, "rb") as f:
                body = f.read()
            p = parse_csv(body.decode("utf-8-sig"), kind)
        except (OSError, UnicodeDecodeError, ValueError, csv.Error) as e:
            summary["unreadable_files"].append((label, str(e)))
            if isinstance(e, ValueError):
                summary["unexpected_headers"].append((label, str(e)))
            continue
        read.add((kind, fid))
        summary["contests" if kind == "contest" else "questions"] += 1
        summary["duplicate_choices"].extend((name, d) for d in p["duplicates"])
        summary["malformed_lines"].extend((name,) + m for m in p["malformed"])
        crow = dict(base, source_sha256=hashlib.sha256(body).hexdigest(), contest_id=name, contest_name=name,
                    contest_type="measure" if kind == "question" else "candidate")
        sums = {c: 0 for c in p["choices"] + [TOTAL]}
        seen = set()
        for n, town, ward, values, pct in p["lines"]:
            pid = f"{ward}/{pct}"
            if (town, pid) in seen:
                summary["duplicate_precincts"].append((name, town, pid))
                continue
            seen.add((town, pid))
            prow = dict(crow, level="precinct", county_id=town, county_name=town, precinct_id=pid,
                        precinct_name=f"{town} Precinct {pct}" if ward == "-" else f"{town} Ward {ward} Precinct {pct}",
                        precinct_is_virtual="N")
            for c, v in values.items():
                if not isinstance(v, int):
                    summary["non_numeric"].append((name, town, pid, c, v))
                    sums[c] = None
                elif sums[c] is not None:
                    sums[c] += v
            for c in p["choices"]:
                v = values[c]
                rows.append(dict(prow, choice=c, party="" if kind == "question" else p["parties"].get(c, ""),
                                 votes=v if isinstance(v, int) else ""))
            parts = [values[c] for c in p["choices"]]
            if not all(isinstance(v, int) for v in parts + [values[TOTAL]]):
                summary["total_votes_not_checked"].append((name, town, pid))
            elif sum(parts) != values[TOTAL]:
                summary["total_votes_mismatches"].append((name, town, pid, values[TOTAL], sum(parts)))
        totals = p["totals"]
        for c in p["choices"] + [TOTAL]:
            t = totals.get(c) if totals else None
            if c != TOTAL and isinstance(t, int):
                rows.append(dict(crow, level="state", choice=c, votes=t,
                                 party="" if kind == "question" else p["parties"].get(c, "")))
            if not isinstance(t, int) or sums[c] is None:
                summary["totals_row_not_checked"].append((name, c))
            elif t != sums[c]:
                summary["totals_row_mismatches"].append((name, c, t, sums[c]))
        if info is not None:
            listed = {cand: (party, _number(votes)) for cand, party, votes in info["candidates"]}
            for c in p["choices"] + [TOTAL]:
                if c not in listed:
                    t = totals.get(c) if totals else None
                    if isinstance(t, int):
                        summary["list_mismatches"].append((name, c, None, t))
                    else:
                        summary["list_not_checked"].append((name, c))
                    continue
                lv, t = listed[c][1], totals.get(c) if totals else None
                if not isinstance(lv, int) or not isinstance(t, int):
                    summary["list_not_checked"].append((name, c))
                elif lv != t:
                    summary["list_mismatches"].append((name, c, lv, t))
                if kind == "contest" and listed[c][0] and p["parties"].get(c) and listed[c][0] != p["parties"][c]:
                    summary["party_label_differences"].append((name, c, p["parties"][c], listed[c][0]))
            for cand, (_, lv) in listed.items():
                if cand not in p["choices"] + [TOTAL]:
                    if isinstance(lv, int):
                        summary["list_mismatches"].append((name, cand, lv, None))
                    else:
                        summary["list_not_checked"].append((name, cand))
    if lists_ok:
        cids, qids = select(contests, questions, offices, locations)
        for kind, ids, table in (("contest", cids, contests), ("question", qids, questions)):
            for i in ids:
                if (kind, i) not in read and not any(x["kind"] == kind and x["id"] == i for x in rec["files"]):
                    summary["contests_without_file"].append((kind, i, _name(table[i], kind, i)))
    else:
        for k in LIST_CHECKS:
            summary[k] = None
    return rows, summary, []
