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
