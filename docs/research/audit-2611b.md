<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Gap audit (2026-11-20): conclusions and corrected beliefs

Scope: the 2026-11-20 gap audit: conclusions, beliefs the stored data corrects, one-way stage boundaries, what stays unverified. Not here: the code-bug audit -> [audit-2611](audit-2611.md); host-load drift -> [benchmark-drift-2611](benchmark-drift-2611.md).
Keys: gap audit, audit-2611b, s2-merit213, corrected beliefs, near-miss metric, pooled A/B null, stage coupling, one-way boundaries, prices and bounds, winnable ceiling, undecided

**Status:** findings only; nothing run, no code changed. **Date:** 2026-11-20. **Repo state read:** main c2dd008a. **Data:** stored experiment `s2-merit213` (213 merit boards), the kaeres index. **Method:** thirteen read-only agent reports (routing to state of the art), merged into one synthesis; the reports are not published.

Evidence marks (the audit's own; here [V] is not the docs' vendor tag): **[V]** re-checked in code or stored data; **[2+]** computed independently by two or more agents; **[A]** one agent's claim, not re-checked.

## Six conclusions

1. **The yardstick no longer sees most of what is tested.** 168 of 213 merit boards are 2-layer; 48 have a clean human layout [V]. The bridge leaves zero opens on 164 boards; the 10 boards over 1,000 pads hold 82 % of all opens and no method finishes any of them [V]. cp1 is a near-miss metric (21-22 boards sit 1-5 opens from clean [V]); summed opens is a ten-board metric. Report them separately.
2. **Three weeks of single-knob A/Bs are collectively a null.** 41 arms pooled: −0.7 % opens [−1.5, +0.1], no heterogeneity; the median arm could detect only 10.9 % [A]. Each knob is worth about a percent. Single nulls at this power are **undecided**, not "did not work" ([status legend](README.md#status-legend)).
3. **The stage-coupling thesis is not refuted; the instrument for it is broken.** With the same router, the human placement leaves fewer opens than kae's on 47 boards and more on 10 (1,179 vs 1,434 on 205 common boards) [V]. The only path back (re-place, rip about 10 nets, fresh Freerouting, full-board DRC per try) kept 126 of 4,036 windows (3.1 %) [2+]: about two useful placement revisions per CPU-hour.
4. **Stages hand each other copper or nothing.** Freerouting accepts no plan: pre-laid copper is a wall or gets ripped. The "did not work" verdicts on escape plans, bus order, pairs-first, critical copper and window repair tested that handoff, not the idea [2+]. General fix: pass **prices and bounds, not copper**.
5. **Physics does not yet do what the project says.** It steers the placer on class priors, does not steer the main router, never chooses the delivered board, and its score is 53-57 % a constant floor [A; rank and restart code V]. kae's placement shows no physics gain over the human one (routed hot-loop median 4.6 vs 2.9 nH) [A]. No model has met a measurement.
6. **Effort is allocated by constants.** In a run every share is a constant (`place_share`, `router_share`, reserve, growth, resume); resumed attempts remove 24 opens per CPU-hour, fresh ones 6.5; the 10 biggest boards take 34-48 % of CPU and none becomes clean [A]. In research, 15 experiment families were re-registered 2-7 times and no migrated A/B has a verdict [A].

## Corrected beliefs

| Belief | What the data says | Doc fixed |
|---|---|---|
| "88 % of opens on pour boards are pours cut by routing" | The Freerouting fork alone on 30 selected boards. In kae's delivered boards 2-10 % of opens involve a zone [2+]; in `s2-merit213` bridge output 156 of 2,205 open items (7 %) name a zone [A]. Pours matter for return paths, not completion. | [pour truth](routing/freerouting-pour-truth.md), [routing README](routing/README.md) |
| "59-64 % of opens join two large parts" | A connectivity regex that overcounts 1.4-1.7×; big parts at human poses on gecko5 barely helped [A]. Unknown. | — |
| "kae staged is the best method (.296 vs .272)" | +12/−7 boards [V], lower completion, 8 no-output boards [V], about twice the nominal budget, windows-phase CPU not recorded [A]. Its lead comes from re-placing away errors in the human placement. | [kae-staged](joint/kae-staged.md) |
| "113 winnable boards" | 23-28 carry inherited errors no method removes; the ceiling is about 85-90 [2+]. | — |
| "10× budget closes nothing" | A small-board result (33 A+B boards). On big boards opens fall along every resumed run (nekoink 193 → 156 → 132 → 115 → 102; sdi-mipi 249 → 145); fresh starts at that budget stall [A]. | [routing README](routing/README.md), [dead ends § 1](routing/kae-routing-dead-ends.md#1-longer-budgets-did-not-work) |
| "Seeds are the lever" | Route-only: extra seeds cleaned 0 boards. On three big boards seeds 0/2 and 1/3 give identical results [V]: the seed permutation does not act there: the Freerouting fork creates components in reference-name order whatever the DSN's ([dead ends 2611 § 15](dead-ends-2611.md#15-more-budget-and-seed-restarts-for-big-boards)). | [restart portfolio](routing/kae-restart-portfolio.md) |
| "Placement and routing are not separable (2× copper)" | One seed, boards ≤ 200 pads, lab engine; says nothing about iteration vs restarts [A]. | — |
| "Split C clean 30/78 (kae) vs 43/78 (human)" | From 2026-10-24 with connectors free. `s2-merit213` attempt 0, staged vs bridge on the human placement: clean 63 vs 58 (all), 38 vs 43 (48 human-clean boards), 21 vs 24 (split C, 120); opens 1,434 vs 1,179 [V]. | [placement README](placement/README.md), [research README](README.md) |
| "The manufacturability axis exists" | All `mfg_*` columns are empty in all 2,011 rows [V]. | — |
| "Physics vs human" in the newest baseline | Every cell is blank; the 94 human rows are from two older evaluators [V]. | — |
| IPC-2221 "conservative against IPC-2152" | A code comment (`excite/dc.py`) [V]; the project's own table shows the opposite above about 1 A [A] ([high-current](../topics/rules/power/high-current.md)). The heating unit test only inverts the same formula [V]. | not repeated in docs |
| "Holding the human poses of big parts makes routing worse" (`pose-transplant`, 2026-11-22: K − B −0.42 [−0.74, −0.10] log1p opens, g_B −0.71) | Invalid run: held parts stayed at the task input's off-board parking poses, so 66 of 70 (big tier) and 70 of 70 (mid tier) runs were illegal; edge-clearance errors 651 → 1,580. It decides nothing. Re-run as `pose-transplant-2` (branch `pose-transplant-fix` c50478c2) with the human poses held, queued 2026-11-23 [V]. | not repeated in docs |
| Underpowered nulls filed as "did not work" | Crossing term, routing history, barrier weight, Freerouting settings, restart screen (joint): estimates within noise. | now **undecided** |

External statements corrected the same day, each in place with its source: Cadence, Zuken ([incumbents](../topics/landscape/commercial-incumbents-and-startups.md)), Freerouting on zoned fixtures and "wait for 2.6.0" ([freerouting](../topics/routing/freerouting.md#nightly-benchmark)), PCBWorld as the only comparison ([measured comparisons](../topics/landscape/measured-tool-comparisons.md)), DeepPCB rank ([ML routing](../topics/routing/ml-rl-routing.md)), D3-C ([pcbworld](../topics/routing/pcbworld.md#datasets)), KiCad 11 SWIG ([ecosystem](../digests/ecosystem.md)).

## One-way stage boundaries

Why the implemented coupling does not pay: hard keep rule (38 % of windows die as illegal placements, 28 % end with more opens [2+]); windows pick parts near an open's ends while 81 % of diagnosed opens are blocked by kae's own copper [2+]; at most 6 small parts move; 90 % of the opens it was judged on sit on boards open under the human placement too [V]; opens vary 4× more across placement seeds than across routing order [A].

| Boundary | Frozen decision | Evidence it binds |
|---|---|---|
| Placement → routing | every pose; side; pin assignment | 47 vs 10 boards [V]; kae's placement 3× more crowded around pads [A] |
| Physics term → placer | margin rewarded below budget, no "satisfied" state | crowding; physics-weighted arm +10.6 % opens [A] |
| Plan → Freerouting | escape plan computed then discarded; pairs, buses, layers | laid plans became walls [2+] |
| Module copper → router | locked critical copper | 45 "fixed copper" opens on 13 boards; completion .958 vs .969 [A] |
| First route → repair → last mile | no way back; absolute 135 s reserve | repair skipped in 175 of 264 attempts with a median 48 % of budget unused [A; code V] |
| Clean board → physics phase | `--alt` re-places from the input | 118 boards; never measured [A] |
| Attempt → attempt | open lists, causes, losing boards dropped | restarts fail on different nets but the same number [A] |
| Clean → delivered | first clean attempt wins | physics never selects [V] |
| Netlist → layout | pin assignment tuned to the human placement | bus lanes inverted 21.6 % where an end is swappable vs 29.7 % where not [A] |
| Validation → constants | no discrepancy ever changes a number | AN-139 trend off by up to 1.9×, filed as "fixture unknown" [A] |

Coupling the evidence supports: soft state with thousands of graded moves per CPU-hour; feedback attached to parts and nets, not board coordinates (parts move a median 11 % of the diagonal between attempts [A]); prices and bounds between stages; separate stages only where the later cannot invalidate the earlier (brief and rules, shape and finish, the judge).

## Unverified, and where the reports disagree

- Staged CPU: 220.9 h recorded [V]; one report estimates about 369 h including unrecorded phases.
- Winnable ceiling: 85 or 90 boards, by report.
- `side-front-ab`: one reading is 232 boards, +4.9 % opens, interval includes 0; two others read 53-58 of 300 boards. No verdict is written anywhere.
- Placement-term family: pooled −0.7 % and a rough combined p of 0.03 both fit a real but tiny effect.
