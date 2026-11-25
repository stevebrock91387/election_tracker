"""Parse Maryland results: the State Board of Elections' live results pages (static HTML).

Design: docs/superpowers/specs/2026-11-24-step2-md-reader-design.md.

A pass record lists county pages (gen_results_<year>_by_county_<n>.html: every contest on that
county's ballot, statewide questions included), office pages (gen_results_<year>_<n>.html: one
office, every district) and statewide question pages, plus the configured county names, the office
title of each office page and the title of each question page. Each contest on a page is an h2
office, an optional h3 district (or, for judicial retention, an h3 "<judge><br>Vote Yes or No<br>
..."), a "Vote for" heading, "(N of M election day precincts reported)" and a table: Name, Party
(absent for questions and retention), the vote types, Total, Percentage; the last row is Totals.

Rows: county pages at level "county" (county_id the page number), office and question pages at
level "state". contest_id = office plus district or judge. One row per vote type and TOTAL;
reporting_status is the reporting phrase as published. No ids are published: the county-vs-state
check joins on contest and choice names. No turnout table (the pages carry none).

Nothing is corrected; the summary lists the anomalies (see the design). The county-vs-state check
runs per contest only when the county pages' precinct counts add up to the state page's; otherwise
the contest is listed as not checked, with the reason.
"""
import json
import os
import re
from html.parser import HTMLParser

from pipeline.schema import COLUMNS

REPORTING = re.compile(r"\((\d+) of (\d+) election day precincts reported\)")
REFRESHED = re.compile(r"Last refreshed:\s*(.+?)\s*$")
VOTE_FOR = re.compile(r"Vote for (?:up to )?(\d+)")
TITLE = re.compile(r"Results for (.+)$")
LISTS = ["vote_type_sum_mismatches", "totals_row_mismatches", "county_state_mismatches", "contests_one_side",
         "contests_not_checked", "reporting_mismatches", "county_title_mismatches", "non_numeric",
         "duplicate_choices", "duplicate_contests", "unexpected_columns", "malformed_rows",
         "contests_without_reporting", "page_problems", "out_of_scope_titles", "mixed_refresh"]


