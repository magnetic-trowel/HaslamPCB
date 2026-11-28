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
bench/scripts/setup.sh --all                 # KiCad 10 (apt with sudo, else Apptainer), the Freerouting fork of
                                             # bench/freerouting.ref, bench/haslam/synth venvs, ~/.cache/haslambench/env.sh
source bench/.venv/bin/activate && haslambench doctor --pipeline   # every piece below, checked
```

`env.sh` exports everything the pipeline reads: `HASLAM_HOME`, `HASLAM_KICAD_WRAP` (empty with a native KiCad; run KiCad
as `$HASLAM_KICAD_WRAP kicad-cli …` or `$HASLAM_KICAD_WRAP python3`), `KICAD10_SYMBOL_DIR`/`KICAD10_FOOTPRINT_DIR`, and with a
container KiCad `APPTAINER_BIND` (the checkout; set it yourself for a work dir elsewhere). Every shell and job:
`source ~/.cache/haslambench/env.sh`, KiCad under `ulimit -v 40000000`. The synth venv has `haslam/src` on its path; the
haslam venv has haslam installed, so no `PYTHONPATH` is needed.

On a shared host, run anything over about ten minutes or two cores through haslamq (`tools/haslamq/README.md`):
`haslamq submit --cpus N --mem XG --timeout T --owner <name> -- CMD`, then one background `haslamq wait`. Jobs run a
frozen snapshot of the checkout. Retry and cancel your own jobs only, by id or `--owner`. On a single-user machine (your
own computer, a cloud container without haslamq), run the same commands directly, long ones in the background.

---

# Part 1: Design a PCB

A design lives in `tools/research/llm-design/designs/<slug>/` (example: `solar-small`). **This table is the canonical
stage list**; [brief-to-board](docs/topics/workflow/brief-to-board.md) holds the worked example and failure modes, and
[synth/README.md](tools/research/llm-design/synth/README.md) the `design.py` API. Stages 3-11 run through
`synth/scripts/pipeline.py`, from the repo root in the haslam venv with `env.sh` sourced:

```bash
P="haslam/.venv/bin/python tools/research/llm-design/synth/scripts/pipeline.py tools/research/llm-design/designs/<slug>"
$P status          # every gate and the next stage
$P build           # then board, preflight, size, layout (once per seed), physics, warnings, review, fab
```

`pipeline.py` records each gate in `haslam-work/<slug>/pipeline/status.json`, refuses a stage while an earlier gate is
unmet or older than `design.py`/`parts.py`/`board.json`, and writes fabrication files only for a board that passed
every gate. Script paths below are relative to `tools/research/llm-design/synth/scripts/`.

| # | Stage | `pipeline.py` stage: what it runs | Gate |
|---|---|---|---|
| 1 | Requirements and parts | (you) read datasheets (tables and figures, not summaries); check stock and basic/extended status with the JLC parts API | every number has a page citation |
| 2 | Circuit as code | (you) `designs/<slug>/parts.py` (part cards), `design.py` (blocks, nets, placement relations, intent; `haslamsynth api` lists every call), `board.json` (outline, holes, fixed parts, pours, keepouts), custom footprints | — |
| 3 | Schematic and checks | `build`: `haslamsynth jlc` (LCSC numbers of generic passives, `jlc.json`), then `haslamsynth build -v` → `designs/<slug>/out/`: `.kicad_sch`, `.kicad_pro`, `.kicad_dru`, `bom.csv`, `report.md`, `<slug>.haslam_intent.json` | exit 0: 0 unwaived errors (incl. `rules.pin_escape`, `rules.pad_gap`), ERC clean, netlist round trip identical; read every warning in `report.md` |
| 4 | Unplaced board | `board`: `sch_to_board.py out board.json` at the `size` stage's best outline, else `board.json`'s | board written |
| 5 | Pre-flight | `preflight`: `preflight.py <board> --probe` (KiCad and Freerouting reachable, rules parse, schematic parity, fixed parts legal, fab profile, intent, a 3-minute place-and-route probe) | 0 FAIL; read each WARN and `blocked:` line. This is the unplaced board's gate: a plain DRC lists every unplaced part |
| 6 | Board size | `size`: `size_search.py` (start at 25 % courtyard density, shrink while DRC and `width_check.py` pass; resumable) | a passing outline |
| 7 | Layout | `layout --seed N`: `layout.sh <board> <run> <seed>` (place, route, DRC, `width_check.py`; minutes to hours) | ≥ 3 seeds routed; the best has 0 DRC errors, 0 unconnected and passes `width_check` |
| 8 | Physics | `physics`: `haslam.excite.evaluate` + `haslam.intent status` on the best seed | evaluation complete; no `hard` term violated |
| 9 | DRC warnings | `warnings`: the best seed's DRC warnings by type | each type listed in `designs/<slug>/drc_warnings.json` with a reason |
| 10 | Review | `review`: an independent review | `designs/<slug>/REVIEW.md` newer than `design.py` and `parts.py` |
| 11 | Fabrication | `fab`: `fab_outputs.py` (zone refill, DRC, Gerbers, drill, CPL, BOM) | fab-report gate passes; no blocking question open in `report.md`; `fab-report.json` lists extended parts (each a JLC setup fee) |

Where to run the long stages (`size`, `layout`, `physics`): on a single-user machine run `$P layout --seed N`
directly (in the background); on a shared host submit each through haslamq (`haslamq submit … -- $P layout --seed N`)
and wait with one background `haslamq wait`. Comparing seeds or design variants side by side (DRC by type, open
connections, every physics term): `compare_ab.py <rundir> --md table.md`.
`designs/solar-small/run_ab.sh` is solar-small's own A/B of layout recipes, not a stage.

**How each stage works** (by name; stages 1-2 are yours, the rest are `pipeline.py` stages)

- **Requirements and parts.** The designer (often an LLM) turns the product brief into numbers (voltages, currents,
  switching frequencies, limits) and picks parts that JLCPCB can assemble, preferring basic parts, which have no
  per-order setup fee.
- **Circuit as code.** The circuit is Python: part cards carry each part's pins, footprint, ratings and datasheet facts;
  `design.py` connects them into blocks and nets and states what the board must achieve; `board.json` gives the
  outline and anything mechanical that cannot move (connectors, holes, the module socket).
- **Schematic and checks.** Generic resistors and capacitors are matched to in-stock JLC parts by value, package,
  voltage and dielectric. haslamsynth checks the circuit (ratings against operating stress, ERC, netlist round trip)
  and writes the KiCad project. It derives clearance rules per net pair from each net's voltage (IPC-2221B) and track
  minimums from the finest pad pitch, and proves every pin can still escape under them. It also writes the **operating
  intent** (`<slug>.haslam_intent.json`, beside the board like `.kicad_pro`): the facts haslam cannot read from copper (rail
  voltages; each converter's input, output, current and switching frequency; cables) and the requirements, as terms
  with tiers (`hard` limits, `limit` budgets, `cost`). `python -m haslam.cli brief <board>` shows how haslam reads them.
- **Unplaced board.** The netlist becomes a `.kicad_pcb` with every footprint, the fixed parts in place, pours,
  keepouts and the fab's stackup (JLC 2-layer 1.6 mm FR-4 unless `board.json` `stackup` says otherwise).
- **Pre-flight.** A few minutes of checks catch what would waste a long run: KiCad and Freerouting reachable, rules
  accepted by KiCad, schematic parity, fixed parts legal, intent complete, and a short place-and-route probe that
  lists any connection the rules block.
- **Board size.** The outline is edge-anchored (`board_spec.py`), so the search can shrink it and re-place the fixed
  parts without hand edits.
- **Layout.** haslam places the parts (an annealer with legality checks, priced by wire length, physics terms
  and routability), routes them (Freerouting plus haslam's repair and last-mile router, which respect pad-entry,
  thermal-spoke and clearance rules), and restarts with new seeds while connections stay open, on a budget of counted
  work rather than wall time. KiCad's DRC and the width check (IPC-2221 width against each net's current) judge the
  routed board.
- **Physics.** haslam's evaluator solves the copper (layered, with 3D inductance and the stackup's capacitance) with
  every converter as a noise source and reports pickup, overshoot, emissions, losses and temperatures against the
  intent's terms. An incomplete evaluation (`why_incomplete`) prices nothing it could not compute.
- **DRC warnings and review.** Every DRC warning type gets a written reason, and an independent reviewer reads the
  design, so a board that passes the checks is still read by someone who did not write it.
- **Fabrication.** Zones are refilled, DRC must pass, and the Gerbers, drill files, pick-and-place file and BOM with
  LCSC numbers are written in JLCPCB's formats.

Judge every result by KiCad's DRC and the evaluator on the re-opened board, never by a tool's own log.

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
