"""Electoral-vote totals, tipping point, flip swing, sensitivity, and rendering.

Every rendered output starts with LABEL.
"""
import csv
import dataclasses
import io

from scenarios.engine import ScenarioError, apply

LABEL = "Scenario, not a forecast: inputs are hand-set assumptions."
TO_WIN = 270
NUDGE = 1e-6  # points past a crossing when testing whether the winner changed
FLIP_BOUND = 100.0


def ev_totals(results):
    """EVs per unit winner ("R", "D", third-party names, "TIE" for tied units),
    plus `winner` (whoever reaches 270, else None) and `tie` (269-269)."""
    ev = {"R": 0, "D": 0}
    for r in results:
        ev[r.winner] = ev.get(r.winner, 0) + r.ev
    winner = next((k for k, v in ev.items() if k != "TIE" and v >= TO_WIN), None)
    top = sorted((v for k, v in ev.items() if k != "TIE"), reverse=True)
    tie = winner is None and len(top) >= 2 and top[0] == top[1] == TO_WIN - 1
    return {**ev, "winner": winner, "tie": tie}


def _lead(r, who):
    """Winner's lead over the runner-up in a unit, as a share of the unit's total vote."""
    votes = {"R": r.r, "D": r.d, **r.third}
    total = r.r + r.d + sum(r.third.values()) + r.other
    mine = votes[who]
    second = max(v for k, v in votes.items() if k != who)
    return (mine - second) / total


def tipping_point(results):
    """Unit whose EVs carry the overall winner to 270, taking the winner's units
    from largest lead to smallest. None when nobody reaches 270."""
    winner = ev_totals(results)["winner"]
    if winner is None:
        return None
    cum = 0
    for r in sorted((r for r in results if r.winner == winner),
                    key=lambda r: _lead(r, winner), reverse=True):
        cum += r.ev
        if cum >= TO_WIN:
            return r.id
    return None


def _crossings(units, s):
    """Changes to national_swing (points) at which two candidates tie in some unit."""
    out = set()
    for u in units:
        two = u.r + u.d
        m = (u.d - u.r) / two
        base = s.national_swing + s.regional_swing.get(u.state, 0.0)
        total = u.r + u.d + u.other
        take_r = sum(tp.share / 100 * total * tp.from_r for tp in s.third_party)
        take_d = sum(tp.share / 100 * total * tp.from_d for tp in s.third_party)
        shifts = [100 * ((take_d - take_r) / two - m)]  # R == D
        for tp in s.third_party:
            t3 = tp.share / 100 * total
            shifts.append(100 * (2 * (t3 + take_d) / two - 1 - m))  # D == third
            shifts.append(100 * (1 - m - 2 * (t3 + take_r) / two))  # R == third
        out.update(S - base for S in shifts)
    return out


def flip_swing(units, s):
    """Smallest change to national_swing (signed, points) at which the overall
    winner changes (including to no majority). None if none within ±100."""
    start = ev_totals(apply(units, s))["winner"]
    for delta in sorted(_crossings(units, s), key=abs):
        if delta == 0 or abs(delta) > FLIP_BOUND:
            continue
        nudged = delta + (NUDGE if delta > 0 else -NUDGE)
        try:
            res = apply(units, dataclasses.replace(s, national_swing=s.national_swing + nudged))
        except ScenarioError:
            continue
        if ev_totals(res)["winner"] != start:
            return delta
    return None


def sensitivity(units, s):
    """(national_swing, R EVs, D EVs) for national swing -10.0..+10.0 in 0.5 steps,
    all other inputs held."""
    rows = []
    for k in range(-20, 21):
        swing = k * 0.5
        t = ev_totals(apply(units, dataclasses.replace(s, national_swing=swing)))
        rows.append((swing, t["R"], t["D"]))
    return rows


def _name(s, key):
    return {"R": s.r_name + " (R)", "D": s.d_name + " (D)"}.get(key, key)


def render_markdown(s, results, totals, tp, flip, sens):
    lines = [LABEL, "", f"# {s.r_name} (R) vs {s.d_name} (D) — `{s.name}`", "",
             f"Inputs: national swing {s.national_swing:+g} points (positive = toward the Democrat); "
             f"regional swing {s.regional_swing or 'none'}; third parties "
             + (", ".join(f"{t.name} {t.share:g}% (from R {t.from_r:g}, from D {t.from_d:g})"
                          for t in s.third_party) or "none") + ".", ""]
    if totals["tie"]:
        lines.append("**269–269. No majority: House decides.**")
    elif totals["winner"] is None:
        lines.append("**No candidate reaches 270. No majority: House decides.**")
    else:
        lines.append(f"**Winner: {_name(s, totals['winner'])}**")
    ev = ", ".join(f"{_name(s, k)} {v}" for k, v in totals.items() if k not in ("winner", "tie"))
    lines += ["", f"Electoral votes: {ev} (of 538).",
              f"Tipping point: {tp or 'none'}.",
              "National swing needed to change the winner: "
              + ("none within ±100 points" if flip is None else f"{flip:+.3f} points") + ".", "",
              "| Unit | EV | R votes | D votes | Third party | Margin (D−R, pts) | Winner |",
              "|---|---|---|---|---|---|---|"]
    for r in results:
        total = r.r + r.d + sum(r.third.values()) + r.other
        third = ", ".join(f"{k} {v:,.0f}" for k, v in r.third.items() if v) or ""
        lines.append(f"| {r.id} | {r.ev} | {r.r:,.0f} | {r.d:,.0f} | {third} | "
                     f"{(r.d - r.r) / total * 100:+.2f} | {_name(s, r.winner)} |")
    if sens:
        lines += ["", "## Sensitivity (national swing, other inputs held)", "",
                  "| National swing | R EV | D EV |", "|---|---|---|"]
        lines += [f"| {sw:+.1f} | {r_ev} | {d_ev} |" for sw, r_ev, d_ev in sens]
    return "\n".join(lines) + "\n"


def render_csv(s, results):
    buf = io.StringIO()
    buf.write("# " + LABEL + "\n")
    w = csv.writer(buf)
    names = [t.name for t in s.third_party]
    w.writerow(["matchup", "unit", "state", "ev", "r", "d", *names, "other_2024", "winner"])
    for r in results:
        w.writerow([s.name, r.id, r.state, r.ev, f"{r.r:.1f}", f"{r.d:.1f}",
                    *(f"{r.third.get(n, 0):.1f}" for n in names), r.other, r.winner])
    return buf.getvalue()
