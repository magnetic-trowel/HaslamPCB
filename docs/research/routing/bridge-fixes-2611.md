<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Two bridge rule fixes, each tested alone (2026-11-14)

Scope: whether the bridge should, by default, give Freerouting's widened session widths back, and keep net classes
off layers a custom rule disallows. Each fix is tested alone against main. Not here: why they were found ->
[diffpair-fixes-2611](diffpair-fixes-2611.md) (branch `diffpair-ab4`); the bridge itself ->
[kae-freerouting-bridge](kae-freerouting-bridge.md).
Keys: bridge-fixes-ab, bridge-ses-width, bridge-disallow-layers, track_width, items_not_allowed, use_layer, session
units, disallow track, rip errors

**Status:** pre-registered (`tools/kaeres/experiments/bridge-fixes-ab/PLAN.md`), smoke done, full run queued
2026-11-14 (`bridge-fixes-mech`, `bridge-fixes-odd`). Verdict pending.

## Mechanisms
1. **Session widths (W).** Freerouting keeps a trace's half width in whole session units (0.1 um). A class width of an
   odd number of units comes back one unit wider: 0.1521 mm is returned as 0.1522 mm. This breaks the board's rule
   only where the rule's max equals the width, as in controlled-impedance rules with min = opt = max.
2. **Disallowed layers (L).** `(constraint disallow track)` with a net, class or layer condition was not read, so
   Freerouting routed those classes on forbidden layers. The fix splits classes by the layers they are kept off and
   writes `(circuit (use_layer ...))`.

## Where the mechanisms exist
A text scan of the 268 usable boards whose class widths are an odd number of units (`select_boards.py`) found that
on 35 of the 47 boards with an earlier bridge run, wires came back at exactly class width + 0.1 um. Only 4 boards have
a rule that this breaks: thunderscope rev5-3 and three ducktop2 boards. Disallow-track rules exist on 10 boards: 7
condition on nets, classes or layers, and 3 only on areas, where L does nothing. Elsewhere, L's DSN is byte-identical
to main's apart from the header path (checked on 5 boards).

## Smoke (ducktop2 right_io, 1 attempt)
| arm | round 0 track_width | round 0 items_not_allowed | final opens | final errors |
|---|---|---|---|---|
| C (main) | 78 | 44 | 133 | 0 (last mile ripped them) |
| W | 0 | 52 | 85 | 68 (59 items_not_allowed) |
| L | 88 | 0 | 102 | 49 (44 track_width) |

Each fix removes its own error type at the first route. On these boards, each arm still has the other fix's bug.
When time allows, the bridge's last mile rips erroring items, so a bug's errors can end up as opens. The primaries are
therefore read at repair round 0 and on the final board. The end-to-end guard is defects (opens + errors). On tigard,
which has odd widths but no binding rule, all three arms gave the same board result.

## Results
**bridge-fixes-odd (2026-11-15, 83 of 85 boards, k = 2, W vs C):** W gave widths back on 95 of 154 runs. Both arms
had 0 track_width errors, because no binding rule is in this set. Guards, as geometric-mean ratio W/C [95 % CI]:
- opens 1.001 [0.969, 1.034], totals -0.3 %;
- other errors 1.002 [0.990, 1.012], +0.6 %;
- defects 1.006 [0.992, 1.020], -0.1 %;
- cp1 4 vs 4, cpk 5 vs 5, completion 0.849 vs 0.849.

All are under the +5 % margin, so the guard passes without the extension. Per-type errors are the same within a
few counts. This shows W is harmless where it acts without a binding rule. It cannot show the primary (errors
removed); that needs `bridge-fixes-mech`, still running (8 of 14 jobs retried at a 10 h timeout).
