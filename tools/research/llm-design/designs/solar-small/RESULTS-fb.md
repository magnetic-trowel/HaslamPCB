<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# solar-small: feedback-node pickup (T-FB, T-FB3), what each change did

Question: how to bring the copper pickup on the two regulator feedback nodes under their limits, as haslam's physics
evaluator measures it. T-FB: LTC3130 FB (U101.9, net /CHG/FB), limit 5 mV. T-FB3: TPS62933 FB (U301.8, /PWR/FB3),
limit 16 mV. Value = `pickup.peak`, worst over the evaluator's corners, from `haslam.intent status`.

Evaluator: `haslam.excite.evaluate` + `haslam.intent status` from a frozen copy of the evaluator with the facts, mesh and
DC fixes (base `4e2cbc61` plus the uncommitted `dc.py`/`heat.py` changes of that scratch checkout), one intent file
for every run (the solar-small2 `eval-intent.json`), pitch 0.25 mm. The evaluator prices inductive and
shared-copper coupling through the board's circuit (every two-pad part lumped into the copper); it does NOT price
electric-field (capacitive) coupling into a victim node: the trace-to-trace capacitances it computes feed only the
switch-node loss. A change that makes a feedback node higher-impedance at high frequency (removing a capacitor,
adding a series R) is therefore scored without the E-field pickup that impedance invites.

## 1. Screens on the routed A0 board (no re-layout)

Board: `solar-small2/A0/s1/out` (haslam A0 recipe). Each change edits the evaluator's circuit before the solve
(`whatif.py` in the work dir; the advisor's `--add-part/--remove-part` do the same). An added part sits on two
existing pads with no copper of its own: the best placement any layout could give it. Baseline reproduced
exactly (398.6 / 396.4 mV).

Placement on that board: the FB divider R115/R116/R117/C117 sits by the DAC (y 75-84 mm), 40 mm of FB trace from
U101.9 (y 41); R301/R302/C307 sit 15 mm from U301.8; U302's VDD capacitor C312 is 70 mm from U302.

| Variant | Change | T-FB | T-FB3 | Limits mW_eq | Dominant aggressor on the changed node |
|---|---|---|---|---|---|
| S0 | none | 398.6 mV | 396.4 mV | 5641 | FB: boost cell U101; FB3: core U302 (+3V3) |
| S1 | C117 22 -> 8.2 pF (LTC3130 DS p.17: CFF = 40/R1(MOhm) pF = 8.0 pF) | 303.8 mV | = | 4448 | boost U101 |
| S2 | C117 removed (CFF is "optional", DS p.17) | 0.51 mV | = | 699 | boost U101 |
| S3 | RFF 249 k in series with C117 (DS p.17: ~R1/20) | 2.87 mV | = | 699 | buck U301 |
| S9 | C117 8.2 pF + RFF 249 k (both DS values) | 2.86 mV | = | 699 | buck U301 |
| S10 | RFF 100 k in series with C117 | 6.91 mV | = | 709 | buck U301 |
| S13 | 10 pF FB-GND at U101.9-U101.17 (EP) | 292.4 mV | = | 4315 | boost U101 |
| S4 | 100 pF FB-GND at U101.9-U101.17 | 88.2 mV | = | 1778 | boost U101 |
| S11 | C117 8.2 pF + 100 pF FB-GND | 41.2 mV | = | 1173 | buck U101 |
| S5 | 330 pF FB-GND (compensated divider: Cfb/CFF = R1/(R2‖R3)) | 37.4 mV | = | 1111 | buck U101 |
| S6 | 1 nF FB-GND at U101.9-U101.17 (EP) | 21.7 mV | = | 872 | buck U101 |
| adv c1n | 1 nF FB-GND at U101.9-U101.11 (MODE pin = GND) | 11.2 mV | = | | (advisor run) |
| adv c4n7 | 4.7 nF FB-GND at U101.9-U101.11 | 11.6 mV | = | | (advisor run) |
| S12 | C117 moved: 22 pF from U101.14 (VOUT pin) to U101.9 | **1.839 V** | = | 12820 | boost U101 |
| S8 | divider x0.1 (499 k / 39.2 k / 402 k), CFF 82 pF per DS formula | 461.1 mV | = | 6425 | boost U101 |
| adv div01 | divider x0.1, CFF kept | 398.6 mV | = | | (advisor run) |
| S7 | 10 nF on the DAC injection node (U302.2-U302.14) | 398.6 mV | 396.1 mV | 5641 | DAC output modelled as a 40 ohm driver: no effect |
| T1 | C307 removed | = | 2.51 mV | 4941 | buck U301 |
| T8 | RFF 100 k in series with C307 (R301/10) | = | 6.02 mV | | buck U301 |
| T2 | 100 pF FB3-GND at U301.8-U301.4 | = | 109.3 mV | 5078 | core U302 |
| adv c1n301 | 1 nF FB3-GND at U301.8-U301.4 | = | 27.2 mV | | (advisor run) |
| T6 | C307 moved: 22 pF from the output cap's +3V3 pad (C305.1) to U301.8 | = | 141.5 mV | | core U302 |
| T3 | divider x0.1 (100 k / 31.6 k), C307 kept | = | 396.5 mV | 5644 | core U302 |
| T7 | divider 100 k / 31.6 k, C307 removed | = | 23.96 mV | | buck U301 |
| T4 | U302's VDD cap C312 moved onto U302 (U302.15-U302.17) | 398.1 mV | 58.8 mV | 5006 | buck U301 |

"=" = unchanged from S0 within 0.1 mV.

What the screens say (mechanism):
- Both pickups enter through the 22 pF feed-forward capacitors, not through the MOhm dividers or the FB trace
  length: without C117 the 40 mm FB trace picks up 0.51 mV. At the 10 MHz edge band C117 is 723 ohm, against a
  node impedance of ~590 ohm (5 pF pin capacitance), so the FB node follows SYS's copper voltage, and SYS at C117's
  pad carries the boost cell's return-path voltage. Same for C307 on +3V3 (whose copper carries U302's core current,
  C312 being 70 mm away).
