# fr-neck-gated-ab6: neck-down on dense fine-pitch boards (2026-11-20)

Experiment `fr-neck-gated-ab6`: kae and harness 51e40a7 (branch `fr-neck-gated-m6`), Freerouting fork 37b1a8b, counted
work. Arms `frn2 control` and `frn2 neck` (`--neckdown`). 25 boards were scored in both arms. The other 25 were parked
by the 2026-11-20 trim (`TRIM-2026-11-20.json`, boards over 0.5 CPU-h per method run) and are not resubmitted.
Analysis: the plan's `analyze.py` plus the class, near-miss and wall-time checks below. Read-only.

## Primary (pre-registered): opens per attempt, paired by seed
| set | boards | gm [95 % bootstrap] | lower / higher | SD | MDE (80 %) |
|---|---|---|---|---|---|
| all kept | 25 | **1.019 [0.971, 1.091]** | 9 / 11 | 0.159 | 9.3 % |
| without squantor nuclone (outlier: 6 pairs of near-zero opens, +0.72) | 24 | 0.989 [0.964, 1.013] | 9 / 10 | | |
| >= 1,000 pads | 6 | 0.995 [0.968, 1.015] | | | |
| < 1,000 pads | 19 | 1.026 [0.963, 1.125] | | | |

Sign-flip p = 0.79. Two things leave this test underpowered:
- the per-board SD is 0.159, against the 0.06-0.074 the plan assumed;
- the trim halved n, from the planned 50 to 25.

The MDE is therefore 9.3 %, not 2.9 %.

## Guards
- **Delivered opens:** 1,302 -> 1,367, gm 1.091 [1.010, 1.209], 4 boards lower and 9 higher. The CI excludes 1 on
  the worse side.
  - The largest moves don't match the attempt level. arduino-asx00031 went 193 -> 222 delivered while its
    attempts were 6.9 % better. cameranexus went 195 -> 218 with attempts unchanged (+0.6 %).
  - mikegoelzer ecp5-sbc went 8 -> 22, with attempts +5 %.
  - So most of the delivered gap is the restart-lottery noise the plan warned of, not the setting. I still record it
    as a guard that did not hold, not a pass.
- **DRC errors:** 2,215 -> 2,222 (+0.3 %, inside the 3.4 % A/A spread). The only type change above 2 is
  `starved_thermal` 4 -> 10 (below 30). No change in `track_width` or clearance.
- **Plane-net vs signal-net opens** (KiCad's listed items): plane 195 -> 185, signal 1,107 -> 1,182.
- **CPU:** 46.8 h -> 46.4 h.
- **Wall vs charged:** median wall/budget 1.19 (control) and 1.07 (neck), max 2.75; no `ceiling_hit`.
- **Manipulation check:** the neck arm's Freerouting calls have `automatic_neckdown` true and the control's false.
  cameranexus's rules set a 100 µm neck width, so the automatic width does not apply there.

## Near-miss closure (boards within 5 opens of clean), reported separately
7 boards:
- clean in both arms: battoota, glaubinator, noctalabs, squantor, valar;
- abx00080: 1 -> 1;
- lil-soundie: 0 -> 1.

Neck-down closed none and lost one.

## Board by board
The result is mixed (9 lower, 11 higher).
- **Gains:** thingino teacup (-19 %), metro-rp2040 (-14 %), arduino-asx00031 (-6.9 %), battoota and openvault
  (-7 to -9 % per attempt, both clean delivered). Pad tags of the gainers vs losers were not read here.
- **Losses:** squantor (+0.72 on near-zero counts), lil-soundie (+7.9 %), abx00080, mikegoelzer, gpio-block
  (+4.7 %). Small 2-4 layer boards.
- That echoes fr-settings-ab's split: necks help where escapes are blocked and cost a little where they are not. But
  the class CIs here all include 1.

## Verdict
- **Undecided.** The attempt-level effect is +1.9 % [-2.9 %, +9.1 %] over all kept boards, -1.1 % [-3.6 %, +1.3 %]
  without the outlier; the MDE is 9.3 %.
- The pre-registered extension needs a point estimate at least 1 % lower. The pooled estimate is higher, so no
  extension. Without the outlier it qualifies, but that is post hoc.
- Not a decided gain, so no canary and no PR.
- **What would decide it:** about 100 boards at this SD for a 4.5 % MDE, under the 2026-11-20 rules (sprint suites,
  0.5 CPU-h per attempt cap). That makes it a mechanism-suite question (fine-pitch escapes), not this board list.
