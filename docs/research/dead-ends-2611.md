<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Ideas dropped 2026-11-20 to 2026-11-22

Scope: the fifteen ideas dropped after the 2026-11-20 design sessions: what was tried, the evidence, why each is a dead end, what would reopen it. Not here: the audit that set them up -> [audit-2611b](audit-2611b.md); ideas that passed (ground-side routing cost, TraceMaker hybrid) -> their experiments `ground-side-ab`, `tm-hybrid`.
Keys: dead ends 2611, place_phys_hinge, satisficing physics, part slides, cut overflow, learned failure model, pin swap, bus inversion, LLM diagnosis, count certificate, stop rule, conflict-set closure, repair_cycles, permute_pins, reach check, confidence sequence, TraceMaker, joint-loop windows, ground skeleton, budget exponent, seed diversity

**Status:** per item (first line of each section; README rows carry the same). **Dates:** 2026-11-20 (stage 0 analyses) to 2026-11-22 (sprint verdicts). **Code base:** tag `baseline/2026-w47` (main c2dd008); stored control `control-w47` (seeds 0, 1; counted-work budget 900 s × √(footprints / 40); Freerouting fork 37b1a8b). **Kinds:** *experiment* = sprint run judged by kicad-cli DRC; *stored-data analysis* = no new run, a pre-registered kill line applied to stored outputs (mostly `s2-merit213`); *micro replay* = short re-run from stored boards. Intervals: 95 % board bootstrap unless named.

## 1. Satisficing physics term in the placer

**Did not work (opens undecided)**; experiment.

- **Tried:** experiment `place-satisfice` (arms `t07`, `t10`), branch `place-physics-satisficing` 2f3e7d8e, unmerged; setting `place_phys_hinge=θ`, off by default. Annealer price per structure with `u = value / budget`: 0 for u ≤ θ; `(u − θ)/(1 − θ)` up to budget; plus `β(u − 1)²`, β = 4, to u = 3; log tail. Suite `sprint-quality`, 79 boards under the cap, seeds 0, 1 (158 pairs); control `control-w47` staged.
- **Evidence** [C]:

| | θ 0.7 | θ 1.0 |
|---|---|---|
| opens, Δ log1p | −2.6 % [−9.6, +4.9]; 25 better / 37 same / 17 worse | −0.7 % [−8.5, +8.1] |
| routed modules with u > 1 | 484 → 566; +0.52 / board [0.29, 0.75] | 486 → 588; +0.65 [0.37, 0.96] |
| routed decap ratio arm / control | 1.21 [1.05, 1.43] | 1.40 [1.01, 1.87] |
| crowding (control 0.99, human 0.72) | ×0.96 [0.91, 1.03] | ×0.92 [0.86, 0.99] |

  A/A of the control's seeds: +0.23 [0.01, 0.44] over-budget modules. CPU 78 h.
- **Why dead:** the pre-registered kill fired: over-budget modules rise beyond A/A. Margin freed at placement is not kept by routing (placer physics vs routed physics within a board: ρ 0.02-0.18) and crowding barely moves. Opens alone are undecided; deciding them needs about 3× the boards.
- **Reopen if:** the hinge-only arm (`place_phys_hinge_beta=0`, the plan's named follow-up) is run, or the freed room is aimed at the pads that end up stranded (escape room at 2-4 mm, [§ 3](#3-cut-overflow-routability-term)), on about 240 boards.

## 2. Part slides inside the last mile

**Did not work**; stored-data analysis.

- **Tried:** slide a small unlocked part (≤ 4 pads) by the deficit `kae.route.blocked` reports, so the relaxed path becomes legal. Stored-data analysis: relaxed search with all copper in place on 966 diagnosed opens of 59 staged boards, kae's own geometry, no KiCad DRC; 2.6 CPU-h. Scripts `t1_rediag.py`, `t2_elastic.py`, `t3_insert.py` (design-session scratch, not committed).
- **Evidence** [C]: binding gap against another net's via 33.0 %, own part's pad 15.5 %, another net's track 14.5 %, larger part 9.7 %, **small unlocked part 6.0 % [3.9, 8.8]** (kill line 20 %); P22 (staged open, bridge clean) 15.1 % [6.9, 23.1]; joint loop 6.0 %, bridge 3.4 %. Deficits median 0.22 mm, yet a legal slide in any of 17 directions clears the binding gap for 1.0 / 1.4 / 2.1 % of opens at 0.5 / 1 / 2 mm, and every gap of the path for 1 of 966 (the path runs between the part's pads).
- **Why dead:** small parts are rarely what blocks, and moving one rarely clears the whole path.
- **Reopen if:** an elastic finishing state exists (vias and tracks move with the part: 51.2 % [44, 59] of slides ≤ 1 mm are feasible without rip-up; track shove alone fits 11.7 % of opens). Part slides then become one move of that engine, not a mechanism of their own.

