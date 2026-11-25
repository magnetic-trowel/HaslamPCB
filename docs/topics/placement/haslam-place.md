# haslam place: the placer, what works, what did not

Scope: hub for `haslam place`: pipeline stages → modules, budgets, and where each result lives. Not here: mechanism and runs -> research pages linked per section (defensive publications, canonical for numbers).
Keys: haslam place, physics-first placer, pipeline.py, Problem, brief, macros, seed, CP-SAT floorplan, FastAnnealer, numba engine, legalize, ExactModel, exact closed loop, fix_order, fix_silk, KiCad loop, human gate, labels, --fix-class, mech_rules, routability estimators, probe-select, dense sensor boards, pmw3610

## Pipeline

Source [`haslam/src/haslam/place/`](../../../haslam/src/haslam/place/), entry `haslam place IN OUT` ([cli.py](../../../haslam/src/haslam/cli.py)), stages in [pipeline.py](../../../haslam/src/haslam/place/pipeline.py).

| Stage | What it does | Module | Detail |
|---|---|---|---|
| Problem | Movable and fixed parts (locked, Edge.Cuts carriers, `--fix`), grid rectangles per rotation, outline cover, fixed copper and text, keepouts | `problem.py` | [placer § 6](../../research/placement/haslam-placer.md#idea-and-how-it-works) |
| Brief | Net roles (ground ×0.1, power ×0.2) and, with physics, structures: decaps, hot loops, crystals, protection chains ([comprehension](../physics/comprehension.md)) | `stubs.py`, `haslam.circuit` | [brief](../../research/placement/haslam-comprehension-brief.md) |
| Macros | Each structure's top-K rigid layouts (CP-SAT), protection-order rules of connector chains | `clusters.py` | placer § 3 |
| Seed | Quadratic placement, connectors anchored to the nearest edge, spreading; CP-SAT floorplan (NoOverlap2D, 4 rotations, macros with their layouts, HPWL + small displacement) up to `FLOORPLAN_MAX_ITEMS`, bisection spread above | `seed.py`, `cpsat.py` | placer § 1, 2, 4 |
| Anneal | Numba engine (Python reference `anneal.py`): HPWL, place terms (utilization priced linearly, saturated at 3× budget), legality ramp, displacement, protection order, soft silk/channel grids, label anchors | `engine.py`, `anneal.py` | placer § 5 |
| Legalize | Windowed CP-SAT, greedy fallback, then the exact model | `legalize.py`, `_fastlegal.py` | placer § 6 |
| Exact closed loop | Per-part polygon check; repair moves each offender to the nearest grid-free, exactly clean spot, with eviction, re-seed and lookahead escalation | `exact.py` | [exact legality](../../research/placement/haslam-exact-legality.md) |
| Order pass | Puts protection parts back between connector and protected part within a physics bound | `exact.fix_order` | same |
| Silk pass | Moves the smaller part of each silk conflict within +3% physics and +10% local HPWL | `exact.fix_silk` | same |
| KiCad loop | kicad-cli DRC on the written board; findings become constraints; repair; rewrite; up to 6 rounds | `cli._kicad_loop`, `exact.kicad_feedback` | same |

- Budget: finish in min(0.85·time − 10 s, 20 s + 3 s per movable part); annealer counts CPU seconds; CP-SAT wall seconds with `--workers` threads; split C median 11.7k moves/s ([split C sweep](../../../bench/results/2026-10-23-place-split-c-e171267.md)) [C].
- Each numba kernel gets the engine's state tuple by value: every extra field costs move rate (12 fields ≈ 10%), so label and silk data are packed into two arrays [C].

## Defaults decided in 2026-11

- **Severity ladder** (`--severity`, default `strict_then_level_c`). Courtyards, copper-to-edge, rule areas, clearance, shorts and hole clearance are errors whatever the project says. On a project that waives courtyard overlap, haslam places with drawn courtyards (`strict`, no body relaxation) in 55% of `--time`; only if that leaves placement errors (the exact check, or KiCad's verdict after the KiCad rounds) does it place again with courtyards taken in 0.15 mm (IPC Level C, `level_c`), body relaxation last. Each rung keeps 15% of its share for its KiCad loop; a rung KiCad judged beats one it did not, else level_c is kept unless strict was better by KiCad's counts. On 113 waiving boards strict was legal under the real rules on 46% of runs against level_c's 28%, but left 12 boards with placement shorts against 6. `strict`, `level_c`, `board` remain options -> [exact legality](../../research/placement/haslam-exact-legality.md).
- **Body relaxation** (`relax_bodies`, default `escalate`: only when legalization fails; `off`, `auto`).
- **Report hazards.** The report closes with `hazards` and `hazard_summary` ([hazards](../architecture/hazards.md)): each relaxed part gets `body_overlap` (block) when its body lies over another part, else `body_relaxed` (info), plus `severity_fallback` and `connector_off_edge`. The written board is rechecked with the safety checks forced on (`--recheck`), whatever profile the placer used.
- **Edge connectors** (`connector_edge`, default 2). Plain `place` pins free USB, barrel, RJ, video and SMA/BNC parts to the outer edge, facing out; the old "connector edge pull" term was dropped only for `*-fixed` tasks -> [fixed interface](../../research/placement/haslam-fixed-interface.md#edge-connectors-in-plain-place-mode-2026-11).
- **Crossing term** (`place_w_xing`, default 2 mm of weighted HPWL per ratsnest crossing, `haslam.place.crossings`). On because it cuts ratsnest crossings to 0.62x without harming opens (−1.7 % [−7.1, +3.7]), DRC errors (−2 %) or legality on 26 placement-fail boards (xing-ext-m6): a cleaner ratsnest is adopted for itself (user decision 2026-11-21), not for an opens gain -> [xing-ext plan](../../../tools/haslamres/experiments/placement-routability-xing-ext/PLAN.md).
- **Routing margin** (`place_margin` −1, auto, gated to boards with at least 4 pads/cm²/layer, capped per region): −14 % per-attempt opens on 44 dense boards (margin-gate-m6) -> [margin gate](../../research/placement/margin-gate-2611.md).
- **Off by default:** RUDY congestion (`place_w_cong` 0, [routability estimators](../../research/placement/haslam-routability-estimators.md)), equal to its old value on A/B placement-decide-staged; escape bands (`escape_band` 0, escape-ab3) -> [escape keep-outs](../../research/placement/escape-keepouts.md).

## Where the rest lives

| Subject | Page |
|---|---|
| Exact model checks (incl. board copper text as glyph outlines), KiCad-loop blame rules, retry, safety net, silkscreen model, board silk labels, human gate (caught every model bug shipped: run it after any change to `haslam.place.exact`) | [exact legality](../../research/placement/haslam-exact-legality.md#human-gate) |
| `--fix`, `--fix-class` (the benchmark's own place-fixed rules, [mech_rules](../../../bench/src/haslambench/kicad_scripts/mech_rules.py)), classifier counts on 112 boards, fixed-interface 6-board test | [fixed interface](../../research/placement/haslam-fixed-interface.md) |
| RUDY, channel term, cut capacity, corridor overflow, pour fragmentation, probe-select, edge pull, free angles | [routability estimators](../../research/placement/haslam-routability-estimators.md) |
| Runs (split C legal 72/72; physics 1,410 vs human 4,392; split C clean 30/78 vs human 43/78), physics ablation, routability probe, open problems (dense sensor boards, split-C routability) | [haslam placer](../../research/placement/haslam-placer.md) |
| Place terms (physics) | [physics terms](../../research/placement/haslam-physics-terms.md), [place-terms](../physics/place-terms.md) |

## Sources

- Results: [physics ablation](../../../bench/results/2026-10-24-place-physics-ablation-1ef5bf1.md), [routability probe](../../../bench/results/2026-10-24-place-routability-probe-1ef5bf1.md), [pipeline A+B](../../../bench/results/2026-10-24-pipeline-ab-c9c49d6.md), [pipeline C](../../../bench/results/2026-10-24-pipeline-c-c9c49d6.md), [split C sweep](../../../bench/results/2026-10-23-place-split-c-e171267.md), [full benchmark](../../../bench/results/2026-10-24-full-benchmark-03096d9.md)
- Study tools under [`tools/research/place/`](../../../tools/research/place/): `humangate.py`, `labels.py`, `fixed.py`, `anglepolish.py`, `csweep.py`
- Related: [legalization](legalization.md), [strategy candidates](strategy-candidates.md), [Freerouting bridge](../routing/freerouting-constraint-bridge.md), [status 2026-10-25](../architecture/status-2026-10-25.md)
