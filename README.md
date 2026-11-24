# kicad-auto-everything

Turns a product description into a manufacturable KiCad board. An LLM (or a person) writes the circuit as
Python; the tools produce the schematic, place and route the board, score its physics, and write JLCPCB
fabrication files. No step calls an LLM: every decision is a command with a traceable result.

- **[Part 1: Design a PCB](#part-1-design-a-pcb)**: use the tools on your own board.
- **[Part 2: Improve kae](#part-2-improve-kae)**: change the placer, router or physics and prove the change helps.

| Part | Path | Does |
|---|---|---|
| kaesynth | `tools/research/llm-design/synth/` | circuit code → checked KiCad schematic, rules, BOM, operating intent |
| kae | `kae/` | placement, routing, physics evaluation |
| kaeq | `tools/kaeq/` | job queue for a shared host |
| kaeres, kaebench | `tools/kaeres/`, `bench/` | benchmark corpus, results store, experiments |

## Setup (Ubuntu, no sudo)

```bash
bench/scripts/setup.sh                       # KiCad 10 in Apptainer, Freerouting fork, writes ~/.cache/kaebench/env.sh
python3 -m venv kae/.venv && kae/.venv/bin/pip install -e 'kae[dev,fast]'
cd tools/research/llm-design/synth && uv venv .venv && . .venv/bin/activate && uv pip install -e '.[test]' && cd -
```

Every shell and job: `source ~/.cache/kaebench/env.sh` (sets `KAE_KICAD_WRAP`; run KiCad as `$KAE_KICAD_WRAP kicad-cli …`
or `$KAE_KICAD_WRAP python3`), `export APPTAINER_BIND=<work dir root>`, KiCad under `ulimit -v 40000000`. kaesynth needs
`KICAD10_SYMBOL_DIR` and `KICAD10_FOOTPRINT_DIR` pointing at the image's `usr/share/kicad/{symbols,footprints}`.

On a shared host, run anything over about ten minutes or two cores through kaeq (`tools/kaeq/README.md`):
`kaeq submit --cpus N --mem XG --timeout T --owner <name> -- CMD`, then one background `kaeq wait`. Jobs run a
frozen snapshot of the checkout. Retry and cancel your own jobs only, by id or `--owner`.

---

# Part 1: Design a PCB

A design lives in `tools/research/llm-design/designs/<slug>/` (example: `solar-small`). Paths below are relative to
`tools/research/llm-design/`. Run each stage and check its gate; do not continue past a failed gate.

| # | Stage | Command | Gate |
|---|---|---|---|
| 1 | Requirements and parts | Read datasheets (tables and figures, not summaries); check stock and basic/extended status with the JLC parts API | every number has a page citation |
| 2 | Circuit as code | Write `designs/<slug>/parts.py` (part cards), `design.py` (blocks, nets, placement relations, intent), `board.json` (outline, holes, fixed parts, pours, keepouts), custom footprints | — |
| 3 | LCSC numbers | `kaesynth jlc designs/<slug>/design.py` (writes `jlc.json`) | every generic passive has a number |
| 4 | Schematic and checks | `kaesynth build designs/<slug>/design.py -v` → `designs/<slug>/out/`: `.kicad_sch`, `.kicad_pro`, `.kicad_dru`, `bom.csv`, `report.md`, `<slug>.kae_intent.json` | 0 errors; every warning in `report.md` read (rule feasibility, density) |
| 5 | Unplaced board | `$KAE_KICAD_WRAP python3 synth/scripts/sch_to_board.py designs/<slug>/out designs/<slug>/board.json` | DRC schematic parity 0 |
| 6 | Pre-flight | `python synth/scripts/preflight.py <board> --probe` | 0 FAIL |
| 7 | Layout and scoring | from the repo root, several seeds: `tools/research/llm-design/synth/scripts/layout.sh <board> <outdir> <seed>` (minutes to hours) | `eval/drc.json`: 0 errors, 0 unconnected; `eval/status.json`: `complete` true |
| 8 | Compare seeds or variants | `python synth/scripts/compare_ab.py <rundir> --md table.md` (layout `<rundir>/<arm>/s<seed>/{out,eval}`) | choose by hard violations, then limits, then cost |
| 9 | Fabrication | `python synth/scripts/fab_outputs.py <routed board> <fabdir>` (`sch_to_board.py --update` first if parts changed) | DRC gate passes; `fab-report.json` lists extended parts (each a JLC setup fee) |

**What the stages rely on**

- **Rules.** kaesynth writes clearance rules per net pair from each net's voltage (IPC-2221B) and board minimums from
  the finest pad pitch, and checks at build time that every pin can still escape under them.
- **Operating intent** (`<board>.kae_intent.json`, schema kae.intent/1). It sits beside the board like `.kicad_pro`, and
  every kae stage reads it. Facts: rail voltages, converter cells (V, I, switching frequency), cables. Requirements:
  terms with tiers (`hard` limits, `limit` budgets, `cost`). A value is a number, `[lo, hi]` or `[lo, typ, hi]`; state
  the typical point. Written from `design.py`: net `v_typ=`, part-card `kae=`, `d.kae.net/part/cell/cable/term(...)`.
  `python -m kae.cli brief <board>` shows how kae reads it.
- **Stackup.** `sch_to_board.py` writes the fab's stackup into the board (JLC 2-layer 1.6 mm FR-4 unless `board.json`
  `stackup` says otherwise); the physics uses it.
- **Layout recipe.** `layout.sh` runs kae's default: `tools/kaeres/restart.py` completion-first over `kae.joint.cli`
  (place, route with the Freerouting fork, repair, last mile) on counted-work budgets (`KAE_BUDGET=work`; `KAE_TIME=S`
  overrides the budget), then KiCad DRC, `kae.excite.evaluate` and `kae.intent status` under the board's intent.
- **Physics.** `kae.excite.evaluate` solves the routed copper (layered, 3D partial inductance, stackup capacitance) with
  every converter cell as an aggressor, and reports pickup, overshoot, emissions, losses and temperatures against the
  intent's terms. An incomplete evaluation (`why_incomplete`) prices nothing it could not compute.
- **Only the re-opened board counts.** Judge by `kicad-cli` DRC and the evaluator, never by a router's log.

The worked example, with its rules and known limits: [`docs/topics/workflow/brief-to-board.md`](docs/topics/workflow/brief-to-board.md).

---

# Part 2: Improve kae

kae is improved by experiment: a change is adopted when it measurably helps on benchmark boards, paired against a
control, and never by changing how results are scored.

**Extra setup.** The corpus and harness: `source bench/.venv/bin/activate && kaebench doctor`; boards in the corpus
directory, results in `$KAE_RESULTS` (default `~/kae-baselines`, `tools/kaeres/README.md`). Unit tests:
`kae/.venv/bin/pytest kae/tests`, `pytest bench/tests`.

**Procedure** (`docs/topics/verification/experiment-tiers.md`, `bench/suites/README.md`):

1. Branch off the weekly baseline tag (`baseline/<year>-w<week>`), make one change, add tests, push.
2. Write `$KAE_RESULTS/experiments/<name>/PLAN.md`: the question, the change, the suite, the primary endpoint, guards.
3. Choose the boards. A change that acts on every board runs on the sprint suites; a change to one mechanism (BGA escape,
   pours, converters, …) runs on `bench/suites/mech/<mechanism>.txt`. Limits: at most 40 CPU-h per campaign, no board
   over 0.5 CPU-h per run; larger tiers (ladder, canary) only after a sprint result.
4. Run: `python3 tools/kaeres/kaeres.py sprint <name> --base bridge|staged --commit <sha>` runs your arm against the
   stored control's runs. Smoke one or two boards first and read their runs.
5. Verdict, paired per board and seed: better, worse or undecided, with an interval, in `VERDICT.md`. Mixed results
   get a per-board look before anything is concluded.

**Rules that keep results comparable**

- Scoring code (`bench/src/kaebench/score.py`, the evaluators) defines the benchmark. A fix to it is its own commit that
  says why, and stored results are re-scored, not re-run.
- Every arm runs at the same tag, with the same Freerouting build, on counted-work budgets, side by side.
- A method's only score is `kicad-cli` on its re-opened output board.

Background: [`docs/INDEX.md`](docs/INDEX.md) (digests, then topic docs; `research_notes/` is raw evidence).

## License

Code is [GPL-3.0-or-later](LICENSE); docs and research notes CC-BY-4.0, rule packs CC0-1.0, datasets CDLA-Permissive-2.0,
model weights Apache-2.0 ([`LICENSING.md`](LICENSING.md); [`CONTRIBUTING.md`](CONTRIBUTING.md), DCO sign-off).
