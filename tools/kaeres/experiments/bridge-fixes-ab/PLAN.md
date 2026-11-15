<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# bridge-fixes-ab: two bridge fixes as default changes, each alone against main (pre-registered plan)

Written 2026-11-14, before any full run. Smoke and profile: section "Smoke". Context:
[diffpair-fixes-2611](../../../../docs/research/routing/diffpair-fixes-2611.md) (branch `diffpair-ab4`), where both
fixes were found and put into every diffpair-ab4 arm, the control included. That experiment cannot say what either fix
does on its own; this one does.

## The two fixes
- **W, `bridge-ses-width` (e93216a3):** Freerouting keeps a trace's half width in whole session units (0.1 um), so a
  class width of an odd number of units comes back one unit wider (0.1521 -> 0.1522 mm). Where the board's rule has
  max = that width, every such wire is a `track_width` error (92 on one ducktop2 right_io board). `fix_session` gives
  a wire its class width back when the session's is at most one unit above it.
- **L, `bridge-disallow-layers` (e6741eb8):** kae's rule port did not read `(constraint disallow track)`, so
  Freerouting routed classes on layers the board forbids them (`items_not_allowed`). `constraints.plan` splits classes
  by the layers their tracks are disallowed on and writes `(circuit (use_layer ...))`. Geometric conditions are not
  read (rule areas cover those).

