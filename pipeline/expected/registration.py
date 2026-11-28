"""2026 registered voters per county from the step-3 database's turnout tables (step 4).

registration_2026(conn) -> (rows, listed); rows {state, county_name, registered, source_id, snapshot_id}.
- One snapshot per source: its latest non-pruned one (by first_seen_utc).
- Town layouts (result_level "town" in pipeline/turnout_map.toml: CT, VT) are listed, not summed: towns
  aren't counties. A source whose units carry no county name (AK, DC, HI, DE) is listed.
- Units are summed by (state, county_name). Where the units carry a contest_id (LA: one row per race and
  parish, and a district race counts only its part of a parish), only the contests covering the most
  counties in that snapshot (the statewide ones) are read, and they must agree per county; a county where
  they differ is listed.
- A unit with neither a precinct id nor a name beside named units is the county's total (NJ Clarity counties):
  it is used only when it equals the precincts' sum, which are then the county's units; otherwise listed.
- A county with any unit's registered voters NULL, whose sum is 0 (31 AL counties publish 0), or whose sum is
  below its ballots cast (AL Cleburne, Henry, Randolph: 0 everywhere but a provisional unit), is listed.
- A county that two sources both report is listed as "two sources" and taken from neither.
listed entries: (state, source_id(s), county_name, reason).
"""
import collections

from pipeline.db import load_turnout_map


def _town_layouts():
    return {name for name, lay in load_turnout_map().items() if lay.get("result_level") == "town"}


def registration_2026(conn):
    towns = _town_layouts()
    snaps = conn.execute("""SELECT snapshot_id, source_id, state FROM snapshot s WHERE pruned = 0 AND first_seen_utc =
                            (SELECT max(first_seen_utc) FROM snapshot WHERE source_id = s.source_id AND pruned = 0)
                            ORDER BY source_id""").fetchall()
    found = collections.defaultdict(list)  # (state, county) -> [(registered, source, snapshot)]
    listed = []
    for sid, source, state in snaps:
        units = conn.execute("SELECT layout, county_name, contest_id, registered_voters, ballots_cast,"
                             " coalesce(precinct_id, '') <> '' OR coalesce(precinct_name, '') <> ''"
                             " FROM turnout WHERE snapshot_id = ?", (sid,)).fetchall()
        if not units:
            continue
        layouts = {u[0] for u in units}
        if layouts & towns:
            listed.append((state, source, "", f"towns (layout {', '.join(sorted(layouts))})"))
            continue
        if not any(u[1] for u in units):
            listed.append((state, source, "", "no county names"))
            continue
        if any(u[2] for u in units):
            cover = collections.Counter(contest for contest, _ in {(u[2], u[1]) for u in units})
            widest = max(cover.values())
            per = collections.defaultdict(set)
            for _, county, contest, reg, _, _ in units:
                if cover[contest] == widest:
                    per[county].add(reg)
            for county, regs in sorted(per.items()):
                if len(regs) > 1:
                    listed.append((state, source, county, "registered voters differ by contest: "
                                   + ", ".join(str(r) for r in sorted(regs, key=lambda x: (x is None, x)))))
                else:
                    (reg,) = regs
                    _add(found, listed, state, source, sid, county, [(reg, None, True)])
            continue
        per = collections.defaultdict(list)
        for _, county, _, reg, ballots, named in units:
            per[county].append((reg, ballots, bool(named)))
        for county, regs in sorted(per.items()):
            _add(found, listed, state, source, sid, county, regs)
    rows = []
    for (state, county), hits in sorted(found.items()):
        if len(hits) > 1:
            listed.append((state, " ".join(sorted(h[1] for h in hits)), county, "two sources"))
            continue
        reg, source, sid = hits[0]
        rows.append({"state": state, "county_name": county, "registered": reg, "source_id": source, "snapshot_id": sid})
    return rows, sorted(listed)


def _add(found, listed, state, source, sid, county, units):
    """units: [(registered, ballots_cast, has a precinct id or name)]."""
    if not county:
        listed.append((state, source, "", f"{len(units)} unit(s) with no county name"))
        return
    totals = [u for u in units if not u[2]]
    if totals and len(totals) < len(units):
        if len(totals) > 1 or any(u[0] is None for u in units):
            listed.append((state, source, county, f"{len(totals)} county-total unit(s) beside precincts"))
            return
        precincts = [u for u in units if u[2]]
        if totals[0][0] != sum(u[0] for u in precincts):
            listed.append((state, source, county, f"county-total unit {totals[0][0]} differs from its precincts "
                           f"{sum(u[0] for u in precincts)}"))
            return
        units = precincts
    regs = [u[0] for u in units]
    missing = sum(r is None for r in regs)
    ballots = sum(u[1] for u in units if u[1] is not None)
    if missing:
        listed.append((state, source, county, f"registered voters missing for {missing} unit(s)"))
    elif sum(regs) == 0:
        listed.append((state, source, county, "registered voters 0"))
    elif sum(regs) < ballots:
        listed.append((state, source, county, f"registered voters {sum(regs)} below ballots cast {ballots}"))
    else:
        found[(state, county)].append((sum(regs), source, sid))
