"""Parse Vermont results: the SOS static JSON, by town part.

Design: docs/superpowers/specs/2026-11-24-step2-vt-reader-design.md.

A pass record lists the election file (electionDetails, towns, lastUpdatedDate, ...) and, from one
snapshot, the results files federal, stateWide, senate, house ({"d": [{"o": [office]}]}) and
turnOut ({"d": [{tid, tn, tvr, tvc, tabs, tdis, tdisr}]}). Each office: oid, on, vf, district dc/dn
(senate, house), and cs: one entry per town part (a town split by legislative districts has one per
(repd, send)) plus one total entry (tid 0, "STATE WIDE" or "District Wide"). Each entry: sc (vote
slots: votes + bv + sv), bv (blank votes), sv (overvotes), townsReported / distReported, rc
(candidates: cid, cn, vc, pn) and wc (write-ins; cid 0 is "OTHER WRITE-IN").

Rows: town parts at level "town" (county_id = tid, county_name = tn, precinct_id = "repd|send");
total entries at level "state" (district totals too). contest_id = oid, or "oid:dc" for senate and
house; vote_for = vf; contest_type = the file kind. One row per candidate and write-in, plus
"Blank Votes" (bv) and "Overvotes" (sv) with an empty choice_id. reporting_status = townsReported,
else distReported, as published. source_created_at = lastUpdatedDate.

The turnout table has one row per town: registered (tvr), ballots (tvc), absentee (tabs) and
districts reporting (tdisr/tdis).

Nothing is corrected; the summary lists: town-part sums that differ from the total entry (per
contest and choice, blank and over included), offices with no or several total entries, entries
whose sc differs from votes + bv + sv, towns whose sc for a single-seat federal office (summed
over parts) differs from their turnout ballots, that office's total sc vs the sum of turnout
ballots, towns in the federal file but not the turnout file and vice versa, town ids not in the
election file, duplicate (contest, town, repd, send, choice) entries, non-integer counts (votes ""),
choices in town parts but not in the total entry and the reverse, malformed entries (a value of the
wrong JSON type; skipped), and missing or unreadable files (a results file with no offices counts
as unreadable). Checks that need a file that wasn't read are None: when any results file is
unread, every results check is None, since its offices can't be checked.
"""
import hashlib
import json
import os

from pipeline.schema import COLUMNS

RESULT_KINDS = ("federal", "stateWide", "senate", "house")
KINDS = ("election",) + RESULT_KINDS + ("turnOut",)
TURNOUT_COLUMNS = ["state", "source_id", "source_sha256", "county_id", "county_name", "registered_voters", "ballots",
                   "absentee", "districts_reporting"]
RESULT_LISTS = ["sum_mismatches", "total_entry_missing", "total_entry_repeated", "sc_mismatches", "duplicate_entries",
                "non_numeric", "choices_not_in_total", "choices_not_in_towns"]
TURNOUT_LISTS = ["turnout_mismatches", "turnout_total_mismatches", "towns_missing_from_turnout",
                 "towns_missing_from_federal"]
LISTS = RESULT_LISTS + TURNOUT_LISTS + ["unknown_towns", "malformed_entries"]


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _dicts(kind, where, seq, summary):
    """The dict items of a list; anything else (and a non-list) is listed as malformed and skipped."""
    if seq is None:
        return []
    if not isinstance(seq, list):
        summary["malformed_entries"].append((kind, where))
        return []
    out = []
    for x in seq:
        if isinstance(x, dict):
            out.append(x)
        else:
            summary["malformed_entries"].append((kind, where))
    return out


