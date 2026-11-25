<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Handoff: solar-small and the haslam fixes it drove (2026-11-25)

Scope: the state of the solar-small charger design and of every haslam change it produced, and how a new agent should proceed.
Keys: handoff, solar-small, merge candidates, integrate-w48, physics advisor, intent relations, facts everywhere

## Goal and priorities (user)

Take a design from brief to manufacturing files through haslam, and use the experience to improve haslam. **Improving haslam
matters more than the board.** Rules: every intent field is used by haslam or removed (nothing stated is ignored); every
haslam behaviour change is the weekly tag + one change with its own experiment (`docs/topics/verification/experiment-tiers.md`
on branch experiment-tiers; sprint ≤ 40 CPU-h, priority 5, board cap 0.5 CPU-h/run, mechanism suites, `mechscreen` to pick
boards); scorer changes go in separate commits and are re-scored (CLAUDE.md). Process doc: `docs/topics/workflow/brief-to-board.md`.

Where state lives: each experiment's `PLAN.md`/`VERDICT.md`/`PR-BODY.md` in `$HASLAM_RESULTS/experiments/<name>/`
(default `~/haslam-baselines`); the merge summary in `$HASLAM_RESULTS/experiments/MERGE-READY.md` and `MERGE-CANDIDATES-w48.md` (copy of MERGE-READY: `docs/research/handoff-2026-11-merge-ready.md`).

## The board (solar-small)

Design: `tools/research/llm-design/designs/solar-small/` (branch `solar-small`; best design on `solar-small-fb`; unified
relations emitter on `haslamsynth-relations-unified`). LTC3130 buck-boost (panel ≤ 25 V → 12-14 V battery), TPS62933 3.3 V,
DAC63002 setpoint injection, LTC2959 coulomb counter, FireBeetle ESP32-C6. Fab outputs: `synth/scripts/fab_outputs.py`.

- Feedback pickup was the board's main harm (≈ 400 mV vs 5/16 mV limits), entering through the 22 pF feed-forward caps.
  Fixed on `solar-small-fb`: 8.2 pF + 249 kΩ series on C117, 100 kΩ series on C307 → 0.9-3.6 mV, every limit met
  (`RESULTS-fb.md`). TPS62933 series R is not datasheet-backed: load-step test on hardware.
- **Open, real:** U101 overshoot ring 2.75 V at 25 V panel input vs 2 V headroom to its 27.5 V abs max (T-OS101 restated
  on haslamsynth-relations). Fix: limit panel Voc, tighter input hot loop, or TVS/snubber; score with the evaluator.
- **Open:** LTC3130 effective COUT below DS Table 3 (20 µF at 13.5 V; 2×10 µF X5R gives ≈ 8 µF): advisor proposed +3×10 µF
  (DAC supply noise 1.32 V → 29 mV, but U201 SYS noise doubled: attribute before adopting). State M301's real current in facts.
- Evaluating solar-small needs all evaluator fixes together: use `integrate-w48` (+ `gfix-dc-own-loads`, `gfix-facts-sections`).

## haslam changes: status

Ready (verdict better; PR branches `pr-w48/*` off main, bodies in MERGE-READY.md; merge order there; **PRs opened 2026-11-25: #154 clock, #155 pnr-soft, #156 netrules, #157 stitch+kconn, #158 em-topology, #159 dc-model-2, #160 advisor (after #159), #161 haslamq, #162 mechscreen. (Earlier note:
GitHub API was blocked from the host — open from `https://github.com/magnetic-trowel/HaslamPCB/compare/main...pr-w48/<name>`**):

