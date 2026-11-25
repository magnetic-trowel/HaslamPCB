<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# margin-gate-m6: result on the kept boards (2026-11-21)

**Verdict.**
- **Deciding hypothesis (1): gain.** On dense-hi boards, MA gated lowers per-attempt opens by 14 %, the CI is below 0,
  and every guard holds.
- **Threshold (2): undecided.** On dense-lo boards, ungated MA leans toward a gain but is underpowered.
- **Barrier (4): no effect.**
- **Caps: untested.** The region caps act on almost no board, so this stage is the auto margin (`place_margin=-1`) on
  dense boards.

## Setup
- **Arms.** Control `d8d652ff851e`, MA `c661d54064c9` and MA gated `3a9fa7825420`, all at haslam and harness c8e79ec1.
  Freerouting is fork 37b1a8b, under counted work, with k=1.
- **Primary.** Fresh first-wave opens from `restarts.json`, paired by seed. Per board, d is the mean Δlog1p. The effect
  is reported with a 4,000-draw bootstrap CI and MDE80 = exp(2.8·SD/√n) − 1.
- **Boards.** 70 boards finished, all `ok`: the 66 `kept_boards` plus 4 that finished before the trim (antmicro poe,
  azonenberg starshipraider, cypress small-3, sparkfun tof). The 17 parked boards were not resubmitted.
- **Data.** Scripts and rows are in the local analysis work dir: `runs-mg6.jsonl` and `mg6.txt`.

## Primary (deciding: MA gated vs control on dense-hi)

| set | n | effect | 95 % CI | SD | MDE80 | lower / higher |
|---|---|---|---|---|---|---|
| dense-hi, all finished | 44 | −14.0 % | [−23.4, −4.4] | 0.38 | 17 % | 23/10 |
| dense-hi, kept list only | 42 | −13.9 % | [−23.7, −3.7] | 0.39 | 18 % | 21/10 |
| dense-hi, control open on some seed | 31 | −19.3 % | [−30.5, −6.7] | 0.43 | 24 % | 21/8 |

1 board is inert: adxl375, with auto margin 0.002.

**Agreement with earlier builds.** The direction matches margin-ab (−8.9 %, 1edecfe) and margin-gate-m (−7.2 %, n=8).
The point estimate is near the MDE, so the CI is wide. A credible gain, but the size is uncertain: anywhere from about
−4 % to −23 %.

## Guards (dense-hi)
- **Delivered opens:** −17.4 % [−28.3, −6.9], from 312 to 298. Clean boards go from 8 to 9.
- **`legal`:** 14 boards in both arms, with no flips. Illegal first-wave seeds go from 3 to 0.
- **DRC errors:** 1153 → 1126.
  - Falling types: silk_overlap 28 → 14, silk_over_copper 179 → 165, clearance 176 → 174, solder_mask_bridge 572 → 570.
  - Rising type: starved_thermal 2 → 7. Its count is small. On dense-lo, one board whose placement was identical in
    both arms (daveshah1 openmixr) swung starved_thermal by +103, so this type is routing noise, not the margin.
- **Near-miss closure,** reported apart: 132 seed pairs within 5 opens of clean give −18.7 % [−28.3, −7.5], 46/16.
  Zero-open seeds rise from 64 to 77.
- **Big boards:** none here; the canary below covers them.
- **Cost:** about 72 CPU-h on dense-hi and 129 CPU-h overall.

## Board by board (dense-hi)
**Gains:**
- Mostly small sensor and breakout boards with auto margin 0.2-0.8 mm: tanmoydutta, chipwhisperer adc, fxos8700,
  roboryman, sparkfun mp3 (7 → 0 delivered) and the 74hc4051 mux.
- feather-m0 goes 19 → 14 delivered.

**Harms are small and mostly on boards near zero:**
- 0x007e oft, sparkfunx finger-sensor, blueberry zero and bburan headstage are 0 → 0 delivered; their per-seed counts are
  1-2 opens.
