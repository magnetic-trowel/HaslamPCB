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
Over the 14,199 `usable_route_test` boards, two mechanisms push a value past a bound on main.
- **Width maximum:** a `.kicad_dru` constraint with a max (or min = max) that main's chain of roundings (kae up to
  0.1 um, then Freerouting's 0.2 um width grid) crosses. This happens on **4 boards**. thunderscope rev5-3 has
  track_width 0.19079 (outer) and 0.14789 (inner); ducktop2 center, left_io and right_io have 0.1521. No
  via_diameter or hole_size maximum is affected anywhere.
- **Annular ring:** main rounds a via's drill and diameter up to 1 um each on its own, which shrinks the ring
  below the minimum. thunderscope's 0.4064/0.2032 mm via with a 0.1016 mm ring becomes 0.407/0.204, a 0.1015 mm
  ring: 199 annular_width errors in a control run. This happens on **2 boards**, thunderscope and regymm pynqsdr
  ebaz_sdr (0.50038/0.30226, ring 0.09906). The scan reads only net-class vias and design-setting minimums.

Off-grid minimums are common: net-class widths off 0.1 um on about 200 boards, and via sizes, drills and edge
clearances in design settings on 10-180 boards each. Rounding a minimum up is safe, though, and only last mile and
escapes rounded one down, to the nearest 0.1 um.

## Arms (same recipe and harness as bridge-fixes-ab: main 091163c0, fork d137fd1, 900 s, `--seed {attempt}`)
C main; Q rule-quantize; CB bridge-fixes-combined (b135072a: W2 + L); QL rule-quantize-layers (ebf20ae4: Q + L).
New ids (`REP=rq`) so all arms run side by side in each board's job, kaeq timed class.

| experiment | boards | arms | attempts |
|---|---|---|---|
| `rule-quantize-mech` | `mech.txt` (the 5 scan boards) | C, Q, CB, QL | 5 |
| `rule-quantize-guard` | `guard-hard.txt`: 68 boards, one per repo family, class widths off the 0.1 um grid, all `route_demand` hard/extreme or `pad_density` very_dense/extreme (`select_boards.py`) | C, Q | 2 |

On guard boards, Q changes only the widths kae writes itself (critical router, last mile, escapes). Each moves by
less than 0.1 um: the width is now kept in nm instead of being rounded up. Freerouting's widths are unchanged.

## Outcomes and decision rules
**Primaries (mech), per board as the mean over attempts, each at round 0 (the bridge's DRC after the first
Freerouting route) and on the scorer's final board:**
- grid width errors: track_width errors whose actual width is within 0.2 um of the rule's bound. All track_width
  errors are reported too;
- grid ring errors: annular_width errors whose actual ring is within 1 um of the minimum.

- **Q fixes it** when Q has no grid error of either kind on any final board, and its round-0 totals are each at
  most 10 % of C's. For widths, C must have some on at least 3 of the 4 width boards; for rings, on at least 1 of
  the 2 ring boards.
- **Q subsumes W** when QL has no more grid width errors than CB on any board (final and round 0), and QL's guards
  against CB pass at +10 %.

**Guards** (per board, mean over attempts of log(x + 1), arm minus control, geometric-mean ratio, 95 % bootstrap
interval over boards, B = 4000): x = opens, other errors (all errors except track_width and items_not_allowed),
all errors, and defects (opens + errors). A guard passes when the upper end is below the margin, fails when the
lower end is above it, and is otherwise undecided.
- mech: Q vs C and QL vs CB, margin +10 %. Five boards can't resolve 5 %, so these are reported as descriptive
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
About 0.3-0.5 CPU-h per run. mech: 5 x 4 x 5 = 100 runs, about 45 CPU-h; one job per board runs 20 attempts in
sequence (wall about 5-6 h; 10 h job timeout). guard: 68 x 2 x 2 = 272 runs, about 110 CPU-h. Extension: about
130 CPU-h more.

## Smoke (2026-11-15, before the full run; a local smoke script, kaeq owner rule-quantize)
C (main 091163c0) and Q (e27df322), seed 0, 900 s, fork d137fd1, one run each on thunderscope rev5-3 and ducktop2
right_io, with KiCad DRC run the way the scorer runs it.

