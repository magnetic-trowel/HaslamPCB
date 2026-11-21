<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# chan-gated-m6: channel term (place_w_chan 3) on boards with >= 20 movable-pair overlaps (2026-11-21)

Experiment `chan-gated-m6` (branch `chan-gated-m6`, kae and harness a18d6c6d on main 6d726340, Freerouting fork 37b1a8b,
counted work). Two arms: control 25339b559703, chan3 f58828799b68. Seeds 0-2, one placement and one route. 66 boards
finished with every arm-seed (86 gated at >= 20 overlaps; 20 parked by the 2026-11-20 trim, TRIM-2026-11-20.json).
Scripts: `/var/tmp/$USER/chan-gated/m6/{collect,analyse}.py`, output `analyse.out`, per-board table `perboard.json`.

## Primary (pre-registered)
| measure | chan3 vs control |
|---|---|
| per-board mean Δlog1p(opens), seeds averaged | **-4.3 %** (95 % CI -8.8 to +0.7), sign-flip p 0.09, lower/higher 39/22 boards |
| per-attempt, paired by seed (board-cluster bootstrap) | -4.3 % (CI -8.9 to +0.7), lower/higher 100/66 attempts |
| ratio of summed opens | 4,938 -> 4,796 = 0.971 (CI 0.936-1.007) |
| power | SD(Δ) 0.207, MDE80 7.4 % at n 66; within-arm seed SD 0.27 |

**Verdict: undecided, leaning gain.** The point estimate is about half the earlier subgroup's -12 % (winner's curse,
as expected). No canary run, since the gain is not decided.

## Mechanism
The term does what it aims at: the final movable-pair overlapping pairs fall from 7,551 to 191 in total. chan3 is
lower in 198 of 198 paired attempts.

## Guards and secondary
- **DRC errors:** 7,252 -> 7,882 (+8.7 %, board bootstrap CI -4 % to +25 %; 16 boards up, 10 down). Not a decided
  failure, but the rise is concentrated in three boards. particle-iot xenon alone adds shorting_items +195,
  solder_mask_bridge +156 and clearance +154; adafruit qt-py-esp32-c3 and itsybitsy-rp2040 add about 40-70 each.
  - shorting_items 489 -> 742 (5 boards up, 3 down); solder_mask_bridge 2,104 -> 2,340; clearance 1,574 -> 1,733.
  - courtyards_overlap 47 -> 65 (doorman +15).
  - pth_inside_courtyard 54 -> 15.
  - Other types are flat.
  - The three boards are also among chan3's worst for opens (qt-py +0.13, itsybitsy +0.15). The halo spreads dense
    MCU boards into each other's pads, and the router then shorts.
- **Legality and completion:** legal runs 71 vs 70 of 198; clean 11 vs 9; completion 0.775 vs 0.781.
- **Wirelength:** wirelength per routed connection +2.9 %; total wirelength +3.3 %.
- **Near-miss closure** (13 boards with control mean <= 5 opens): 44 -> 53 opens. That is worse, with small counts
  (dragonlock k66f, candykingdom firefly2, electrooptical cap-multiplier).
- **Board by board:**
  - Gains: doorman 1/5/10 -> 0/3/4; bioamp 6/7/6 -> 3/5/2; twig sensor 20/17/16 -> 10/10/9; snappergps; hackquad;
    moco.
  - Losses: cap-multiplier, firefly2, k66f (near-clean boards: noise level); tigard; groundstudio carbon; cosmos
    keyboard; itsybitsy; qt-py.
  - No feature explanation was tested beyond the DRC concentration above.

## Next
- **The pre-registered extension is triggered:** the CI includes 0 and the gain (4.3 %) exceeds half the MDE (3.7 %),
  so the plan adds seeds 3-5 for both arms. It is not submitted.
  - On the 57 boards under the 0.5 CPU-h per attempt cap it costs about 96 CPU-h (method CPU 125 CPU-h for this run).
  - That is over the 40 CPU-h sprint cap, so it needs the user's call. The 9 boards over the cap would drop.
- **2x2 with xing: not worth it under the sprint rules.**
  - 2 arms x 3 seeds on the 57 cap boards is about 96 CPU-h.
  - At k = 1 (32 CPU-h) its MDE is about 13 %, far above the 4 % effect it would have to separate.
  - Run it only if the chan3 extension decides a gain.
