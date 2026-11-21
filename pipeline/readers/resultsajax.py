"""Parse ResultsAjax-engine results (MT, NE, NM, OR, SD) into common-format rows, county level.

Design: docs/superpowers/specs/2026-11-21-step2-resultsajax-reader-design.md.

parse_page reads a results page's BuildCounty('<type>', '<raceID>', '<osn>', '<party>')
calls: one per race shown on that page.
"""
import re

_BUILD_COUNTY = re.compile(r"BuildCounty\('([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)")


def parse_page(html):
    """[(type, race_id, osn, party)] in page order, duplicates removed."""
    out = []
    for m in _BUILD_COUNTY.finditer(html):
        if m.groups() not in out:
            out.append(m.groups())
    return out
