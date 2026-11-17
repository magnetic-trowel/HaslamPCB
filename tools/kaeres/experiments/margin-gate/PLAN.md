<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# margin-gate: the auto margin, gated to dense boards and capped per region (pre-registered 2026-11-16)

Written before any run of this experiment. Code: branch `margin-gate` (`kae/src/kae/place/margin_gate.py`);
registration: `tools/kaeres/experiments/margin-gate.sh`; analysis: `analyze.py` here.

## Question
margin-ab (60 boards, k=1; control `6c9adb94b936`, M2 `ba3326ec9ca6`, MA `3245520a0385`) found the auto
margin (`place_margin=-1`) a possible gain of about −5 to −8 % opens per board, not separable from A/A noise,
concentrated on dense fine-pitch boards, with one systematic harm (davang breakout-boards: movable parts pushed
across cutouts, crossing opens 24 → 31-37). main still defaults to `place_margin=0` (the earlier
placement-decide-staged A/B found auto and 0 equal), so the control is margin 0.

Does the auto margin, applied only on boards dense per copper layer and capped at each region's own room,
lower opens on dense boards, and leave other boards alone?

## The change (both settings off by default)
- `place_margin_gate=4`: keep the margin only when every pad of every footprint over the outline area is at
  least 4 per cm² per copper layer; else margin 0. Threshold chosen on margin-ab (MA vs C, Δlog1p opens):
  - ≥ 4 pads/cm²/layer: 14 boards, 6 lower / 0 higher, mean −0.31; below: 46 boards, 1 lower / 6 higher, mean −0.006.
  - The suggested "finest_pad_gap < 0.25 mm" clause does not separate: of the gap < 0.25 boards under 4
    pads/cm²/layer, 1 was lower and 5 higher (jetson, sycamore, siderakb, dasduino, tft-bonnet). It is left out.
  - 2.3 pads/cm²/layer (the median) lets in 3 of the 6 harmed boards. 4 is post hoc on 13 boards that moved,
    which is why this test uses only boards margin-ab did not use.
- `place_margin_regions=1`: regions are the outline minus rule areas no track may cross, with necks narrower
  than 6 mm cut (sub-boards between cutouts; davang splits into 7). Anchored parts sit in the region of their
  pads; a movable part joins the region of the anchored parts it shares nets with (label propagation, a net
  voting 1/(pins − 1), signal nets first). Each movable part's margin is capped at its region's auto margin
  (2 × (0.7 − region utilization), 0..1 mm): the auto margin's capacity charge, made per region. A board that
  is one region is unchanged. Cost: under 1 s per board in the probes.
- Not in this test: board-level mask graphics as placer obstacles (wickerbox, a separate bug).

