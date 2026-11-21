"""The common results format every reader produces: one row per vote count (long format).

level: "state", "county" or "precinct".
vote_type: "TOTAL" for an option's total, otherwise the source's own group name, unchanged.
reporting_status: as the source states it for that row's unit and vote type; "" when absent.
contest_scope: "statewide" when the contest appears in the source's state-level results
  (district races such as a US House seat included), so contest_id identifies it across
  counties; "local" when it appears only in county results, so the key is (county_id, contest_id).
choice_id: the source's own id for the choice within its contest. Join on ids, not names:
  names are spelled differently across counties under the same id.
"""
import csv

COLUMNS = [
    "state", "source_id", "source_sha256", "source_created_at", "election_name", "election_date",
    "level", "county_id", "county_name", "precinct_id", "precinct_name", "precinct_is_virtual",
    "contest_id", "contest_scope", "contest_name", "contest_type", "vote_for", "choice", "choice_id", "party",
    "vote_type", "votes", "reporting_status",
]


def write_csv(rows, path):
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
            n += 1
    return n
