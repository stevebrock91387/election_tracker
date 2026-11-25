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
from html.parser import HTMLParser

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


def parse_pass(record_path, base_dir="."):
    raise NotImplementedError
