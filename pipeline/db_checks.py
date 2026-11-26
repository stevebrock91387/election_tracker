"""Step 3 checks on the results database (pipeline/db.py). Report only: nothing is blocked or changed.

Design: docs/superpowers/specs/2026-11-25-step3-checks-database-design.md.
Every check is check_<name>(conn, source_id=None) -> (exceptions, not_checked); a not_checked entry has
source_id, scope and reason, so a check that couldn't run is never an empty, clean-looking list.
"""
import csv
import os

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
    """(source ids with a kept snapshot, not-checked entries for the rest): a source whose parses were never
    loaded (it has load notes but no snapshot), or a requested source with no snapshot, is reported, never
    silently absent."""
    sql = "SELECT DISTINCT source_id FROM snapshot WHERE pruned = 0"
    args = ()
    if source_id is not None:
        sql, args = sql + " AND source_id = ?", (source_id,)
    have = [r[0] for r in conn.execute(sql + " ORDER BY source_id", args)]
    noted = {os.path.basename(os.path.dirname(p)) for (p,) in conn.execute("SELECT DISTINCT csv_path FROM load_note")}
    unloaded = sorted(s for s in noted - set(have) if source_id in (None, s)
                      and not conn.execute("SELECT 1 FROM snapshot WHERE source_id = ?", (s,)).fetchone())
    missing = [{"source_id": s, "scope": "source", "reason": "not loaded (see load notes)"} for s in unloaded]
    if source_id is not None and not have and not unloaded:
        missing.append({"source_id": source_id, "scope": "source", "reason": "no snapshot"})
    return have, missing


def _kept(conn, source_id):
    """snapshot_ids of a source's kept snapshots, newest first."""
    return [r[0] for r in conn.execute("SELECT snapshot_id FROM snapshot WHERE source_id = ? AND pruned = 0 "
                                       "ORDER BY first_seen_utc DESC", (source_id,))]


def check_decreases(conn, source_id=None):
    """Check 1: each source's latest snapshot against the one before it. Lists every lower count
    (kind "decrease"), every key that disappeared ("disappeared"), and keys that occur more than once in
    either snapshot ("duplicate_key", not compared). A NULL or non-integer count on either side is skipped."""
    sources, not_checked = _sources(conn, source_id)
    exceptions = []
    # k_ aliases: GROUP BY a bare name like "choice" would resolve to the table column, not the alias.
    keys = ", ".join(f"{expr} AS k_{name}" for name, expr in KEY)
    group = ", ".join("k_" + k for k in KEY_NAMES)
    for src in sources:
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
    """{(county, contest_id, choice, vote_type): (n_repeated, sum, n_not_integer)} for one level; n_repeated
    counts rows beyond one per party line. Party isn't
    part of the key: readers spell it differently across levels (IN: "D" vs "Democratic"), and a choice on
    several party lines (CT, DC) is summed the same way on both sides."""
    where = "snapshot_id = ? AND level = ?" + (" AND contest_scope = 'statewide'" if statewide_only else "")
    county = f"{dict(KEY)['county']}" if by_county else "''"
    sql = f"""SELECT {county} AS k_county, contest_id, {dict(KEY)['choice']} AS k_choice, vote_type,
                     COUNT(*) - COUNT(DISTINCT party),
                     SUM(CASE WHEN typeof(votes) = 'integer' THEN votes ELSE 0 END),
                     SUM(typeof(votes) != 'integer')
              FROM result WHERE {where} GROUP BY k_county, contest_id, k_choice, vote_type"""
    return {tuple(r[:4]): r[4:] for r in conn.execute(sql, (snapshot_id, level))}


PARTS_KEY = ["county", "contest_id", "choice", "vote_type"]


