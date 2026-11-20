"""Load and validate scenarios/matchups.toml (Python's built-in tomllib; no dependencies)."""
import os
import tomllib

from scenarios.engine import Scenario, ScenarioError, ThirdParty

DEFAULT_MATCHUPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matchups.toml")
SPLIT_TOLERANCE = 1e-9


def load_matchups(path=DEFAULT_MATCHUPS, known_states=None):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    out = []
    for m in data.get("matchup", []):
        name = m["name"]
        regional = {k: float(v) for k, v in m.get("regional_swing", {}).items()}
        if known_states is not None:
            unknown = sorted(set(regional) - set(known_states))
            if unknown:
                raise ScenarioError(f"{name}: regional_swing has unknown state codes {unknown}")
        third = []
        for tp in m.get("third_party", []):
            t = ThirdParty(tp["name"], float(tp["share"]), float(tp["from_r"]), float(tp["from_d"]))
            if abs(t.from_r + t.from_d - 1) > SPLIT_TOLERANCE:
                raise ScenarioError(f"{name}: {t.name} from_r + from_d = {t.from_r + t.from_d}, must be 1")
            third.append(t)
        out.append(Scenario(name=name, r_name=m["r_name"], d_name=m["d_name"],
                            national_swing=float(m.get("national_swing", 0.0)),
                            regional_swing=regional, third_party=tuple(third)))
    return out
