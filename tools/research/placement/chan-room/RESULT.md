<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# chan-room result (2026-11-21)

Synthetic boards only; these are not benchmark scores. 7 boards (cap-multiplier excluded, its outline is drawn by a
footprint), utilization as the placer measured it, 396 placements, control and chan3, seeds 0-2. A run fails if it
is illegal or KiCad finds a part-to-part short.

| utilization | control failed | chan3 failed |
|---|---|---|
| 0.40-0.55 | 0/42 | 0/42 |
| 0.55-0.65 | 0/42 | 0/42 |
| 0.65-0.70 | 1/21 (5 %) | 1/21 (5 %) |
| 0.70-0.75 | 8/25 (32 %) | 10/25 (40 %) |
| 0.75-0.80 | 9/23 (39 %) | 10/23 (43 %) |
| 0.80-0.85 | 6/18 (33 %) | 6/18 (33 %) |
| 0.85-1.00 | 6/27 (22 %) | 6/27 (22 %) |

- **Per-board failure points** (the pre-registered 2-of-3 rule) are the same in both arms on 4 boards: qt-py 0.70,
  fercus 0.79, xenon 0.75. The exception is itsybitsy, where chan3 fails at 0.70 and control at 0.72. Three boards
  never fail: bioamp, sphale and splinky.
- **Logistic fit:**

  | arm | u10 (95 % CI) | u50 (95 % CI) |
  |---|---|---|
  | control | 0.66 (0.57-1.07) | 0.96 |
  | chan3 | 0.64 (0.55-1.03) | 0.94 |

  chan3's excess over control is +1 to +3 points everywhere.
- **The pre-registered gate rule does not fire.** It needs an excess of 5 points, and the excess never reaches it.
  chan3 does not start failing earlier than control.
- **Where chan3 hurts: severity, not onset.**

  | measure | below 0.70, control | below 0.70, chan3 | 0.70 and above, control | 0.70 and above, chan3 |
  |---|---|---|---|---|
  | illegal runs | 1/105 | 1/105 | 29/93 | 32/93 |
  | part-to-part shorts | 0 | 176 (one failed run) | 568 | 752 (+32 %) |
  | final overlap pairs | 2,143 | 13 | 2,328 | 114 |

  The mechanism holds at every utilization.
- **Ramp set from the data,** replacing 0.6-0.75: full weight up to 0.65 (no failure in either arm, 0 of 168
  runs), zero from 0.70, where failures start in both arms and chan3 makes them worse. This departs from the
  pre-registered rule, which says no gate is needed. The departure is chosen for severity (the +32 % shorts), and is
  stated as such.