- Lower divider impedance does nothing while the CFF stays (S8, T3, adv div01): the noise path is the capacitor.
- An FB-GND capacitor works only as a capacitive divider against CFF; it needs ~1 nF at the pin to reach 11-22 mV
  and never meets 5 mV here; which ground pad it returns to changes the result 2x (EP 21.7 vs MODE pin 11.2 mV).
- Taking the CFF's supply end at the IC's own VOUT pin is the worst place (S12, 1.8 V): the VOUT pin sits in the
  boost cell's hot loop. A quiet tap at the output capacitor (T6) helped FB3 only 2.8x.
- A series R in the CFF branch (DS p.17 RFF) blocks the path above its RC corner and keeps the feed-forward lead
  below it: 2.9 mV (FB) and 6.0 mV (FB3), both under their limits.

## 2. Layouts (haslam A0 recipe, haslamq), 2-4 seeds per variant

Each variant: `haslamsynth build`, `sch_to_board.py`, then `run_ab.sh A0 SEED` (no intent file beside the input) with
this branch's haslam, then DRC and the same frozen evaluator under the same intent file.
(run folders outside the repo: `solar-fb-runs/<variant>/A0/s<seed>/`).

Variants: **L0** the design as on `origin/solar-small` (22 pF CFFs straight to SYS / +3V3). **L1** L0 with the FB
networks fixed next to their pins in `board.json` (U101 + R115/R116/R117/C117 in a column 1-6 mm from U101.9; U301
+ R301/R302/C307 under U301.8). **L3b** the schematic fix only, haslam places everything: LTC3130 CFF 8.2 pF + RFF
249 k (R120), TPS62933 CFF 22 pF + RFF 100 k (R320). **L2b** L3b plus L1's fixed placement (R120/R320 beside their
CFFs).