def check_parts(conn, source_id=None):
    """Check 3, on each source's latest snapshot: precinct rows summed per county against the county row
    (key: county, contest, choice, vote type), and county (or town) rows summed against the state row
    (statewide contests only). Exceptions: kind "mismatch" (part_sum != whole) and "duplicate_whole" (a whole
    line repeats for one party). A missing level makes the pair not checked; a line with an empty count, or
    with parts but no whole (or the reverse), is a not-checked line. Precinct rows with no county are left
    out of the precinct pair and counted in a not-checked entry."""
    sources, not_checked = _sources(conn, source_id)
    exceptions = []
    for src in sources:
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
            compared = 0
            for key in sorted(set(parts) | set(wholes)):
                base = dict(zip(PARTS_KEY, key), source_id=src, snapshot_id=sid, pair=pair)
                p, w = parts.get(key), wholes.get(key)
                if p is None or w is None:
                    not_checked.append({"source_id": src, "scope": "line",
                                        "reason": f"no {part if p is None else whole} rows", **base})
                elif w[0] > 0:
                    exceptions.append(dict(base, kind="duplicate_whole", part_sum=None, whole=None))
                elif p[2] or w[2]:
                    not_checked.append({"source_id": src, "scope": "line", "reason": "empty count", **base})
                else:
                    compared += 1
                    if p[1] != w[1]:
                        exceptions.append(dict(base, kind="mismatch", part_sum=p[1], whole=w[1]))
            if not compared:
                not_checked.append({"source_id": src, "scope": "pair", "reason": f"{pair}: nothing compared"})
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
    Both sides are grouped by the layout's key (summing finer units into the turnout unit). A choice counts its
    TOTAL rows, or the sum of its vote-type rows when it has no TOTAL. Exceptions (kind): zero_registered
    (listed, not compared), ballots_over_registered, contest_over_registered (a contest's choices, every
    choice row as published, > registered x vote_for), blank_vote_for (counted as 1,
    listed once per contest), result_unit_without_turnout, turnout_unit_without_results. Turnout rows whose key
    is all empty are totals, not units, and are ignored. Not checked: no turnout table, unknown layout, a layout
    that can't be joined, no registered voters published; per line, an empty count."""
    from pipeline.db import load_turnout_map
    turnout_map = turnout_map or load_turnout_map()
    sources, not_checked = _sources(conn, source_id)
    exceptions = []
    for src in sources:
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

        # Per choice: its TOTAL rows when it has any, else the sum of its vote-type rows (CO county rows
        # carry only "Total Votes", WV only "Election Day", NJ XML precincts only their vote types).
        choices = {}  # (unit, contest_id, choice) -> [total, total_bad, has_total, types, types_bad, vote_for]
        for r in conn.execute(f"SELECT {cols}, contest_id, {dict(KEY)['choice']}, vote_type, vote_for, votes "
                              f"FROM result WHERE snapshot_id = ? AND level = ?", (sid, layout["result_level"])):
            u = _unit(r[:len(key)], key, strip)
            cid, ch, vt, vf, v = r[len(key):]
            cur = choices.setdefault((u, cid, ch), [0, False, False, 0, False, vf])
            i = 0 if vt == "TOTAL" else 3
            if i == 0:
                cur[2] = True
            if isinstance(v, int):
                cur[i] += v
            else:
                cur[i + 1] = True
        contests = {}  # (unit, contest_id) -> [sum, any_bad, vote_for]
        for (u, cid, _), (tot, tot_bad, has_tot, types, types_bad, vf) in choices.items():
            cur = contests.setdefault((u, cid), [0, False, vf])
            cur[0] += tot if has_tot else types
            cur[1] = cur[1] or (tot_bad if has_tot else types_bad)

        def exc(kind, unit, **kw):
            exceptions.append(dict({"source_id": src, "snapshot_id": sid, "kind": kind, "unit": "|".join(unit),
                                    "contest_id": "", "registered": None, "ballots": None, "votes": None,
                                    "vote_for": None}, **kw))

        result_units = {u for u, _ in contests}
        for u in sorted(result_units - set(units)):
            exc("result_unit_without_turnout", u)
        for u in sorted(set(units) - result_units):
            exc("turnout_unit_without_results", u)
        blank_listed, compared = set(), 0
        for u in sorted(set(units) & result_units):
            reg, bal = units[u]
            if reg is None:
                not_checked.append({"source_id": src, "scope": "unit", "reason": "registered voters not a count",
                                    "unit": "|".join(u)})
                continue
            if reg == 0:
                exc("zero_registered", u, ballots=bal)
                continue
            if has_ballots and bal is not None:
                compared += 1
                if bal > reg:
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
            compared += 1
            if total > units[u][0] * n:
                exc("contest_over_registered", u, contest_id=cid, registered=units[u][0], votes=total, vote_for=vf)
        if not compared:
            not_checked.append({"source_id": src, "scope": "source", "reason": "nothing compared"})
    exceptions.sort(key=lambda e: (e["source_id"], e["kind"], e["unit"], e["contest_id"]))
    return exceptions, not_checked


CHECKS = {"decreases": check_decreases, "registered": check_registered, "parts": check_parts}
REPORT_COLUMNS = {
    "decreases": ["source_id", "old_snapshot", "new_snapshot", "kind"] + KEY_NAMES + ["old_votes", "new_votes"],
    "registered": ["source_id", "snapshot_id", "kind", "unit", "contest_id", "registered", "ballots", "votes",
                   "vote_for"],
    "parts": ["source_id", "snapshot_id", "pair", "kind"] + PARTS_KEY + ["part_sum", "whole"],
}
NOT_CHECKED_COLUMNS = ["source_id", "scope", "reason", "pair", "unit", "county", "contest_id", "choice", "party",
                       "vote_type"]


def _write(path, columns, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run_checks(conn, out_dir, source_id=None):
    """Run every check; write <name>.csv and <name>-not-checked.csv (headers even when empty) to out_dir, plus
    snapshots.csv (every snapshot's time, so a stale source shows). Returns {name: (n_exceptions, n_not_checked)}."""
    os.makedirs(out_dir, exist_ok=True)
    cols = ["source_id", "snapshot_id", "first_seen_utc", "loaded_utc", "pruned", "csv_path"]
    _write(os.path.join(out_dir, "snapshots.csv"), cols,
           [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM snapshot "
                                                    "ORDER BY source_id, first_seen_utc")])
    counts = {}
    for name, fn in CHECKS.items():
        exc, nc = fn(conn, source_id)
        _write(os.path.join(out_dir, f"{name}.csv"), REPORT_COLUMNS[name], exc)
        _write(os.path.join(out_dir, f"{name}-not-checked.csv"), NOT_CHECKED_COLUMNS, nc)
        counts[name] = (len(exc), len(nc))
    return counts