## 3. Cut-overflow routability term

**Did not work**; stored-data analysis.

- **Tried:** stored-data analysis, `tools/research/joint/cut_rank.py` (branch `d2-cutflow` 55dee915). Delaunay triangulation of pad centres; per-layer cut capacity `⌊(gap − clearance)/(width + clearance)⌋` from the board's rules; nets routed over the dual graph; 8 negotiated rounds; overflow summed. Ranked against routed KiCad opens within a board.
- **Evidence** [C], median within-board Spearman:

| Measure | `bus-pose-ab` (103 boards, 1,209 placements) | `placement-routability` (41, 623) |
|---|---|---|
| cut overflow, negotiated | 0.275 [0.18, 0.39] | 0.21 [0.16, 0.32] |
| HPWL | 0.28 [0.15, 0.36] | 0.07 [−0.14, 0.34] |
| RUDY, top decile | 0.25 [0.16, 0.40] | 0.31 [0.23, 0.42] |

  Kill line 0.3. Partial given HPWL 0.19 [0.12, 0.28]; 2-layer 0.42, HPWL 0.44. A 60 s real route ranks at 0.53. Human vs ours (195 boards): overflow is higher on ours where opens are worse (23 vs 8) and also where equal (17 vs 9).
- **Why dead:** it sees that our placements are tighter, not where tightness costs connections; no better than HPWL or RUDY.
- **Reopen if:** a placement-only measure ranks above 0.3 and beats HPWL and RUDY on the same placements. The measured lead is part-attached: excess crowding at stranded pads, AUC 0.567 [0.526, 0.608] at 2 mm.

## 4. Learned placement-level failure model

**Did not work**; stored-data analysis.

- **Tried:** stored-data analysis, `tools/research/diagnostics/placement_rank.py` (branch `d5-stage0-tools` c7b00198): 9,809 placements, 211 boards, 165 owners, 42 features.
- **Evidence** [C]: model minus best single feature +0.04 to +0.075 in within-board ρ, intervals include 0. On 201 same-arm seed pairs, flyline crossings alone order pairs at 0.629 [0.567, 0.686], every model 0.52-0.56; HPWL at chance. Within-board share of log-opens variance 1.7-5.5 %; model-based selection −2.4 % opens, oracle −12 %.
- **Why dead:** little within-board variance to learn, and one feature already captures it.
- **Reopen if:** labels exist per connection on kae placements (connection ledger). Net-level signal is real: within-board AUC 0.847 vs 0.804 for MST length (+0.043 [+0.015, +0.074]), +0.115 [+0.063, +0.167] on 2-3 pad signal nets, human placement only.

## 5. Pin and gate swaps as a search variable

**Undecided (parked)**; stored-data analysis.

- **Tried:** stored-data analysis, `tools/research/diagnostics/bus_inversions.py` (`d5-stage0-tools`): 529 census buses on 113 merit boards (census reproduced on 527).
- **Evidence** [C]: inversion density staged 0.284 vs human 0.266, +0.018 [−0.022, +0.061] (435 buses, 105 boards). An optimal in-group swap removes 76-79 % of inversions under either placement (40 % with strict classes). 34 % of diagnosed staged opens sit on a bus with a swappable end (15 % strict), half of them on three big boards. Within boards, inverted buses have more opens on 7, fewer on 6.
- **Why parked:** the premise (pin-outs co-adapted to the human placement, so our placements invert buses) is not supported; whether inversion causes opens is undecided. **Not refuted for FPGA boards:** there the pin-out is a free choice inside banks, swap groups are far larger than the census's classes, and few merit boards carry one.
- **Reopen if:** the connection ledger shows opens tied to inversion (board as a random effect), or an FPGA/CPLD suite is built.

