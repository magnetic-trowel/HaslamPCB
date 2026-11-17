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

## Addendum 2026-11-17, before any run on the new build: current components
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own.
- **Code.** `simp-drc-parse` is rebased onto main c81770e1 as `simp-drc-parse-m2` (no conflict; the original branch is
  left as it was). `simp-drc-items` is in main, so C is the bridge at main c81770e1 and P the bridge at 24b9ed0a (was
  d19411e5: the same three parser commits). Harness c81770e1. The touched sites' tests pass on the rebased branch.
- **Freerouting:** the pinned fork 9a5512d, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work, `--time
  900`, wall timeout 3,600 s as before.
- **New experiment `drc-parse-ab-m`** (owner `exp-drc-parse-ab-m`), new method ids, each board's job running both arms
  side by side as this plan says (the first submission had split them by arm). The runs of `drc-parse-ab` (old build, 36
  jobs done) are excluded from the decision; its queued jobs are cancelled.
- The 49 boards were chosen from the old pinned fork's outputs (open bracketed nets); kept as they are, since the parser
  sites are reached on any board whose open nets carry brackets. Arms, k = 2, outcomes and decision rules unchanged.
- **Still worth running:** the parser change is not in main; this is its guard before a PR, about 60 CPU-h.

## Addendum 2026-11-17 (m3), before any run on this build: main 22ff779a and Freerouting f1c41d3
Main (kae #105) and the pin moved after `drc-parse-ab-m` was submitted: the fork now counts the optimizer's search steps and
pour fills inside `autorouter.max_work`, and kae stops charging optimizer passes on top of that and sets the new
weights. Checked before deciding: on a small board where no budget binds the bridge's copper came out item for item
the same on both builds, but the charged clock did not (53.3 s against 39.1 s). Its arms run the bridge under counted work on boards where the repair and last-mile budgets bind (open nets, hard boards), and those budgets follow the charged clock. So its outputs change
on the new build.
- Migrated: branch `simp-drc-parse-m3` (rebased on main 22ff779a, no conflict; the -m2 branch is left as it
  was). Arms: C = bridge at main 22ff779a, P = bridge at 4676027d; harness 22ff779a. Freerouting fork f1c41d3, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- New experiment `drc-parse-ab-m3` (owner `exp-drc-parse-ab-m3`), new method ids. The runs of `drc-parse-ab-m` (9 jobs done) are on the
  previous build and excluded from the decision; its jobs are cancelled.
- Boards, arms, attempts, primary, guards, looks and the earlier trims unchanged.
- 2026-11-17 (main 9e54baed, #106 + #108): kept as registered. #108 changes only kae.joint.scorecard.accept, which the joint loop calls for windows, the finishing stage and its last-mile close; these arms never reach it (staged chassis `--max-iters 0` has no finishing stage, or bridge/placement only), the module stage's re-laid-copper guard keeps the old rule unchanged (physics_guard), and restart.py's judge returns the same key. #106 is harness-only.

## Addendum 2026-11-17 (trim)
Approved by the user 2026-11-17 after the analysis of finished rows from older builds (explore-2611 results); written before any result of this build is read. Eight boards are dropped: identical copper on every pair in every build where they ran, or no output in both arms: adafruit pybadge (no open bracketed net), adafruit pygamer, adafruit rp2040 prop-maker feather, adafruit fruit-jam, owon-lilliput scopefun v2, groupgets kimchi-micro, oro-os link, antmicro artix-dc-scm. `drc-parse-ab-m3` continues on the other 41 boards at k = 2; primary, guards and decision rules unchanged. Boards like alphaonex86 socket7 (many open bus nets, a large last-mile backlog) are read apart. If its last-mile regression recurs, the verdict is "fix last-mile ordering, then keep the parser", not a rejection of the parser.
