"""Load and validate scenarios/matchups.toml (Python's built-in tomllib; no dependencies)."""
import math
import os
import tomllib

from scenarios.engine import Scenario, ScenarioError, ThirdParty

DEFAULT_MATCHUPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matchups.toml")
SPLIT_TOLERANCE = 1e-9


def _finite(name, what, value):
    v = float(value)
    if not math.isfinite(v):
        raise ScenarioError(f"{name}: {what} must be a finite number, got {value}")
    return v


def load_matchups(path=DEFAULT_MATCHUPS, known_states=None):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    out = []
    for m in data.get("matchup", []):
        name = m["name"]
        regional = {k: _finite(name, f"regional_swing.{k}", v)
                    for k, v in m.get("regional_swing", {}).items()}
        if known_states is not None:
            unknown = sorted(set(regional) - set(known_states))
            if unknown:
                raise ScenarioError(f"{name}: regional_swing has unknown state codes {unknown}")
        third = []
        for tp in m.get("third_party", []):
            t = ThirdParty(tp["name"], *(_finite(name, f"{tp['name']} {k}", tp[k])
                                         for k in ("share", "from_r", "from_d")))
            if t.share < 0:
                raise ScenarioError(f"{name}: {t.name} share must be 0 or more")
            if not (0 <= t.from_r <= 1 and 0 <= t.from_d <= 1):
                raise ScenarioError(f"{name}: {t.name} from_r and from_d must each be between 0 and 1")
            if abs(t.from_r + t.from_d - 1) > SPLIT_TOLERANCE:
                raise ScenarioError(f"{name}: {t.name} from_r + from_d = {t.from_r + t.from_d}, must be 1")
            third.append(t)
        out.append(Scenario(name=name, r_name=m["r_name"], d_name=m["d_name"],
                            national_swing=_finite(name, "national_swing", m.get("national_swing", 0.0)),
                            regional_swing=regional, third_party=tuple(third)))
    return out