| board | arm | round 0 errors | round 0 track_width / annular_width | final errors | final opens |
|---|---|---|---|---|---|
| thunderscope | C | 430 | 190 / 199 | 430 (190 track_width, 199 annular_width) | 499 |
| thunderscope | Q | 48 | 0 / 0 | 8 (length 4, edge 4) | 499 |
| right_io | C | - | - | 3 (items_not_allowed; last mile ripped the width errors) | 138 |
| right_io | Q | - | - | 58 (54 items_not_allowed: L's bug; 4 diff_pair_gap) | 97 |

- **Output.** Q's board has 157 tracks at 0.19079 and 4 at 0.14789 (C: 190 at 0.1908). Vias are 0.408/0.204 (C:
  0.407/0.204). `widths_fitted` is 78 on thunderscope and 27 on right_io. KiCad's SES import takes the fractional
  session width (1907.9 units) as 0.19079 mm.
- **Profile** (py-spy on the python process, JFR on Freerouting d137fd1). Q on thunderscope: 931 s wall, peak RSS
  2.2 GB. Freerouting 55 % (wall-budgeted; JFR: TreeMap, MinAreaTree overlaps, ShapeSearchTree completion, maze
  priority queue). Last mile and repair 18 % (shapely intersection, union, buffer). KiCad DRC 12 %, pcbnew calls
  6 %, rule evaluation 6 %, board I/O 1 %, imports and numba under 1 %.
- **right_io:** Freerouting 81 %, last mile 12 % (grid `_connect`), DRC 3 %. C has the same split.
- **Time and sizing.** The jobs are budget-bound, so no speedup shortens them, and Q adds no measurable time.
  kaeres' default sizing (2 CPUs, about 2-3 GB) matches the measured peak.

## Addendum 2026-11-17, before any run on the new build: current components (guard and zw)
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own.
- **Code.** `rule-quantize` is rebased onto main c81770e1 as `rule-quantize-m2` (the original branch is left as it
  was). Two conflicts, both with main's `bridge-disallow-layers` (#79): `RoutingClass` keeps both its `layers` and its
  `limits` field (resolved as on `rule-quantize-layers`), and two independent new tests in `test_route_critical.py`.
  `test_route_quantize.py` and `test_route_critical.py` pass (98 tests). Q is 13568d89 (was e27df322), Q2 91dfc301
  (was af3cc286); C and ZM are main c81770e1; harness c81770e1.
- **Freerouting:** the pinned fork 9a5512d, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`.
- **Counted work** (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), the project's recipe since these arms were
  registered: each run's nominal budget is the old wall budget (guard: `--time 900`; zw: 900 s x sqrt(fp/40)), and the
  harness timeout is 4x that, as the wall ceiling.
- **New experiments `rule-quantize-guard-m` and `rule-quantize-zw-m`** (owners `exp-rule-quantize-guard-m`,
  `exp-rule-quantize-zw-m`), new method ids, every arm of a board in one job, side by side. All runs of
  `rule-quantize-guard` (107 of 136 jobs done) and `rule-quantize-zw` are on the old build and excluded from the
  decision; their queued jobs are cancelled.
- Boards (guard-hard.txt, 68; zw.txt, 10), arms, attempts (2), primaries, guards and decision rules unchanged.
- **Still worth running:** Q is not in main, and the guard is what clears it for a PR; the zw arms decide whether the
  zero-width fix goes with it. About 160 CPU-h together (queue triage), plus cold numba compiles (the caches are
  per commit).

## Addendum 2026-11-17 (m3), before any run on this build: main 22ff779a and Freerouting f1c41d3
Main (kae #105) and the pin moved after `rule-quantize-guard-m` was submitted: the fork now counts the optimizer's search steps and
pour fills inside `autorouter.max_work`, and kae stops charging optimizer passes on top of that and sets the new
weights. Checked before deciding: on a small board where no budget binds the bridge's copper came out item for item
the same on both builds, but the charged clock did not (53.3 s against 39.1 s). Its arms run the bridge under counted work on boards where the repair and last-mile budgets bind (open nets, hard boards), and those budgets follow the charged clock. So its outputs change
on the new build.
- Migrated: branch `rule-quantize-m3` (rebased on main 22ff779a, no conflict; the -m2 branch is left as it
  was). Arms: C = main 22ff779a, Q = 6b2a86ec; harness 22ff779a. Freerouting fork f1c41d3, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- New experiment `rule-quantize-guard-m3` (owner `exp-rule-quantize-guard-m3`), new method ids. The runs of `rule-quantize-guard-m` (12 jobs done) are on the
  previous build and excluded from the decision; its jobs are cancelled.
- Boards, arms, attempts, primary, guards, looks and the earlier trims unchanged.
