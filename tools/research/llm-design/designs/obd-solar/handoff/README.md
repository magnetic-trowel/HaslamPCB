<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# obd-solar handoff package: boards, evaluations and how to reproduce

Scope: every file needed to study obd-solar's power-net track widths without rebuilding it. The findings are in
[docs/research/routing/power-net-track-width.md](../../../../../../docs/research/routing/power-net-track-width.md); the
run's friction log is [../FRICTION.md](../FRICTION.md); the circuit is [../design.py](../design.py) and
[../parts.py](../parts.py) (explained in [../DESIGN.md](../DESIGN.md), reviewed in [../REVIEW.md](../REVIEW.md)).
Keys: obd-solar handoff, board package, routed board, width_check, reproduction

These boards are this project's own design (GPL-3.0-or-later, like the rest of `designs/`), not corpus boards, so they
may be committed. Generated on branch `obd-solar-e2e` with KiCad 10.0.8 and the Freerouting fork pinned at 06d2686.

## Contents

| Path | What | Made by |
|---|---|---|
| `unplaced/obd-solar.kicad_pcb` | 96 x 66 mm, 2-layer JLC stackup, 94 footprints, fixed connectors, GND pours, nothing placed or routed | `haslamsynth build` + `sch_to_board.py` (outline 96 x 66) |
| `unplaced/obd-solar.kicad_pro`, `.kicad_dru` | net classes sized from each net's current (10 C rise), JLC fab profile (board setup + FAB rules), functional spacing rules | haslamsynth |
| `unplaced/obd-solar.haslam_intent.json` | operating facts (rails, 3 commutation cells, J301 load 1 A typ / 2 A max), terms (FB/MPPT pickup, overshoot, heat.track 20 K, drop.rail VBUS 150 mV, Tj), 35 placement relations (hot loops as requested near) | haslamsynth |
| `unplaced/netlist.json` | every pin's net, each net's `i_max`, `board.trace_rise_c` | haslamsynth |
| `unplaced/bom.csv`, `fp-lib-table`, `sym-lib-table` | BOM with LCSC numbers; library tables (custom footprints in `../footprints/custom.pretty`) | haslamsynth |
| `routed-s1/obd-solar.kicad_pcb` | seed 1 of `layout.sh` (restart.py recipe, HASLAM_TIME 1200), **before** any power-copper post-pass; this is the board measured in the research doc | `layout.sh` |
| `routed-s1/eval/drc.json` | KiCad DRC with schematic parity: 4 `starved_thermal`, 0 unconnected, parity 0 | kicad-cli |
| `routed-s1/eval/width.json`, `width.txt` | branch-current width gate: 7 nets too narrow (VBAT 69.7 mm, VBUS 20.9, CHG_OUT 41.7, BB_SW2 25.8, OBD_RAW 8.6, BB_SW1 6.8, ...) | `width_check.py` |
| `routed-s1/eval/excite.json`, `status.json` | physics evaluation (0.125 mm cell windows): hottest track 199.6 K, VBUS drop 266 mV, U301 Tj 185 C, FB pickup 259 mV, copper loss 1.76 W | `haslam.excite.evaluate`, `haslam.intent status` |
| `variants/widen/` | `routed-s1` after `power_copper` (widen mode): VBAT 68.2 / VBUS 15.5 / CHG_OUT 11.2 mm too narrow, DRC 4 | `haslam.route.power_copper` |
| `variants/zones-into-pads/` | after `power_copper --mode vector --vector-out zones --no-neck` (67 zones pour into SMD pads): 65.2 / 11.8 / 8.3 mm, DRC 3 | same |

`width_check.py` takes every net's DC current paths from the evaluator's plan under the intent file beside the board (the
hand-written `width_injections.json` it once needed for the OBD feed, VBAT, PV_IN, CHG_OUT and the switch nodes was removed
once the plan covered them: FRICTION.md #73).

## Reproduce

From the repo root, in the haslam venv with `~/.cache/haslambench/env.sh` sourced and `PYTHONPATH=haslam/src`:

```bash
H=tools/research/llm-design/designs/obd-solar/handoff
python tools/research/llm-design/synth/scripts/width_check.py $H/routed-s1/obd-solar.kicad_pcb $H/unplaced/netlist.json
```

```bash
python -m haslam.route.power_copper $H/routed-s1/obd-solar.kicad_pcb /tmp/pc/obd-solar.kicad_pcb --mode vector --vector-out zones --no-neck
```

Route the unplaced board again (copy `unplaced/` to a work folder first; a renamed board runs on KiCad's default rules):

```bash
HASLAM_TIME=1200 HASLAM_EVAL=0 bash tools/research/llm-design/synth/scripts/layout.sh <work>/obd-solar.kicad_pcb <outdir> 1
```

Rebuild everything from source instead: `python tools/research/llm-design/synth/scripts/pipeline.py tools/research/llm-design/designs/obd-solar build`,
then `board`, `preflight`, `layout` (see the script's docstring for the gates).

## Notes

1. `routed-s1` was placed and routed before the hot-loop `requested` relations and the J301 load fact were added to the
   intent; its copy of the intent file is the current one (used for the evaluation). The unplaced board's intent is current.
2. Zones written by power_copper are unfilled until refilled (`synth/scripts/refill.py`, KiCad's Python); the variant boards
   here are refilled.
3. Smoke A/B of the router change (`gfix-route-width` + `bridge.neckdown=1` vs the current recipe) on `unplaced/` was running when
   this package was written; results go into FRICTION.md.