| Change | Branch | Evidence |
|---|---|---|
| test clock flake fix (merge first) | pr-w48/test-budget-clock | main's own flaky test |
| pnr copper soft for the last mile + physics guard | pr-w48/gfix-pnr-soft | opens −1.0/run [−1.33, −0.67], physics no worse |
| placer enforces net-conditioned .kicad_dru rules | pr-w48/gfix-place-netrules | clearance errors −91, 0 worse |
| last mile connectivity = KiCad (touch rule) + pour stitching vias | pr-w48/gfix-stitch-on-kconn | opens −0.63/run [−1.20, −0.17] |
| field mesh topology-safe (scorer) | pr-w48/gfix-em-topology | eval complete on fine pitch; haslamres physics identical 40/40 |
| evaluator DC model (scorer) | pr-w48/gfix-dc-model-2 | DC band computes; T-TJ plausible |
| physics advisor v2 + session protocol | pr-w48/physics-advisor | 22/24 what-ifs within 4 % of full solves |
| haslamq: scoped retry, snapshots without git identity, --kicad | pr-w48/haslamq-retry-scope | run tools/haslamq/install.sh after merge |
| mechscreen | pr-w48/mechscreen | tooling |

Integration branch `integrate-w48` (main + all of the above + facts sidecar): 1701 tests pass.

Done after integrate-w48, not yet in a PR branch (each has PR-BODY in its experiment folder):
- `gfix-dc-own-loads` (scorer): loads draw their own current (U201 1.5 W → 1.35 mW). `gfix-facts-sections`: facts check
  accepts provenance/pins/radios (**required** for physics-set evaluation on integrate-w48).
- `intent-wiring`: status reads the board's intent file; overshoot uses stated v_sw_max_V; stated rail V wins; every term/knob
  has a reader (`haslam.intent.uses`). Verified.
- `facts-everywhere` (on intent-wiring): stated rating sets hot-loop budget; heat sized after facts; controller f_sw/t_i reach
  cells. A/B physics ×0.90 [0.83, 0.97] on 5 boards (weak base: run the 15 over-cap boards in the ladder).
- `relations-unified` (off main): #141's relation framework + our pad-to-pad measure, pricing of near/group, board intent file
  through every stage. Output-neutral without intent; solar-small relations met 7-10 → 15-18 of 20. haslamsynth emits it on
  `haslamsynth-relations-unified`.

Undecided: `gfix-thermal-ring` (screened rerun −0.68 opens/run [−1.56, +0.06]; not harmful). Superseded: `intent-relations`
(use relations-unified), `haslamsynth-relations` (use -unified), `gfix-dc-loads` commit B (connector exports only when stated:
breaks completeness; option: keep unstated exports at 1 % of rating, measure separately).

## Decisions waiting on the user

1. Review and merge PRs #154-#162 in MERGE-READY.md's order.
2. gfix-dc-loads rule B: drop, or the 1 % option.
3. Relations vs physics: #141 lets physics win (relation weighted weak where place terms price the parts); keep or give stated
   relations full weight.
4. Re-score the 11 over-cap physics-set boards (~170 CPU-h) — deferred by the user.

## How to proceed (next agent)

1. Read this, `brief-to-board.md`, MERGE-READY.md and the VERDICT.md files above; check `haslamq status` for nothing pending.
2. After merges: rebase `intent-wiring` → `facts-everywhere` → `gfix-dc-own-loads` + `gfix-facts-sections` → `relations-unified`
   onto main as one PR each (tests, then the experiment's own check), re-score stored haslam.excite evaluations (scorer changes).
3. Fix the eight remaining ignored-facts gaps listed in `docs/topics/workflow/intent-file-fields.md` (range_V-only nets, t_sw
   re-derivation, series-fed rails, critical router's T_amb/eta/I_A, place/heat + power_copper + thermal_vias reading only
   HASLAM_OPERATING, worst-corner overshoot budgets, power-path current prior, pnr skipping term budgets); A/B what changes placement.
4. Advisor next steps (`docs/research/physics-advisor.md`): first-order check from stored copper potentials (missed T2 by 23 %),
   per-edit attribution in verify, move-existing-part remedy, a default priced supply-noise term, re-layout loop with relations.
5. Board: fix the U101 overshoot, COUT, and state M301's current; re-run place-and-route with the unified relations and score.
6. Run every new haslam change the documented way: branch off the current weekly tag, PLAN.md first, smoke, ≤ 40 CPU-h, verdict.
