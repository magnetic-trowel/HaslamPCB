<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# ground-side-ladder: why the clean guard lost boards (seed 0, 2026-11-26)

Analysis only, from the stored runs: `rootcause_extract.py` (router and repair trace from each run's adapter.log JSON;
scored opens and errors from results.csv) and `rootcause_cov.py` (per-board `cov_opp`, return_board). Outputs:
`rootcause_seed0.json`, `rootcause_cov_seed0.json`.

## Findings

1. **The losses are completion losses on large, congested boards, not DRC errors.** Of the 10 boards lost by either
   price, 9 lose by open connections. Only one adds DRC errors (kahan64bit-kp60 at 2: copper_edge_clearance 1 and
   hole_clearance 1). The one board gained, circuitscout, gains because the control's 63 solder_mask_bridge are absent
   in both priced arms.
2. **Size.** Boards the control routes clean, by pad count: under 200 pads, price 2 loses 1 of 41 and price 4 loses
   0. At 200 pads or more, price 2 loses 5 of 30 and price 4 loses 8 of 30. The `cov_opp` gain is about the same at
   every size: medians +0.079 (< 200 pads) and +0.058 (>= 200) at price 2; +0.116 and +0.129 at price 4.
3. **Mechanism at price 4.** On the 8 boards lost at price 4:
   - Freerouting's first pass leaves more connections unrouted: +25.5 per board (median), 219 more in total. On the 22
     boards of >= 200 pads that stay clean it is +1.
   - The repair rounds start with 173 more opens.
   - Vias rise by a median ratio of 1.52 (1.26 on the boards that stay clean).
   - The repair rounds re-route ripped and open nets under the same price (`haslam.route.repair` translates the
     plan, ground side included), so they do not close the extra opens.
   - What remains open is mostly signal nets and parts (col/row matrix nets, IC pins, `/CPU/D4`, `reset`). GND
     accounts for 4 of 38 open objects.
   - Examples (first pass unrouted, control → price 4): goga64-ulk 1 → 37, coco3 42 → 93, jimbro1000-dragon32
     42 → 111, dmcke5-zendeck 18 → 38, kahan64bit-kp60 6 → 15.
4. **At price 2 the losses are mostly single opens on near-miss boards.** Price 2 loses 6 boards:
   - byungyoonc (GND), calebhabesh (+5V), harrislab (GND / C102, a 50-pad board) and modern-hobbyist each end with
     1 open.
   - jimbro1000 ends with 9 opens and kahan64bit with 2 DRC errors.
   - The first-pass unrouted change is 0 per board (median); repair round 0 starts with 21 more opens in total.
   - Single opens like these can come from seed-to-seed noise. One seed cannot separate the price from seed noise
     here, which is why seed 1 was planned (PLAN.md addendum).
5. **Not found.**
   - The opens are not the price pushing ground stitching or return detours: few open objects are GND.
   - The price does not grow without bound: it is a fixed per-length factor on one layer.
   - There are no DRC clearance errors from the extra vias, except on kahan64bit.

## Per board (seed 0; first pass = Freerouting's unrouted count after its last pass, of the count at start)

