"""Electoral units for the scenario model.

A unit is anything that awards electoral votes on its own plurality: each
winner-take-all state and DC; and, for Maine and Nebraska, an at-large unit
(2 EVs, statewide vote) plus one unit per congressional district (1 EV each).

District rows are transcribed from the 2024 Certificates of Ascertainment;
their `other` excludes write-ins, which the certificates don't split by district.
"""
import csv
import os
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATES_CSV = os.path.join(_HERE, "data", "baseline_2024_states.csv")
DEFAULT_DISTRICTS_CSV = os.path.join(_HERE, "data", "baseline_2024_districts.csv")
DISTRICT_STATES = ("ME", "NE")
AT_LARGE_EV = 2


@dataclass(frozen=True)
class Unit:
    id: str
    state: str
    ev: int
    r: int
    d: int
    other: int


def load_units(states_csv=DEFAULT_STATES_CSV, districts_csv=DEFAULT_DISTRICTS_CSV):
    units = []
    with open(states_csv, newline="") as f:
        for row in csv.DictReader(f):
            st = row["state"]
            votes = dict(r=int(row["r"]), d=int(row["d"]), other=int(row["other"]))
            if st in DISTRICT_STATES:
                units.append(Unit(id=f"{st}-AL", state=st, ev=AT_LARGE_EV, **votes))
            else:
                units.append(Unit(id=st, state=st, ev=int(row["electoral_votes"]), **votes))
    with open(districts_csv, newline="") as f:
        for row in csv.DictReader(f):
            units.append(Unit(id=row["id"], state=row["state"], ev=1,
                              r=int(row["r"]), d=int(row["d"]), other=int(row["other"])))
    return units
