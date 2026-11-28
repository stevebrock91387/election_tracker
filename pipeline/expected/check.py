"""The exact check of MEDSL county totals against the FEC, per (state, office) (step 4, Steve's option C).

check(medsl_totals, fec, year, notes) -> {(state_po, office): {"passed", "differences", "reason"}}, for
US SENATE and US HOUSE (GOVERNOR is not in the FEC compilation and is never a key).

Per contest, (district_key, special), on each side: votes are summed per candidate (MEDSL: by candidate
name over counties, county "" included, and party lines; FEC: by line, or its combined total), write-ins are
added into one total, and the non-write-in totals are sorted. Names are not joined (spellings differ
between the two); a contest passes when both sorted lists and both write-in totals are equal (a missing
write-in line is 0). A blank MEDSL House district is the at-large seat when it is the state's only district and
the FEC's only one is "00" (MEDSL 2022 AK, DC).

A contest that isn't equal still passes on its named candidates (Steve, 2026-11-27, option 1) when the FEC
has at least one named candidate, every FEC named total appears among MEDSL's non-write-in totals (as a
multiset), and every MEDSL line left over (medsl_extra: "ALL OTHERS", "SCATTERING", write-in names MEDSL
doesn't flag) is smaller than the FEC's smallest named total. Write-in totals may then differ; the
difference is recorded, not failed. An office passes when every contest passes either way.

differences: one entry per contest that isn't equal {district, special, named, medsl, fec, medsl_writein,
fec_writein, medsl_extra}, medsl, fec and medsl_extra as [[name, votes]] sorted by votes (largest first);
named is True where the contest passed on its named candidates.
reason: "passed"; "passed (named candidates)" (some contest passed only on its named candidates); "not in FEC" (the FEC has no rows for the office, e.g. no Senate race that year);
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


def _named_extra(a, b):
    """MEDSL's leftover lines when the contest passes on its named candidates, else None."""
    fec = collections.Counter(b["cands"].values())
    if not fec or fec - collections.Counter(a["cands"].values()):
        return None
    left = collections.Counter(a["cands"].values()) - fec
    extra = []
    for n, v in _sorted(a["cands"]):
        if left[v]:
            left[v] -= 1
            extra.append([n, v])
    return extra if all(v < min(fec) for _, v in extra) else None


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
                extra = _named_extra(a, b)
                diffs.append({"district": k[2], "special": k[3], "named": extra is not None,
                              "medsl": _sorted(a["cands"]), "fec": _sorted(b["cands"]),
                              "medsl_writein": a["writein"], "fec_writein": b["writein"], "medsl_extra": extra or []})
        failing = [d for d in diffs if not d["named"]]
        if not diffs:
            reason = "passed"
        elif not failing:
            reason = "passed (named candidates)"
        elif not any(k in off for k in keys):
            reason = "not in FEC"
        elif notes["suppressed"].get((st, office)):
            reason = "suppressed rows"
        else:
            reason = "differences"
        results[(st, office)] = {"passed": not failing, "differences": diffs, "reason": reason}
    return results
