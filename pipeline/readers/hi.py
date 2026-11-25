"""Parse Hawaii results: the Office of Elections' statewide summary and precinct detail text files.

Design: docs/superpowers/specs/2026-11-24-step2-hi-reader-design.md.

Both files are tab-separated UTF-8 with CRLF lines; quoted fields may hold newlines (the Governor and
Lieutenant Governor names span four lines). summary.txt: "#FormatVersion 1", then the header, then one
line per (contest, candidate) with the contest's blank/over/invalid votes (mail and in-person),
registered voters, Total and Counted Precincts. media.txt: a "Column1 … Column16" line, "#FormatVersion
1", the header, then one line per (unit, contest, candidate) with mail and in-person votes. Every
precinct appears as two units: a plain one (registered voters, mail votes, Reporting 1) and a "VSC"
one (Voter Service Center: in-person votes, registered 0, Reporting 0); units are keyed by
precinct_splitId. Party is a name prefix ("(D) TOKUDA, Jill N."); the party columns are empty.

Rows: precinct rows from media.txt (vote types TOTAL = mail + in-person, "Mail votes", "In-Person
votes"); state rows from summary.txt (TOTAL as published, "Mail Votes", "In-Person Votes", plus Blank,
Over and Invalid Votes per contest). Choice names have whitespace runs collapsed to one space. The
turnout table has one row per unit.

Nothing is corrected; the summary lists every check named in the design. A check that couldn't run is
None: cross-checks need both files, summary-only checks the summary, unit checks the media file, line
checks at least one file. A value that can't be compared (not a number, or conflicting within a unit
or contest) puts the comparison in a *_not_checked list, never in a mismatch list.
"""
import csv
import hashlib
import io
import json
import os
import re

from pipeline.schema import COLUMNS

SUMMARY_HEADER = ["#Contest ID", "Contest Title", "Contest Seq Nbr", "Contest Type", "Contest Party",
                  "Mail Blank Votes", "In-Person Blank Votes", "Mail Over Votes", "In-Person Over Votes",
                  "Mail Invalid Votes", "In-Person Invalid Votes", "Registered Voters", "Total Precincts",
                  "Counted Precincts", "Candidate ID", "Candidate Name", "Candidate Seq Nbr", "Candidate Party",
                  "Mail Votes", "In-Person Votes", "Total Votes"]
MEDIA_HEADER = ['#"Precinct_Name"', "Split_Name", "precinct_splitId", "Reg_voters", "Ballots", "Reporting",
                "Contest_id", "Contest_title", "Contest_party", "Choice_id", "Candidate_name", "Choice_party",
                "Candidate_Type", "Mail votes", "In-Person votes", ""]
HEADERS = {"summary": SUMMARY_HEADER, "media": MEDIA_HEADER}
KINDS = ("summary", "media")
HEADER_WITHIN = 5
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "precinct_id", "precinct_name", "registered_voters",
                   "ballots", "reporting"]
CONTEST_FIELDS = ["Contest Title", "Contest Type", "Contest Party", "Mail Blank Votes", "In-Person Blank Votes",
                  "Mail Over Votes", "In-Person Over Votes", "Mail Invalid Votes", "In-Person Invalid Votes",
                  "Registered Voters", "Total Precincts", "Counted Precincts"]
EXTRA = [("Blank Votes", "Mail Blank Votes", "In-Person Blank Votes"),
         ("Over Votes", "Mail Over Votes", "In-Person Over Votes"),
         ("Invalid Votes", "Mail Invalid Votes", "In-Person Invalid Votes")]
UNIT_FIELDS = ['#"Precinct_Name"', "Split_Name", "Reg_voters", "Ballots", "Reporting"]
PAIRS = [("Mail Votes", "Mail votes"), ("In-Person Votes", "In-Person votes")]
CONTEST_TYPES = {"OF": "candidate", "MS": "measure"}
REAL = re.compile(r"\d\d-\d\d")
PREFIX = re.compile(r"\((\w+)\)\s")
CROSS = ["state_precinct_mismatches", "state_precinct_not_checked", "registered_mismatches", "registered_not_checked",
         "precinct_count_mismatches", "precinct_count_not_checked", "title_mismatches", "choice_name_mismatches"]