Both are one commit on main 091163c0 (main's head when written; nothing to rebase).

## Where each mechanism exists (`select_boards.py`, from the board corpus and the tag tables)
The scan reads, for every `usable_route_test` board, the widths kae may give a class (net-class `track_width`,
`diff_pair_width`, KiCad 5 net classes, a `.kicad_dru` track_width's opt or min) and the `.kicad_dru` disallow rules.

- **Odd-unit widths (W acts):** 268 boards. The tag was checked against stored outputs: 35 of the 47 of these boards
  with an earlier bridge run have wires at exactly class width + 0.1 um (`scan/prior_widened.txt` in the work dir).
  The rounding only makes errors where a rule's max equals the width: 4 boards (`mech-width.txt`: thunderscope
  rev5-3, ducktop2 center, left_io, right_io). Earlier bridge runs show `track_width` errors on no other board.
- **Disallow-track rules (L acts):** 10 boards; 7 condition on nets, classes or layers (`mech.txt`); 3 condition only
  on areas or courtyards (stab-rabbit serenity pilot and tacco, techmiguel stillpoint), where L does nothing.

## Experiments and arms
Same harness (main 091163c0) for every method, Freerouting fork d137fd1 (the pin) named in every recipe, 900 s,
`--seed {attempt}`, kaeq timed class, `KAE_STEP_CACHE` (result-neutral). `setup.sh` registers the methods.

| experiment | boards | arms | attempts |
|---|---|---|---|
| `bridge-fixes-mech` | `mech.txt` (7) | C, W, L | 5 |
| `bridge-fixes-odd` | `boards-odd.txt`: 85 boards, one per repo family, all `route_demand` hard/extreme or `pad_density` very_dense/extreme, W acts, no binding rule | C, W | 2 |

L is not run on the odd boards: it writes the same DSN there as C (checked byte for byte on 12 boards before the run,
section "Smoke"), so it cannot change them.

## Outcomes and decision rules
Primary, W (on the 4 `mech-width.txt` boards): `track_width` errors whose actual width is above the rule's max by at
most 0.15 um (the bug's signature), per board, mean over attempts; all `track_width` errors reported. **W fixes it**
when W has none on any attempt and C has some on at least 3 of the 4 boards.

Primary, L (on the 7 `mech.txt` boards): `items_not_allowed` errors on tracks, per board, mean over attempts.
**L fixes it** when L's total is at most 20 % of C's and L is no higher than C on any board where C has one.

Guards, each arm against C: per board, mean over attempts of log(x + 1), arm minus C, for x = opens (unconnected
items), the DRC errors other than the primary's type, and all errors; geometric-mean ratio with a 95 % bootstrap
interval over boards. A guard **passes** when the interval's upper end is below the margin, **fails** when its lower
end is above it, else it is undecided.
- W: all boards W ran (odd + mech), margin +5 %.
- L: the 7 mech boards, margin +10 %: L takes layers away from classes on purpose, so some opens may be the price of
  keeping the board's rule; 7 boards cannot resolve 5 %.

**Adopt** a fix as the default when its primary holds and its guards pass. A guard that fails rejects it as is.

## Noise, and why these sizes
A/A spread of the same bridge control on the same boards (diffpair-ab4 PLAN: three runs of 108-120 boards): total
opens -0.9 % to +4.3 %, per-board SD of the log ratio of two single runs 0.34-0.42 (per-run sigma ~0.28); DRC errors
differ 3.4 % between replicates elsewhere (loop-polish). With per-board heterogeneity ~0.1, the board-level SD of the
arm-minus-C mean is about sqrt(2 * 0.28^2 / k + 0.1^2): 0.30 at k = 2, 0.20 at k = 5.
- W guards: 92 boards at k = 2 (mech at 5) give a standard error of ~0.031, a 95 % interval of about +-6 %. A true
  effect of 0 is then decided at the +5 % margin only when the observed ratio is below ~0.99, so round 1 may well be
  undecided; the extension below brings the interval to about +-4.5 %.
- W primary: the signature is deterministic (each widened wire on a min = max rule is an error); C had 37-92 of them
  per run on right_io.
- L guards: 7 boards at k = 5, standard error ~0.08 (+-16 %) without heterogeneity: likely undecided at +10 % in
  round 1; extension to k = 10 (+-11 %).
- L primary: C had 2-44 `items_not_allowed` per run on right_io; a deterministic layer ban should remove nearly all.

Extensions (pre-registered, run only if a guard is undecided after round 1): W: the next 65 boards of `ordered.txt`
(`boards-odd-ext.txt`, not hard-tagged), then a third attempt on every odd board. L: attempts 5-9 on the mech boards.
Looks: after round 1 and after each extension, each at the 95 % level (three looks at most; reported as such).

## Reported
Per arm against C: the primaries per board, guards with intervals, totals, cp1, cpk, completion, CPU, per-type DRC
errors (read before any verdict), the boards whose opens moved most and why. `analyze.py bridge-fixes-mech
bridge-fixes-odd`.

## Smoke (2026-11-14, before the full run; experiment `bridge-fixes-smoke`, methods without REP)
ducktop2 right_io and tigard, C/W/L, 1 attempt.
- **Mechanisms seen at the first route** (the bridge's repair round 0, DRC after the first Freerouting session):
  C 78 track_width + 44 items_not_allowed; W 0 track_width (50 widths restored) + 52 items_not_allowed;
  L 88 track_width + 0 items_not_allowed (the DSN carries 6 `use_layer` circuits, classes 6 -> 7).
- **Final boards hide part of it:** C's last mile ripped every erroring item ("rip errors": 64 errors -> 0, opens
  111 -> 136, final 133 opens / 0 errors); W ended 85 opens / 68 errors (59 items_not_allowed: L's bug), L 102 / 49
  (44 track_width: W's bug). So the bug's errors can turn into opens, and on these boards each arm keeps the other
  fix's bug. **Addendum to the outcomes (written before the full run):** each primary is measured at round 0 (from
  the run's route report) as well as on the scorer's final board, and decided on round 0: W fixes it when its round-0
  track_width total on the 4 width boards is at most 20 % of C's, C has some on at least 3 of them, and W has no
  signature error on any final board; L when its round-0 items_not_allowed total on the 7 boards is at most 20 % of
  C's, no higher than C on any board where C has some, and its final tracks-not-allowed total is no higher than C's.
  Guards gain `defects` (opens + errors), and "other errors" leave out both track_width and items_not_allowed.
- tigard (odd widths, no binding rule): C, W and L gave the same board result (3 opens, 24 errors, the same types).
- **DSN identity (L acts nowhere else):** the bridge's DSN from C and L is byte-identical except the header's path on
  tigard, olimex nb-iot, matgla gpu-vga, ducktop2 bms and techmiguel stillpoint (a courtyard-conditioned disallow
  rule); it differs, with `use_layer`, on right_io (6) and the keyboard daughterboard (5). The two stab-rabbit boards
  could not be exported from the raw corpus file (KiCad 9 format; prepared tasks are upgraded).
- **Profile** (C, right_io, py-spy on the python process, JFR on Freerouting d137fd1): 867 s wall, 1,010 s CPU,
  peak RSS 1.7 GB. Freerouting 79 % (wall-budgeted; JFR: MinAreaTree overlaps, maze priority queue, search-tree
  completion), last mile and repair 12 %, KiCad DRC 3.6 %, pcbnew calls 2 %, rule evaluation 1.3 %, numba compile
  0.8 % (cold; warm caches made for the three commits), imports 0.7 %. The run is budget-bound, so no speedup shortens
  a job; W and L add no measurable time. Job sizing: kaeres' estimate (2 CPUs, ~2 GB) matched the measured peak.

## Expected cost (information, not a limit)
About 0.3-0.5 CPU-h per run (900 s budget, ~1,000 CPU-s routing, plus scoring and physics). `bridge-fixes-mech`
7 x 3 x 5 = 105 runs on 800-3,600-pad boards, ~50 CPU-h; `bridge-fixes-odd` 85 x 2 x 2 = 340 runs, ~120 CPU-h.
Extensions if needed: W +65 boards x 2 x 2 (~90 CPU-h) and a third attempt (~75 CPU-h); L attempts 5-9
(7 x 2 x 5 = 70 runs, ~35 CPU-h).
