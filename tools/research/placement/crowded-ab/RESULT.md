<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# crowded-ab: placer helps for crowded boards, placement only (2026-11-21)

Plan: `tools/research/placement/crowded-ab/PLAN.md` (branch `crowded-fixes`, kae ce093dc4 on main c8807505).
- Counted work, fresh seeds 5-7. 36 boards, 79 board-seeds, six arms, all complete, no crashes.
- Data: `/var/tmp/$USER/crowded-ab/out`. Script: `scripts/analyse.py`. Output: `analyse.out`.

**Control twin:** identical poses on 79 of 79 board-seeds. Each placement runs in a fresh process, and there is no
nondeterminism here.

## Failing boards (7 boards, 21 board-seeds): the primary
| arm | legal | Δ legal vs control (95 % CI) | placement errors other than edge clearance | part-to-part shorts | HPWL, geometric mean ratio |
|---|---|---|---|---|---|
| control | 1/21 | - | 513 | 306 | 1.000 |
| headers | 8/21 | **+7 [+1, +14]** | 354 | 122 | 0.974 |
| unfit | 4/21 | +3 [0, +9] | 536 | 322 | 0.996 |
| fine | 3/21 | +2 [0, +6] | 372 | 136 | 1.038 |
| all | 9/21 | **+8 [+2, +15]** | 295 | 110 | 0.989 |

Board flips:
- headers: itsybitsy 3, qt-py 3, xenon 1;
- unfit: itsybitsy 3;
- fine: olimex-lora 2;
- all: itsybitsy 3, xenon 3, lora 2.
fercus and doorman do not move in any arm.

## Do no harm
- **Crowded boards** (10 boards, 20 board-seeds): every arm is 20/20 legal except fine (19/20; feather-rp2040-rfm
  loses one). headers and all add 4 placement errors and 2 shorts. HPWL is +1.7 % (headers) and +3.4 % (all).
- **Header boards** (19 boards, 38 board-seeds; the detector fires on all of them):
  - unfit and fine are unchanged: legal 28/38, and fine's poses are identical.
  - headers and all are legal on 32/38 boards, against 28/38 for control. But HPWL rises 10-12 % (geometric mean),
    and shorts rise by 54-61 (CI -80 to +205).
  - The detector also fires on parts that are not edge headers: a keyboard MCU row (ferro-dactyl, HPWL 2.45x), DIP
    and dev-board rows (avi1861 1.7-2.0x, rp2040-large 1.5x, eurorack, ft232h).
  - Pinning a row that fits anywhere costs wire for nothing.

## Verdict
- **headers: gain where it is needed, harm where it is not.** Not a default. It needs a gate: pin only when the
  detected part does not fit (`fits` False), or when the board's utilization is at least 0.7. Two parallel rows on
  opposite sides would tighten the detector further.
- **unfit:** safe (no change on 58 do-no-harm board-seeds). Its gain is small and undecided: +3 [0, +9], all on one
  board.
- **fine:** undecided. It helps lora, loses one feather run, and adds 3.8 % HPWL on the failing boards.
- **No fix is a decided gain with no harm, so none is proposed on by default yet.** A routed check and a canary
  are premature.

## Next (proposed)
- Rebuild on current main (kae #134, place-clock-frame).
- Add the gate to headers.
- Rerun placement only: control, gated headers, and gated headers plus unfit plus fine. Same boards, fresh seeds,
  about 15 CPU-h.
- If gated headers keeps about +7 legal on the failing boards with no HPWL rise on the header stratum, run the
  routed sprint check: the failing and crowded strata, k = 2, control and the chosen arm, joint chassis, about
  15-20 CPU-h. Then the weekly canary.
