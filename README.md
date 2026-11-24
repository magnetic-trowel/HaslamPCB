# HaslamPCB

Turns a product description into a manufacturable KiCad board. An LLM (or a person) writes the circuit as
Python; the tools produce the schematic, place and route the board, score its physics, and write JLCPCB
fabrication files. No step calls an LLM: every decision is a command with a traceable result.

| Part | Path | Does |
|---|---|---|
| haslamsynth | `tools/research/llm-design/synth/` | circuit code → checked KiCad schematic, rules, BOM, operating intent |
| haslam | `haslam/` | placement, routing, physics evaluation (`haslam.cli`, `haslam.joint.cli`, `haslam.route.cli`, `haslam.excite`, `haslam.em`) |
| haslamq | `tools/haslamq/` | job queue for the shared host; every long job goes through it |
| haslamres / haslambench | `tools/haslamres/`, `bench/` | results store, benchmark corpus and experiments for changing haslam |

## Setup (Ubuntu, no sudo)

```bash
bench/scripts/setup.sh                       # KiCad 10 in Apptainer, Freerouting fork, writes ~/.cache/haslambench/env.sh
python3 -m venv haslam/.venv && haslam/.venv/bin/pip install -e 'haslam[dev,fast]'
cd tools/research/llm-design/synth && uv venv .venv && . .venv/bin/activate && uv pip install -e '.[test]' && cd -
```

Every shell and job: `source ~/.cache/haslambench/env.sh` (sets `HASLAM_KICAD_WRAP`; run KiCad as `$HASLAM_KICAD_WRAP kicad-cli …`
or `$HASLAM_KICAD_WRAP python3`), `export APPTAINER_BIND=<work dir root>`, KiCad under `ulimit -v 40000000`. haslamsynth needs
`KICAD10_SYMBOL_DIR` and `KICAD10_FOOTPRINT_DIR` pointing at the image's `usr/share/kicad/{symbols,footprints}`.

## Pipeline: concept to fabrication files

A design lives in `tools/research/llm-design/designs/<slug>/` (example: `solar-small`). Paths below are relative to
`tools/research/llm-design/`. Run each stage and check its gate; do not continue past a failed gate.

| # | Stage | Command | Gate |
|---|---|---|---|
| 1 | Requirements and parts | Read datasheets (tables and figures, not summaries); check stock and basic/extended status with the JLC parts API | every number has a page citation |
| 2 | Circuit as code | Write `designs/<slug>/parts.py` (part cards), `design.py` (blocks, nets, placement relations, intent), `board.json` (outline, holes, fixed parts, pours, keepouts), custom footprints | — |
| 3 | LCSC numbers | `haslamsynth jlc designs/<slug>/design.py` (writes `jlc.json`) | every generic passive has a number |
| 4 | Schematic and checks | `haslamsynth build designs/<slug>/design.py -v` → `designs/<slug>/out/`: `.kicad_sch`, `.kicad_pro`, `.kicad_dru`, `bom.csv`, `report.md`, `<slug>.haslam_intent.json` | 0 errors; every warning in `report.md` read (rule feasibility, density) |
| 5 | Unplaced board | `$HASLAM_KICAD_WRAP python3 synth/scripts/sch_to_board.py designs/<slug>/out designs/<slug>/board.json` | DRC schematic parity 0 |
| 6 | Pre-flight | `python synth/scripts/preflight.py <board> --probe` | 0 FAIL |
| 7 | Layout and scoring | from the repo root, through haslamq, several seeds: `tools/research/llm-design/synth/scripts/layout.sh <board> <outdir> <seed>` | `eval/drc.json`: 0 errors, 0 unconnected; `eval/status.json`: `complete` true |
| 8 | Compare seeds or variants | `python synth/scripts/compare_ab.py <rundir> --md table.md` (layout `<rundir>/<arm>/s<seed>/{out,eval}`) | choose by hard violations, then limits, then cost |
| 9 | Fabrication | `python synth/scripts/fab_outputs.py <routed board> <fabdir>` (`sch_to_board.py --update` first if parts changed) | DRC gate passes; `fab-report.json` lists extended parts (each a JLC setup fee) |

