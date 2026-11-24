"""Cut the Ohio test fixture from a real feed file.

    /opt/homebrew/bin/python3 -m pipeline.make_oh_fixture SRC OUT

Keeps the root and Election attributes, every GpUnit (so the 88 result counties, their turnout
and the 88 unreferenced "... County" units are real), the contests in KEEP, and only the
Candidates, Persons, Parties and Offices those contests reference. The OfficeGroup tree is
dropped (it names offices that are no longer in the fixture).
"""
import sys
import xml.etree.ElementTree as ET

NS = "http://grouper.ieee.org/groups/1622/groups/2/V1/1622_2-election_results_reporting.xsd"
E = "{%s}" % NS
KEEP = [
    "_55A742EA56A709A3E0633390EE0AE290",  # U.S. Senator
    "_55A742EA571009A3E0633390EE0AE290",  # Representative to Congress - District 10 (Butler part)
    "_55A742EA574109A3E0633390EE0AE290",  # Representative to Congress - District 08 (Butler part)
    "_58F2C0185A8C8A6AE0633390EE0AF8C5",  # State Issue 3
    "_55A742EA542A09A3E0633390EE0AE290",  # Governor and Lieutenant Governor
    "_55A742EA55F109A3E0633390EE0AE290",  # Justice of the Supreme Court (term 2027-01-01)
    "_55A742EA564C09A3E0633390EE0AE290",  # Justice of the Supreme Court (term 2027-01-02)
]


def cut(src, out):
    ET.register_namespace("", NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    tree = ET.parse(src)
    root = tree.getroot()
    election = root.find(E + "Election")
    contests = election.find(E + "ContestCollection")
    for c in list(contests):
        if c.get("ObjectId") not in KEEP:
            contests.remove(c)
    cand_ids = {x.text for x in contests.iter(E + "CandidateId")}
    office_ids = {x.text for x in contests.iter(E + "OfficeId")}
    cands = election.find(E + "CandidateCollection")
    for c in list(cands):
        if c.get("ObjectId") not in cand_ids:
            cands.remove(c)
    party_ids = {c.findtext(E + "PartyId") for c in cands}
    person_ids = {c.findtext(E + "PersonId") for c in cands}
    for coll, keep in (("PartyCollection", party_ids), ("PersonCollection", person_ids),
                       ("OfficeCollection", office_ids)):
        el = root.find(E + coll)
        for x in list(el):
            if x.tag == E + "OfficeGroup" or x.get("ObjectId") not in keep:
                el.remove(x)
    tree.write(out, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    cut(sys.argv[1], sys.argv[2])
