# County results-report PDFs (New Jersey: Camden, Sussex; precinct level)

Surveyed and built 2026-11-27. Steve approved a PDF dependency the same day ("Add one now").

## The dependency

`pypdfium2` 5.15.2 (released 2026-11-09; BSD-3-Clause / Apache-2.0; no Python dependencies), Python bindings to PDFium, Chrome's PDF engine. It's pinned in `requirements.txt` by the SHA-256 of its macOS arm64 wheel. Another platform needs that wheel's hash added. Install as for xlrd (`docs/al.md`):

    .venv/bin/python -m pip install --require-hashes --only-binary :all: -r requirements.txt

Why this one, after testing three on the 2026 files:
- **pypdf** (pure Python, no dependencies) glues abutting right-aligned numbers together, even in its positioned-fragment mode. Camden's `Ballots Cast - Total … 4,149` and `178,067` came out as `4,149178,067`.
- **pdfminer.six** reads correctly, but pulls in cryptography, cffi, pycparser and charset-normalizer.
- **pypdfium2** keeps every number apart and every printed line together. It reads Camden's 278 pages in about 0.3 s.

The trade-off: PDFium is native code parsing downloaded files. It's the engine Chrome uses on untrusted PDFs.

Without the venv, the reader's PDF tests skip ("needs pypdfium2 (.venv)"). The text-based tests run anywhere.

## Where the data is