class _Events(HTMLParser):
    """Flattens a page into ("h1".."h4", text), ("text", text) and ("table", headers, rows) events.
    Header rows are those inside <thead>; question tables put a <th> row header in body rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events, self.skip, self.head, self.cell, self.table, self.row, self.in_thead = [], 0, None, None, None, None, False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.head = (tag, [])
        elif tag == "br" and self.head:
            self.head[1].append("\n")
        elif tag == "table":
            self.table = ([], [])
        elif tag == "thead":
            self.in_thead = True
        elif tag == "tbody":
            self.in_thead = False
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif self.head and tag == self.head[0]:
            self.events.append((tag, "".join(self.head[1])))
            self.head = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            (self.table[0] if self.in_thead else self.table[1]).append(self.row)
            self.row = None
        elif tag == "thead":
            self.in_thead = False
        elif tag == "table" and self.table is not None:
            heads = self.table[0][0] if self.table[0] else []
            self.events.append(("table", heads, self.table[1]))
            self.table = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.head:
            self.head[1].append(data)
        elif self.table is None and data.strip():
            self.events.append(("text", " ".join(data.split())))


def parse_page(text):
    """Contests on one page: office, district, vote_for, reporting (n, m) or None, retention, columns,
    rows (lists of cell text), totals (a row or None); plus title, refreshed and problems."""
    p = _Events()
    p.feed(text)
    p.close()
    out = {"title": None, "refreshed": None, "contests": [], "problems": []}
    office = vote_for = reporting = None
    quals = {}  # heading level (3, 4, ...) -> qualifier: a district, a county or a retention judge
    retention, pending = False, None  # pending: (level, label) of the last heading with no table yet

    def close(level):
        # A heading at `level` arrives: the pending one was a leaf without a table unless it is a parent.
        if pending and pending[0] >= level:
            out["problems"].append(f"heading without a table: {pending[1]}")

    def label():
        return " ".join([office] + [quals[k] for k in sorted(quals)])

    for ev in p.events:
        kind = ev[0]
        if kind == "h1":
            m = TITLE.search(" ".join(ev[1].split()))
            out["title"] = m.group(1).strip() if m else " ".join(ev[1].split())
        elif kind == "h2":
            close(2)
            office, vote_for, reporting, retention, quals = " ".join(ev[1].split()), None, None, False, {}
            pending = (2, office)
        elif kind in ("h3", "h4", "h5"):
            lines = [" ".join(x.split()) for x in ev[1].split("\n") if x.strip()]
            if not lines:
                continue
            m = VOTE_FOR.match(lines[0])
            if m:
                vote_for = m.group(1)
                continue
            level = int(kind[1])
            close(level)
            quals = {k: v for k, v in quals.items() if k < level}
            quals[level] = lines[0]
            retention = len(lines) > 1 and lines[1] == "Vote Yes or No"
            vote_for, reporting = ("1" if retention else None), None
            pending = (level, label())
        elif kind == "text":
            m = REFRESHED.search(ev[1])
            if m and out["refreshed"] is None:
                out["refreshed"] = m.group(1)
            m = REPORTING.search(ev[1])
            if m:
                reporting = (int(m.group(1)), int(m.group(2)))
        elif kind == "table":
            if office is None or pending is None:
                out["problems"].append(f"table without a contest heading (first header {ev[1][:1]})")
                continue
            heads, body = ev[1], ev[2]
            totals = [r for r in body if r and r[0] == "Totals"]
            district = " ".join(quals[k] for k in sorted(quals)) or None
            out["contests"].append({"office": office, "district": district, "vote_for": vote_for, "reporting": reporting,
                                    "retention": retention, "columns": heads,
                                    "rows": [r for r in body if not (r and r[0] == "Totals")],
                                    "totals": totals[-1] if totals else None})
            pending, reporting = None, None
    close(2)
    return out


def _count(text, where, s):
    t = text.replace(",", "").strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    if t == "NR":
        s["not_reported"] += 1
    else:
        s["non_numeric"].append(where + (text,))
    return ""


def parse_pass(record_path, base_dir="."):
    with open(record_path) as fh:
        rec = json.load(fh)
    s = {k: [] for k in LISTS}
    s.update(unreadable_files=[], missing_files=[], refresh_times={}, not_reported=0, counties=0, contests_checked=0)
    counties = rec.get("counties", {})
    question_titles = set(rec.get("questions", []))
    scope = set(rec.get("offices", [])) | question_titles
    per_county = set(rec.get("per_county_offices", []))  # one contest per county (circuit judges): county pages add the county
    pages_by_title = {t: (k, n) for k, d in (("office", rec.get("office_pages", {})), ("question", rec.get("question_pages", {})))
                      for n, t in d.items()}
    listed = {(f["kind"], str(f["number"])) for f in rec["files"]}
    s["missing_files"] = sorted(f"county {n}" for n in counties if ("county", n) not in listed)
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide")
    rows, out_titles, read_state_pages = [], set(), set()
    county_vals, state_vals, county_rep, state_rep, seen_c, seen_s = {}, {}, {}, {}, {}, {}
    read_counties = 0
    for f in rec["files"]:
        kind, n = f["kind"], str(f["number"])
        label = f"{kind} {n}"
        path = f["path"] if os.path.isabs(f["path"]) else os.path.join(base_dir, f["path"])
        try:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8")
            page = parse_page(text)
            if not page["contests"]:
                raise ValueError("no contest tables")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            s["unreadable_files"].append((label, str(e)))
            continue
        if kind == "county":
            read_counties += 1
            want = counties.get(n)
            if page["title"] != want:
                s["county_title_mismatches"].append((n, want, page["title"]))
        else:
            read_state_pages.add((kind, n))
        s["refresh_times"][page["refreshed"]] = s["refresh_times"].get(page["refreshed"], 0) + 1
        s["page_problems"] += [(label, p) for p in page["problems"]]
        level = "county" if kind == "county" else "state"
        seen_ids = set()
        for c in page["contests"]:
            office = c["office"]
            if office not in scope:
                out_titles.add(office)
                continue
            cid = f"{office} {c['district']}" if c["district"] else office
            if kind == "county" and office in per_county:
                cid = f"{cid} {counties.get(n, '')}".strip()
            if cid in seen_ids:
                s["duplicate_contests"].append((label, cid))
                continue
            seen_ids.add(cid)
            cols = c["columns"]
            has_party = len(cols) > 1 and cols[1] == "Party"
            first = 2 if has_party else 1
            if len(cols) < first + 3 or cols[-2:] != ["Total", "Percentage"] or (has_party and cols[0] != "Name"):
                s["unexpected_columns"].append((label, cid, cols))
                continue
            types = cols[first:-2]
            if c["reporting"] is None:
                s["contests_without_reporting"].append((label, cid))
            rep = "" if c["reporting"] is None else f"{c['reporting'][0]} of {c['reporting'][1]} election day precincts reported"
            ctype = "question" if office in question_titles else "retention" if c["retention"] else "candidate"
            row0 = dict(base, level=level, contest_id=cid, contest_name=cid, contest_type=ctype, vote_for=c["vote_for"] or "",
                        reporting_status=rep)
            if level == "county":
                row0.update(county_id=n, county_name=counties.get(n, ""))
                if c["reporting"]:
                    r0 = county_rep.setdefault(cid, [0, 0])
                    r0[0] += c["reporting"][0]
                    r0[1] += c["reporting"][1]
                vals = county_vals
            else:
                state_rep[cid] = c["reporting"]
                vals = state_vals
            names = set()
            sums = [0] * (len(types) + 1)
            sum_ok = [True] * (len(types) + 1)
            for r in c["rows"]:
                if len(r) != len(cols):
                    s["malformed_rows"].append((label, cid, r))
                    continue
                choice = r[0]
                if choice in names:
                    s["duplicate_choices"].append((label, cid, choice))
                    continue
                names.add(choice)
                counts = [_count(x, (label, cid, choice, col), s) for x, col in zip(r[first:-1], types + ["Total"])]
                for i, v in enumerate(counts):
                    if v == "":
                        sum_ok[i] = False
                    else:
                        sums[i] += v
                if all(v != "" for v in counts) and sum(counts[:-1]) != counts[-1]:
                    s["vote_type_sum_mismatches"].append((level, n if level == "county" else "", cid, choice, counts[-1], sum(counts[:-1])))
                for vt, v in zip(types + ["TOTAL"], counts):
                    rows.append(dict(row0, choice=choice, party=r[1] if has_party else "", vote_type=vt, votes=v))
                    if v != "":
                        key = (cid, choice, vt)
                        vals[key] = vals.get(key, 0) + v
            if c["totals"] is not None and len(c["totals"]) == len(cols):
                for i, (x, col) in enumerate(zip(c["totals"][first:-1], types + ["Total"])):
                    t = x.replace(",", "").strip()
                    if sum_ok[i] and t.isdigit() and int(t) != sums[i]:
                        s["totals_row_mismatches"].append((level, n if level == "county" else "", cid, col, int(t), sums[i]))
            (seen_c if level == "county" else seen_s).setdefault(cid, office)
    s["counties"] = read_counties
    if not rows and not read_counties and not read_state_pages:
        for k in LISTS:
            s[k] = None
        return [], s, []
    s["out_of_scope_titles"] = sorted(out_titles)
    times = s["refresh_times"]
    s["mixed_refresh"] = sorted(times.items(), key=lambda x: str(x[0])) if len(times) > 1 else []

    for cid in sorted(set(seen_c) | set(seen_s)):
        office = seen_c.get(cid) or seen_s.get(cid)
        page_key = pages_by_title.get(office)
        if cid not in seen_s:
            if page_key in read_state_pages:
                s["contests_one_side"].append((cid, "county pages only"))
            else:
                s["contests_not_checked"].append((cid, "office page not read" if page_key in listed else "office page not in the pass"))
            continue
        if cid not in seen_c:
            s["contests_one_side"].append((cid, "office page only"))
            continue
        st, co = state_rep.get(cid), county_rep.get(cid)
        if st is None or co is None:
            s["contests_not_checked"].append((cid, "no precinct counts to compare"))
            continue
        if co[1] != st[1]:
            s["contests_not_checked"].append((cid, f"county pages cover {co[1]} of {st[1]} precincts"))
            continue
        if co[0] != st[0]:
            s["reporting_mismatches"].append((cid, f"{st[0]} of {st[1]}", f"{co[0]} of {co[1]}"))
        s["contests_checked"] += 1
        keys = {k for k in state_vals if k[0] == cid} | {k for k in county_vals if k[0] == cid}
        for k in sorted(keys):
            a, b = state_vals.get(k), county_vals.get(k)
            if a != b:
                s["county_state_mismatches"].append((cid, k[1], k[2], a, b))
    if not read_state_pages:  # no office or question page read: only the not-checked reasons stand
        for k in ("county_state_mismatches", "contests_one_side", "reporting_mismatches", "contests_checked"):
            s[k] = None
    return rows, s, []
