"""The FEC's official federal-elections compilation (xlsx), one row per general-election candidate line.

Layout (confirmed 2026-11-27 on federalelections2018.xlsx and federalelections2022.xlsx): the sheets whose
names contain "US Senate Results by State" and "US House Results by State" ("2018 US Senate Results by
State", "7. US Senate Results by State", ...). Row 1 is the header; columns are found by header name:
STATE ABBREVIATION, DISTRICT, CANDIDATE NAME, TOTAL VOTES (holds the labels of total lines: "Party Votes:",
"District Votes:", "Total State Votes:"), PARTY, "GENERAL VOTES " (trailing space in both files) and the
column starting "COMBINED GE PARTY TOTALS" (fusion: one candidate's combined total, repeated on each of
the candidate's party lines; NY and CT).

read_fec(path, year, notes=None) returns {state_po, office, district, special, candidate, writein, votes}:
- a candidate row has a CANDIDATE NAME, no label, and a whole-number GENERAL VOTES. Other rows (district
  headings like "DISTRICT 1", primary-only candidates, total lines) are skipped. "Unopposed" in GENERAL
  VOTES (no votes counted) is listed in notes["unopposed"] as (state, office, district, candidate).
- a candidate's lines in one contest are summed, or, where the combined column is filled, the combined
  total is used once (every line must carry the same combined value, else ValueError).
- names: clean_name (footnote markers * and # and non-breaking spaces removed), so a marked line joins its candidate.
- writein: PARTY "W" or ending "/W", or a candidate named "Scattered". Labels read "primary/general"
  (inferred from the data, the FEC's legend not read): "W(D)/W" was a write-in in the general (WI-08 2022),
  "W(D)/D" and "W(R)/R" were on the general ballot; WF, WC, WEP are parties.
- district: district_key; special: DISTRICT contains "UNEXPIRED" (S-UNEXPIRED TERM, 13-UNEXPIRED TERM).
- the territories' delegates (AS GU MP PR VI) are skipped and counted in notes["territory_lines"]; DC's is kept.
- GENERAL VOTES is the November general; the GE runoff columns (GA, MS) are not read.
"""
import collections
import re

from pipeline.readers.wy import read_xlsx

OFFICE_SHEETS = {"US SENATE": "US Senate Results by State", "US HOUSE": "US House Results by State"}
AT_LARGE = {"AT-LARGE", "AT LARGE"}
TERRITORIES = {"AS", "GU", "MP", "PR", "VI"}  # House delegates; MEDSL files them as DELEGATE TO THE US HOUSE


def district_key(office, district):
    """US SENATE: "". US HOUSE: two-digit district, at-large "00" (MEDSL "000"/"0"/"0.0", FEC "00", or
    "AT-LARGE"); MEDSL 2018 NY writes "23.0"; FEC writes "13-FULL TERM". Blank stays ""."""
    if office != "US HOUSE":
        return ""
    s = (district or "").strip().upper()
    if s in AT_LARGE:
        return "00"
    try:
        return f"{int(float(s)):02d}"
    except ValueError:
        pass
    mt = re.match(r"\d+", s)
    return f"{int(mt.group()):02d}" if mt else s


def clean_name(name):
    """FEC candidate names carry footnote markers ("Corey, Matthew  *", "Gershon, Perry  #") and
    non-breaking spaces ("Thompson, James\xa0A."): drop trailing markers, collapse whitespace."""
    return re.sub(r"[\s*#]+$", "", " ".join(name.split()))


def _col(header, name, prefix=False):
    for i, h in enumerate(header):
        h = (h or "").strip()
        if h == name or (prefix and h.startswith(name)):
            return i
    raise ValueError(f"FEC sheet has no column {name!r}")


def parse_sheets(sheets, notes=None):
    notes = {} if notes is None else notes
    notes.setdefault("unopposed", [])
    notes.setdefault("territory_lines", 0)
    lines = collections.defaultdict(list)
    for office, marker in OFFICE_SHEETS.items():
        grids = [g for n, g in sheets if marker in n]
        if len(grids) != 1:
            raise ValueError(f"expected one sheet containing {marker!r}, found {len(grids)}")
        grid = grids[0]
        h = grid[0]
        c = {"st": _col(h, "STATE ABBREVIATION"), "dist": _col(h, "DISTRICT"), "cand": _col(h, "CANDIDATE NAME"),
             "label": _col(h, "TOTAL VOTES"), "party": _col(h, "PARTY"), "gen": _col(h, "GENERAL VOTES"),
             "comb": _col(h, "COMBINED GE PARTY TOTALS", prefix=True)}
        for row in grid[1:]:
            v = {k: ((row[i] if i < len(row) else None) or "").strip() for k, i in c.items()}
            v["cand"] = clean_name(v["cand"])
            if not v["cand"] or v["label"] or not v["gen"]:
                continue
            if v["st"] in TERRITORIES:
                notes["territory_lines"] += 1
                continue
            district = district_key(office, v["dist"])
            if v["gen"].upper() == "UNOPPOSED":
                notes["unopposed"].append((v["st"], office, district, v["cand"]))
                continue
            if not v["gen"].isdigit():
                raise ValueError(f"FEC {office} {v['st']} {v['cand']}: GENERAL VOTES {v['gen']!r}")
            writein = (v["party"] == "W" or v["party"].endswith("/W")
                       or v["cand"].upper().startswith("SCATTERED"))
            key = (v["st"], office, district, "UNEXPIRED" in v["dist"].upper(), v["cand"], writein)
            lines[key].append((int(v["gen"]), int(float(v["comb"])) if v["comb"] else None))
    out = []
    for (st, office, district, special, cand, writein), ls in sorted(lines.items()):
        combined = {cb for _, cb in ls if cb is not None}
        if len(combined) > 1:
            raise ValueError(f"FEC {st} {office} {district} {cand}: differing combined totals {combined}")
        votes = combined.pop() if combined else sum(g for g, _ in ls)
        out.append({"state_po": st, "office": office, "district": district, "special": special,
                    "candidate": cand, "writein": writein, "votes": votes})
    return out


def read_fec(path, year, notes=None):
    with open(path, "rb") as f:
        return parse_sheets(read_xlsx(f.read()), notes)