| County | Results page | Files (2026 general, official) | Script access |
|---|---|---|---|
| Camden | `camdencounty.com/service/voting-and-elections/election-results/` | `wp-content/elections/general2026/2026_General_Election_Canvasser.pdf` (278 pages, 2.7 MB) | 200 |
| Sussex | `sussexcountyclerk.org/939/General-Election` | `DocumentCenter/View/4874/…countywide-SUPP` (14 pages), `…/4875/…district-SUPP` (238 pages) | 200 |
| Warren | `warrencountyvotes.com/elections/past-election-results` | summary, write-in and precinct PDFs (`home/showpublisheddocument/15169`, `15171`, `15181`) | **403** to the project fetcher: not read (the blocked-site rule) |
| Hunterdon | `co.hunterdon.nj.us/994/ElectionVoter-History` | no 2026 general results posted (2026-11-27; the primary's are) | — |

File URLs change per election (`pipeline/sources_pdfreport.toml`). Sussex also posts a write-in names report and daily periodic reports; Camden's PDF includes a write-in names section. None of those are read; the write-in names are private individuals.

## The two layouts

Both are text PDFs from the same family of report (headers such as "Summary Results Report", "Precinct Results Report", "District Table Report"; the vendor is not confirmed).

**Camden** (one PDF, `layout = "camden"`):
- *Summary Results Report* (pages 2–26): county statistics (registered 393,550; ballots 178,067 by four vote types). Then each contest: the vote-type header, `Vote For N`, the name, and `<choice> (<party>) TOTAL Early Voting / Vote By Mail / Election Day / Provisional`. Each contest also lists Write-In Totals, Total Votes Cast, Overvotes, Undervotes and Contest Totals.
- *District Table Report* (157 pages): one contest per page, drawn rotated. Each page has the name, `VOTE FOR N`, wrapped column labels, one line per precinct, and a `Totals` line. A STATISTICS table gives each precinct's registered voters and ballots. No vote types.
- Also present but not read: municipality tables by vote type (9 pages each) and write-in names (134 pages).

**Sussex** (`layout = "sussex"`, two PDFs, both marked "SUPP"):
- The countywide summary and the precinct report (two pages per precinct, the precinct's name the first line of each page) have the same block layout: name, `Vote For N`, header, then `<PARTY> <choice> TOTAL PCT%`.
- The six vote types (Election Day, Early Voting, Mail-In, Provisional, Emergency, Overseas) are printed only for some contests: 9 lines in the summary, 64 in the precinct report. They're read where printed.
- Walpack Twp District 1 (9 registered voters) prints no counts at all for its six contests. They're withheld: votes are empty, listed, not estimated, and the precinct-sum check skips those 23 lines.

## The reader

`pipeline/readers/pdfreport.py`, `pipeline/run_pdfreport.py` (`fetch | parse | fetch-parse SOURCE_ID`; `.venv/bin/python`), `pipeline/sources_pdfreport.toml` (`pdf-NJ-Camden-2026-general`, `pdf-NJ-Sussex-2026-general`). Camden is one request per pass; Sussex is two, 5 s apart.

**Rows:**
- County rows come from the summary: every vote type printed, plus TOTAL. Precinct rows come from the district table (Camden) or precinct report (Sussex): TOTAL, plus vote types where Sussex prints them.
- `contest_scope` is "local", as for the other NJ counties. There are no ids: `contest_id` is the contest name and `choice_id` is empty, so join on county + contest + choice.
- Over- and undervotes are choices (Camden). `party` is as printed: Camden `D/R/I`, Sussex `DEM/REP/ETC/SWP/SIG/HSF/IND`.
- `-turnout.csv` holds registered voters and ballots per precinct (layout `pdfreport` in `pipeline/turnout_map.toml`).

**Placeholders.** "No Nomination Made" and "No Petition Filed" are empty ballot positions. They aren't rows, but they're counted and listed if nonzero (2026: 15 in Camden, 183 in Sussex, all 0). In Camden's tables they're matched as columns and checked the same way.

**Camden district table:**
- Column labels are matched to the summary contest's labels (case and spacing ignored). A header that can't be split exactly into them is listed, and that page is skipped.
- A table name the header cut short (2026: the House race, "…1st Congressional", plus two local contests) is accepted only when exactly one summary contest begins with it. It's listed.
- PDFium returns U+FFFE for a hyphen printed at a line break (7 places, e.g. "Corry-Gaft"). It's read as "-".
- *Side by side:* 13 pages print the County Question next to a municipal question, both six columns wide, so a precinct line's text alone can't say which contest its values belong to. `page_texts` splits those pages by character position, keeping PDFium's line order. Each contest's labels end with "Contest Total" and the next contest's labels follow, so the border is midway between them; the precinct-name band ends at the widest gap before the first contest. Each contest then gets its own page.

**Checks** (nothing corrected; the summary lists):
- Total Votes Cast = sum of choices, and Contest Totals = Total Votes Cast + over + under, per vote type and per unit.
- TOTAL = sum of vote types.
- Precinct sums = county totals for every choice and total. Camden also checks its table's `Totals` lines against both.
- Contests in one report but not the other.
- Sum of precinct registered voters and ballots = the county's statistics.
- Report timestamps from the page footers (`report_times`).

## 2026 run (2026-11-27 22:31 UTC)

| County | Rows | County / precinct rows | Contests | Precincts | Checks |
|---|---|---|---|---|---|
| Camden | 16,601 | 2,595 / 14,006 | 92 | 387 (incl. 43 provisional, 1 VBM unit) | all clean; 3 truncated table names (listed) |
| Sussex | 3,351 | 243 / 3,108 | 71 | 119 | all clean; Walpack's 6 contests withheld (23 precinct-sum checks not run) |

- **House.** Camden is all of NJ-1: Norcross 129,363, Galdo 43,758. Sussex is split between NJ-5 (Kirrane 15,521, Gottheimer 14,765) and NJ-7 (Bennett 12,494, Kean 12,319).
- **Report times.** Camden 11/17/2026 4:15–4:34 PM; Sussex 11/18/2026 1:44 and 1:47 PM.
- **Step 3.** Both loaded with no new parts exceptions. Camden adds 44 registered-voter exceptions: its provisional units report 0 registered voters, like other sources' provisional units.
- **Superseded parses.** My development parses of the same downloads are in `data/parsed-superseded/pdf-NJ-*`.

## Unverified / not done

- **Election night:** these are the certified reports. Both counties also post election-night and periodic reports (Sussex's are separate PDFs). Whether those share this layout is unchecked.
- **Layout changes:** the parsers know only these two 2026 layouts. A new one should show up as header mismatches, unparsed lines or failed checks, not silent misreads; that's untested beyond these files.
- **Not read:**
  - Camden's municipality tables (vote types by municipality), and per-precinct vote types (none printed).
  - Warren (403 to scripts; its precinct report is a PDF) and Hunterdon (nothing posted yet).
  - Bergen's district PDF (`docs/lvt.md`).
- **Per-row table checks:** a table line's own internal sums aren't checked; the precinct-vs-county and `Totals` checks cover the columns.