def parse_pass(record_path, base_dir="."):
    with open(record_path) as f:
        rec = json.load(f)
    summary = {"snapshot": rec.get("snapshot", ""), "contests": 0, "towns": 0}
    summary.update({k: [] for k in LISTS})
    summary.update(unreadable_files=[], missing_files=[])
    paths = {}
    for x in rec["files"]:
        p = x["path"]
        paths[x["kind"]] = p if os.path.isabs(p) else os.path.join(base_dir, p)
    summary["missing_files"] = [k for k in KINDS if k not in paths]
    data, sha = {}, {}
    for k in KINDS:
        if k not in paths:
            continue
        try:
            with open(paths[k], "rb") as f:
                body = f.read()
            obj = json.loads(body.decode("utf-8-sig"))
            if not isinstance(obj, dict):
                raise ValueError("not a JSON object")
            if k != "election":
                blocks = obj.get("d")
                if not isinstance(blocks, list) or not blocks:
                    raise ValueError("no d list")
                if k in RESULT_KINDS and not any(isinstance(b, dict) and b.get("o") for b in blocks):
                    raise ValueError("no offices")
            data[k], sha[k] = obj, hashlib.sha256(body).hexdigest()
        except (OSError, ValueError) as e:
            summary["unreadable_files"].append((k, str(e)))

    el = data.get("election", {})
    details = el.get("electionDetails") if isinstance(el.get("electionDetails"), dict) else {}
    if "election" in data and not isinstance(el.get("electionDetails"), (dict, type(None))):
        summary["malformed_entries"].append(("election", "electionDetails"))
    towns = ({t.get("townId"): t.get("townName", "") for t in _dicts("election", "towns", el.get("towns"), summary)}
             if "election" in data else None)
    base = dict.fromkeys(COLUMNS, "")
    base.update(state=rec["state"], source_id=rec["source_id"], contest_scope="statewide", vote_type="TOTAL",
                election_name=details.get("electionName", ""), election_date=details.get("electionDate", ""),
                source_created_at=el.get("lastUpdatedDate", "") if isinstance(el.get("lastUpdatedDate"), str) else "")
    rows = []
    federal = []   # (contest id, total sc or None, {tid: summed sc}) for single-seat federal offices
    federal_towns = set()

    def count(raw, where):
        n = _int(raw)
        if n is None:
            summary["non_numeric"].append(where + (raw,))
        return n

    for kind in RESULT_KINDS:
        if kind not in data:
            continue
        for block in _dicts(kind, "d", data[kind]["d"], summary):
            for o in _dicts(kind, "o", block.get("o"), summary):
                oid = o.get("oid")
                cid_ = str(oid) if kind in ("federal", "stateWide") else f"{oid}:{o.get('dc', '')}"
                name = o.get("on", "") if kind in ("federal", "stateWide") else f"{o.get('on', '')} – {o.get('dn', '')}"
                summary["contests"] += 1
                crow = dict(base, contest_id=cid_, contest_name=name, contest_type=kind, vote_for=str(o.get("vf", "")))
                totals, sums, seen, town_choices, town_sc = [], {}, set(), set(), {}
                for e in _dicts(kind, cid_, o.get("cs"), summary):
                    tid = e.get("tid")
                    if not isinstance(tid, int) or isinstance(tid, bool):
                        summary["malformed_entries"].append((kind, cid_, "tid"))
                        continue
                    is_total = tid == 0
                    if not is_total and towns is not None and tid not in towns and tid not in summary["unknown_towns"]:
                        summary["unknown_towns"].append(tid)
                    part = f"{e.get('repd') or ''}|{e.get('send') or ''}"
                    status = e.get("townsReported") if e.get("townsReported") is not None else (e.get("distReported") or "")
                    row = dict(crow, level="state" if is_total else "town", source_sha256=sha[kind],
                               county_id="" if is_total else str(tid), county_name="" if is_total else e.get("tn", ""),
                               precinct_id="" if is_total else part, reporting_status=status)
                    values = {}
                    choices = [(str(c.get("cid")), c.get("cn", ""), c.get("pn") or "", c.get("vc")) for c in
                               _dicts(kind, cid_, e.get("rc"), summary) + _dicts(kind, cid_, e.get("wc"), summary)]
                    choices += [("blank", "Blank Votes", "", e.get("bv")), ("over", "Overvotes", "", e.get("sv"))]
                    for key, cn, party, raw in choices:
                        n = count(raw, (cid_, tid, part, key))
                        values[key] = n
                        if not is_total:
                            dkey = (cid_, tid, e.get("repd"), e.get("send"), key)
                            if dkey in seen:
                                summary["duplicate_entries"].append(dkey)
                            seen.add(dkey)
                            town_choices.add(key)
                            if n is not None:
                                sums[key] = sums.get(key, 0) + n
                        rows.append(dict(row, choice_id="" if key in ("blank", "over") else key, choice=cn,
                                         party=party, votes="" if n is None else n))
                    sc = count(e.get("sc"), (cid_, tid, part, "sc"))
                    if sc is not None and None not in values.values() and sc != sum(values.values()):
                        summary["sc_mismatches"].append((cid_, str(tid), part, sc, sum(values.values())))
                    if is_total:
                        totals.append((values, sc))
                    elif sc is not None:
                        town_sc[tid] = town_sc.get(tid, 0) + sc
                if kind == "federal":
                    federal_towns |= set(town_sc)
                if not totals:
                    summary["total_entry_missing"].append(cid_)
                    continue
                if len(totals) > 1:
                    summary["total_entry_repeated"].append(cid_)
                    continue
                total, total_sc = totals[0]
                if kind == "federal" and o.get("vf") == 1:
                    federal.append((cid_, total_sc, town_sc))
                summary["choices_not_in_total"] += [(cid_, k) for k in sorted(town_choices - set(total))]
                summary["choices_not_in_towns"] += [(cid_, k) for k in sorted(set(total) - town_choices)
                                                    if k not in ("blank", "over") or town_choices]
                for key, n in total.items():
                    if n is not None and key in sums and sums[key] != n:
                        summary["sum_mismatches"].append((cid_, key, n, sums[key]))

    turnout, ballots = [], {}
    if "turnOut" in data:
        for t in _dicts("turnOut", "d", data["turnOut"]["d"], summary):
            tid = t.get("tid")
            turnout.append(dict(state=rec["state"], source_id=rec["source_id"], source_sha256=sha["turnOut"],
                                county_id=str(tid), county_name=t.get("tn", ""), registered_voters=t.get("tvr", ""),
                                ballots=t.get("tvc", ""), absentee=t.get("tabs", ""),
                                districts_reporting=f"{t.get('tdisr', '')}/{t.get('tdis', '')}"))
            ballots[tid] = _int(t.get("tvc"))
        summary["towns"] = len(turnout)
    if "turnOut" in data and "federal" in data:
        summary["towns_missing_from_turnout"] = sorted(federal_towns - set(ballots))
        summary["towns_missing_from_federal"] = sorted(set(ballots) - federal_towns)
        for cid_, total_sc, town_sc in federal:
            for tid, n in sorted(town_sc.items()):
                if tid in ballots and ballots[tid] != n:
                    summary["turnout_mismatches"].append((cid_, tid, n, ballots[tid]))
            known = [b for b in ballots.values() if b is not None]
            if total_sc is not None and (len(known) != len(ballots) or sum(known) != total_sc):
                summary["turnout_total_mismatches"].append((cid_, total_sc, sum(known)))
    else:
        for k in TURNOUT_LISTS:
            summary[k] = None
    if any(k not in data for k in RESULT_KINDS):
        for k in RESULT_LISTS:
            summary[k] = None
    if towns is None:
        summary["unknown_towns"] = None
    return rows, summary, turnout