## Arms (side by side, one job per board runs all three)
All at one commit, kae staged restart portfolio of margin-ab (`kae.joint.cli --max-iters 0 --no-modules`;
restart.py `--parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final lastmile
--check-placement`), counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`, nominal 900 s ×
sqrt(fp/40), harness timeout the 4× wall ceiling), Freerouting fork d137fd1 set explicitly
(`KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`).
- **control**: `place_margin` 0 (main's default).
- **MA**: `--set place_margin=-1`, ungated.
- **MA gated**: `--set place_margin=-1 --set place_margin_gate=4 --set place_margin_regions=1`.

The project's Freerouting control is switching to the work-counting build abefc74 when kae PR #97 and
freerouting PR #11 merge. This experiment keeps d137fd1 in every arm; a later re-run on abefc74 must keep
one build across its arms too.

## Boards (163, k=1; each run's first wave is 4 seeds)
`select.py` (seeded, one board per repo), from the board-tag suites, intersected with `usable_route_test`
and `prepared_task`, excluding margin-ab's 60 boards:
- **dense-hi** (90): `pad_density.dense` ∪ `very_dense` (10-50 pads/cm²) with ≥ 4 pads/cm²/layer
  (73 two-layer, 16 four-layer, 1 six-layer). The gate keeps the margin here: the gain should show.
- **dense-lo** (40): the same suites below 4 pads/cm²/layer (mostly 4-8 layers). The gate drops the margin.
  MA vs control here tests the threshold: a real MA gain here would mean the gate throws it away.
- **sparse** (20): `pad_density.sparse`, ≥ 15 footprints. The gate drops the margin.
- **barrier** (13): boards of the barrier study (`bwab2-analysis/seed.jsonl`: nets crossing a barrier at
  the seed) that split into ≥ 2 regions by the neck rule, ≥ 20 parts; davang included as the known case
  (it was in margin-ab; it is here for the mechanism, and reported apart). 4 of them are ≥ 4 pads/cm²/layer,
  so the region caps act there; on the other 9 the gate drops the margin.

The density tags are geometric (pads over area); kae's own count matched the extractor's on the probes
(2.279 vs 2.278, 6.37 vs 6.34).

## Metrics and decision
**Primary** (per-attempt, paired by seed; `analyze.py`): fresh attempts (restarts.json `attempt_log`,
`resumed_from` null) both arms ran with the same seed; Δ = log1p(opens) difference per seed, opens = the
restart judge's unconnected count; per-board mean over its paired seeds; mean over boards with a 95 %
bootstrap CI; MDE at 80 % = 2.8 × SD / √n. Reported per stratum.

Hypotheses and how each is read:
1. **Gain kept (deciding):** MA gated vs control on dense-hi. A gain is a mean below 0 with the CI excluding 0.
2. **Threshold:** MA vs control on dense-lo. CI excluding 0 below 0 means the gate is too strict (lower it,
   re-test); a null with MDE under 15 % or a harm supports the gate.
3. **Gate does nothing below the threshold:** on dense-lo, sparse and the 9 gated-out barrier boards, MA
   gated runs the control's code path with margin 0. Their per-seed opens should be equal; the share equal
   and the spread of the rest are this test's own A/A floor (the same code twice), reported beside every CI.
4. **Barrier:** MA gated vs MA on the barrier boards, per board, with the opens whose pin-to-pin line
   crosses a cutout (as in margin-ab's davang reading). Too few boards for a CI; read board by board.

**Guards** (delivered, `kaeres exp report`): delivered opens (per-board mean Δlog1p, not the ratio of sums),
cp1/cpk (= cp1 at k=1), completion, legality, DRC errors by type against the A/A band (aa-joint: ±1.96 ×
SD × √n of summed twin deltas), CPU and counted work, ceiling hits. Plane-net and signal-net opens apart
where the primary moves.

**Adopt** `place_margin=-1, place_margin_gate=4, place_margin_regions=1` as the default (its own PR) if
(1) holds and the guards hold. If MA ungated is as good as MA gated on every stratum (2 and 3 show no
difference), the simpler ungated MA is the candidate instead. A credible small gain with guards holding is a
gain; a null with the CI spanning both signs is "unknown".

## Power (measured, not assumed)
From margin-ab's restart logs (MA vs C, mean over each board's first 4 restarts, Δlog1p): SD 0.45 over all
60 boards, 0.51 over the 15 boards open in the control, 0.80 over the 14 dense ones (the effect itself
varies there). Delivered k=1 dense-group SD was about 0.46. For dense-hi (n=90): MDE80 is 14 % at SD 0.45,
19 % at 0.6, 27 % at 0.8. margin-ab's ≥ 4 pads/cm²/layer group moved −27 % (n=14, wide CI).

**One pre-registered extension:** if after all 163 boards (1)'s CI includes 0 and its point estimate is
below −3 %, 90 more dense-hi boards (`select.py` with seed 4, same rules) run at the same commit, and the
pooled 180 decide. No other looks.

## Cost (information, not a limit)
margin-ab: 0.6 CPU-h per board and arm at the same budget on a mixed suite. Dense boards are larger (median
130 pads in dense-hi, 550 in dense-lo); estimate 1-1.5 CPU-h per board and arm, about 500-750 CPU-h for 163
boards × 3 arms. Profiled on the smoke (below) before the full run.

## Smoke and profile
`margin-gate-smoke`: uzixls nanoswinsidc (92 pads, 2 layers, 7.3 pads/cm²/layer) and azonenberg
reworkctf v2 (572 pads, 4 layers, 5.4), all three arms, k=1, py-spy on the kae processes and JFR on
Freerouting for one board per arm; read end to end before the full run.

## Addendum 2026-11-17 (before any result): trimmed runs
Approved by the user (queue triage, 2026-11-17), to save CPU in the shared queue. No result had arrived.
- **dense-hi:** the ungated MA run is cancelled on 89 of the 90 boards. On these boards the gate keeps the
  margin. A read-only count of `margin_gate.regions` found 87 boards with one region and 2 with none (no closed
  outline, or no piece wider than the neck rule). Either way the caps give nothing, so MA gated runs the same
  code as MA, and an ungated run would be a twin. resummit seismos 5corestencil has 3 regions, so its MA run is
  kept: there, MA gated vs MA tests the caps.
- **sparse:** all 20 boards are cancelled. The gate drops the margin there, and margin-ab saw no MA effect on
  sparse boards.
- **Effect on the hypotheses:**
  - (1) is unchanged.
  - (2) and the barrier comparison (4) are unchanged.
  - (3)'s A/A floor now comes from dense-lo (40 boards) and the 9 gated-out barrier boards.
  - MA vs MA gated on dense-hi is answered by construction (identical code) rather than measured. The one
    multi-region board is read on its own.
- 129 jobs cancelled. The full run now has 197 queued jobs plus the smoke and profile.

## Addendum 2026-11-17 (2), before any run on the new build: current components
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own.
- **Code.** `margin-gate` is rebased onto main c81770e1 as `margin-gate-m2` (no conflict; the original branch is left as
  it was). Every arm runs kae and harness 84756122, the rebased commit before this addendum (it holds the gate, the
  plan and the first addendum). `test_place_margin_gate.py`, `test_place_problem.py` and `test_place_pipeline.py` pass.
- **Freerouting:** the pinned fork 9a5512d, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- **New experiment `margin-gate-m`** (owner `exp-margin-gate-m`), new method ids, all of a board's arms in one job. The
  trim of the first addendum is kept: the 20 sparse boards are left out (143 boards), and the MA run is not submitted on
  the 89 dense-hi boards with one region or none (kept on resummit seismos 5corestencil). Nothing of `margin-gate` or
  `margin-gate-smoke` had produced a result; their queued jobs (full run, smoke, profile) are cancelled.
- The smoke and profile on the old build never ran. The full run is submitted without them, as the previous submission
  was; the first finished jobs are read end to end (scores, Freerouting 9a5512d in the log) before any analysis.
- Arms, k = 1, hypotheses, primary, guards and the A/A source unchanged.
- **Still worth running:** margin-ab left MA at -7.5 % [-15.1, -0.9], unknown, and the gated default is still open on
  main. About 490 CPU-h after the trim (queue triage).
