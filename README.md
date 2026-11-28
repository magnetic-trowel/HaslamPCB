# HaslamPCB

Turns a product description into a manufacturable KiCad board. An LLM (or a person) writes the circuit as
Python; the tools produce the schematic, place and route the board, score its physics, and write JLCPCB
fabrication files. No step calls an LLM: every decision is a command with a traceable result.

- **[Part 1: Design a PCB](#part-1-design-a-pcb)**: use the tools on your own board.
- **[Part 2: Improve haslam](#part-2-improve-haslam)**: change the placer, router or physics and prove the change helps.

| Part | Path | Does |
|---|---|---|
| haslamsynth | `tools/research/llm-design/synth/` | circuit code → checked KiCad schematic, rules, BOM, operating intent |
| haslam | `haslam/` | placement, routing, physics evaluation |
| haslamq | `tools/haslamq/` | job queue for a shared host |
| haslamres, haslambench | `tools/haslamres/`, `bench/` | benchmark corpus, results store, experiments |

## Setup (Ubuntu, no sudo)

```bash
bench/scripts/setup.sh                       # KiCad 10 in Apptainer, Freerouting fork, writes ~/.cache/haslambench/env.sh
python3 -m venv haslam/.venv && haslam/.venv/bin/pip install -e 'haslam[dev,fast]'
cd tools/research/llm-design/synth && uv venv .venv && . .venv/bin/activate && uv pip install -e '.[test]' && cd -
```

Every shell and job: `source ~/.cache/haslambench/env.sh` (sets `HASLAM_KICAD_WRAP`; run KiCad as `$HASLAM_KICAD_WRAP kicad-cli …`
or `$HASLAM_KICAD_WRAP python3`), `export APPTAINER_BIND=<work dir root>`, KiCad under `ulimit -v 40000000`. haslamsynth needs
`KICAD10_SYMBOL_DIR` and `KICAD10_FOOTPRINT_DIR` pointing at the image's `usr/share/kicad/{symbols,footprints}`.

On a shared host, run anything over about ten minutes or two cores through haslamq (`tools/haslamq/README.md`):
`haslamq submit --cpus N --mem XG --timeout T --owner <name> -- CMD`, then one background `haslamq wait`. Jobs run a
frozen snapshot of the checkout. Retry and cancel your own jobs only, by id or `--owner`.

---

# Part 1: Design a PCB

A design lives in `tools/research/llm-design/designs/<slug>/` (example: `solar-small`). Paths below are relative to
`tools/research/llm-design/`. **Run the stages with `synth/scripts/pipeline.py designs/<slug> <stage>`**: it records each
gate, refuses a stage while an earlier gate is unmet, and only writes fabrication files for a board that passed every
gate (fab profile, current-sized track widths, ≥ 3 seeds, complete physics, acknowledged DRC warnings, a review).
`pipeline.py designs/<slug> status` prints the next stage. The table below is what each stage does.

| # | Stage | Command | Gate |
|---|---|---|---|
| 1 | Requirements and parts | Read datasheets (tables and figures, not summaries); check stock and basic/extended status with the JLC parts API | every number has a page citation |
| 2 | Circuit as code | Write `designs/<slug>/parts.py` (part cards), `design.py` (blocks, nets, placement relations, intent), `board.json` (outline, holes, fixed parts, pours, keepouts), custom footprints | — |
| 3 | LCSC numbers | `haslamsynth jlc designs/<slug>/design.py` (writes `jlc.json`) | every generic passive has a number |
| 4 | Schematic and checks | `haslamsynth build designs/<slug>/design.py -v` → `designs/<slug>/out/`: `.kicad_sch`, `.kicad_pro`, `.kicad_dru`, `bom.csv`, `report.md`, `<slug>.haslam_intent.json` | 0 errors; every warning in `report.md` read (rule feasibility, density) |
| 5 | Unplaced board | `$HASLAM_KICAD_WRAP python3 synth/scripts/sch_to_board.py designs/<slug>/out designs/<slug>/board.json` | DRC schematic parity 0 |
| 6 | Pre-flight | `python synth/scripts/preflight.py <board> --probe` | 0 FAIL |
| 7 | Layout and scoring | from the repo root, several seeds: `tools/research/llm-design/synth/scripts/layout.sh <board> <outdir> <seed>` (minutes to hours) | `eval/drc.json`: 0 errors, 0 unconnected; `eval/status.json`: `complete` true |
| 8 | Compare seeds or variants | `python synth/scripts/compare_ab.py <rundir> --md table.md` (layout `<rundir>/<arm>/s<seed>/{out,eval}`) | choose by hard violations, then limits, then cost |
| 9 | Fabrication | `python synth/scripts/fab_outputs.py <routed board> <fabdir>` (`sch_to_board.py --update` first if parts changed) | DRC gate passes; `fab-report.json` lists extended parts (each a JLC setup fee) |

**How each stage works**

1. **Requirements and parts.** The designer (often an LLM) turns the product brief into numbers (voltages, currents,
   switching frequencies, limits) and picks parts that JLCPCB can assemble, preferring basic parts, which have no
   per-order setup fee.
2. **Circuit as code.** The circuit is Python: part cards carry each part's pins, footprint, ratings and datasheet facts;
   `design.py` connects them into blocks and nets and states what the board must achieve; `board.json` gives the
   outline and anything mechanical that cannot move (connectors, holes, the module socket).
3. **LCSC numbers.** Generic resistors and capacitors are matched to in-stock JLC parts by value, package, voltage and
   dielectric, so the BOM can be assembled without hand lookups.
4. **Schematic and checks.** haslamsynth checks the circuit (ratings against operating stress, ERC, netlist round trip)
   and writes the KiCad project. It derives clearance rules per net pair from each net's voltage (IPC-2221B) and track
   minimums from the finest pad pitch, and proves every pin can still escape under them. It also writes the **operating
   intent** (`<slug>.haslam_intent.json`, beside the board like `.kicad_pro`): the facts haslam cannot read from copper (rail
   voltages; each converter's input, output, current and switching frequency; cables) and the requirements, as terms
   with tiers (`hard` limits, `limit` budgets, `cost`). `python -m haslam.cli brief <board>` shows how haslam reads them.
5. **Unplaced board.** The netlist becomes a `.kicad_pcb` with every footprint, the fixed parts in place, pours,
   keepouts and the fab's stackup (JLC 2-layer 1.6 mm FR-4 unless `board.json` `stackup` says otherwise).
6. **Pre-flight.** A few minutes of checks catch what would waste a long run: KiCad and Freerouting reachable, rules
   accepted by KiCad, schematic parity, fixed parts legal, intent complete, and a short place-and-route probe that
   lists any connection the rules block.
7. **Layout and scoring.** haslam places the parts (an annealer with legality checks, priced by wire length, physics terms
   and routability), routes them (Freerouting plus haslam's repair and last-mile router, which respect pad-entry,
   thermal-spoke and clearance rules), and restarts with new seeds while connections stay open, on a budget of counted
   work rather than wall time. The routed board is then checked by KiCad's DRC and scored by haslam's physics
   evaluator, which solves the copper (layered, with 3D inductance and the stackup's capacitance) with every converter
   as a noise source and reports pickup, overshoot, emissions, losses and temperatures against the intent's terms.
   An incomplete evaluation (`why_incomplete`) prices nothing it could not compute.
8. **Compare.** Seeds and design variants differ; the table puts DRC, open connections and every physics term side by
   side, so the choice is by the intent's tiers, not by eye.
9. **Fabrication.** Zones are refilled, DRC must pass, and the Gerbers, drill files, pick-and-place file and BOM with
   LCSC numbers are written in JLCPCB's formats.

Judge every result by KiCad's DRC and the evaluator on the re-opened board, never by a tool's own log.

The worked example, with its rules and known limits: [`docs/topics/workflow/brief-to-board.md`](docs/topics/workflow/brief-to-board.md).

---

# Part 2: Improve haslam

haslam is improved by experiment: a change is adopted when it measurably helps on benchmark boards, paired against a
control, and never by changing how results are scored.

**Extra setup.** The corpus and harness: `source bench/.venv/bin/activate && haslambench doctor`; boards in the corpus
directory, results in `$HASLAM_RESULTS` (default `~/haslam-baselines`, `tools/haslamres/README.md`). Unit tests:
`haslam/.venv/bin/pytest haslam/tests`, `pytest bench/tests`.

**Procedure** (`docs/topics/verification/experiment-tiers.md`, `bench/suites/README.md`):

1. Branch off the weekly baseline tag (`baseline/<year>-w<week>`), make one change, add tests, push.
2. Write `$HASLAM_RESULTS/experiments/<name>/PLAN.md`: the question, the change, the suite, the primary endpoint, guards.
3. Choose the boards. A change that acts on every board runs on the sprint suites; a change to one mechanism (BGA escape,
   pours, converters, …) runs on `bench/suites/mech/<mechanism>.txt`. Limits: at most 40 CPU-h per campaign, no board
   over 0.5 CPU-h per run; larger tiers (ladder, canary) only after a sprint result.
4. Run: `python3 tools/haslamres/haslamres.py sprint <name> --base bridge|staged --commit <sha>` runs your arm against the
   stored control's runs. Smoke one or two boards first and read their runs.
5. Verdict, paired per board and seed: better, worse or undecided, with an interval, in `VERDICT.md`. Mixed results
   get a per-board look before anything is concluded.

**Rules that keep results comparable**

- Scoring code (`bench/src/haslambench/score.py`, the evaluators) defines the benchmark. A fix to it is its own commit that
  says why, and stored results are re-scored, not re-run.
- Every arm runs at the same tag, with the same Freerouting build, on counted-work budgets, side by side.
- A method's only score is `kicad-cli` on its re-opened output board.

Background: [`docs/INDEX.md`](docs/INDEX.md) (digests, then topic docs; `research_notes/` is raw evidence).

## License

Code is [GPL-3.0-or-later](LICENSE); docs and research notes CC-BY-4.0, rule packs CC0-1.0, datasets CDLA-Permissive-2.0,
model weights Apache-2.0 ([`LICENSING.md`](LICENSING.md); [`CONTRIBUTING.md`](CONTRIBUTING.md), DCO sign-off).