## 6. LLM diagnosis-from-report test on past A/Bs

**Did not work**; stored-data analysis.

- **Tried:** stored-data analysis (`cases0.py`, `select0.py`, design-session scratch): label past knob A/Bs "helped" or "hurt" per board, then test whether a diagnosis read from the control's report predicts the label.
- **Evidence** [C]: 98 knob A/Bs (186 arms, 1,232 boards open in control). Rule: helped if opens fall ≥ max(2, 20 %) or the board becomes clean. Knob A/Bs: helped 9.4 %, hurt 18.8 %; two seeds of one recipe: helped 9.2 %, hurt 7.2 %. P(helped on seed 1 | helped on seed 0) 0.27 (n 260) vs 0.055. Helped on every seed: 47 cases on 30 boards; a diagnosis exists for 16 of them; 384 of 400 sampled control runs have no `restart-report.json`. Picking the best arm per board on seed 0, scored on seed 1: −2.1 % [−5.1, +0.7]; one global arm −2.5 % [−5.8, +0.6].
- **Why dead:** "helped" fires at the seed-noise rate, so there is no ground truth to score a diagnosis against, and with today's knobs a perfect per-board choice is worth no more than one global setting.
- **Reopen if:** every run stores its diagnosis and DRC detail, and knobs exist whose per-board effects exceed seed noise.

## 7. Count-based capacity certificate

**Did not work**; stored-data analysis (replay).

- **Tried:** stored-data analysis, scheduler replay (`tools/research/effort/replay.py`, branch `d4-replay` f60e6e1f): stop when the open count stays flat over doublings.
- **Evidence** [C]: the premise (stable count, changing nets) holds in 5 of 55 same-placement groups with ≥ 3 runs. Replayed: −0.8 % CPU on the bridge; on route-only restarts (CB) −53.8 % CPU, **−9 clean boards, +698 opens** (flat over two doublings, then clean).
- **Why dead:** a flat count does not mean no capacity.
- **Reopen if:** never as a count rule. The sound form is per-placement certification by cause: rule and geometry diagnoses recur on the same placement with probability 0.98-0.99, fixed copper 0.96, congestion 0.61 (`tools/research/effort/certified.py`).

## 8. Stopping earlier as the budget lever

**Did not work**; stored-data analysis (replay).

- **Tried:** stored-data analysis, the same replay on 209 bridge boards (fixed schedule 125.9 CPU-h, 157 clean, 847 opens).
- **Evidence** [C]: oracle "stop after the best wave" −9.3 % CPU [−15.0, −4.9]; near-miss plus count-stability stop −6.4 % CPU, 154 clean, 865 opens. Stopping Freerouting after dry passes: ceiling under 1 %. Lanes instead: probe 4 seeds, then 1 fresh + 1 resumed lane, −44.1 % CPU, −5 [−10, −1] clean; at equal CPU +21 [+13, +31] clean.
- **Why dead:** even a perfect stop rule saves 7-10 %; no policy saves 15 % at equal outcome. The lever is lane width, which `d4-sched-width` tests.
- **Reopen if:** budgets grow far past the last useful wave.

## 9. Conflict-set closure for near-miss boards

**Did not work**; micro replay.