| Variant | Seed | T-FB | T-FB3 | Limit-tier mW_eq | Dominant on FB / FB3 | Unconnected (DRC) | Evaluation |
|---|---|---|---|---|---|---|---|
| L0 | 1 | 2.941 V | 241.9 mV | 16230 | boost U101 / core U302 | 1 (BST1 U101-C111) | complete |
| L0 | 2 | (214.3 mV) | (68.4 mV) | (0: not priced) | buck U101 / buck U101 | 1 (GND island) | incomplete: copper open for boost U101, buck U301 |
| L0 | 3 | 229.9 mV | 311.2 mV | 2580 | boost U101 / core U302 | 0 | complete |
| L0 | 4 | 2.337 V | 466.3 mV | 23480 | boost U101 / buck U101 | 0 | complete |
| L1 | 1 | (243.8 mV) | (144.2 mV) | (0: not priced) | boost U101 / buck U101 | 1 (GND island) | incomplete: copper open for core U302, U201, DC |
| L1 | 2 | 1.911 V | 203.9 mV | 17780 | boost U101 / core U302 | 1 (GND island) | complete |
| L3b | 1 | 0.875 mV | 1.015 mV | 0 | buck U101 / buck U301 | 0 | complete |
| L3b | 2 | 1.754 mV | 2.427 mV | 0 | buck U101 / buck U101 | 1 (BST1 U101-C111) | complete |
| L3b | 3 | 1.692 mV | 3.624 mV | 0 | buck U301 / buck U301 | 1 (BST1 U101-C111) | complete |
| L3b | 4 | 2.441 mV | 2.254 mV | 0 | buck U301 / core U201 | 0 | complete |
| L2b | 1 | 1.984 mV | 1.247 mV | 0 | boost U101 / core U201 | 0 | complete |
| L2b | 2 | 1.401 mV | 6.738 mV | 0 | buck U301 / buck U301 | 0 (1 starved thermal) | complete |

Limits: T-FB 5 mV, T-FB3 16 mV. Every complete L3b and L2b run meets both (T-FB 0.9-2.4 mV, T-FB3 1.0-6.7 mV);
no complete L0 or L1 run meets either (T-FB 0.23-2.9 V, T-FB3 0.20-0.47 V). The DRC opens (BST1, a GND pour
island) are haslam routing outcomes seen in every arm, not caused by these changes.

What the layouts add to the screens:
- The CFF-to-supply path is also what makes the baseline swing 10x between seeds (230 mV to 2.9 V): the value
  depends on where haslam happens to put C117's SYS pad relative to the boost cell's return current.
- Placement alone (L1) does not help and can hurt: with C117 next to U101, its SYS pad lands in the cell's copper
  (1.9 V on seed 2, as S12 predicted). "Keep the FB node short" is the wrong first fix on this board; the FB trace
  length was never the path.
- With the series R in place, haslam's own placement (L3b) is as good as the hand-fixed one (L2b), so the
  recommendation needs no `board.json` constraints.

## 3. Cost, stability, citations

