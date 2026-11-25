# Joint placement and routing

Scope: our methods that place parts and route copper together: the **pnr line** (own place-and-route engine, 2026-10-24 to 2026-10-27, 30 methods, judged by KiCad DRC and haslam physics) and the haslam line's joint loop. Not here: joint-loop design -> [joint-loop](../../topics/architecture/joint-loop.md); experiment log -> [joint-pnr-experiments.md](../../topics/placement/joint-pnr-experiments.md); verdict per idea -> [scorecard.md](../../ideas/original/scorecard.md).
Keys: joint place-and-route, pnr, pnr line, ab33, dev6, phys10, v5 era, v7 era, xf3, merit list, merit arm, eras, harness bugs, board licences

## Results

- Placement and routing are not separable: the same continuation with parts frozen after the start used ~2× the copper on 24/24 boards → [jc.md](jc.md#jc).
- Physics terms in the placement objective cost nothing in routability → [physics-objective.md](physics-objective.md).
- What worked keeps several alternatives alive and judges them by real routing (beam search, annealing, restarts, continuation); continuous forces, exact solvers and an LLM proposer did not beat simple controls [I].

## Pages

| page | methods (code) | verdict |
|---|---|---|
| [board-studies-2611.md](board-studies-2611.md) | four hard boards taken apart: open connections by cause (polarfire-som, nekoink, sdi-mipi, gecko5education) | worked (study): fixed zones ignored by the placer, scattered arrays, deep BGA rings, blind restart choices |
| [engine.md](engine.md) | pnr engine, `route_only`, fast router `PNR_FAST`, anytime output (`tools/research/pnr`) | worked (substrate); fast router thin evidence; anytime untested alone |
| [sequential-controls.md](sequential-controls.md) | seq, seq_margin, grow | control; no merit; no merit alone |
| [physics-objective.md](physics-objective.md) | physics place terms, physics scorer (`pnr_phys`) | worked |
| [anneal-and-repair.md](anneal-and-repair.md) | anneal(_phys), blocker repair, CP-SAT windows (`pnr_cpsat`) | worked; worked as a stage; did not work |
| [tree-search.md](tree-search.md) | beam, MCTS (`pnr_mcts`) | beam worked (moderate); MCTS did not at this budget |
| [combo.md](combo.md) | beam → repair_phys → anneal_phys | worked |
| [forces-and-fields.md](forces-and-fields.md) | pin tension, bloat, soft-route gradients (`pnr_grad`), Physarum (`pnr_slime`) | did not work; grad_phys partial for physics |
| [llm-proposer.md](llm-proposer.md) | LLM relational moves (`pnr_llm`) | did not work |
| [layer-collapse-analysis.md](layer-collapse-analysis.md) | layer-count bounds, exact layer assignment, collapse placement terms (`collapse_obst`, `collapse_assign`, `collapse_cplace`) | did not work; narrow partial results |
| [jc.md](jc.md) | negotiate, jc, jc2 (`collapse_joint`) | partial; worked on ab33 (best family), did not carry to the 213-board merit suite (cp1 0.225 vs haslam 0.29–0.31); jc2 likely worked, unconfirmed |
| [jc-extensions.md](jc-extensions.md) | harmonic pressure, learned value, QD archive, min-plus maps (T1), exact physics maps (T2) (`harmonic`, `learn_value`, `qd_archive`, `xf_minplus`, `xf_physmap`) | none clearly beat jc; min-plus leans merit on vias |
| [pour-models.md](pour-models.md) | minimal-partition pours, pour-damage maps (T4) (`collapse_pour`, `xf_pour`) | did not work; worked on physics, needs confirming |
| [untested-ideas.md](untested-ideas.md) | T3, T5–T12, untested catalog ideas | untested |
| [haslam-staged.md](haslam-staged.md) | haslam place, then Freerouting bridge + last mile (`haslam/src/haslam/joint/cli.py` `--max-iters 0 --no-modules`) | worked on A+B; partial on split C |
| [haslam-joint-loop.md](haslam-joint-loop.md) | haslam joint loop (`haslam/src/haslam/joint/`, `tools/research/joint/`) | worked on A+B; clock-bound on split C |
| [window-outcomes-2611.md](window-outcomes-2611.md) | how the joint loop's windows end; J3 skip windows on DRC types no move can change | J3 did not work: futile windows gone, freed time unused |
| [window-budget-2611.md](window-budget-2611.md) | joint-loop windows at 1–4 budgets; fixes J2, J4, J5, J14; compute-matched vs restarts | windows pay only with extra compute; J2/J4/J5 did not work; J14 (`first_last_mile`) worked; restarts beat windows at equal CPU |
| [restart-screen-2611.md](restart-screen-2611.md) | `restart.py --screen` on the joint method (j1-screen) | did not work: inside replicate noise |
| [restart-last-slot-2611.md](restart-last-slot-2611.md) | restarts' last slot: fresh attempt vs resumed bridge pass vs windows polish on the kept board (pk3-ab) | resumed pass worked (-6.3 % opens); windows add nothing on top; the default recipe already resumes via `--open-alt` |
| [dead-ends-2611.md § 2](../dead-ends-2611.md#2-part-slides-inside-the-last-mile) | Part slides inside the last mile, compiled from the blocked diagnosis | 6.0 % of binding gaps name a movable small part (kill line 20 %); a legal slide clears 1-2 %: did not work (stored-data analysis) |
| [dead-ends-2611.md § 6](../dead-ends-2611.md#6-llm-diagnosis-from-report-test-on-past-abs) | LLM diagnosis-from-report test on past knob A/Bs | "helped" labels fire at 9.4 %, seed noise at 9.2 %: did not work (stored-data analysis) |
| [dead-ends-2611.md § 13](../dead-ends-2611.md#13-joint-loop-windows-as-built) | Joint-loop windows as built; campaigns `loop-win3`, `j10-joint-window2` retired by user decision | 3.1 % of windows kept; window stage unreached at sprint budgets: did not work |
| [window-choice-2611](window-choice-2611.md) | Windows chosen from the blocked diagnosis, tabu, exact legality (`loop-win`, `loop-win3`) | Wall vs restarts undecided (d −0.059, p 0.17); delivered opens −20 % vs restarts; tabu worse; evidence no gain; `legal_exact` illegal windows −71 % |
| [window-ends-2611](window-ends-2611.md) | Window fixes, diagnosis, ends-only rip-up, soft window copper; the windows line concluded | Keep rate stays 5-8 %; window-ends5 opens −1.6 % (p 0.31): did not work |
| [dead-ends-2611b § 1](../dead-ends-2611b.md#1-exact-legality-for-windows-and-a-resumed-bridge-instead-of-windows-legal_exact-openalt) | `legal_exact` in the default's windows half; a resumed bridge pass instead of windows (`openalt-ab`, `openalt-ladder`) | Dwx 0.997 [0.980, 1.016] (null); Dbridge 1.163 [1.100, 1.238] (decided loss): windows half kept |

Older micro-benchmarks of the same research, listed in the placement area: synthetic CP-SAT / annealing placement (`tools/research/solver-bench`, [solver benchmarks](../../topics/solvers/benchmarks.md)); decap distance statistics (`tools/research/layout-data`).

## Eras and caveats

| era | engine | harness / task | seeds | notes |
|---|---|---|---|---|
| v5 | v5 | harness v3, `--kinds place --probe self` (method places, probe routes) | mostly **1** | |
| v7 | v6.3 ([c78c537](https://github.com/magnetic-trowel/HaslamPCB/commit/c78c537d0b4928fb4505065a39d07934887c577b)) | score v7, `--kinds joint` (method places and routes in one output) | **3** | headline set: 28 boards engine v6.4 leaves unchanged ([v63-v64-unchanged.txt](../../../tools/research/pnr/results/v63-v64-unchanged.txt)) |
| xf3 | fixed engine [4c4330a](https://github.com/magnetic-trowel/HaslamPCB/commit/4c4330a97b4bd1e1ee735a441674f095be12d458) | score v7, joint tasks, fresh `xf3-base-*` baselines | **3** | all 33 boards; xf rounds 1 (place tasks, older engine) and 2 (stopped when the engine fix landed) not comparable |

- Numbers from different eras never share a table; runs compare only within one engine version.
- Suites: **ab33** = 33 qualified A/B boards (≤ 31 and 32–200 pads), 120 CPU-s per board, KiCad 10.0.7; **phys10** = the 10 of them with any physics structure; **dev6** = 6 development boards.
- haslam's physics priors are unmeasured ("E5"): physics ratios are relative, not absolute.
- Judge: kicad-cli DRC on the re-opened board; a router's own log is not a score.
- Two boards (azonenberg, suzyqboard) draw their outline inside an unlocked footprint, which the place task stages off-board: every method fails them.
- Joint methods compact boards more than humans do; place-task scoring does not reward connectors at edges or mechanical intent.
- Partial or thin evidence: v7 jc baselines ([jc.md](jc.md#jc)); jc2 ([jc.md](jc.md#jc2-jc-hardened)); fast router, 2 boards ([engine.md](engine.md#fast-router-pnr_fast-2026-10-26)).

## Merit list

22 pnr arms are in the 500-board comparison (`tools/haslamres/experiments/merit-restart.sh`; experiments `merit-500r3` / `merit-500r3k`, running; results pending), all on engine [957a37f](https://github.com/magnetic-trowel/HaslamPCB/commit/957a37fd0d58483e0b8194d24ab47cfd69c56d9d) (fast router + anytime output): route_only, seq, seq_phys, anneal, anneal_phys, repair, negotiate, beam, combo, combo_full, seq_collapse, grad_phys, jc, jc_lv, jc_full, xf_h, pjc2, pjc2_lv_nopol, hjc_press, qd, jc2_fix, jc2_fixmp_lv. Selection: "merit or partial merit"; seq_collapse, qd, hjc_press, xf_h, pjc2_lv_nopol, combo_full and jc2 carry weaker verdicts on their pages. Arm options: `beam --opt phys_w=2`, `seq_collapse --opt w_fv=4 w_x=1 w_ovf=0`, `grad_phys --opt post=phys`. Not merit arms: mcts, grow, seq_margin, cpsat, combo_lv, collapse pours, exact physics maps, LLM proposer. haslam arms "haslam staged (restarts)" and "haslam joint loop (restarts)": [haslam-staged.md](haslam-staged.md), [haslam-joint-loop.md](haslam-joint-loop.md).

## Harness and engine lessons

Harness bugs found along the way (each fixed in a separate commit): relative paths for `--command`; locked footprints staged off-board (made 7 of 33 place tasks unsolvable); no way to score joint methods (→ `--kinds joint`, score v7); a legality model stricter than KiCad; the sandbox hiding `/tmp` (haslam import); concurrent `prepare` runs writing one workdir; tasks re-prepared, and the engine edited, under running jobs; `cpu_s` near zero for sandboxed methods. Details: [v7-bugs.md](../../../tools/research/pnr/results/v7-bugs.md), [BUGS.md](../../../tools/research/collapse_joint/BUGS.md), [scorecard.md](../../ideas/original/scorecard.md).

## Boards and licences

ab33 boards come from public repositories in `bench/manifests/candidates.jsonl`. Only summary numbers are published, no board geometry or renders. Licences of boards named on these pages:

| licence | boards |
|---|---|
| CERN-OHL-S-2.0 | olimex dcdc-50-5-12, 0rax esphome xiao, lambdakb lt6c, tzarc kobold, caffeinated aftonsparv |
| CERN-OHL-P-2.0 | badjeff paw3222, paw3395, pmw3610; siderakb pmw3360, pmw3610; jvedder bipolar supply; 0xjmux esp-prog adapter; bluerobotics ping dev kit |
| CERN-OHL-W-2.0 | berkeleylab obsidian |
| CC-BY-SA-4.0 | electron271 tuxkeychain, kicad-demos ecc83 and video |
| GPL-3.0-only | tcsullivan noisecard |
| GPL-2.0-only | c-biscuit crowbar |
| MIT | jangtrinh desktop companion, d3a kitspace gas sensor, bentwire usb-c fusb302, m1geo pi5-pcie |
| Apache-2.0 | justbuchanan oasis (pcb, ledboard), rapidanalysis xerxes |

## Sources

- Catalog: [joint-pnr.md](../../ideas/original/joint-pnr.md), [layer-collapse.md](../../ideas/original/layer-collapse.md).
- Notes: [literature survey](../../../research_notes/joint-pnr/literature-survey.md), [transformations](../../../research_notes/transformations/transformations.md), [layer-collapse analogs](../../../research_notes/layer-collapse/analogs.md).
- Other areas: placement, routing and physics under `docs/research/`.