| board | pads | side | arm | opens | DRC errors | vias | first pass left (of start) | repair 0 opens | open nets / parts | cov_opp |
|---|---|---|---|---|---|---|---|---|---|---|
| byungyoonc-truestrike42-truestrike | 686 | F.Cu | ctl | 0 | 0 | 344 | 94 / 274 | 18 | - | 0.634 |
|  |  |  | gs2 **lost** | 1 | 0 | 402 | 107 / 274 | 32 | GND | 0.632 |
|  |  |  | gs4 **lost** | 1 | 0 | 461 | 125 / 274 | 16 | GND | 0.655 |
| calebhabesh-doorlink-smart-doorbel | 383 | B.Cu | ctl | 0 | 0 | 170 | 12 / 183 | 8 | - | 0.406 |
|  |  |  | gs2 **lost** | 1 | 0 | 168 | 7 / 183 | 5 | +5V | 0.524 |
|  |  |  | gs4 | 0 | 0 | 176 | 11 / 183 | 5 | - | 0.602 |
| dmcke5-zendeck-lhs-controller-pcb | 326 | F.Cu | ctl | 0 | 0 | 78 | 18 / 147 | 4 | - | 0.008 |
|  |  |  | gs2 | 0 | 0 | 105 | 28 / 147 | 6 | - | 0.006 |
|  |  |  | gs4 **lost** | 1 | 0 | 159 | 38 / 147 | 9 | /LY | 0.003 |
| dvhx-pedal-snow-white-autowah-peda | 290 | B.Cu | ctl | 0 | 0 | 28 | 9 / 156 | 10 | - | 0.600 |
|  |  |  | gs2 | 0 | 0 | 26 | 13 / 156 | 10 | - | 0.744 |
|  |  |  | gs4 **lost** | 1 | 0 | 47 | 15 / 156 | 14 | GND | 0.731 |
| harrislab-brown-vibecheck-vibechec | 50 | B.Cu | ctl | 0 | 0 | 7 | 3 / 15 | 3 | - | 0.769 |
|  |  |  | gs2 **lost** | 1 | 0 | 8 | 4 / 15 | 4 | C102, GND | 0.663 |
|  |  |  | gs4 | 0 | 0 | 7 | 4 / 15 | 4 | - | 0.780 |
| jimbro1000-dragon32issue2asecam-dr | 1139 | B.Cu | ctl | 0 | 0 | 208 | 42 / 695 | 7 | - | 0.001 |
|  |  |  | gs2 **lost** | 9 | 0 | 320 | 57 / 695 | 31 | /CPU/A1, /CPU/D4, /VDG/GD5, C15, ESND, IC12, IC13, IC15, IC20, IC35, I | 0.000 |
|  |  |  | gs4 **lost** | 30 | 0 | 469 | 111 / 695 | 98 | /CPU/D4, /CPU/D6, ESND, GND, IC12, IC16, IC17, IC19, IC2, IC20, PL7, p | 0.000 |
| kahan64bit-kp60-kp60 | 562 | F.Cu | ctl | 0 | 0 | 64 | 6 / 216 | 4 | - | 0.746 |
|  |  |  | gs2 **lost** | 0 | copper_edge_clearance 1, hole_clearance 1 | 76 | 5 / 216 | 2 | - | 0.706 |
|  |  |  | gs4 **lost** | 3 | 0 | 104 | 15 / 216 | 10 | B30, D+, GND, U2 | 0.806 |
| modern-hobbyist-aesir-hermod-right | 925 | B.Cu | ctl | 0 | 0 | 383 | 55 / 239 | 40 | - | 0.207 |
|  |  |  | gs2 **lost** | 1 | 0 | 423 | 46 / 239 | 27 | U1, U6, col9 | 0.409 |
|  |  |  | gs4 **lost** | 5 | 0 | 543 | 52 / 239 | 26 | U1, U6, col10, col7, col8, col9, row2 | 0.522 |
| pcbcorpus-goga64-ulk-ulk | 646 | B.Cu | ctl | 0 | 0 | 104 | 1 / 134 | 5 | - | 0.009 |
|  |  |  | gs2 | 0 | 0 | 80 | 26 / 134 | 8 | - | 0.002 |
|  |  |  | gs4 **lost** | 28 | 0 | 26 | 37 / 134 | 28 | RSW1, RSW2, SW10, U1, U2, col2_r, col3, col4, col4_r, reset, reset_r,  | 0.002 |
| qbancoffee-coco-motherboards-coco3 | 1028 | B.Cu | ctl | 0 | 0 | 459 | 42 / 624 | 30 | - | 0.262 |
|  |  |  | gs2 | 0 | 0 | 518 | 50 / 624 | 21 | - | 0.342 |
|  |  |  | gs4 **lost** | 48 | 0 | 493 | 93 / 624 | 90 | - | 0.407 |

## Change designed from it

The price is kept in the first pass, which is where the coverage comes from, and dropped in the DRC repair rounds,
which only re-route the ripped and open nets. Setting `ground_side_repair` (default 0) is on branch
`route/ground-side-gate`. The alternative, gating by board size (no price at 200 pads or more), would also drop the
gain on the 30 large boards, where the gain is as large as on small ones. Its A/B is ground-side-repair-ab
(`../ground-side-repair-ab/PLAN.md`).

## Update 2026-11-26: the repair-round hypothesis is falsified

ground-side-repair-ab (`../ground-side-repair-ab/VERDICT.md`) ran 18 boards × 2 seeds at current code:
- With the price off in the repair rounds, the arm ends as with the price on: clean +1 / −4 against no price, the same
  as price 2 in every round.
- kahan64bit's DRC errors (copper_edge_clearance, hole_clearance) are present after the first priced pass, and the
  unpriced repair rounds do not remove them.
- The other losses are single opens on near-miss boards. The unpriced arm also flips on such boards between seeds.

So at price 2 the loss is made in the first priced pass, or it is seed noise. Price 4's larger first-pass completion
loss (finding 3) is the clearer mechanism. Separating them at price 2 needs the seed-1 runs.