| Change | Quiescent current | Stability note | Source |
|---|---|---|---|
| RFF 249 k + CFF 8.2 pF (LTC3130) | 0 (no DC path) | zero 1/(2 pi R1 CFF) = 3.9 kHz as the DS formula gives; RFF caps the lead above 1/(2 pi RFF CFF) = 78 kHz, the DS's own remedy "where the voltage-loop bandwidth is high" | LTC3130 DS (3130f) p.17 Programming VOUT, Fig. 2 |
| C117 removed | 0 | allowed ("optional"); loses the DS's Burst-ripple and transient benefit; DS Table 3 (p.23) gives Burst-mode minimum COUT only for the with-feed-forward column (20 uF at 6.6-14 V) | DS p.17, p.23 |
| FB-GND 330 pF - 1 nF | 0 | adds a pole at 1/(2 pi (R1‖R2‖R3)(CFF+Cfb)): 1.4 kHz (330 pF, cancels the CFF zero: flat divider) to 0.5 kHz (1 nF): removes the feed-forward lead and adds lag; no DS guidance for an FB-GND cap on the LTC3130 (only a ~10 pF RUN filter, p.20) | DS p.17, p.20 |
| LTC3130 divider x0.1 | +22.9 uA at 13.7 V (2.55 -> 25.5 uA): 0.31 mW, 0.16-0.31 % of 100-200 mW panel power; night budget 29.5 -> 52.4 uA (limit 50) | none | design.py calcs |
| RFF 100 k + C307 22 pF (TPS62933) | 0 | CFF zero 7.2 kHz (1 M x 22 pF), lead capped above 72 kHz; TI gives CFF guidance (10.2.2.10: CFF helps when RFBT > 100 k) but no series-R guidance: this R is the LTC3130 DS's remedy carried over, to be checked by a load-step test | TPS62933 DS SLUSEA4D 10.2.2.10, 9.3.4 |
| C307 removed | 0 | DS: large RFBT with the FB pin's parasitic C makes a pole that can hurt stability; CFF mitigates it (10.2.2.10). With RFBT = 1 M, removing CFF is against that guidance | SLUSEA4D 10.2.2.10 |
| TPS62933 divider 100 k / 31.6 k | +22.8 uA at 3.33 V, ~7.3 uA from the battery (80 % buck at 13 V): 0.1 mW; night budget 29.5 -> 36.8 uA | DS-compliant (RFBT <= 100 k needs no CFF) but 24 mV with C307 removed: over the limit | SLUSEA4D 9.3.4 |
| 10 nF on DAC_FB | 0 | DAC63002 allows CL <= 200 pF (1000 pF at 30 deg PM): 10 nF is out of spec; the evaluator sees no effect anyway (DAC output modelled as a 40 ohm driver; its Hi-Z state is not modelled) | DAC63002 DS SLASF48 Electrical Characteristics, CL |

## 4. Recommendation (committed on `solar-small-fb`)

L3b: on each feed-forward capacitor, a resistor in series, no placement constraints.
- LTC3130: R120 249 k (SYS-FF) + C117 8.2 pF C0G (FF-FB), the values LTC3130 DS p.17 gives (CFF = 40/R1(MOhm) pF,
  RFF ~ R1/20). Screen 2.86 mV; layouts 0.88-2.44 mV (limit 5 mV).
- TPS62933: R320 100 k (+3V3-FF3) + C307 22 pF (FF3-FB3). Screen 6.0 mV; layouts 1.0-6.7 mV (limit 16 mV). The
  series R is not in TI's datasheet; it is the LTC3130's remedy applied to the same structure, to confirm with a
  load-step test on the built board.
- Cost: no quiescent current (no DC path), two 0603 resistors (C2933177 extended, C25803 basic); C117 becomes an
  extended part (C1685, was basic C1653).
- Rejected: removing the CFFs (best numbers, 0.5 / 2.5 mV, but against TPS62933 DS 10.2.2.10 with a 1 M top resistor,
  and it gives up the LTC3130's Burst-ripple benefit); FB-GND capacitors (never under 11 mV, and they cancel the
  feed-forward lead); lower divider impedance (no effect while the CFF stays, +23 uA); placement constraints alone
  (worse).
- Caveat for every high-impedance option here: the evaluator does not price E-field pickup into the FB nodes, and
  the series R raises the FB node's high-frequency impedance. Keeping the FB copper short and away from SW1/SW2/SW3
  is still good practice; haslam's placer has no term for it (the LTC3130 divider sits 20-31 mm from U101 and the
  TPS62933 divider 14-22 mm from U301 on every L0 and L3b seed; 40 mm on the solar-small2 board), and the design's `d.place.near` relations are written to `intent.yaml`, which haslam does not read.

Other findings on the way: U302's VDD capacitor C312 lands 27-86 mm from U302 (70 mm on the solar-small2 board) (haslam ignores haslamsynth's
decoupling relation), making +3V3 noise at U302 "implausible" (1.67 V) and the FB3 aggressor; LTC3130 DS Table 3
(p.23) asks for 20 uF effective COUT at 6.6-14 V in Burst Mode, and C114 + C115 are 2 x 10 uF 35 V X5R 1206 at
13.5 V bias (well under 20 uF effective).

Reproduce: `whatif.py`, `run1.sh`, `layout1.sh`, `prep.sh` in the session work dir (outside the repo);
screens in `screen/<variant>/`, layouts in `solar-fb-runs/<variant>/A0/s<seed>/` beside it.
