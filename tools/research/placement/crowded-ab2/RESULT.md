<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# crowded-ab2: gated edge headers plus unfit parts, placement only (2026-11-22)

Plan ff201a83 (`tools/research/placement/crowded-ab2/PLAN.md`). kae 66aaa596 on main 1cdbf617 (with #134).
Counted work, fresh seeds 8-10. Data: `/var/tmp/$USER/crowded-ab2/out`. Output: `analyse.out`.

**Control twin:** identical poses on 79 of 79 board-seeds.

| stratum | control legal | gated legal | Δ legal (95 % CI) | placement errors other than edge clearance | part-to-part shorts | HPWL, geometric mean |
|---|---|---|---|---|---|---|
| failing (21) | 2 | 5 | +3 [0, +9] | 443 -> 369 | 206 -> 166 | 0.991 |
| crowded (20) | 19 | 19 | 0 | 57 -> 57 | 11 -> 11 | 1.000 (identical) |
| headers (38) | 29 | 31 | +2 [0, +6] | 278 -> 369 (+91 [0, +211]) | 38 -> 126 (+88 [0, +204]) | 1.003 |

- **Failing boards:** the gain is itsybitsy alone (3 of 3 seeds). qt-py, xenon and the passive-crowded boards do not
  move. In crowded-ab, where pinning was ungated, qt-py had flipped 3 of 3 and xenon 1. Here the gate leaves
  xenon's HEAD2 free, and qt-py still stacks neighbours against its pinned rows.
- **Header stratum:**
  - The keyboard-MCU case (ferro-dactyl) and avi1861 are untouched, as the gate intends.
  - Shorts rise on bkw777-teeprom (+24 on each seed), qt-py-esp32-s2 (+6) and uzsito (+10 to +18), which turns
    legal by kae's own check yet has more DRC shorts.
  - HPWL rises on rp2040-large (1.53x) and feather-32u4 (1.1x).

**Verdict: it does not hold.** The primary CI includes 0, and the shorts guard on the header stratum sits at its
harm edge (CI [0, +204]). Per the plan, neither the routed sprint check nor the canary was submitted.

**What would help next:**
- Look at why pinned rows still get stacked neighbours (qt-py, teeprom): the pinned part becomes fixed, but its
  pads at the edge may clash with parts already counted as legal.
- Look at why HEAD2 on xenon has a grid spot that is not on the edge.
- The only robust result is ItsyBitsy-type boards, where pinning lifts legality from 0 to 3 of 3.
