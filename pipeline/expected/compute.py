"""Expected vote per county for a target election from its two comparable years (step 4).

norm_county(name), the county-name join key, rules in order:
1. case-fold; collapse runs of whitespace; strip.
2. "st." / "st" as a word becomes "saint"; "ste." / "ste" becomes "sainte".
3. drop one trailing " city and borough", " census area", " borough", " county" or " parish".
   " city" is kept: independent cities ("Baltimore city", "St. Louis city") stay apart from same-named counties.

expected(target, years, baselines, registration, listed_in=None) -> (rows, listed).
- baselines: {year: baseline rows}; counties are joined across years on (state, county_fips). A county name
  (norm_county) found under more than one FIPS across the two years is listed, not split into two counties.
- registration: {(state, norm_county(name), year): registered}.
- Formulas (the design's, verbatim):
  "rate × registration" (registration for both years and the target): rate_y = votes_y / registered_y;
     point = rate_latest × registered_target; low/high = min/max of rate_y × registered_target.
  "raw" (both years, some registration missing): point = votes_latest; low/high = min/max of the two votes;
     reason names the years without registration.
  "one year": point = low = high = that year's votes; reason names the missing year (and why, from listed_in).
  Neither year: no row; listed (state, county_fips, county_name, reason) with each year's reason.
- point, low and high are rounded only at output (round(), half to even). Nothing is imputed or clamped.
"""
import re

EXPECTED_COLUMNS = ["state", "county_fips", "county_name", "target", "point", "low", "high", "method", "reason",
                    "years_used"]
SUFFIXES = (" city and borough", " census area", " borough", " county", " parish")


def norm_county(name):
    s = " ".join(name.casefold().split())
    s = re.sub(r"\bst\.?(?=\s|$)", "saint", s)
    s = re.sub(r"\bste\.?(?=\s|$)", "sainte", s)
    for suf in SUFFIXES:
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def expected(target, years, baselines, registration, listed_in=None):
    listed_in = listed_in or {}
    early, late = sorted(years)
    by = {y: {(r["state"], r["county_fips"]): r for r in baselines.get(y, [])} for y in (early, late)}
    why = {y: {(l[0], l[1]): l for l in listed_in.get(y, [])} for y in (early, late)}
    rows, listed = [], []
    keys = set(by[early]) | set(by[late]) | set(why[early]) | set(why[late])
    fips_of = {}
    for y in (early, late):
        for (st, fips), r in by[y].items():
            fips_of.setdefault((st, norm_county(r["county_name"])), {})[fips] = r["county_name"]
    for (st, _), seen in sorted(fips_of.items()):
        if len(seen) > 1:
            ids = sorted(seen)
            listed.append((st, " ".join(ids), seen[ids[0]], "county under two FIPS across years: " + ", ".join(ids)))
            keys -= {(st, f) for f in ids}
    for key in sorted(keys):
        have = [y for y in (early, late) if key in by[y]]
        if not have:
            name = (why[early].get(key) or why[late].get(key))[2]
            reasons = "; ".join(f"{y}: {why[y][key][3] if key in why[y] else 'no baseline'}" for y in (early, late))
            listed.append(key + (name, reasons))
            continue
        name = by[have[-1]][key]["county_name"]
        votes = {y: by[y][key]["votes"] for y in have}
        if len(have) == 1:
            (y,) = have
            (gone,) = [g for g in (early, late) if g != y]
            reason = f"{gone}: {why[gone][key][3]}" if key in why[gone] else f"no {gone} baseline"
            point = low = high = votes[y]
            method = "one year"
        else:
            reg = {y: registration.get((key[0], norm_county(by[y][key]["county_name"]), y)) for y in (early, late)}
            reg[target] = registration.get((key[0], norm_county(name), target))
            missing = [y for y in (early, late, target) if not reg[y]]
            if missing:
                point, low, high = votes[late], min(votes.values()), max(votes.values())
                method, reason = "raw", "no registration for " + ", ".join(str(y) for y in missing)
            else:
                est = {y: votes[y] / reg[y] * reg[target] for y in (early, late)}
                point, low, high = est[late], min(est.values()), max(est.values())
                method, reason = "rate × registration", ""
        rows.append({"state": key[0], "county_fips": key[1], "county_name": name, "target": target,
                     "point": round(point), "low": round(low), "high": round(high), "method": method,
                     "reason": reason, "years_used": " ".join(str(y) for y in have)})
    return rows, listed
