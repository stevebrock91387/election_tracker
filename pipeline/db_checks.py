"""Step 3 checks on the results database (pipeline/db.py). Report only: nothing is blocked or changed.

Design: docs/superpowers/specs/2026-11-25-step3-checks-database-design.md.
Every check is check_<name>(conn, source_id=None) -> (exceptions, not_checked); a not_checked entry has
source_id, scope and reason, so a check that couldn't run is never an empty, clean-looking list.
"""

# A row's identity across snapshots: ids where the source has them, names where it doesn't.
KEY = [("level", "level"),
       ("county", "COALESCE(NULLIF(county_id, ''), county_name)"),
       ("precinct", "COALESCE(NULLIF(precinct_id, ''), precinct_name)"),
       ("contest_id", "contest_id"),
       ("choice", "COALESCE(NULLIF(choice_id, ''), choice)"),
       ("party", "party"),
       ("vote_type", "vote_type")]
KEY_NAMES = [k for k, _ in KEY]


def _sources(conn, source_id):
    sql = "SELECT DISTINCT source_id FROM snapshot WHERE pruned = 0"
    args = ()
    if source_id is not None:
        sql, args = sql + " AND source_id = ?", (source_id,)
    return [r[0] for r in conn.execute(sql + " ORDER BY source_id", args)]


def _kept(conn, source_id):
    """snapshot_ids of a source's kept snapshots, newest first."""
    return [r[0] for r in conn.execute("SELECT snapshot_id FROM snapshot WHERE source_id = ? AND pruned = 0 "
                                       "ORDER BY first_seen_utc DESC", (source_id,))]


def check_decreases(conn, source_id=None):
    """Check 1: each source's latest snapshot against the one before it. Lists every lower count
    (kind "decrease"), every key that disappeared ("disappeared"), and keys that occur more than once in
    either snapshot ("duplicate_key", not compared). A NULL or non-integer count on either side is skipped."""
    exceptions, not_checked = [], []
    # k_ aliases: GROUP BY a bare name like "choice" would resolve to the table column, not the alias.
    keys = ", ".join(f"{expr} AS k_{name}" for name, expr in KEY)
    group = ", ".join("k_" + k for k in KEY_NAMES)
    for src in _sources(conn, source_id):
        kept = _kept(conn, src)
        if len(kept) < 2:
            not_checked.append({"source_id": src, "scope": "source", "reason": "one snapshot"})
            continue
        new, old = kept[0], kept[1]
        sql = f"""
            WITH o AS (SELECT {keys}, COUNT(*) AS n, MAX(votes) AS v, typeof(MAX(votes)) AS t
                       FROM result WHERE snapshot_id = :old GROUP BY {group}),
                 w AS (SELECT {keys}, COUNT(*) AS n, MAX(votes) AS v, typeof(MAX(votes)) AS t
                       FROM result WHERE snapshot_id = :new GROUP BY {group})
            SELECT {", ".join("o.k_" + k for k in KEY_NAMES)}, o.n, o.v, o.t, w.n, w.v, w.t
            FROM o LEFT JOIN w USING ({group})
            UNION ALL
            SELECT {", ".join("w.k_" + k for k in KEY_NAMES)}, NULL, NULL, NULL, w.n, w.v, w.t
            FROM w LEFT JOIN o USING ({group}) WHERE o.n IS NULL AND w.n > 1
            ORDER BY 1, 2, 3, 4, 5, 6, 7"""
        for r in conn.execute(sql, {"old": old, "new": new}):
            key = dict(zip(KEY_NAMES, r[:7]))
            on, ov, ot, wn, wv, wt = r[7:]
            base = dict(key, source_id=src, old_snapshot=old, new_snapshot=new)
            if (on or 0) > 1 or (wn or 0) > 1:
                exceptions.append(dict(base, kind="duplicate_key", old_votes=None, new_votes=None))
            elif wn is None:
                exceptions.append(dict(base, kind="disappeared", old_votes=ov, new_votes=None))
            elif ot == "integer" and wt == "integer" and wv < ov:
                exceptions.append(dict(base, kind="decrease", old_votes=ov, new_votes=wv))
    return exceptions, not_checked


def _levels(conn, snapshot_id):
    return {r[0] for r in conn.execute("SELECT DISTINCT level FROM result WHERE snapshot_id = ?", (snapshot_id,))}


