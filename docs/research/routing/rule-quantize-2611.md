<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Rule-aware quantization of widths and vias (2026-11-15)

Scope: one helper that puts every width and via size on a grid without leaving the board rule's interval, where
it applies, and the A/B that decides it. Not here: the bridge's other rule fixes ->
[bridge-fixes-2611](bridge-fixes-2611.md) (branch `bridge-fixes-ab`); the bridge itself ->
[kae-freerouting-bridge](kae-freerouting-bridge.md).
Keys: rule-quantize, quantize.fit, track_width, annular_width, min = max, session units, DSN resolution, nm grid

**Status:** pre-registered (`tools/kaeres/experiments/rule-quantize/PLAN.md`), smoke and full run below. Verdict
pending.

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
(clamped into the class's limits). Already safe and unchanged: `critical_space.clamp_width` (falls back to the exact
max), clearances (rounded up, the safe side), and coordinates written at 6 decimals.

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
Pending: `rule-quantize-mech` (5 boards x C, Q, CB, QL x 5 attempts) and `rule-quantize-guard` (68 hard
boards x C, Q x 2).