- **Tried:** branch `d4-closure` 428c8f61 (`kae/src/kae/route/closure.py`, setting `closure=1`): take the path that exists without our copper, rip the nets it crosses (conflict set K, shrunk greedily), solve {open} + K jointly over all orders (≤ 24), all-or-nothing through the journal; never rip input or locked copper. Sets are small (median 2-3 nets). Micro replay `d4-closure-micro`: 11 near-miss bridge boards, 30 opens, 120 s counted work from the stored board.
- **Evidence** [C]: control (last mile with rip-up) and closure each closed 0 opens; none worse. Closure records: 15 "needs fixed copper", 5 joint solve failed, 5 out of time.
- **Why dead:** pre-registered kill (fewer than 3 boards) met. Half the opens need fixed or input copper moved, which closure may not touch; `lastmile.close` already rips what a soft search crosses. Limit: the control closed nothing either, so 120 s cannot separate arms.
- **Reopen if:** an elastic state can move vias and fixed copper ([§ 2](#2-part-slides-inside-the-last-mile)), or a longer replay in which the control closes something.

## 10. Routing-budget reserve and repair loop

**Undecided**; experiment.

- **Tried:** experiment `route-budget` (arms `route-budget-loop`, `route-budget-permute-pins`), branch `route-budget-fixes` c5820913. `last_mile_reserve_share=0.15` (reserve 0.15 × budget, 30-90 s, instead of an absolute 135 s rule) and `repair_cycles=0` (repair rounds and last mile alternate while the board improves). Suite `sprint-frontier`, 51 boards (9 over cap), target set 19 pairs on 10 boards (control open, < 90 % budget used).
- **Evidence** [C]: paired `d = (o_arm − o_ctl)/(o_arm + o_ctl + 1)` −0.015 [−0.049, +0.001] (sign-flip), 1 better / 9 same / 0 worse; opens 166 → 158; DRC errors 866 → 864. CPU 43.5 h.
- **Why undecided, not dead:** at ≥ 600 s budgets nothing is left over to spend (137 of 140 sprint boards get the 90 s reserve in both arms). The failure was measured in 60-365 s restart waves: 175 of 264 `s2-merit213` attempts skipped every repair round for time, with a median 48 % of budget unused.
- **Reopen with:** a control at 60-365 s wave budgets.

## 11. State-hash reach check and confidence sequences at sprint size

**Did not work**; stored-data analysis.

- **Tried:** stored-data analysis. Reach (`tools/kaeres/reach.py`, branch `d6-reach` 4dafcfd4): skip an arm's run when its state after the changed stage hashes equal to the control's. Stopping: empirical-Bernstein confidence sequence (Waudby-Smith and Ramdas 2024) on paired board differences clipped at ±2 (`confseq.py`, design-session scratch).
- **Evidence** [C]: placement fingerprint (`hpwl, scorecard, crossings`) identical on **0 of 507** pairs for the crossing and channel terms (89 under counted work), 5 of 132 for untangle. Sequence width / fixed-n width: 5.0× at 60 boards, 2.5× at 300, 1.8× at 1,200; on 188 stored arms fixed-n excludes 0 on 79, the sequence on 24.
- **Why dead:** any annealer term change moves the whole anneal, so a hash saves nothing for placement terms; a sequence costs 5× the boards at sprint size.
- **Reopen if:** the change is gated or late (reach check pays about half the CPU there), or evidence accumulates over weeks to ≥ 1,200 boards (sequence then 1.8×).

## 12. TraceMaker as a replacement engine

**Did not work**; experiment.

- **Tried:** experiments `tm-d3c`, `tm-mech30`, `tm-mech-bridge`; TraceMaker v0.12.1 db5950f4 (GPL-3.0) as a sandboxed `--command` method reading the board and rules natively, 120 s and 600 s × 8 threads, wall clock (branch `tracemaker-trial` 0fae2dbd).
- **Evidence** [C]: TraceMaker 600 s against the bridge on 30 boards: better 6, worse 23, median log opens ratio +1.04; against the fork alone better on 26. Open signal connections 262 vs bridge 488, but 294 of its 712 opens involve a zone (bridge 12): it trusts its own in-memory zone fill, and KiCad's refill splits planes and starves thermals. 5× time: opens −16 % for 3.5× CPU.
- **Why dead:** loses on planes, runs on wall clock. Kept: its signal routing, as the first router on BGA boards in `tm-hybrid` (hybrid − control −15.2 opens per pair [−29.7, −3.2]; 272 CPU-h against a 150 cap) and as pin-first strict search to port into the fork.
- **Reopen if:** it keeps KiCad's zone refill in its loop and budgets by counted work.

## 13. Joint-loop windows as built

**Did not work**; experiments + user decision.

- **Tried:** the joint loop's window repair (re-place parts near an open, rip about 10 nets, fresh Freerouting, full-board DRC per try) → [kae-joint-loop](joint/kae-joint-loop.md), [window outcomes](joint/window-outcomes-2611.md), [window budget](joint/window-budget-2611.md).
- **Evidence** ([audit-2611b](audit-2611b.md#six-conclusions); `j10-joint-window2` verdict): 126 of 4,036 windows kept (3.1 %), about 2 useful revisions per CPU-hour; 38 % die illegal, 28 % end with more opens. `j10-joint-window2` (cancelled at 25 %): in 25 of 28 runs per arm no re-placement ran at 900 s × √(fp/40). Placements under 1 % of the diagonal apart differ in opens as much as unrelated ones (77 pairs, 4 boards, descriptive).
- **Why dead:** a fresh restart re-draws every pose and beats windows at equal CPU. The remaining campaigns `loop-win3` and `j10-joint-window2` (about 1,300 queued CPU-h) were retired by user decision on 2026-11-20.
- **Reopen if:** `d2-perturb-response` shows the router responds smoothly to small placement changes, or windows edit an elastic state instead of ripping nets.

## 14. Ground skeleton first on boards without a plane

**Did not work (superseded)**; stored-data analysis.

- **Tried:** stored-data analysis (`s0_return.py`, design-session scratch) on 46 2-layer boards finished by the human, bridge and staged: reserved ground bands as `kae-crit:` zones, which `constraints.py` treats as hard obstacles, laid before signals.
- **Evidence** [C]: ground within 1 mm on the same layer or directly opposite (`cov_any`): bridge − human −1.3 points [−3.2, +0.5], within noise. Ground directly under the track (`cov_opp`): bridge −3.7 [−6.3, −1.0], staged −9.8 [−13.7, −6.1]. 2-10 % of opens involve a zone, so a skeleton buys no completion.
- **Why dead:** the gap is `cov_opp`, which the price form closes: `ground-side-ab` +8.4 points [+5.5, +11.6] (0.507 → 0.591), adopted as candidate. On the 6 of 43 boards with no ground zone the human is no reference (`cov_any` 5 %); the skeleton's value there rests on a secondary source only.
- **Reopen if:** the ground-side cost fails its completion guard on the ladder, or a measured return-path row shows a gap on plane-less boards.

## 15. More budget and seed restarts for big boards

**Did not work**; stored-data analysis.

- **Tried:** stored-data analysis (`budget_curve.py`, design-session scratch; `route-budget` plan): budget curves of 15 resumed lineages on the ten merit boards over 1,000 pads; seed diversity of route-only restarts.
- **Evidence** [C]: opens fall as CPU^b, median b = −0.27 (−0.14 to −0.65): halving opens costs about 13× CPU; 10 opens only after thousands of CPU-h on every board but gecko5. Best of 110-234 methods, 2,731 CPU-h: never 0 opens. kocer (956 of 989 unconnected) and jetson (117 unconnected, 1,615 errors) are unfinished human layouts holding 54 % of big-board opens. Seeds: the fork from 9a5512d (upstream #1022, `DsnReadOptions.REFERENCE_NAME`) creates components in reference-name order whatever the DSN's, so `translate.permute` changes only net numbers; pass 1 never reads them. First pass identical within seed parity on all 206 boards; 3 extra seeds in wave 0 cleaned 0 boards. `permute_pins=1`: −0.011 [−0.074, +0.048], undecided.
- **Why dead:** budget is a 13×-per-halving lever, and seeds never diversified route-only runs.
- **Reopen if:** an engine change steepens b (a 20 % curve shift equals 2.3× CPU at b = −0.27); seeds: a fork fix (pass-1 order from `autorouter.item_order_seed`, or `DsnReadOptions.INPUT_ORDER`).

## Sources

Stored experiments (results store): `place-satisfice`, `route-budget`, `tm-d3c`, `tm-mech30`, `tm-mech-bridge`, `tm-hybrid`, `ground-side-ab`, `j10-joint-window2`, `loop-win3`, `s2-merit213`, `control-w47`; their `PLAN.md` and `REPORT.md`. Stage 0 analyses: the seven design dossiers of 2026-11-20 (not published); committed scripts are named per item.
