<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Rule-aware quantization of widths and vias (2026-11-15)

Scope: one helper that puts every width and via size on a grid without leaving the board rule's interval, where
it applies, and the A/B that decides it. Not here: the bridge's other rule fixes ->
[bridge-fixes-2611](bridge-fixes-2611.md) (branch `bridge-fixes-ab`); the bridge itself ->
[kae-freerouting-bridge](kae-freerouting-bridge.md).
Keys: rule-quantize, quantize.fit, track_width, annular_width, min = max, session units, DSN resolution, nm grid

**Status:** pre-registered (`tools/kaeres/experiments/rule-quantize/PLAN.md`). The mech run is decided (2026-11-16):
Q removes every grid error, and its guards pass against main. The guard set (`rule-quantize-guard`) and the
zero-width check (`rule-quantize-zw`) are still running; adoption waits for them.

## Mechanism
KiCad stores and judges every length in whole nm. kae and Freerouting keep coarser grids:
- kae's DSN uses 0.1 um, and kae names vias in whole um;
- Freerouting keeps half widths in whole 0.1 um units, so a routed width falls on a 0.2 um grid. It rounds a half
  width to the nearest unit, so a width never comes back narrower than asked.

Rounding onto a grid in a fixed direction is safe for a minimum and wrong for a maximum. Main had three such cases:
- **Width past a max.** thunderscope rev5-3's PCIe rules have min = opt = max = 0.19079 mm (outer) and 0.14789 mm
  (inner). kae rounded them up to 0.1908 and 0.1479: 186 track_width errors in a control run. ducktop2's 0.1521 mm
  rule is on kae's grid but not on Freerouting's, which returns 0.1522 (bridge-ses-width's case).
- **Ring below its min.** A via's drill and diameter were each rounded up to 1 um on their own.
  thunderscope's 0.4064/0.2032 mm via with a 0.1016 mm minimum ring became 0.407/0.204, a 0.1015 mm ring: 199
  annular_width errors in the same run.
- **Minimum rounded down.** Last mile and escapes rounded widths and via sizes to the nearest 0.1 um, so a
  0.24892 mm minimum drill became 0.2489. Repair widened a narrow track to the DRC message's minimum plus 0.1 um,
  past a min = max rule.

## The helper
`kae.route.quantize.fit(v, lo, hi, q, side)` returns the point of grid `q` inside `[lo, hi]` nearest `v` (or the
nearest at or above, or at or below, it). Where the interval holds no point of `q`, it uses KiCad's nm grid instead.
It returns None only for a contradictory rule (lo > hi).

There are two rules for using it:
- a value only a router sees (a DSN width or clearance) may round outward on the router's grid;
- a value KiCad will judge is fitted into the rule's interval.

The bridge closes the gap between the two at session import. `translate.fit_widths` brings a wire that
Freerouting's grid put just outside its class's limits (within one 0.2 um step) back to the nearest width inside
them. Narrowing a wire keeps every clearance Freerouting kept. Wires already inside their limits are left alone.

Alternatives considered:
- **A finer DSN resolution (nm).** This is not possible: Freerouting divides its resolution by 10 while 5 x the largest
  coordinate reaches 2^25 units (Structure.java), which at nm allows only about 6.7 mm of board. Half widths
  would still be rounded.
- **Snapping down when the result still meets the minimum.** Fails for min = max: no 0.1 um point lies in
  [0.19079, 0.19079].
- **Point fixes per call site.** Seven sites (below) would each repeat the same interval logic.

Where it is used: `constraints._width_choice` (class widths, nm), `_via_choice` (um, with the diameter's floor taken
after the drill is rounded), the DSN class width (up to 0.2 um), `translate.fit_widths`, `lastmile.widths_of` (and
its two callers that rounded), `escape.small_via` / `legal_via` (up, never below a minimum), and `repair` widening
(clamped into the class's limits). Already safe and unchanged: clearances (rounded up, the safe side) and
coordinates written at 6 decimals.

**Effective limits (af3cc286, PR #66 folded in).** `critical_space.Space.width_limits` is the one source of a net's
width limits for kae's own routers. They are the board's stated min, opt and max, and where the board states no
minimum, the narrowest class width (the bridge's own neck in that case), capped at opt and max. The board's rules
win; kae only fills their silence. With a minimum of 0, width ladders ending at the minimum laid zero-width copper
(chassis-soft M: on 10 boards). `clamp_width` fits into these limits with `fit`, and so do the module stage's trim
widths. Check: `PLAN-zw.md`.

Gaps left (not rounding): `fr_entry` rail class widths and `constraints.width_at` necks are not checked against a
rule's max, and `power_copper` zone thermal sizes are fixed at 0.3 mm.

## Where the mechanism exists
`scan_rules.py` over the 14,199 usable boards: width maximums crossed on 4 boards (thunderscope; ducktop2 center,
left_io, right_io), and annular rings shrunk on 2 (thunderscope; regymm pynqsdr ebaz_sdr). No via diameter or drill
maximum is crossed anywhere. Off-grid minimums are common (about 200 boards have net-class widths off 0.1 um), but
only last mile and escapes rounded them the unsafe way.

## Smoke (seed 0, one run per arm)
- **thunderscope, round 0.** C had 430 errors (190 track_width, 199 annular_width); Q had 48, with no
  track_width or annular_width error.
- **thunderscope, final board.** C had 430 errors and 499 opens; Q had 8 errors (length 4, edge 4) and 499 opens.
  Q's board carries 157 tracks at exactly 0.19079 mm, 4 at 0.14789 mm, and vias of 0.408/0.204 mm.
- **ducktop2 right_io, final board.** Neither arm has a width error. C ripped them, ending at 138 opens and 3
  errors. Q ended at 97 opens and 58 errors, 54 of them items_not_allowed, the disallowed-layer bug that L fixes.
  That is why QL is set against CB.
- **Profile.** The run is budget-bound: Freerouting 55-81 %, last mile 12-18 %, DRC 3-12 %. Q adds no
  measurable time. Details are in PLAN.md.

## Results
### rule-quantize-mech (2026-11-16, 5 boards x 4 arms x 5 attempts, all 100 runs scored)
Grid errors per board, as the mean over attempts. "Width" means track_width within 0.2 um of the bound; "ring"
means annular_width within 1 um of the minimum.

| board | C width / ring (final) | Q | CB | QL | C round 0 width / ring |
|---|---|---|---|---|---|
| thunderscope rev5-3 | 171.4 / 199.0 | 0 / 0 | 179.6 / 199.0 | 0 / 0 | 148.4 / 159.2 |
| ducktop2 right_io | 38.0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 91.2 / 0 |
| ducktop2 center | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 2.6 / 0 |
| ducktop2 left_io | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| regymm pynqsdr | 0 / 2.4 | 0 / 0 | 0 / 2.4 | 0 / 0 | 0 / 16.4 |

- **Primary, Q vs C: fixed.** Q has no grid error on any run, final or round 0. C had round-0 width errors on 2 of
  the 4 width boards (right_io, center), plus thunderscope's off-grid rule. thunderscope's own errors are not the
  one-unit kind, so the pre-registered "3 of 4 boards" count is met only with thunderscope included.
- **Guards, Q vs C** (ratio [95 % CI], margin +10 %): all four pass.
  - opens 0.62 [0.24, 1.03];
  - other errors 0.50 [0.18, 1.02];
  - errors 0.40 [0.12, 1.03], total 531 -> 98;
  - defects 0.76 [0.62, 0.94].
- **Per-type errors per run, C -> Q:**
  - track_width 41.9 -> 0;
  - annular_width 40.3 -> 0;
  - connection_width 6.0 -> 2.4;
  - items_not_allowed 10.7 -> 10.0 (L's bug, in both);
  - everything else the same within 0.2.

  Completion is 0.669 -> 0.691; cp1 and cpk are 0 in both arms.
- **QL vs CB:** CB (W2 + L) still has thunderscope's 179.6 width errors per run, because W only restores
  one-unit widths and the error is kae's own rounding, and both rings. QL has none of either, and no board has more
  grid errors under QL than under CB.
  - opens 0.62 [0.24, 1.00]: pass;
  - defects 0.79 [0.62, 0.99]: pass;
  - errors 0.56 [0.13, 1.40], total 448 -> 45: undecided on 5 boards (reported as descriptive, per the plan);
  - other errors: same as errors.

  analyze.py prints "not shown" for QL vs CB. That is its Q-vs-C rule (C needs round-0 width errors on 3 boards),
  not the plan's QL-vs-CB rule, which QL meets on its primary.
- **CPU is not comparable:** 5.4 h for C vs 8.8 h for Q, and 4.6 h for CB vs 14.0 h for QL. C and CB replayed
  step-cache hits from the bridge-fixes runs of the same methods (the same inputs), so their Freerouting and DRC
  steps were cached. The smoke's profile shows Q adds no measurable time.

**Verdict (mech):** Q fixes every grid-rounding error on the boards where the mechanism exists, with no guard
failing. As part of Q+L, it does what bridge-ses-width (W) does and also fixes what W misses (thunderscope's
off-grid rule and both annular-ring cases). Width handling should therefore go with rule-quantize, superseding
bridge-ses-width, provided `rule-quantize-guard` (68 boards, +5 %) and `rule-quantize-zw` pass.

### rule-quantize-zw (2026-11-17, 10 boards, chassis M, ZM / ZQ / ZQ2)
ZQ2 left no zero-width copper in any of its 19 runs, over two builds. The control left some on 5 boards. Against the
control on the c81770e build (7 boards, 14 pairs) the guards pass at +10 %: opens 0.952 [0.862, 1.000], errors 0.925
[0.790, 1.000], defects 0.932 [0.844, 1.000]. ZQ (Q without the zero-width fix) gave the control's output on 13 of 14
runs, so the stage was stopped there.

### rule-quantize-guard-m6 (2026-11-20, guard only: 46 hard boards, k = 1)
Q is 40eb8b82, the commit that ships. C is main 6d726340, with Freerouting fork 37b1a8b under counted work. Each figure is
the geometric-mean ratio, Q against C, with a 95 % board bootstrap interval.
- DRC errors: 1.002 [1.000, 1.006].
- Defects: 0.998 [0.974, 1.017].
- track_width, annular_width and connection_width: equal on every board (0/0, 67/67, 0/0). So is every other type with at
  least 20 errors, except two:
  - starved_thermal: 1.003 [1.000, 1.010].
  - solder_mask_bridge: 1.024 [1.000, 1.074]. Its upper end is over the +5 % margin, and the excess is one board, home-mini
    v1, with +2. Both new errors are 0.2 mm SPK+ and SPK- tracks under J2's mask aperture. Those tracks have the same
    width in both arms and are not a width Q changes, so the extra errors come from a different route of those nets.
- Opens: 0.996 [0.966, 1.024], with 6 boards better and 5 worse.

18 of the 46 boards had identical output in both arms. No harm.

The 10 big canary boards (`canary-big`) run once before merging.
