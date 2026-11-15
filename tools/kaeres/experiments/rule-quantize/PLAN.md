<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# rule-quantize: rule-aware quantization of widths and vias (pre-registered plan)

Written 2026-11-15, before any full run. Context: [bridge-fixes-2611](../../../../docs/research/routing/bridge-fixes-2611.md)
(branch `bridge-fixes-ab`), whose mech run found a third width bug: thunderscope rev5-3 gets about 184 track_width
errors per run because kae rounds its 0.19079 mm (min = opt = max) PCIe width up to 0.1 um, past the max.

## The change (Q, `rule-quantize` e27df322)
One helper, `kae.route.quantize.fit(v, lo, hi, q, side)`, puts a value on grid `q` at the point nearest `v` (or the
nearest above or below it) inside the rule's `[lo, hi]`. Where the interval holds no point of `q`, it falls back to
KiCad's whole nm. Router-only values round outward on their own grid; values written to the board stay inside the
rule. It is used for:
- class widths (`_width_choice`): the width in whole nm, not rounded up to 0.1 um;
- DSN class widths: rounded up to Freerouting's 0.2 um grid (half widths in whole 0.1 um units). Freerouting
  routed at that width already, so its input is unchanged in effect;
- session import (`translate.fit_widths`): a wire within one 0.2 um step outside its class's limits comes back to
  the nearest width inside them. This covers bridge-ses-width's case (0.1521 returned as 0.1522), on canonical and
  user-named layers. Wires inside their limits are left alone, unlike W, which also restored legal ones;
- via sizes (whole um inside the drill and diameter limits), last-mile widths (whole nm inside the limits),
  escape's smallest legal via (up, never below a minimum), and repair's widening of a narrow track (clamped into
  the class limits).

## Where the mechanism exists (`scan_rules.py`, `scan.json`)
Over the 14,199 `usable_route_test` boards, a `.kicad_dru` constraint with a max (or min = max) that main's chain
of roundings (kae up to 0.1 um, or to 1 um for vias, then Freerouting's 0.2 um width grid) pushes past a bound:
**4 boards**. thunderscope rev5-3 has track_width 0.19079 (outer) and 0.14789 (inner), ducktop2 center, left_io
and right_io have 0.1521. No via_diameter, hole_size or annular_width maximum is affected anywhere. Off-grid
minimums are common: net-class widths off 0.1 um on about 200 boards, and via sizes, drills and edge clearances
in design settings on 10-180 boards each. Rounding a minimum up is safe, though, and only last mile and escapes
rounded one down, to the nearest 0.1 um.

## Arms (same recipe and harness as bridge-fixes-ab: main 091163c0, fork d137fd1, 900 s, `--seed {attempt}`)
C main; Q rule-quantize; CB bridge-fixes-combined (b135072a: W2 + L); QL rule-quantize-layers (ebf20ae4: Q + L).
New ids (`REP=rq`) so all arms run side by side in each board's job, kaeq timed class.

| experiment | boards | arms | attempts |
|---|---|---|---|
| `rule-quantize-mech` | `mech.txt` (the 4 scan boards) | C, Q, CB, QL | 5 |
| `rule-quantize-guard` | `guard-hard.txt`: 68 boards, one per repo family, class widths off the 0.1 um grid, all `route_demand` hard/extreme or `pad_density` very_dense/extreme (`select_boards.py`) | C, Q | 2 |

On guard boards, Q changes only the widths kae writes itself (critical router, last mile, escapes). Each moves by
less than 0.1 um: the width is now kept in nm instead of being rounded up. Freerouting's widths are unchanged.

## Outcomes and decision rules
**Primary (mech):** grid track_width errors are track_width errors whose actual width is within 0.2 um of the
rule's bound. They are counted at round 0 (the bridge's DRC after the first Freerouting route) and on the scorer's
final board, per board as the mean over attempts. All track_width errors are reported too.
- **Q fixes it** when Q has no grid error on any final board and its round-0 total is at most 10 % of C's, with C
  having some on at least 3 of the 4 boards.
- **Q subsumes W** when QL has no more grid errors than CB on any board (final and round 0), and QL's guards
  against CB pass at +10 %.

**Guards** (per board, mean over attempts of log(x + 1), arm minus control, geometric-mean ratio, 95 % bootstrap
interval over boards, B = 4000): x = opens, other errors (all errors except track_width and items_not_allowed),
all errors, and defects (opens + errors). A guard passes when the upper end is below the margin, fails when the
lower end is above it, and is otherwise undecided.
- mech: Q vs C and QL vs CB, margin +10 %. Four boards can't resolve 5 %, so these are reported as descriptive
  where undecided;
- guard set: Q vs C, margin +5 %.

**Adopt Q** as the default (PR) when its primary holds and the guard-set guards pass. A failing guard rejects it
as is.

## Noise and size
A/A spread of the bridge control (diffpair-ab4 PLAN): per-run sigma of log opens about 0.28, per-board
heterogeneity about 0.1. Guard set, k = 2, 68 boards: SE about sqrt(0.28^2 + 0.1^2) / sqrt(68) = 0.036, i.e. about
+-7 %. A true ratio of 1.00 is then decided at +5 % only if the observed ratio is below about 0.98, so round 1 may
end undecided. **Extension (pre-registered):** attempt 2 on every guard board, then the next 85 boards of
`guard.txt` (not hard-tagged) at k = 2. That is two more looks at most, each at 95 %, reported as such. The
primary is deterministic in mechanism: each grid-rounded wire on a min = max rule is an error. C had about 184 per
run on thunderscope and 28-92 on right_io.

## Reported
Per arm against its control: the primaries per board, guards with intervals, totals, cp1, cpk, completion, CPU,
per-type DRC errors (read before any verdict), and the boards whose opens moved most and why. Tables are by tag
where it matters (hard vs not).

## Expected cost (information, not a limit)
About 0.3-0.5 CPU-h per run. mech: 4 x 4 x 5 = 80 runs, about 35 CPU-h; one job per board runs 20 attempts in
sequence (wall about 5-6 h; 10 h job timeout). guard: 68 x 2 x 2 = 272 runs, about 110 CPU-h. Extension: about
130 CPU-h more.

## Smoke
(Filled in before the full run.)
