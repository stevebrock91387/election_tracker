# Queued: National Popular Vote Interstate Compact (NPVIC) tracking

Spec as given by Steve, 2026-11-20. Not started. Queued behind current work (source verification).

1. config/npvic.yaml
   - members: one entry per jurisdiction: state, electoral_votes (2024/2028 apportionment), enacted_date, source_url
   - pending: states with bills in progress: state, electoral_votes, bill_status, source_url
   - compact_active: false   # manual override; see rule below
   - Verify the member list yourself from National Popular Vote's state-status page and Ballotpedia. Do not copy names from memory.
     Expected as of Nov 2026: 18 states + DC = 222 EVs (Virginia was the latest, April 2026). If your verified total differs, flag it to me instead of forcing 222.

2. Deterministic check (tools/npvic_status.py)
   - Sums member EVs and prints the total, the gap to 270, and which pending-state combinations would cross 270.
   - Test: with the current members, the total equals the verified count; adding PA+WI+MI+NV gives +50.
   - It never flips compact_active by itself. Reaching 270 doesn't settle the matter (litigation, effective-date rules), so I set the flag by hand. The script only prints "THRESHOLD REACHED: review compact_active" when the sum is >= 270.

3. Election-night behavior (applies once the results pipeline exists)
   - Always compute both the electoral vote count and the national popular vote.
   - compact_active = false: the headline metric is EVs (270 to win).
   - compact_active = true: the headline metric is the national popular vote plurality. Still show EVs, labeled as the pre-compact count.

4. Watch list for 2027 sessions: PA (19), MI (15), WI (10), AZ (11), NV (6). Add these to pending with sources as bills are filed.

Small commits: config + status script + tests first; election-night behavior later.
