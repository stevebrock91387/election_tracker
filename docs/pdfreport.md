# County results-report PDFs (New Jersey: Camden, Sussex, Bergen; precinct level)

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
| Bergen | `bergencountyclerk.gov/Election` | `_Content/pdf/ElectionResult/2026%20General%20District%20Report.pdf` (735 pages, 5.9 MB; county totals also in `docs/lvt.md`) | 200 |
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

## Bergen: statement-of-votes tables (`layout = "bergen"`, `pipeline/readers/sovtable.py`)

Added 2026-11-27 (same day, same dependency). One PDF, 735 pages, one contest per page:
- **Layout.** The title (top left, up to three lines) comes first. Then rotated column labels: Registered Voters, Voters Cast, Turnout (%), one per choice ("REP - JUSTIN MURPHY"), Write-ins, Total Votes. Then one line per unit and vote type, `<unit> <Early Voting|Election Day|Mail-In|Provisional|Total> <cells>`.
- **Units.** Election districts ("Allendale 1"), each municipality's provisional unit ("Allendale Provisional"), the municipality subtotal ("Allendale"), and the contest's county rows ("Total - Early Voting" … "Contest Total").
- **Wide contests continue on further pages.** Teaneck Council's choices are on pages 564–566; its Total Votes are on 567–569, repeating the units.
- **Empty cells aren't printed.** "Allendale 2 Early Voting 920 117 12.72% 52 65 117" has two blank candidates. So text order can't place numbers; positions do.
- **Withheld cells.** "***" (1,050 cells in 2026) marks counts withheld for voter privacy. They're left empty, listed, not estimated.

**Two stages:**
- *Positions* (`table_pages`, pypdfium2).
  - A column is a band of header characters. A label's rotated lines read right to left; within a line, characters keep PDFium's text order (PDFium sometimes reverses the line order itself, e.g. "COLELLA PHILIP S.").
  - Each cell character goes to the first column whose right edge (+5 pt) it doesn't pass; numbers are right-aligned. That also rejoins numbers PDFium's text splits ("1 17" for 117).
  - A line with no cells is part of a wrapped unit name ("Hasbrouck Heights" / "Provisional" / "Early Voting 0 0"). Every real row prints at least its registered voters.
  - U+FFFE in a label is a line-break hyphen ("O'CONNELL-SORIANO").
- *Rows* (`parse_pages`, text only).
  - Cells are merged per contest, unit, vote type and label; a repeat with a different value is listed.
  - A unit whose name every district since the last subtotal begins with is that municipality's subtotal.
  - Blank is 0, "***" is empty, and the leading "1 " of every title is dropped (its meaning is unknown; it isn't vote-for).

**Rows written.** Precinct rows for districts and provisional units, and county rows from "Total - …" / "Contest Total" (vote types plus TOTAL). Municipality subtotals are checks only. Choices are the printed labels with the party split off; Write-ins is a choice. Contests have no vote_for (not printed). The turnout file has registered voters and voters cast per district.

**Checks** (2026: all 0):
- Choices + Write-ins never exceed Total Votes.
- Vote types sum to the Total row.
- Districts sum to their municipality subtotal; subtotals sum to the county rows.
- Registered voters are the same across a unit's vote types.

**Total Votes includes votes in no printed column.** Choices + Write-ins fall short of Total Votes by 9,490 votes across the 192 contests. In every contest the remainder equals LiveVoterTurnout's "Personal Choice" line, or 0 where it has none. So "Personal Choice" (written-in names) is in Total Votes but not printed as a column. The Write-ins column itself is blank everywhere except one vote in Maywood Board of Education, which is also why LVT's Maywood ballot balance is off by 1. The remainder is listed per contest (`unattributed_by_contest`), not stored as rows: nothing prints it per precinct.

**2026 run (2026-11-27 22:52 UTC; "Data Refreshed: Monday, November 16, 2026 3:22 PM"):**
- 108,290 rows, 192 contests, 637 districts.
- Cross-check: all 526 choice county totals equal `lvt-NJ-Bergen-2026-general`, a separate file on another host.
- Step 3: no parts exceptions. 540 registered-voter exceptions:
  - 192 blank vote_for;
  - 74 provisional units with 0 registered voters;
  - 274 "contest over registered". All of these are 2- to 5-seat contests (vote_for from LVT), and none is over with the real vote_for.

## Unverified / not done

- **Election night:** these are the certified reports. Both counties also post election-night and periodic reports (Sussex's are separate PDFs). Whether those share this layout is unchecked.
- **Bergen election night:** the district report is dated Nov 16; whether election-night versions share its layout is unchecked. vote_for isn't in Bergen's PDF (LVT has it).
- **Layout changes:** the parsers know only these three 2026 layouts. A new one should show up as header mismatches, unparsed lines or failed checks, not silent misreads; that's untested beyond these files.
- **Not read:**
  - Camden's municipality tables (vote types by municipality), and per-precinct vote types (none printed).
  - Warren (403 to scripts; its precinct report is a PDF) and Hunterdon (nothing posted yet).
- **Per-row table checks:** a table line's own internal sums aren't checked; the precinct-vs-county and `Totals` checks cover the columns.
