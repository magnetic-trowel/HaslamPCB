<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: ground-side-ladder (ground-side price on 2-layer boards, ladder confirmation)

**Hypothesis.** Pricing signal tracks on the ground-pour side of a 2-layer board (`ground_side_cost`) raises the share of
signal track length over ground copper (`cov_opp`) on boards it has not been tuned on, without losing clean boards.
The via cost grows with the price, so a lower price (2) may keep most of the gain for fewer vias.

**What passed sprint.** ground-side-ab (sprint, `mech/ground-pour-2layer`, 59 boards, 118 pairs): `cov_opp` +8.4 points
[+5.5, +11.6], clean net of input 44 → 43 (within the guard), vias x1.20 [1.08, 1.37], track x1.04.

**Measure.** `kaeres quality NAME --control '<control>' --return-rows` (`tools/kaeres/quality.py` + `return_board.py`).
Before this run, `return_board.py` was checked against KiCad's own geometry (`tools/kaeres/return_check.py`: real refill,
pcbnew item shapes) on 5 boards x 3 layouts with null, slot and added-ground mutants; two measure bugs it found are
fixed on this branch (zone cutouts read as pour; outlines of lines and arcs left open). See `VALIDATION.md` beside this file.

**Mechanism and suite.** Ground pour on a 2-layer board. Suite `bench/suites/mech/ground-pour-2layer-ladder.txt`: the 146
2-layer boards of `ladder.txt` on which `kae.route.ground_side.ground_side()` names a pour side, exported with KiCad
from the corpus board: 95 boards (67 B.Cu, 28 F.Cu); 11 whose control runs cost over 0.5 CPU-h are skipped, 84 run. None is in a sprint suite, so the result is out of sample. The
other 51 2-layer ladder boards have no qualifying pour: the setting does nothing there by construction (the price
needs a side), so they are left out rather than paid for.

**Arms.** One change: the setting. All arms are the stored control recipe of `control-w47` at tag `baseline/2026-w47`.

- control: `control bridge single c2dd008 fr37b1a8b` (`71e60a91475d`), stored runs reused; boards without a stored run
  get it in this campaign (control fill).
- gs4: the same recipe at `9a3bbca` (`d3-ground-side`: the tag plus the setting) with `--set ground_side_cost=4`.
- gs2: the same with `--set ground_side_cost=2`.

Seed 0 only, paired with the control's seed 0 (two seeds were estimated at 181 CPU-h by the guard, and the sprint's
actual cost was twice its estimate; one seed on 84 boards gives about the sprint's 118 pairs' precision). Command:
`kaeres sprint ground-side-ladder --tier ladder --base bridge --commit 9a3bbca --suite ground-pour-2layer-ladder
--arm gs4:ground_side_cost=4 --arm gs2:ground_side_cost=2 --attempts 1 --skip-over-cap --smoke 2`, then `kaeres exp submit
ground-side-ladder --prio 5` after the smoke. Priority 5.

**Endpoints** (each arm against the control, paired per board and seed, owner bootstrap 95 % intervals):

- Primary: `return: cov_opp`, mean B − A on boards both finish.
- Guard: clean net of input (`xc`), near-miss closure, big-board opens (none expected: all boards are small).
- Cost, reported for both arms: vias (median ratio), track length, errors added by type, CPU.
- Secondary: `cov_any`, `fast_cov_opp`, `unc_mm`, physics module ratios.

**Deciding result** (per arm):

- Confirmed: `cov_opp` interval above 0, and `xc` not worse (its interval does not lie wholly below 0) and near-miss
  closure not worse.
- If both arms are confirmed, the default is the one with fewer vias (median ratio) unless its `cov_opp` gain is under
  two thirds of the other's; vias for both are reported either way.
- Undecided: `cov_opp` interval includes 0. Not adopted; reported with the estimate.

**Kill rule.** Stop and do not change the default if, at both prices, the `cov_opp` interval includes 0 or the clean
guard is worse. Cancel the campaign if the queue projects it over 200 CPU-h (the guard's estimate is printed at
create; the smoke's measured cost is checked against it before the rest is submitted).

**CPU.** At most 200 CPU-h. Guard estimate about 90 (two arms and the control fill on 82 of the 84 boards, one seed:
250 method-runs; 181 for two seeds); the sprint ran at twice its estimate, so up to about 180 is possible. The smoke's
and the 25 % mark's measured CPU per run are projected to the whole; over 200 projected, the campaign is cancelled.

**Afterwards.** The one-line default change is ready on branch `ground-side-default-on` (`constraints.DEFAULTS
ground_side_cost` None → the chosen price; `--set ground_side_cost=0` keeps the old behaviour). It is merged only on a
confirmed result, with the price this plan chooses.
