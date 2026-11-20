<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Ground-side price for two-layer boards: build notes

Design 3 of the 2026-11 gap audit. Stage 0 measured that on 43 two-layer boards every arm
finishes, signal track over opposite-layer ground copper is 0.53 for the human layouts,
bridge 3.7 points lower [-6.3, -1.0] and staged place-and-route 9.8 points lower
[-13.7, -6.1]. The router had no price on the ground side: `translate.plane_layers` only
reads inner layers.

## What the branch does

- `kae/src/kae/route/ground_side.py`: `ground_side(info)` names the outer layer of a
  two-layer board that one ground net's zones (`kae.circuit.names.GND_RE`; rule areas and
  teardrops left out) cover over at least `PLANE_SHARE` (0.30) of the outline. Both sides
  qualify: the side with less SMD pad area; tie: the back layer. `rules()` builds the
  Freerouting rules file with that layer at k (preferred) and 2k (against).
- `translate.apply`: one hook after the plane-cost block. It runs only when
  `plan.ground_side_cost` is set. When it applies, `plan.layer_rules` is the priced rules
  file and the translate summary (`report["translate"]`) gets
  `ground_side: {layer, net, cost}`. The layer stays a signal layer.
- `translate.zone_cover`: the zone and outline cover that `plane_layers` computed inline,
  now shared by both. `plane_layers` returns the same as before.
- Setting `ground_side_cost` in `constraints.DEFAULTS` (None = off), read in
  `constraints.plan` with `setting()`. The board's `KAE_GROUND_SIDE_COST` text variable
  wins, then opts. `bridge.py` is not touched: every route path (bridge, repair,
  incremental, blocked) builds its plan with `constraints.plan(info, board, opts)`, so
  `--set ground_side_cost=4` on `kae.route.cli route` reaches it. `kae.joint.cli` accepts the
  key because it is in `constraints.DEFAULTS`; the joint and staged paths were not smoked.
- Off by default; values <= 1 also mean off. With the setting off, `layer_rules()` and the
  translate summary are unchanged (golden strings in the tests).

## Tests

`kae/tests/test_route_ground_side.py` (7 tests): back pour; both sides by SMD pad area and
the tie; four layers, no zone and 28 % cover give {}; `layer_rules` golden strings (None,
outer surcharge, four-layer plane); off for None, 0 and 1; k=4 prices only the ground-side
line at 4 / 8, under the DSN's own layer names; `setting()` from opts and from the board.
With `test_route_specctra`, `test_route_plan_rules`, `test_route_rules`,
`test_route_fr_entry`, `test_route_pad_entry` and `test_joint_report`: 126 passed.

## Smoke

Two two-layer boards with ground pours on both sides, `kae.route.cli route --seed 1
--time 240` with `KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`, the pinned Freerouting
fork, kaeq priority 5 (6 jobs, 0.1 CPU-h). Arms: main (c2dd008, no option), off (this
branch, no option), on (this branch, `--set ground_side_cost=4`). Both boards are poured
with GND on both sides; `ground_side()` picks B.Cu on both (necroware: no SMD pads, tie
goes to the back; papilio: front 34.4 mm^2 of SMD pads, back 0).

- **Off equals main.** On both boards the DSN is identical apart from its own path line,
  no `.rules` file is written, Freerouting's session is byte-identical, the translate
  summary is equal, and the output board has the same items (only item order and the
  random UUIDs of new copper differ).
- **On applies the price.** The translate summary records
  `ground_side: {layer: B.Cu, net: GND, cost: 4.0}`, `board.rules` prices B.Cu at 4 / 8 and
  F.Cu at 1 / 2, and a board comes out with the same DRC result as main (necroware 0 errors,
  0 unconnected; papilio 0 unconnected and the 9 `copper_edge_clearance` errors that the
  input already has).

Return coverage with the stage-0 prototype measure (`s0_return.measure`, not committed;
cov_opp = share of signal track length over opposite-layer ground copper):

| board | arm | signal mm | cov_opp | no ground near (mm) |
|---|---|---|---|---|
| necroware-dram-tester | human | 567 | 0.60 | 156 |
| | main | 499 | 0.38 | 199 |
| | on (k=4) | 529 | 0.70 | 113 |
| sparkfun-papilio-button-led-wing | human | 223 | 0.71 | 11 |
| | main | 234 | 0.57 | 43 |
| | on (k=4) | 226 | 0.70 | 15 |

Two boards and one seed: this shows that the mechanism acts in the intended direction, not
how large the effect is.

## Sprint arms (ready for sprint)

The sprint command (`bench/suites/README.md` on `experiment-tiers`) does not exist yet, so
no experiment was run. Arms, one change:

- control: the bridge method at the current main and fork pin, no option.
- treatment: the same method with `--set ground_side_cost=4` appended to its
  `kae.route.cli route` (and `lastmile`) commands.

Boards: two-layer boards with a ground pour. `bench/suites/mech/pours.txt` on
`suite-coverage` is any pour over a fifth of the board, not only two-layer ground pours;
filter it to two-layer boards where `ground_side()` names a layer.

## Not done

- The A/B itself: waiting for the sprint command and control (see above).
- `PLAN.md` was added after these notes were written (next commit); nothing of it has run.
- The joint loop and staged place-and-route paths take the setting through
  `constraints.plan` but were not smoked.
- Boards with an inner plane are untouched by design: `ground_side()` needs exactly two
  copper layers.
