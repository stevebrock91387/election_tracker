"""Cut the Massachusetts test fixture from real 2026 downloads, keeping bytes as published.

    /opt/homebrew/bin/python3 -I pipeline/make_ma_fixture.py SEARCH_HTML QUESTIONS_HTML OUT_DIR

Keeps each list page's text before the first row and after the last row, and only the rows of the
ids below. The contest and question CSVs are copied into OUT_DIR separately, unmodified.
"""
import sys

CONTESTS = ["173531", "173571", "173668", "173595", "171923"]  # U.S. Senate, U.S. House 2nd, Rep 1st Barnstable, Sheriff, State Senate 1st Middlesex special
QUESTIONS = ["11789", "11758"]  # Question 1 (statewide), Question 10 (1st Bristol, local)
END = "<!--// END tr#election-id-... //-->"


def cut(text, marker, ids):
    first = text.index(marker)
    last = text.rindex(END) + len(END)
    rows = text[first:last].split(END)[:-1]
    keep = [r + END for r in rows if any(r.lstrip().startswith(f'{marker}{i}"') for i in ids)]
    assert len(keep) == len(ids), (len(keep), ids)
    return text[:first] + "".join(keep) + text[last:]


if __name__ == "__main__":
    search, questions, out = sys.argv[1:4]
    for src, marker, ids, name in [(search, '<tr id="election-id-', CONTESTS, "ma_search.html"),
                                   (questions, '<tr id="bq-id-', QUESTIONS, "ma_questions.html")]:
        with open(src, encoding="utf-8", newline="") as f:
            text = f.read()
        with open(f"{out}/{name}", "w", encoding="utf-8", newline="") as f:
            f.write(cut(text, marker, ids))