def _grouped(conn, snapshot_id, level, by_county, statewide_only):
    """{(county, contest_id, choice, party, vote_type): (n_rows, sum, n_not_integer, max)} for one level."""
    where = "snapshot_id = ? AND level = ?" + (" AND contest_scope = 'statewide'" if statewide_only else "")
    county = f"{dict(KEY)['county']}" if by_county else "''"
    sql = f"""SELECT {county} AS k_county, contest_id, {dict(KEY)['choice']} AS k_choice, party, vote_type,
                     COUNT(*), SUM(CASE WHEN typeof(votes) = 'integer' THEN votes ELSE 0 END),
                     SUM(typeof(votes) != 'integer'), MAX(votes)
              FROM result WHERE {where} GROUP BY k_county, contest_id, k_choice, party, vote_type"""
    return {tuple(r[:5]): r[5:] for r in conn.execute(sql, (snapshot_id, level))}


PARTS_KEY = ["county", "contest_id", "choice", "party", "vote_type"]


def check_parts(conn, source_id=None):
    """Check 3, on each source's latest snapshot: precinct rows summed per county against the county row
    (key: county, contest, choice, party, vote type), and county (or town) rows summed against the state row
    (statewide contests only). Exceptions: kind "mismatch" (part_sum != whole) and "duplicate_whole" (the
    whole occurs more than once). A missing level makes the pair not checked; a line with an empty count, or
    with parts but no whole (or the reverse), is a not-checked line. Precinct rows with no county are left
    out of the precinct pair and counted in a not-checked entry."""
    exceptions, not_checked = [], []
    for src in _sources(conn, source_id):
        sid = _kept(conn, src)[0]
        levels = _levels(conn, sid)
        upper = "town" if "town" in levels else "county"
        for part, whole, by_county in (("precinct", "county", True), (upper, "state", False)):
            pair = f"{part}>{whole}"
            missing = [lv for lv in (part, whole) if lv not in levels]
            if missing:
                not_checked.append({"source_id": src, "scope": "pair", "reason": f"{pair}: no {missing[0]} rows"})
                continue
            if by_county:
                (n_blank,) = conn.execute(
                    f"SELECT COUNT(*) FROM result WHERE snapshot_id = ? AND level = 'precinct' AND "
                    f"{dict(KEY)['county']} = ''", (sid,)).fetchone()
                if n_blank:
                    not_checked.append({"source_id": src, "scope": "pair",
                                        "reason": f"{pair}: {n_blank} precinct rows have no county"})
            parts = _grouped(conn, sid, part, by_county, not by_county)
            wholes = _grouped(conn, sid, whole, by_county, not by_county)
            if by_county:
                parts = {k: v for k, v in parts.items() if k[0] != ""}
            for key in sorted(set(parts) | set(wholes)):
                base = dict(zip(PARTS_KEY, key), source_id=src, snapshot_id=sid, pair=pair)
                p, w = parts.get(key), wholes.get(key)
                if p is None or w is None:
                    not_checked.append({"source_id": src, "scope": "line",
                                        "reason": f"no {part if p is None else whole} rows", **base})
                elif w[0] > 1:
                    exceptions.append(dict(base, kind="duplicate_whole", part_sum=None, whole=None))
                elif p[2] or w[2]:
                    not_checked.append({"source_id": src, "scope": "line", "reason": "empty count", **base})
                elif p[1] != w[3]:
                    exceptions.append(dict(base, kind="mismatch", part_sum=p[1], whole=w[3]))
    return exceptions, not_checked


def _unit(values, key, strip):
    """Unit key tuple from a row's key columns, with any strip_suffix removed."""
    out = []
    for col, v in zip(key, values):
        v = v or ""
        suffix = strip.get(col)
        if suffix and v.endswith(suffix):
            v = v[: -len(suffix)]
        out.append(v)
    return tuple(out)


