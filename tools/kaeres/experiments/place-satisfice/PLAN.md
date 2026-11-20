<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# place-satisfice: a physics price that stops at "requirement met" (pre-registered plan)

Written 2026-11-20, before any routed run. Code: branch `place-physics-satisficing` off `baseline/2026-w47`
(main `c2dd008`); `kae/` differs from the tag only by the `place_phys_hinge` setting, off by default.
Procedure: the sprint tier of `docs/topics/verification/experiment-tiers.md`. Nothing here is submitted yet.

## Hypothesis

The placer spends placement freedom on physics margin no requirement asks for. If a structure that is inside
its budget costs nothing, its parts move for wirelength and legality instead, placements get less crowded
around pads, and the router leaves fewer connections open, while no structure that met its budget on routed
copper stops meeting it.

## The measured failure it targets

The annealer's physics cost is `Σ_s c_s · u_s / structures` with `u = value / budget`, linear from 0 (a log
tail beyond 3 × budget): a hot loop at 0.4 of its allocation is still paid to shrink. Measured on the
placement audit of 2026-11-20 (155 merit boards, stored outputs of `s2-merit213`):

| Symptom | Number |
|---|---|
| Other parts' pads within 2 mm of a pad, mean count, human vs kae | 0.11 vs 0.34 (kae higher on 95 boards, lower on 25) |
| Support part to IC pin distance, kae / human | 0.91 |
| Placer's own physics sum on split C, kae vs human | 1,410 vs 4,392 |
| Open connections of a physics-weighted arm (seq → seq_phys, 151 boards) | +10.6 % |
| Routed hot loops on kae's placement vs on the human placement | not better (inside evaluator noise) |

Within a board, placer physics does not predict routed physics (seed pairs ρ 0.02-0.18), so the margin bought
at placement is not kept by routing.

## Arms

One setting, `place_phys_hinge` (`kae.route.constraints.DEFAULTS`; `--set place_phys_hinge=θ` on
`kae.joint.cli`, or the project text variable `KAE_PLACE_PHYS_HINGE`). With threshold θ the annealer prices a
structure by `kae.physics.priors.hinge`:

```
cost(u) = 0                                   u ≤ θ
        = (u − θ) / (1 − θ)                   θ < u ≤ 1        (1 at budget)
        = (u − θ) / (1 − θ) + β (u − 1)²      1 < u ≤ 3        (β = place_phys_hinge_beta = 4, the scorecard's barrier)
        = logarithmic tail, value and slope matched           u > 3
θ = 1:  0 up to budget, then (u − 1) + β (u − 1)²
```

Unchanged in every arm: macro-internal layouts are ranked and refined on the raw u (`clusters.build_macros`
runs before the switch), the report's scorecard is the raw one, weights, moves, seed, legalizer, router.

| Arm | Method | Differs from control by |
|---|---|---|
| control | `control place-and-route single c2dd008 fr37b1a8b` of the stored `control-w47` (`kae.joint.cli run --max-iters 0 --no-modules`: place, then the bridge; one fresh attempt per seed, no restart wrapper, counted-work budget 900 s × √(footprints / 40), Freerouting fork `37b1a8b`) | - |
| θ 0.7 | the same template with `--code kae=.@<commit of this branch>` and `--set place_phys_hinge=0.7` | margin below 0.7 × budget is free |
| θ 1.0 | the same, `--set place_phys_hinge=1.0` | everything inside budget is free |

Boards: `bench/suites/sprint-frontier.txt` + `bench/suites/sprint-quality.txt` (140). Seeds: those the stored
control holds, paired by seed. Queue priority 5, at most 40 CPU-h for the two new arms (the tier guard of
`kaeres exp create` prints the estimate and says what to trim).

A board whose brief has no structure, or whose physics is off, takes the same code path in all arms: its
placement is identical by construction (checked by output hash) and it adds a paired zero. The report states
how many boards differ between arms.

## Results that decide

All paired per board and seed against control, from `kaeres exp report` and `kaeres quality` (control =
the control method; near-miss closure and big-board opens separately; quality rows on boards both arms finish):

1. **Open connections**: mean paired Δ log1p(opens) with a bootstrap 95 % interval over boards, and the total.
2. **Crowding**: `tools/research/place/crowding.py` on each run's output board, mean count of other parts'
   pads within 2 mm of a pad; paired ratio arm / control, and against the human placement of the task.
3. **Routed physics** from `kaeres quality`: per module kind (hot-loop cell, decap, crystal, chain) the median
   ratio of the same module's routed value, arm / control, on boards both finish; never the summed score.
4. **Structures over budget on routed copper**: count of modules with routed u > 1, per arm, on the boards
   and modules scored in both arms.