SUMMARY_ONLY = ["total_mismatches", "inconsistent_contest_fields"]
MEDIA_ONLY = ["unit_conflicts"]
ALWAYS = ["duplicate_lines", "non_numeric", "malformed_lines"]


def _int(v):
    return int(v) if re.fullmatch(r"\d+", v.strip()) else None


def _collapse(v):
    return " ".join(v.split())


def _party(name, column):
    m = PREFIX.match(name)
    return (m.group(1), True) if m else (column, False)


def read_table(body, header):
    """Return (preamble records, data records with their 1-based record numbers) or raise ValueError."""
    recs = list(csv.reader(io.StringIO(body.decode("utf-8-sig"), newline=""), delimiter="\t"))
    for i, r in enumerate(recs[:HEADER_WITHIN]):
        if r == header:
            data = [(n, f) for n, f in enumerate(recs[i + 1:], start=i + 2) if f and f != [""]]
            if not data:
                raise ValueError("no data lines")
            return recs[:i], data
    raise ValueError(f"header not found in the first {HEADER_WITHIN} lines")


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    paths = {x["kind"]: (x["path"] if os.path.isabs(x["path"]) else os.path.join(base_dir, x["path"])) for x in rec["files"]}
    summary = {"contests": None, "units": None, "plain_units": None, "vsc_units": None, "lines": {},
               "parties_from_prefix": 0, "preamble": {}, "unreadable_files": [],
               "missing_files": [k for k in KINDS if k not in paths]}
    summary.update({k: [] for k in CROSS + SUMMARY_ONLY + MEDIA_ONLY + ALWAYS})
    tables, shas = {}, {}
    for kind in KINDS:
        if kind not in paths:
            continue
        try:
            with open(paths[kind], "rb") as f:
                body = f.read()
            pre, data = read_table(body, HEADERS[kind])
        except (OSError, ValueError, UnicodeDecodeError, csv.Error) as e:
            summary["unreadable_files"].append((kind, str(e)))
            continue
        tables[kind], shas[kind] = data, hashlib.sha256(body).hexdigest()
        summary["preamble"][kind] = pre
        summary["lines"][kind] = 0
    for k in SUMMARY_ONLY if "summary" not in tables else []:
        summary[k] = None
    for k in MEDIA_ONLY if "media" not in tables else []:
        summary[k] = None
    if len(tables) < 2:
        for k in CROSS:
            summary[k] = None
    if not tables:
        for k in ALWAYS:
            summary[k] = None

    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide")
    rows, prefixed = [], set()

    # summary.txt -> state rows
    state, contests = {}, {}  # (contest, choice) -> {vote type: int|None}; contest -> {field: set}
    s_titles, s_names = {}, {}
    if "summary" in tables:
        col = {n: i for i, n in enumerate(SUMMARY_HEADER)}
        sbase = dict(base, level="state", source_sha256=shas["summary"])
        for n, f in tables["summary"]:
            if len(f) != len(SUMMARY_HEADER):
                summary["malformed_lines"].append(("summary", n, len(f)))
                continue
            v = {k: f[i] for k, i in col.items()}
            cid, ch = v["#Contest ID"], v["Candidate ID"]
            summary["lines"]["summary"] += 1
            if (cid, ch) in state:
                summary["duplicate_lines"].append(("summary", cid, ch, ""))
                continue
            counts = {}
            for k in ("Mail Votes", "In-Person Votes", "Total Votes") + tuple(CONTEST_FIELDS[3:]):
                counts[k] = _int(v[k])
                if counts[k] is None:
                    summary["non_numeric"].append(("summary", "", cid, ch, k, v[k]))
            state[(cid, ch)] = counts
            first = cid not in contests
            fields = contests.setdefault(cid, {k: set() for k in CONTEST_FIELDS})
            for k in CONTEST_FIELDS:
                fields[k].add(v[k])
            if None not in (counts["Mail Votes"], counts["In-Person Votes"], counts["Total Votes"]) and \
                    counts["Mail Votes"] + counts["In-Person Votes"] != counts["Total Votes"]:
                summary["total_mismatches"].append((cid, ch, counts["Total Votes"], counts["Mail Votes"] + counts["In-Person Votes"]))
            name = _collapse(v["Candidate Name"])
            party, from_prefix = _party(name, v["Candidate Party"])
            if from_prefix:
                prefixed.add((cid, ch))
            s_titles.setdefault(cid, v["Contest Title"])
            s_names[(cid, ch)] = name
            row = dict(sbase, contest_id=cid, contest_name=v["Contest Title"],
                       contest_type=CONTEST_TYPES.get(v["Contest Type"], v["Contest Type"]),
                       reporting_status=f"{v['Counted Precincts']} of {v['Total Precincts']} precincts counted")
            crow = dict(row, choice=name, choice_id=ch, party=party)
            for vt, k in [("TOTAL", "Total Votes"), ("Mail Votes", "Mail Votes"), ("In-Person Votes", "In-Person Votes")]:
                rows.append(dict(crow, vote_type=vt, votes="" if counts[k] is None else counts[k]))
            if first:
                for choice, mk, ik in EXTRA:
                    m_, i_ = counts[mk], counts[ik]
                    xrow = dict(row, choice=choice)
                    rows.append(dict(xrow, vote_type="TOTAL", votes="" if None in (m_, i_) else m_ + i_))
                    rows.append(dict(xrow, vote_type="Mail Votes", votes="" if m_ is None else m_))
                    rows.append(dict(xrow, vote_type="In-Person Votes", votes="" if i_ is None else i_))
        for cid, fields in contests.items():
            for k in CONTEST_FIELDS:
                if len(fields[k]) > 1:
                    summary["inconsistent_contest_fields"].append((cid, k, sorted(fields[k])))

    # media.txt -> precinct rows
    sums, units, contest_units = {}, {}, {}  # (contest, choice, type) -> int|None; unit -> fields; contest -> set
    m_titles, m_names, seen = {}, {}, set()
    if "media" in tables:
        col = {n: i for i, n in enumerate(MEDIA_HEADER) if n}
        pbase = dict(base, level="precinct", source_sha256=shas["media"])
        for n, f in tables["media"]:
            if len(f) != len(MEDIA_HEADER):
                summary["malformed_lines"].append(("media", n, len(f)))
                continue
            v = {k: f[i] for k, i in col.items()}
            unit, cid, ch = v["precinct_splitId"], v["Contest_id"], v["Choice_id"]
            summary["lines"]["media"] += 1
            if (unit, cid, ch) in seen:
                summary["duplicate_lines"].append(("media", cid, ch, unit))
                continue
            seen.add((unit, cid, ch))
            u = units.setdefault(unit, {k: set() for k in UNIT_FIELDS})
            u.setdefault("first", v)
            for k in UNIT_FIELDS:
                u[k].add(v[k])
            contest_units.setdefault(cid, set()).add(unit)
            counts = {}
            for k in ("Mail votes", "In-Person votes"):
                counts[k] = _int(v[k])
                if counts[k] is None:
                    summary["non_numeric"].append(("media", unit, cid, ch, k, v[k]))
                key = (cid, ch, k)
                sums[key] = None if counts[k] is None or sums.get(key, 0) is None else sums.get(key, 0) + counts[k]
            name = _collapse(v["Candidate_name"])
            party, from_prefix = _party(name, v["Choice_party"])
            if from_prefix:
                prefixed.add((cid, ch))
            m_titles.setdefault(cid, set()).add(v["Contest_title"])
            m_names.setdefault((cid, ch), set()).add(name)
            pname, split = v['#"Precinct_Name"'], v["Split_Name"]
            row = dict(pbase, precinct_id=unit, precinct_name=f"{pname} {split}" if split else pname,
                       precinct_is_virtual="Y" if split or not REAL.fullmatch(pname) else "N",
                       contest_id=cid, contest_name=v["Contest_title"], contest_type="",
                       choice=name, choice_id=ch, party=party, reporting_status=f"Reporting {v['Reporting']}")
            mail, inp = counts["Mail votes"], counts["In-Person votes"]
            rows.append(dict(row, vote_type="TOTAL", votes="" if None in (mail, inp) else mail + inp))
            rows.append(dict(row, vote_type="Mail votes", votes="" if mail is None else mail))
            rows.append(dict(row, vote_type="In-Person votes", votes="" if inp is None else inp))
        for unit, u in units.items():
            bad = {k: sorted(u[k]) for k in UNIT_FIELDS if len(u[k]) > 1}
            if bad:
                summary["unit_conflicts"].append((unit, bad))
            for k in ("Reg_voters", "Ballots", "Reporting"):
                for val in sorted(u[k]):
                    if _int(val) is None:
                        summary["non_numeric"].append(("media", unit, "", "", k, val))
        summary.update(units=len(units), vsc_units=sum(1 for u in units.values() if u["first"]["Split_Name"]),
                       plain_units=sum(1 for u in units.values() if not u["first"]["Split_Name"]))
    summary["contests"] = len(set(contests) | set(contest_units)) if tables else None
    summary["parties_from_prefix"] = len(prefixed)

    # Contest types for precinct rows come from the summary when it was read.
    types = {cid: CONTEST_TYPES.get(next(iter(fl["Contest Type"])), next(iter(fl["Contest Type"])))
             for cid, fl in contests.items() if len(fl["Contest Type"]) == 1}
    for r in rows:
        if r["level"] == "precinct":
            r["contest_type"] = types.get(r["contest_id"], "")

    if len(tables) == 2:
        for (cid, ch), counts in state.items():
            for skey, mkey in PAIRS:
                key, sval = (cid, ch, mkey), counts[skey]
                if key not in sums:
                    if sval is None:
                        summary["state_precinct_not_checked"].append((cid, ch, skey))
                    else:
                        summary["state_precinct_mismatches"].append((cid, ch, skey, sval, None))
                elif sums[key] is None or sval is None:
                    summary["state_precinct_not_checked"].append((cid, ch, skey))
                elif sums[key] != sval:
                    summary["state_precinct_mismatches"].append((cid, ch, skey, sval, sums[key]))
        for (cid, ch, mkey), total in sums.items():
            if (cid, ch) not in state:
                skey = dict((m, s_) for s_, m in PAIRS)[mkey]
                if total is None:
                    summary["state_precinct_not_checked"].append((cid, ch, skey))
                else:
                    summary["state_precinct_mismatches"].append((cid, ch, skey, None, total))
        # A unit whose registered voters conflict across its lines or aren't a number can't be summed.
        regs = [_int(next(iter(u["Reg_voters"]))) if len(u["Reg_voters"]) == 1 else None for u in units.values()]
        reg_sum = None if None in regs else sum(regs)
        if reg_sum is None:
            summary["registered_mismatches"] = None
        for cid, fl in contests.items():
            pub = _int(next(iter(fl["Registered Voters"]))) if len(fl["Registered Voters"]) == 1 else None
            if pub is None:
                summary["registered_not_checked"].append(cid)
            elif reg_sum is not None and pub != reg_sum:
                summary["registered_mismatches"].append((cid, pub, reg_sum))
            tot = _int(next(iter(fl["Total Precincts"]))) if len(fl["Total Precincts"]) == 1 else None
            cnt = _int(next(iter(fl["Counted Precincts"]))) if len(fl["Counted Precincts"]) == 1 else None
            if tot is None or cnt is None:
                summary["precinct_count_not_checked"].append(cid)
            else:
                us = contest_units.get(cid, set())
                rep_ = sum(1 for u in us if units[u]["first"]["Reporting"] == "1")
                if (tot, cnt) != (len(us), rep_):
                    summary["precinct_count_mismatches"].append((cid, tot, cnt, len(us), rep_))
            for t in sorted(m_titles.get(cid, set()) - {s_titles[cid]}):
                summary["title_mismatches"].append((cid, s_titles[cid], t))
        for key, name in s_names.items():
            for other in sorted(m_names.get(key, set()) - {name}):
                summary["choice_name_mismatches"].append((key[0], key[1], name, other))

    turnout = []
    for unit, u in units.items():
        v = u["first"]
        pname, split = v['#"Precinct_Name"'], v["Split_Name"]
        reg, bal = _int(v["Reg_voters"]), _int(v["Ballots"])
        turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=shas["media"], precinct_id=unit,
                            precinct_name=f"{pname} {split}" if split else pname,
                            registered_voters=v["Reg_voters"] if reg is None else reg,
                            ballots=v["Ballots"] if bal is None else bal, reporting=v["Reporting"]))
    return rows, summary, turnout