def check_registered(conn, source_id=None, turnout_map=None):
    """Check 2, on each source's latest snapshot, at the turnout units its layout names (pipeline/turnout_map.toml).
    Both sides are grouped by the layout's key (summing finer units into the turnout unit). Exceptions (kind):
    zero_registered (listed, not compared), ballots_over_registered, contest_over_registered (a contest's
    total-vote-type rows, every choice row as published, > registered x vote_for), blank_vote_for (counted as 1,
    listed once per contest), result_unit_without_turnout, turnout_unit_without_results. Turnout rows whose key
    is all empty are totals, not units, and are ignored. Not checked: no turnout table, unknown layout, a layout
    that can't be joined, no registered voters published; per line, an empty count."""
    from pipeline.db import load_turnout_map
    turnout_map = turnout_map or load_turnout_map()
    exceptions, not_checked = [], []
    for src in _sources(conn, source_id):
        sid = _kept(conn, src)[0]
        layouts = [r[0] for r in conn.execute("SELECT DISTINCT layout FROM turnout WHERE snapshot_id = ?", (sid,))]
        reason = None
        if not layouts:
            reason = "no turnout table"
        elif None in layouts or layouts[0] not in turnout_map:
            reason = "turnout layout unknown"
        else:
            layout = turnout_map[layouts[0]]
            if "not_joinable" in layout:
                reason = layout["not_joinable"]
            elif "registered" not in layout:
                reason = "no registered voters"
        if reason:
            not_checked.append({"source_id": src, "scope": "source", "reason": reason})
            continue
        key, strip = layout["key"], layout.get("strip_suffix", {})
        has_ballots = "ballots" in layout
        cols = ", ".join(key)

        units = {}  # unit -> [registered or None, ballots or None]
        for r in conn.execute(f"SELECT {cols}, registered_voters, ballots_cast FROM turnout WHERE snapshot_id = ?",
                              (sid,)):
            u = _unit(r[:len(key)], key, strip)
            if not any(u):
                continue
            reg, bal = r[len(key)], r[len(key) + 1]
            cur = units.setdefault(u, [0, 0])
            cur[0] = None if cur[0] is None or reg is None else cur[0] + reg
            cur[1] = None if cur[1] is None or bal is None else cur[1] + bal

        contests = {}  # (unit, contest_id) -> [sum, any_bad, vote_for]
        for r in conn.execute(f"SELECT {cols}, contest_id, vote_for, votes FROM result WHERE snapshot_id = ? AND "
                              f"level = ? AND vote_type = ?",
                              (sid, layout["result_level"], layout.get("total_vote_type", "TOTAL"))):
            u = _unit(r[:len(key)], key, strip)
            cid, vf, v = r[len(key):]
            cur = contests.setdefault((u, cid), [0, False, vf])
            if isinstance(v, int):
                cur[0] += v
            else:
                cur[1] = True

        def exc(kind, unit, **kw):
            exceptions.append(dict({"source_id": src, "snapshot_id": sid, "kind": kind, "unit": "|".join(unit),
                                    "contest_id": "", "registered": None, "ballots": None, "votes": None,
                                    "vote_for": None}, **kw))

        result_units = {u for u, _ in contests}
        for u in sorted(result_units - set(units)):
            exc("result_unit_without_turnout", u)
        for u in sorted(set(units) - result_units):
            exc("turnout_unit_without_results", u)
        blank_listed = set()
        for u in sorted(set(units) & result_units):
            reg, bal = units[u]
            if reg is None:
                not_checked.append({"source_id": src, "scope": "unit", "reason": "registered voters not a count",
                                    "unit": "|".join(u)})
                continue
            if reg == 0:
                exc("zero_registered", u, ballots=bal)
                continue
            if has_ballots and bal is not None and bal > reg:
                exc("ballots_over_registered", u, registered=reg, ballots=bal)
        for (u, cid), (total, bad, vf) in sorted(contests.items()):
            if u not in units or units[u][0] in (None, 0):
                continue
            if bad:
                not_checked.append({"source_id": src, "scope": "line", "reason": "empty count",
                                    "unit": "|".join(u), "contest_id": cid})
                continue
            if vf and vf.isascii() and vf.isdigit():
                n = int(vf)
            else:
                n = 1
                if cid not in blank_listed:
                    blank_listed.add(cid)
                    exc("blank_vote_for", (), contest_id=cid, vote_for=vf)
            if total > units[u][0] * n:
                exc("contest_over_registered", u, contest_id=cid, registered=units[u][0], votes=total, vote_for=vf)
    exceptions.sort(key=lambda e: (e["source_id"], e["kind"], e["unit"], e["contest_id"]))
    return exceptions, not_checked
