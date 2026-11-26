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
