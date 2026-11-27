<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Neutrality A/B for one-design fixes

Scope: how a haslam change made while fixing one design is checked on boards without that design's intent, and the results of each such check. Not here: experiment tiers and the sprint procedure -> [experiment-tiers](experiment-tiers.md); the hot-loop window itself -> [hot-loop-evaluation § 3](../physics/hot-loop-evaluation.md#3-the-window-solve).
Keys: neutrality A/B, one-design fix, intent-less boards, F54, bme280-array, before/after, byte-identical placement, HASLAM_HOTLOOP_OWN_WINDOW, injection pad, dropped_injection

## Method

1. Before = `origin/main`, after = the branch head; same venv, `HASLAM_BUDGET=work`, `PYTHONHASHSEED=0`, `HASLAM_WORKERS=1`, seed 0, the same Freerouting fork in both arms.
2. Boards: a stratified sample of the sprint suites (`bench/suites/sprint-*.txt`), fetched and prepared with `haslambench fetch/prepare --only` (no intent file), plus boards whose intent is the point of the change.
3. Stages and what must hold:

| Stage | Command | Equal means |
|---|---|---|
| placement | `haslam.cli place IN OUT --seed 0 --time 120` | output `.kicad_pcb` byte-identical |
| placement with intent | same, `--intent FILE` | byte-identical |
| physics | `haslam.excite.evaluate BOARD -o OUT.json` on the human layout | totals, every observation value, cells' L/R/window equal |
| routing | `haslam.route.cli route IN OUT --seed 0 --time 300` | copper items (segments, arcs, vias; uuid-free, order-free) equal; `kicad-cli pcb drc --refill-zones` with the task's `.kicad_pro`/`.kicad_dru`: unconnected and errors by type equal |
| joint loop | `haslam.joint.cli run IN OUT --seed 0 --time 300 --max-iters 0` | as routing, plus poses |

## 2026-11-27: bme280-array fixes (F54)

Before `b798c5bc` (origin/main), after `5b4c5025` + `e4fd6d79` (branch `claude/youthful-mayer-o7qepm`), Freerouting fork `37b1a8b` in both arms, KiCad 10.0.8, 4-CPU host.

Sample: 27 sprint boards (14-227 footprints, 36-829 pads; 2-6 layers; 14 with keepout rule areas, 26 with zones, 11 with locked parts, 11 of the 19 evaluated with a converter cell the evaluator models) + the 6 relation fixtures of `haslam/tests/data/relations/` (#141, intents with relations, none `required`).

| Stage | Boards | Result |
|---|---|---|
| placement, no intent | 27 | 27 byte-identical |
| placement, fixture intents | 6 | 6 byte-identical (machdyne-blaustahl illegal in both arms, rc 3) |
| physics, no intent | 19 (14-98 footprints) | totals and every observation value identical; cells' L_loop, R_loop, harmonics and windows identical. Differences: a `temp.rise` observation added on 15 boards (no reference, priced only by an intent term: f686563) and the core-current prior's basis text names the facts that replace it |
| hot-loop window `HASLAM_HOTLOOP_OWN_WINDOW=1` vs unset | 12 boards, 11 cells | identical (with e4fd6d79) |
| routing | 7 (odz-hv-spx01, unexpectedmaker-omgs3, fabiansteiner-openvalve, azoninc-doorman, jin-neuron-turtlepico, niektb-fv1, yussufadel8-bldc) | copper identical (238-1005 items); DRC unconnected and errors by type identical; power-copper widening identical (no quiet nets without facts) |
| joint loop | 3 (fabiansteiner-openvalve, juniper-twig, cmnybo-chip-lcd: locked parts and rule areas) | poses and copper identical; DRC identical |

Not run: physics on acmo0-pedalboard and the 7 largest (yussufadel8, brickpico, tyler-stacklight, deco025, tinyllama, controlpaths, kbx81; 92-227 footprints): two evaluations at once exceeded the host's 16 GB and one medium board takes ~15 min per arm; the shared host's sprint covers them.

**Regression found and fixed: own-parts window, far injection part.** e360ef7's window (now opt-in) drops every ≥ 5 % part with no pad within 10 mm of the cell's own parts. On jin-neuron-turtlepico the brief names only the DRV8833 (IC1) and its two caps, and the current enters from module U2 > 10 mm away:

| jin-neuron IC1 half bridge | main window | e360ef7 own window | own window + e4fd6d79 |
|---|---|---|---|
| window | 65.4 x 70.8 mm at 0.125 mm (grown 3x) | 15.7 x 10.1 mm at 0.0625 mm | = main |
| injection outside the window (`dropped_injection`) | 0 | 51 % | 0 |
| truncation correction | -0.03 nH | -3.72 nH (board 8.97 nH) | = main |
| L_loop | 8.855 nH | 8.326 nH (-6 %) | = main |
| R_loop at f_sw, 3 f_sw, 5 f_sw | 25.3, 38.5, 56.9 mΩ | 25.8, 33.7, 39.3 mΩ (5 f_sw -31 %) | = main |
| loss.loop_ac | | -7 to -27 % per corner | = main |

The smaller number is not better physics: half the loop's current had nowhere to go in the window solve. e4fd6d79 keeps a far part that has an injection pad (`Ja`: ICs, connectors, modules outside the copper model); only far lumped parts (decouplers) leave. bme280-array's windows are unchanged by it (its dropped parts, C101-C116 and C2/C10, are lumped). With it the opt-in window changes no cell of the sample; without it, 1 of 9.

Shared-host check (both sprint suites, 140 boards, before and after as two arms against the stored control; each experiment folder needs its PLAN.md first, [procedure](../../../bench/suites/README.md)):

```bash
K="python3 tools/haslamres/haslamres.py"
$K sprint f54-main   --base staged --commit b798c5bc --note "F54 neutrality: origin/main"
$K sprint f54-branch --base staged --commit <pushed branch head> --note "F54 neutrality: bme280-array fixes"
```

Verdict: neutral if f54-branch equals f54-main per board and seed (DRC, physics). Baselines to re-run: none for intent-less boards; haslamres `--intent` evaluations and any run with `HASLAM_HOTLOOP_OWN_WINDOW=1`.

## Sources

Scratch results (not committed, third-party boards): `scratchpad/f54/out2/{before,after,own}/<stage>/<board>/`. Commits: c6d719a, 7cad586, 0a5e45f, 6379503, 51d1737, e360ef7, faae92a8, f686563, bf7a5de, 0ebfad6a, 4398cfa, e4fd6d79.
