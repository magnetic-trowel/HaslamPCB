<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# barrier-fit2-smoke and profile (2026-11-14, before the full run)

Arms at ef6cc04: C `96686b7aab11`, F `4e02f0d5d923` (`--set barrier_split=2`). Both arms run the same frozen commit;
main's later default changes (#74, #75, #77) are in neither arm, so the comparison isolates `barrier_split=2`.

| Board (ab2 board, not in the test) | C opens / legal | F opens / legal | DRC C -> F |
|---|---|---|---|
| len42-synth-audiout | 17 / yes | 29 / yes | 0 -> 0 |
| niektb-sluisbrinkie andes-10hp | 29 / yes | 2 / yes | 14 -> 14 (drill_out_of_range, input) |
| gregification-beems-mini-orion-tem | 65 / no | 47 / no | 40 -> 41 (+1 starved_thermal) |

All 6 runs ok, no ceiling hit (work mode, 9 attempts each); wall 0.9-4.6 ks against nominal 1.1-1.9 ks on a loaded
host. One bug record: the +1 starved_thermal above the human (report-only). Three boards decide nothing.

Fit check, placement only, F's code on 66 ab2 boards (`barrier_split=2`, work mode, 100 s): split applied on 63,
skipped as unfit on 3; placement legal on 65 (the other, neggles-cfxsx, is illegal in the control too); all 10 moved
boards legal (4 of 9 under `barrier_split=1`). Probes 2-61 s.

Profile (len42 audiout, one `haslam.joint.cli` attempt at 373 s nominal, py-spy, JFR): C 594 s sampled: Freerouting wait
45 %, last mile 22 %, numba compile 16 % (cold: the profile started before the warm job finished; the cache now holds
112 entries; compile is not charged as work), placement 6 %, CP-SAT 3 %, KiCad DRC 2 %. F 649 s: Freerouting 53 %,
last mile 19 %, placement 11 % (fit probes and region placement), CP-SAT 6 %, compile 5 %. Freerouting (JFR):
PriorityQueue.siftUp, ShapeSearchTree45Degree.completeShapeUnlocked, MinAreaTree overlaps: inside the router, no
cheap fix here. No speedup changed. Job size: haslamq peaks 4.4-7.4 GB on 4 CPUs, inside haslamres' 8.1-8.5 GB grants.
