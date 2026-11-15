<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hot-loop choose-better: plan

Follow-up of the hot-loop A/B (`hotloop-ab`, code b8703501; its plan is on route-finish-ab). There, the keep-out
(K) helped some cells (bq25306 L 0.67x N, librewave U703 0.57x, robosub, kestrel, govish, qubik) and hurt others
(arvsom's three bucks L up to 2.8x, R up to 5.7x; the sstv badge boost 2.2x; the esp32 flight controller 1.37x;
gecko5 U13 R 1.73x) and cost completion (0.950 -> 0.930). Registration: [`../hotloop-choose.sh`](../hotloop-choose.sh).

## Why K lost (diagnosis)

1. **The keep-outs ban the loop's own vias under the cell.** A keep-out is a zone of one net and a via crosses every
   layer, so the GND plane's keep-out bans the rail's vias and a rail pour's keep-out bans the ground vias. K left no
   loop-net via within 1 mm of the cell hull on arvsom (6 cells), the sstv boost and gecko5 U13, where N had 2-7 per
   cell; the vias moved out onto thin surface stubs (arvsom U4 rail hop 6.0 -> 15.2 mm).
2. **The pour keep-out's bridge on a 2-layer board** (esp32: the F.Cu GND bridge from U6 to C16 lies across the
   switch node's and VIN's paths): the SW pins needed lifted corridors and VIN went round (54 mm against N's 39).

## Arms

| arm | what |
|---|---|
| C | N and K side by side in one portfolio (`restart.py --alt-env KAE_HOTLOOP_KEEPOUT=1 --tiebreak`): odd attempts with K's keep-out, each arm resumes its own best; KiCad's rank first, `kae.excite.cellquote`'s score among equal ranks (margin 0.1); a clean board lets the other arm's running attempts finish |
| KV | K with `KAE_HOTLOOP_KEEPOUT_LOOPVIAS=1`: four via-sized holes beside each loop terminal of another loop net |
| CV | as C with KV as arm B |

N and K are hotloop-ab's runs. Boards (11): the four K lost on, the six it won on, and nekoink.

## Measures and criteria

Routing: cp1, cpk, completion, DRC errors per board and by type against N. Physics: the evaluator with the
truncation fix (hotloop-eval 077dd4f5), `--scope losses`, per cell L_loop and R_loop against N and K.
- **C should get K's gains and avoid its losses:** per cell, C not worse than the better of N and K by more than
  10 % on the boards where both are complete; completion not below N's.
- **KV:** cells better than K on arvsom, sstv and gecko5 U13; completion not below K's.
- The quote's own ranking quality is measured on hotloop-ab's boards (N, K, Kp, human) against the evaluator.