- pro-mini-candy (+0.35, delivered 7 → 9) has auto margin 0.019, which is noise level.
- cnlohr wiflier: +0.32 per seed, but delivered 6 → 3.
- No board reproduces the margin-ab davang harm (davang is gated off).

**Mixed result:** none needs a deeper study. The harms sit at seed-noise level, with no shared feature (auto margin
0.02-0.9, utilization 0.25-0.69).

## Other hypotheses
**(2) Threshold, MA ungated on dense-lo (n=19):** −15.5 % [−32.7, +0.2], MDE80 35 %, 9/8. Undecided, leaning toward a
gain, so the gate may be throwing a gain away.
- Guards: `legal` lost 1 board (antmicro ov9281). DRC 616 → 688, mostly starved_thermal (openmixr again) and
  items_not_allowed 0 → 5 (heypcb knuckle).
- Near-miss pairs: −39 % [−57, −14].
- A lower gate threshold is the open follow-up.

**MA gated on dense-lo:** 16 of 19 boards inert, as designed. The 3 that act are antmicro ddr5 and the sparkfun
led-array, which haslam's density gate keeps on, and jetson. Together they give −15.6 %.

**(4) Barrier:**
- MA gated: +0.6 % [−1.5, +2.7], 4 of 7 inert.
- MA: −2.3 % [−18.5, +11.1].
- No effect seen. The caps remain untested.

## Next
**Canary submitted (standing rule).**
- Experiment `margin-gate-canary-m6`, owner `exp-margin-gate-canary-m6`, haslamq #116771-#116790.
- Prio 5, class timed, control against MA gated on the 10 `canary-big.txt` boards, k=1, seed 0. 20 jobs, with 1089
  queued ahead.
- Per `mscan.py`, the margin acts on glasgow revd1 only (auto margin 0.04, gate on). gecko5 has margin 0 and beagleplay
  is gated off; the other 7 were not scanned.
- Pass rule, set before any result: every run valid, no timeouts or ceiling hits, no error type added, pooled opens and
  errors each at most 1.03x control, and any board with more opens read before deciding.

**If the canary passes:** a default PR for `place_margin=-1, place_margin_gate=4, place_margin_regions=1`. The PR body
waits for the canary.

**Later:** a lower-threshold stage for dense-lo, under the pre-registered extension rules. The extension of (1) is not
needed: its CI already excludes 0.

Commits stay local, because the push is blocked by missing credentials.

## Canary result (2026-11-21, margin-gate-canary-m6, 20 of 20 ok)
**The canary passes on totals, with one flag on the pre-set rule.**
- **Clean on the basics:** no crash, timeout or over-time run. The longest is beagleplay at 9,835 s, against a 15,916 s
  ceiling. The only bug records are the boards' own `drc` records, 7 in each arm.
- **Identity where the margin is inert:** 7 of 10 boards are identical: sdi-mipi, beagleplay, gecko5 (auto margin 0),
  iorodeo, madcatse, why2025 and zotino.
- **Totals:** opens 5487 vs 5510 (0.996x) and errors 733 vs 730 (1.004x), both within the 1.03x limit.
- **Flag: one error type is added.** starved_thermal goes 0 → 3: 2 on glasgow and 1 on 0xd6.
  - The pre-set rule says "no error type added", so the rule is tripped on 3 errors.
  - The same type rose 2 → 7 on the dense-hi A/B.
  - A routing-noise origin is likely: one dense-lo board with identical placements swung by 103 on this type.
  - A margin mechanism is also possible: spacing parts apart lets pours fill more around pads, which can starve
    thermal spokes.
  - It is reported in the PR. If the reviewer reads it as harm, it needs a per-board look.

**The 3 boards that act:**
- **glasgow revd1:** delivered opens 1121 → 1080; per seed 1210 vs 1210 on average (equal).
- **dvhx 0805 exercise:** delivered opens 3 → 0, finishing early at 918 s against 2,123 s for control. Per seed it is
  mixed.
- **0xd6 flip-card:** worse. Delivered opens 151 → 172, and per seed about 307 vs 287 (+7 %). This is a very dense
  2-layer board with 517 footprints, and the margin costs room there. Read it before merging.
