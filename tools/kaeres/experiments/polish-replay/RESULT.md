<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# polish-replay: result (2026-11-16)

Experiment `polish-replay2` (150 jobs, all ok), analysed against `PLAN.md` with `analyze.py`. The plan's
primary is a single pass on a stored board, so there are no seeds to pair; it is paired by board (copy vs
polish on the same kept board), as pre-registered.

**Analysis fix before reading the effect:** `analyze.py` put every row whose method name lacked "copy" into the
polish arm, which included the human reference rows of `results.csv`. It now takes the two arms by name. The
plan and the rule are unchanged.

## Primary (73 boards with a polish board; pre-registered keep rule)
| | copy (R's kept board) | polish, kept by restart.py's rule |
|---|---|---|
| open connections | 1,594 | 1,428 (-10.4 %) |
| per-board geometric mean | | **0.906 [0.866, 0.941]** (bootstrap 95 %) |
| boards better / worse | | 34 / 0 (38 unchanged; the rule rejected 2 polish boards) |
| DRC errors | 3,062 | 3,058 (raw polish 3,068) |
| polish CPU | | 13.8 h |

- **Power:** per-board SD 0.183, so the 80 %-power MDE is 5.8 %. The plan assumed SD 0.25 and an MDE of 8 %.
- **Intent to treat:** two of the 75 boards (arvsom and sdi-mipi) wrote no polish board, so R's board stays.
  Counting them as unchanged gives a geometric mean of about 0.908.
- **R's k = 3 contribution on these boards:** none. k = 3 was a fresh attempt on all 74 boards that have one,
  and it was never better than the board kept without it. One k = 3 attempt was killed (rc -9).
- **Verdict: gain, -9.4 % [-13.4 %, -5.9 %].** That is more than k = 3 delivered (0), so by the plan's rule
  P-k3 goes to a confirmatory A/B.

## By size (post hoc)
| pads | n | opens copy -> kept | gm |
|---|---|---|---|
| <= 400 | 48 | 501 -> 470 | 0.912 |
| 400-1,000 | 21 | 567 -> 526 | 0.908 |
| > 1,000 | 4 | 526 -> 432 | 0.827 |

## Where the gain comes from (adapter logs)
`kae.joint.cli run --start` begins with iteration 0, a full bridge pass (Freerouting, repair rounds and last
mile) on the start board. Only then come the windows and the finish.

| stage | opens (kae's count) | share of the gain |
|---|---|---|
| R's kept board | 1,594 | |
| after iteration 0 (bridge pass on the kept board) | 1,472 | 73 % |
| after windows, last mile and finish | 1,428 | 27 % |

So most of what is called "the polish" is one more bridge pass, resumed from the kept board. Examples:
zotino 132 -> 98 -> 87, usbarmory 157 -> 130 -> 130, nekoink-2 161 -> 141. The windows and finish added gains on
13 boards: kestrel 13 -> 8, undercontrol 29 -> 22, vspeed 15 -> 10, tpa2012 6 -> 2.

R's own k = 3 is a fresh attempt at about 11 % of the allowance, which is too short to beat its earlier
attempts. Spent on the kept board instead, the same slot gains about 10 %.

## Boards that got worse or failed
- **marksard rhymestone:** raw polish 39 -> 40 opens, errors 213 -> 222 (mask bridges +8). The keep rule
  rejected it.
- **bestelampe:** 6 -> 6 opens, errors +1 (`starved_thermal`). Rejected.
- **arvsom and sdi-mipi, no output:** iteration 0's Freerouting ran 4,076 s and 2,733 s, past the method's
  4x wall ceiling. Work mode does not charge Freerouting's time: the known calibration gap that fork #11 and
  kae #97 close. With restart.py the kept board would have stood.

## What would change the verdict, and next
- **Confirmatory test:** R vs P-k3 on fresh boards and the new pin (abefc74 with #97).
- **Third arm:** a resumed `kae.route.cli route @BEST@` in the k = 3 slot. That isolates iteration 0 from the
  windows (27 % of the gain here), so P-k3's windows are kept only if they pay beyond a plain resume.
- An effect below 5.8 % would not have been visible here. The gain is concentrated on the 4 boards over
  1,000 pads, and 2 more such boards failed, so the big-board estimate rests on 4 boards.
