"""Cut the Hawaii test fixture from the real 2026 text files, keeping lines byte for byte.

    /opt/homebrew/bin/python3 -I -m pipeline.make_hi_fixture SUMMARY_TXT MEDIA_TXT OUT_DIR

Keeps the preamble and header lines of each file, then only the records of the contests in
CONTESTS (a record may span lines inside a quoted field).
"""
import sys

CONTESTS = {"47", "23", "43", "38"}  # Councilmember Dist 4, State Rep Dist 2, Governor, Question #1


def records(text):
    """Split text into records (with their line endings), honouring quoted newlines."""
    out, start, quoted = [], 0, False
    for i, ch in enumerate(text):
        if ch == '"':
            quoted = not quoted
        elif ch == "\n" and not quoted:
            out.append(text[start:i + 1])
            start = i + 1
    if start < len(text):
        out.append(text[start:])
    return out


def cut(path, head_lines, id_field, out_path):
    with open(path, encoding="utf-8", newline="") as f:
        recs = records(f.read())
    keep = recs[:head_lines] + [r for r in recs[head_lines:] if r.split("\t")[id_field] in CONTESTS]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(keep))
    return len(keep) - head_lines


if __name__ == "__main__":
    summary, media, out = sys.argv[1:4]
    print(cut(summary, 2, 0, f"{out}/hi_summary.txt"), cut(media, 3, 6, f"{out}/hi_media.txt"))
