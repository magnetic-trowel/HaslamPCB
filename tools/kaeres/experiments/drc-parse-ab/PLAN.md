<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# drc-parse-ab: one DRC item parser (pre-registered plan)

Written 2026-11-16, before any run.

## The change (P, `simp-drc-parse` d19411e5, stacked on `simp-drc-items` 084cc07c)
`kae.drc_items.item_kind / item_nets / item_ref / open_nets / board_nets` replace five regexes in seven places:
`joint.feedback.parse_item`, `place.legalize.violation_parts` and `place.exact`, `board_hazards._objects`,
`route.repair`, `route.lastmile.open_nets` (also used by `route.blocked`), and `restart.overlaps`.
- An item names at most one net. Its first bracket opens the net, and the net closes at the bracket followed by
  " of ", " on " or the end of the description.
- A part's reference may hold spaces.
- "Footprint text of U3 (...)" names U3, not "text".
- Board text names neither a net nor a part.

## Where the mechanism exists
Old against new on 6,000 random corpus DRC reports (all items: `parsediff.py`):
- `lastmile.open_nets` differs on 38 reports. The old parser cut a net at its first "]", so "/MDI[0]+" became
  "/MDI[0". That name matches no board net, so the last mile never joined the net.
- `repair`'s net lists differ on 1,556 of 1.96 M items. The causes are bracketed nets, and layer names in
  brackets ("Via [GND] on L1 [TOP] - L4 [BOT]" read nets TOP and BOT).
- `restart.overlaps` misses 272 of 46,658 pad and footprint items on layers whose names hold a space ("Bottom
  Layer").
- The joint spots' and the hazards' part references differ on about 1.6 % of items, mostly "Footprint text of".

There are 49 `usable_route_test` boards (49 repo families) where the pinned fork's own output leaves at least one
open connection on a bracketed net, 723 such nets in all (`bracketboards.py`). Many are RP2040 boards
(QSPI_DATA[n]), bus designs (cpu_a[n], RAM_ADDR[n]) and Ethernet MDI pairs. These boards are `boards.txt`. The
route kind exercises only the routing sites (last mile, repair, blocked). The placement and restart sites
change only on boards with such names, and only in what they report or which part they blame.

## Arms (`setup.sh`)
C is the bridge at `simp-drc-items` (output-identical to main ca98570e on 4 runs). P is the bridge at
`simp-drc-parse`. Both run `kae.route.cli route --time 900` under counted work (`KAE_BUDGET=work
PYTHONHASHSEED=0 KAE_WORKERS=1`) with Freerouting fork d137fd1 set explicitly. The harness is main ca98570e and the
wall timeout is 3,600 s (4x). Each board's job runs both arms side by side (`replicate=dpab`), attempts 0 and 1
(seeds 0 and 1).

## Outcomes and decision rules
These are read from the scorer's final DRC (`evals/*.drc.json.gz` and the score), on boards where both arms
finished every attempt.
- **Primary:** open connections on bracketed nets, meaning unconnected items whose net (by `item_nets`) contains
  "[" or "]". Sum over the two attempts per board. **P fixes it** when the pooled total under P is lower than
  under C and a one-sided sign test over boards that differ gives p < 0.05.
- **Guards** (both must hold to adopt): total open connections pooled under P are at most 1.03 x C's; DRC errors
  pooled under P are at most 1.03 x C's (the A/A spread is about 3.4 %); and no error type rises by more than
  10 % pooled where C has at least 20 of it.
- **Undecided** (the primary falls short of p < 0.05 but its direction favours P): report it, keep the parser
  anyway if the guards hold, since it is a parse fix with no tuning. Extend with a third attempt only if a guard
  is borderline.
- **Verdict against P:** a guard fails beyond noise. Then find which site caused it before deciding anything.

Expected cost: 49 boards x 2 arms x 2 attempts x about 15-40 min wall (counted 900 s) is about 50-130 CPU-h at
1-2 CPUs per job. Profile one smoke board per arm first (py-spy on the python process).
