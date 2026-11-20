"""Apply a hand-set scenario to the 2024 electoral units.

Per unit, with 2024 votes r, d, other (all percentages in points):

1. Two-party margin swing. m = (d - r) / (r + d). shift = national_swing +
   regional_swing[state] (district units use their state's value). New
   two-party votes keep r + d fixed: d1 = (r + d)(1 + m + shift/100) / 2,
   r1 = (r + d) - d1, so the margin moves by exactly `shift` points.
   Positive shift moves toward the Democrat.
2. Third-party draw. Each ThirdParty takes share/100 of the unit's total
   2024 vote (r + d + other), from_r of it out of r1 and from_d out of d1.
   2024 "other" votes are left as they were.
3. No clamping: a negative r1 or d1 raises ScenarioError naming the unit.

Winner is the plurality among "R", "D" and the third-party names; an exact
tie at the top is "TIE".
"""
from dataclasses import dataclass, field


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class ThirdParty:
    name: str
    share: float
    from_r: float
    from_d: float


@dataclass(frozen=True)
class Scenario:
    name: str
    r_name: str
    d_name: str
    national_swing: float = 0.0
    regional_swing: dict = field(default_factory=dict)
    third_party: tuple = ()


@dataclass(frozen=True)
class UnitResult:
    id: str
    state: str
    ev: int
    r: float
    d: float
    third: dict
    other: int
    winner: str


def apply(units, s):
    results = []
    for u in units:
        two = u.r + u.d
        m = (u.d - u.r) / two
        shift = s.national_swing + s.regional_swing.get(u.state, 0.0)
        d1 = two * (1 + m + shift / 100) / 2
        r1 = two - d1
        third = {}
        total = u.r + u.d + u.other
        for tp in s.third_party:
            take = tp.share / 100 * total
            r1 -= take * tp.from_r
            d1 -= take * tp.from_d
            third[tp.name] = take
        if r1 < 0 or d1 < 0:
            raise ScenarioError(
                f"{u.id}: scenario '{s.name}' gives negative votes (R {r1:.0f}, D {d1:.0f}); "
                f"shift {shift:+g} points on a 2024 margin of {m * 100:+.2f}")
        tally = {"R": r1, "D": d1, **third}
        top = max(tally.values())
        leaders = [k for k, v in tally.items() if v == top]
        winner = leaders[0] if len(leaders) == 1 else "TIE"
        results.append(UnitResult(u.id, u.state, u.ev, r1, d1, third, u.other, winner))
    return results