**What the stages rely on**

- **Rules.** haslamsynth writes clearance rules per net pair from each net's voltage (IPC-2221B) and board minimums from
  the finest pad pitch, and checks at build time that every pin can still escape under them.
- **Operating intent** (`<board>.haslam_intent.json`, schema haslam.intent/1). It sits beside the board like `.kicad_pro`, and
  every haslam stage reads it. Facts: rail voltages, converter cells (V, I, switching frequency), cables. Requirements:
  terms with tiers (`hard` limits, `limit` budgets, `cost`). A value is a number, `[lo, hi]` or `[lo, typ, hi]`; state
  the typical point. Written from `design.py`: net `v_typ=`, part-card `haslam=`, `d.haslam.net/part/cell/cable/term(...)`.
  `python -m haslam.cli brief <board>` shows how haslam reads it.
- **Stackup.** `sch_to_board.py` writes the fab's stackup into the board (JLC 2-layer 1.6 mm FR-4 unless `board.json`
  `stackup` says otherwise); the physics uses it.
- **Layout recipe.** `layout.sh` runs haslam's default: `tools/haslamres/restart.py` completion-first over `haslam.joint.cli`
  (place, route with the Freerouting fork, repair, last mile) on counted-work budgets (`HASLAM_BUDGET=work`), then KiCad
  DRC, `haslam.excite.evaluate` and `haslam.intent status` under the board's intent.
- **Physics.** `haslam.excite.evaluate` solves the routed copper (layered, 3D partial inductance, stackup capacitance) with
  every converter cell as an aggressor, and reports pickup, overshoot, emissions, losses and temperatures against the
  intent's terms. An incomplete evaluation (`why_incomplete`) prices nothing it could not compute.
- **Only the re-opened board counts.** Judge by `kicad-cli` DRC and the evaluator, never by a router's log.

## Running jobs

On the shared host, anything over about ten minutes or two cores is a haslamq job (`tools/haslamq/README.md`):
`haslamq submit --cpus N --mem XG --timeout T --owner <name> -- CMD`, then one background `haslamq wait`. Jobs run a frozen
snapshot of the checkout; untracked inputs need `--link`. Retry and cancel your own jobs only, by id or `--owner`.

## Changing haslam

A haslam change is accepted by experiment (`docs/topics/verification/experiment-tiers.md`, `bench/suites/README.md`):

1. Branch off the weekly baseline tag (`baseline/<year>-w<week>`), make one change, add tests, push.
2. Write `$HASLAM_RESULTS/experiments/<name>/PLAN.md`: question, change, suite, primary endpoint, guards.
3. `python3 tools/haslamres/haslamres.py sprint <name> --base bridge|staged --commit <sha>` runs it against the stored control
   on the sprint suites (at most 40 CPU-h, no board over 0.5 CPU-h). A change to one mechanism runs on
   `bench/suites/mech/<mechanism>.txt` instead. Smoke one or two boards first.
4. Verdict, paired per board and seed: better, worse or undecided, with an interval, in `VERDICT.md`.
   Changes to scoring are separate commits that say why, and stored results are re-scored.

## Docs and license

Start at [`docs/INDEX.md`](docs/INDEX.md); the worked end-to-end example is
[`docs/topics/workflow/brief-to-board.md`](docs/topics/workflow/brief-to-board.md). Code is
[GPL-3.0-or-later](LICENSE); docs and research notes CC-BY-4.0, rule packs CC0-1.0, datasets CDLA-Permissive-2.0,
model weights Apache-2.0 ([`LICENSING.md`](LICENSING.md); [`CONTRIBUTING.md`](CONTRIBUTING.md), DCO sign-off).
