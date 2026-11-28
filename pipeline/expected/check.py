"""The exact check of MEDSL county totals against the FEC, per (state, office) (step 4, Steve's option C).

check(medsl_totals, fec, year, notes) -> {(state_po, office): {"passed", "differences", "reason"}}, for
US SENATE and US HOUSE (GOVERNOR is not in the FEC compilation and is never a key).

Per contest, (district_key, special), on each side: votes are summed per candidate (MEDSL: by candidate
name over counties, county "" included, and party lines; FEC: by line, or its combined total), write-ins are
added into one total, and the non-write-in totals are sorted. Names are not joined (spellings differ
between the two); a contest passes when both sorted lists and both write-in totals are equal (a missing
write-in line is 0). A blank MEDSL House district is the at-large seat when it is the state's only district and
the FEC's only one is "00" (MEDSL 2022 AK, DC). An office passes when every contest on either side passes.

differences: one entry per failing contest {district, special, medsl, fec, medsl_writein, fec_writein},
medsl and fec as [[name, votes]] sorted by votes (largest first).
reason: "passed"; "not in FEC" (the FEC has no rows for the office, e.g. no Senate race that year);
"suppressed rows" (failed, and MEDSL suppressed some of the office's rows with "*": no fix can restore
them); otherwise "differences".
"""
import collections

from pipeline.expected.fec import district_key

CHECKED = ("US SENATE", "US HOUSE")


def _contests(rows):
    out = collections.defaultdict(lambda: {"cands": collections.Counter(), "writein": 0})
    for r in rows:
        if r["office"] not in CHECKED:
            continue
        key = (r["state_po"], r["office"], district_key(r["office"], r["district"]), bool(r["special"]))
        if r["writein"]:
            out[key]["writein"] += r["votes"]
        else:
            out[key]["cands"][r["candidate"]] += r["votes"]
    return out


def _sorted(cands):
    return [[n, v] for n, v in sorted(cands.items(), key=lambda kv: (-kv[1], kv[0]))]


def _blank_at_large(med, off):
    """MEDSL 2022 AK and DC publish the House district blank; where that is the state's only MEDSL House
    district and the FEC's only one is "00", the blank is the at-large seat."""
    for st in {k[0] for k in med if k[1] == "US HOUSE"}:
        mk = [k for k in med if k[:2] == (st, "US HOUSE")]
        fk = [k for k in off if k[:2] == (st, "US HOUSE")]
        if {k[2] for k in mk} == {""} and {k[2] for k in fk} == {"00"}:
            for k in mk:
                med[k[:2] + ("00",) + k[3:]] = med.pop(k)


def check(medsl_totals, fec, year, notes):
    med, off = _contests(medsl_totals), _contests(fec)
    _blank_at_large(med, off)
    empty = {"cands": collections.Counter(), "writein": 0}
    results = {}
    for st, office in sorted({k[:2] for k in med} | {k[:2] for k in off}):
        keys = sorted(k for k in set(med) | set(off) if k[:2] == (st, office))
        diffs = []
        for k in keys:
            a, b = med.get(k, empty), off.get(k, empty)
            if sorted(a["cands"].values()) != sorted(b["cands"].values()) or a["writein"] != b["writein"]:
                diffs.append({"district": k[2], "special": k[3], "medsl": _sorted(a["cands"]),
                              "fec": _sorted(b["cands"]), "medsl_writein": a["writein"], "fec_writein": b["writein"]})
        if not diffs:
            reason = "passed"
        elif not any(k in off for k in keys):
            reason = "not in FEC"
        elif notes["suppressed"].get((st, office)):
            reason = "suppressed rows"
        else:
            reason = "differences"
        results[(st, office)] = {"passed": not diffs, "differences": diffs, "reason": reason}
    return results