Also reported, not deciding: legality (`placement_errors`, DRC errors by type), HPWL, `cp1` / `cpk`,
completion, CPU.

## Verdict and kill rule

- **Worked**: the opens interval lies below 0 and the routed over-budget count does not rise.
- **Kill** (setting stays off, page marked "did not work"): the opens interval excludes a 5 % gain
  (its lower end is above −5 %), or the routed over-budget count rises against control (more modules over
  budget, paired, beyond the A/A difference of the stored control's seeds).
- **Undecided**: the interval includes both no change and a 5 % gain. Then report the effect, the interval and
  the boards carrying it; no ladder run without the coordinator's say.
- θ 0.7 and θ 1.0 are judged separately; if both work, the one with fewer routed structures over budget is
  proposed, ties to θ 0.7 (it keeps a gradient before the budget is crossed).

Known limit of the design: each arm changes the price both below budget (free) and above it (β = 4 instead of
linear). If the result is mixed, the follow-up arm is `place_phys_hinge_beta=0` (hinge only), not a re-read of
these arms.

## Smoke (placement only, 2026-11-20)

`smoke_place.py` (this folder): `kae place --time 300` with KiCad's DRC loop on the prepared place-fixed input,
counted-work budget, 3 boards × 3 arms × seeds 0-1, plus the off arm run from the tag's code; 21 kaeq jobs,
1.1 CPU-h. Crowding = mean count of other parts' pads within 2 mm of a pad (`crowding.py`; it reproduces the
audit script's count exactly on a test board).

| Board (footprints, priced structures) | Human | Control, seeds 0 / 1 | θ 0.7 | θ 1.0 | Over budget at placement: control; θ 0.7; θ 1.0 |
|---|---|---|---|---|---|
| juniper-garden-twig temp-sensor (56, 29) | 0.88 | 0.87 / 0.90 | 0.73 / 0.74 (−17 %) | 0.93 / 0.70 (−8 %) | 13, 10; 6, 9; 8, 10 |
| kata0510 rp2040-8key (55, 18) | 0.60 | 1.48 / 1.45 | 1.10 / 1.42 (−14 %) | 1.35 / 1.40 (−6 %) | 1, 1; 2, 1; 2, 4 |
| zhiayang mikoto (67, 22) | 3.45 | 4.38 / 4.18 | 4.71 / 4.09 (+3 %) | 4.30 / 4.57 (+4 %) | 1, 6; 1, 1; 1, 1 |

1. Legal: all 21 placements pass kae's exact check and KiCad's DRC with no error the placer caused (juniper
   keeps one courtyard overlap between two fixed switches in every arm, control included).
2. Setting off = the tag: the off arm's output board is byte-identical to the one placed by the tag's code
   (`c2dd008`) on all three boards (seed 0, sha256 of the written board).
3. Crowding: lower with the hinge on two boards, not on the third. The spread between two seeds of one arm
   (up to 0.3) is as large as the effect, so three boards do not show that crowding falls; the sprint's
   paired crowding row does. θ 0.7 moved more than θ 1.0 on both boards that moved.
4. Structures over budget at placement (raw scorecard) did not rise in total: 32 (control), 20 (θ 0.7),
   26 (θ 1.0) over the six runs each.
5. Limit: on juniper the seed legalizer used the budget and the annealer made 10,000 of 176,000 planned moves
   in every arm; its difference comes from that short anneal.

## Commands (when `control-w47` is complete; do not improvise another procedure)

```bash
K="python3 tools/kaeres/kaeres.py"
SHA=$(git rev-parse origin/place-physics-satisficing)
# the control's template, read from the store (kaeres method show), with the kae code and one --set changed:
#   ... {py:kae} -m kae.joint.cli run {input} {output} --seed {attempt} --time $(( {timeout} / 4 )) \
#       --max-iters 0 --no-modules --set place_phys_hinge=0.7        (and =1.0)
#   --kind joint-fixed --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 \
#   --code kae=.@$SHA --harness baseline/2026-w47
cat bench/suites/sprint-frontier.txt bench/suites/sprint-quality.txt > "$TMPDIR/sprint.txt"
$K exp create place-satisfice --boards "@$TMPDIR/sprint.txt" --reuse-runs \
   --method "control place-and-route single c2dd008 fr37b1a8b" \
   --method "place-satisfice theta 0.7" --method "place-satisfice theta 1.0" \
   --harness baseline/2026-w47 --kae baseline/2026-w47
$K exp submit place-satisfice && kaeq prio 5 --owner exp-place-satisfice
$K exp report place-satisfice && $K quality place-satisfice --control "control place-and-route single c2dd008 fr37b1a8b"
```
