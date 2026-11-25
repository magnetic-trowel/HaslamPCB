<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Dead ends 2026-10 to 2026-11: routing, bridge and Freerouting lines

Scope: routing, bridge and Freerouting lines dropped, parked or superseded from 2026-10-30 to 2026-11-21 that had no write-up on main: what was tried, evidence, why each stopped, what would reopen it, and the tag that keeps its code. Not here: the 2026-11-20..22 drops -> [dead-ends-2611](dead-ends-2611.md); the larger 2026-11-16..24 lines -> [dead-ends-2611b](dead-ends-2611b.md); every archive tag -> [archive-tags-2611](archive-tags-2611.md).
Keys: dead ends 2611c, bridge-ses-width, restore_widths, bus-alone-b1, bus-escape, escape_bus, buswall, wire_type, shove_fixed, soft wire types, diffpair-ab3, pairs first, post_pass rip, fallback ladder, no_fanout_fallback_strategies, ladder_late, stress dial, hotloop_keepout_exempt, short_neck_width, THT neck, seeds16, best-of-k, route-timesplit, repair_passes auto, escapes=soft, dog-bones, layer_directions, net_order span

**Status:** per item (first line of each section). **Code:** each item names the tag `archive/<branch>` (= branch tip at archiving, 2026-11-25) that keeps its code and branch-only write-ups; `git show archive/<branch>:<path>`. Branches predate PR #163, so paths and names inside them are the old ones (`kae/src/kae/...`, `tools/kaeres/...`, `KAE_*`); the text here uses the new names. Host-only sources (`~/haslam-baselines/experiments/<exp>/`, `/var/tmp/$USER/explore-2611/results/` on the benchmark host) are named; their key numbers are copied here. [C] = computed by our scripts, some re-read on 2026-11-25 from stored results.

## 1. Session widths given back after Freerouting (bridge-ses-width, W / W2)

**Superseded by `rule-quantize`** (PR #121, merged 2026-11-21); experiments `bridge-fixes-odd`, `bridge-fixes-mech`, `bridge-fixes-confirm`, `bridge-fixes-combo`, 2026-11-14 to 2026-11-15.

- **Tried:** Freerouting keeps half widths in whole 0.1 µm session units, so an odd class width comes back one unit wider (0.1521 → 0.1522 mm) and breaks min = max rules. `translate.restore_widths` gives the class width back on SES import (W); W2 (b866798a) also matches user-named copper layers ("Int2 (Sign)"). Tested with the second fix, L (disallowed layers written as `use_layer`), each alone against main and then combined (b135072a). Boards: 83 odd-width boards k = 2 (guard), 6-7 boards with binding rules × 5-10 attempts (mechanism).
- **Evidence:** W guard over 89 boards: opens 1.001 [0.970, 1.031], defects 1.005 [0.993, 1.019]. W2: one-unit width errors on final boards 32.6 → 0; round-0 rule not met (94.2 → 59.4) because thunderscope's 0.19079 mm rule is rounded past max by haslam itself, which W2 does not touch. Combination: errors 0.668 [0.434, 1.002], defects 0.920 [0.773, 1.024]. L adopted (PR #79; on main in `translate.py`).
- **Why dead:** `quantize.fit` (rule-quantize) fixes W's case plus the off-grid rule and annular rings; W adds nothing on top.
- **Reopen if:** never; any new width rounding goes through `quantize.fit`.
- **Code:** `archive/bridge-fixes-combined` b135072a33bbbcc5e30c0f36eb7c107d15315ee3 (W2 + L merged); `archive/bridge-fixes-ab` ecd09b9dfababa976983b16d38c655e05dc07e27 (writeup on the branch: `docs/research/routing/bridge-fixes-2611.md`, plans `tools/kaeres/experiments/bridge-fixes-ab/`). `bridge-ses-width` (origin b866798a, local e93216a3 behind it) and `bridge-ses-width-wip` (b866798a) are inside `bridge-fixes-combined`.

## 2. Bus lanes fail alone; ordered bus escapes laid before Freerouting

**Did not work** (escape); diagnosis decided; experiments `bus-alone-b1`, `bus-alone-b1-ext`, `bus-escape-order-2`, 2026-11-09 to 2026-11-11.

- **Tried:** B1: Freerouting (fork 06d2686, 900 s) routes only the lanes of buses of width ≥ 4 (DSN net filter), opens read on bus-only views, 2,854 boards. Then `--set escape_lay=plan --set wire_type=shove_fixed --set escape_bus=true` (`route.bus_escape`, `escape.plan_grid(order=)`): ball-grid lanes split into the fewest order-keeping chains (LDS), one layer per chain, ending 0.75 pitch past the package as ordered ports; arm `buswall` keeps them as walls (`wire_scope=except_bus`). 133 boards, arms control / plan / bus at 900 s and 300 s, buswall at 900 s, k = 1, fork 2e1125a.
- **Evidence:** 66 % [62, 70] of the control's open bus lanes stay open alone (49,888 lanes); fine-pitch/BGA ends 75 %, coarse ends 44 %; 77 % of lanes open alone have no copper at an end pad. Bus lanes open, bus 900 vs control 1.112 [1.041, 1.323], buswall 1.145 [1.058, 1.370], bus vs plan 1.002 [0.981, 1.028]; whole board ×1.21. Freerouting keeps about 22 % of soft escape length.
- **Why dead:** pre-laid copper does not steer Freerouting: soft copper is ripped, walls block; order changes nothing.
- **Reopen if:** escape and pin order are decided inside the router (pin-first search) or in placement.
- **Code:** `archive/bus-escape` cea194b219143bdeb762765bca633d2d67d39401 (writeups on the branch: `docs/research/routing/bus-escape-2611.md`, `tools/research/bus_escape/where_lanes_die.py`); `archive/bus-alone-b1` 9b17ab27243f7bed59b3502c964eac83ac04733c (`docs/research/routing/bus-alone-b1-2611.md`, final B1 numbers only here).

## 3. Soft (rippable) wire types for pre-routes and pairs-first

**Did not work**; experiments `bus-wire-types`, `bus-wire-types-300`, `diffpair-soft`, `diffpair-soft-300`, 2026-11-09 to 2026-11-11.

- **Tried:** KiCad's Specctra export writes unlocked copper as `(type route)`, which the fork treats as USER_FIXED (never ripped or shoved). `translate.set_wire_types` with `wire_type` = `route` / `shove_fixed` / `normal`, `wire_scope=pairs`, `escape_lay=plan`; pairs-first variants `pairs_unlocked` (soft), `pairs_own_budget` (1,080 s job), `pairs_stage=after_escapes`. bus-wire-types: 120 BGA plane boards (one per family); diffpair-soft: diffpair-ab3's 120 boards; 900 s and 300 s, k = 1, kae b5fa057.
- **Evidence** [C] (REPORT notes runs scored by mixed DRC evaluators): opens vs control, 900 s: shove_fixed +14.5 % [+6.7, +24.6] (27 better / 84 worse), normal +15.8 %, plan-route +6.4 % [+3.5, +10.5], plan-shove +16.5 %; 300 s shove +5.9 % [+2.3, +10.4]. Pairs: first +10.7 % [+5.8, +18.2], soft +7.5 % [+4.2, +12.6], own budget +8.4 %, after escapes +9.2 %; at 300 s own budget −0.0 % [−2.1, +2.5]. DRC errors within ±4 %.
- **Why dead:** making pre-routes rippable does not recover the opens; Freerouting loses the copper and the time (diffpair-fixes-2611: locked walls are most of pairs-first's cost).
- **Reopen if:** never as a wire-type switch alone.
- **Code:** `bus-wire-types` e77e55a2aa51372166c49ae3a94a93160b1cea15 (writeup `docs/research/routing/soft-wire-types-2611.md`, status "pending" there); contained in `archive/diffpair-ab4`.

## 4. Differential pairs, first build: pairs-first, post re-lay, post re-lay with rip-up (diffpair-ab3)

**Did not work** (continued as `diffpair-ab4`, parked); experiments `diffpair-ab3`, `bus-post-relay`, `bus-post-relay-300`, 2026-11-09 to 2026-11-14.

- **Tried:** `route.pair_route` (`--pairs first`: pairs laid locked before Freerouting; `--pairs post`: re-laid in place after it, kept if KiCad finds no worse); `post_pass(rip=True)` rips other nets' unlocked copper within 2 mm (`max_rip` 10, 40) and lets the last mile rejoin. ab3: 120 boards with real pairs, 900 s, k = 1, kae 486f2f1; bus-post-relay: the same boards, 900 s and 300 s, kae 575f1c8.
- **Evidence:** ab3 first: coupled_3w 0.15 → 0.74 (+0.40 [0.30, 0.51]), skew ratio 0.36, −1.47 vias/pair, but opens +15.6 % [+8.2, +28.0], errors +5.0 % [+0.1, +17.5] (`track_width` 0 → 199, `diff_pair_gap_out_of_range` 0 → 173), cp1 6 → 3; post: coupling unchanged, opens +11.1 % [+6.7, +18.1], `starved_thermal` 45 → 1,008. [C] rip-up, 900 s: post +13.3 % [+9.3, +19.7], rip10 +9.5 % [−0.5, +20.0], rip40 +13.0 %; errors +12 % in every arm.
- **Why dead:** locked pairs close corridors; the pair router breaks pair rules; the post pass took the repair rounds' time.
- **Reopen if:** see the parked follow-up `diffpair-ab4` → [dead-ends-2611b § 5](dead-ends-2611b.md#5-differential-pairs-routed-first-pair-stage-before-the-bridge).
- **Code:** `archive/diffpair-route` c6a1a6c9aa05824d13b4b08afe2fcc85d134e3ce (writeup `docs/research/routing/kae-pair-routing.md`; plan `tools/kaeres/experiments/diffpair-ab/PLAN.md`); `bus-post-relay` 5ff15a4b07dcb55c07bc057d3a970d72c8c06320 and the ab4 fix steps `diffpair-rules` c5c694b0, `diffpair-post-budget` 41ff25ec, `diffpair-fanin-soft` c2e5331e are contained in `archive/diffpair-ab4`.

## 5. Freerouting fallback ladder without fanout, in-call and late

**Did not work** (in-call); **Parked** (late); experiments `fr-ladder-ab` (2026-11-14 to 16), `fr-ladder-late` (2026-11-16, held before results).

- **Tried:** fork branch `kae-ladder-no-neck` 40c89c3 on d137fd1: with fanout off, `autorouter.no_fanout_fallback_strategies` = `no-neck,vias-cheaper,vias-dearer,continue-ripped` after a stagnating pass loop. 40 congested boards (fr-settings-ab's), production chassis, one run per arm. Late variant (kae `--set ladder_late=true`, `haslam.route.ladder`, fork 95a4154 with `autorouter.fallback_only`): in-call ladder off; one ladder call on the kept board after repair and last mile, time box 25 % of the attempt, never under 150 s, kept only if KiCad ranks it better.
- **Evidence:** fired on 20/40 boards: delivered opens 262 → 259 (−1.1 %, 9/5, p 0.42; MDE 34 %), cp1 2 → 1, `starved_thermal` 8 → 13. Seed-paired per attempt on fired boards: 1.087 [1.048, 1.130], 2 better / 14 worse (A/A 0.998); attempts where the ladder ran 1.158; repair calls 79 → 41; ladder "wins" by Freerouting's count gave KiCad 541 vs 550. Late: 40 jobs queued, held by the 2026-11-17 queue triage (old pin), no results.
- **Why dead:** the ladder spends repair time and optimises Freerouting's count, not KiCad's.
- **Reopen if:** the late ladder is rebased on the current fork pin and run on the 20 fired boards (about 55 CPU-h).
- **Code:** `archive/fr-ladder-late` 072bf78c2ef18f70811e3c7144ef867ff1026bb9 (plan `tools/kaeres/experiments/fr-ladder-late/PLAN.md`); `archive/fr-ladder-ab` ba0b0c6295c9b3f9f26c316b3b2b0bdc4e8813c3 (writeup `docs/research/routing/fr-ladder-no-fanout-2611.md`); board-level re-read: explore-2611 `results/fr-ladder-ab-boards.md` (host only).

## 6. Stress dial: rules scaled to make saturated boards informative

**Parked**; pilot `stress-dial-pilot`, 2026-11-20 (6 of 12 boards run).

- **Tried:** `tools/research/stress/stress.py derive --factor f` scales net-class `clearance` and `track_width` and the board minimums (and plain-number `.kicad_dru` clearance/width constraints); score = hardest level still clean. Ceiling from the bare input's DRC at 17 factors 1.0-4.0; human level by bisection. 12 cheap `s2-merit213` boards both methods route clean, levels 1 / middle / min(ceiling, 3); fork (`-mp 10`) and bridge (`restart.py`, 450 s counted work); main 6d72634, fork 37b1a8b.
- **Evidence:** ceiling ≥ 2.5 on 17 of 23 boards; human level exactly 1.00 on 14 of 23. On 6 boards: clean and completion monotone in f in 12/12 series; methods separate on 2 of 6 (bridge 3.0, fork 1.0); 3 of 6 stay saturated to the ceiling; bridge at or above the human level on 5 of 6, fork 3 of 6.
- **Why parked:** half the pilot ran; the human reference is weak (designers route at the rule), and saturation persists on half the boards.
- **Reopen if:** a ranking metric is needed on boards every method routes clean; first finish the 6 queued boards (2 four-layer).
- **Code:** `archive/stress-dial-pilot` bab5366ff34dd40a170fe2fd99b1f5ad6bcf99ee (writeup `docs/research/routing/stress-dial-2611.md`).

## 7. Net-exempt hot-loop keep-outs

**Did not work**; pilots 2026-11-16 (host bench reports, no kaeres experiment).

- **Tried:** fork c226cce (base d137fd1) lets a keep-out exempt nets; `hotloop_keepout_exempt` (`HASLAM_HOTLOOP_KEEPOUT=1`, `HASLAM_HOTLOOP_KEEPOUT_EXEMPT=hard|soft`, soft cost 4): hot-loop reference keep-outs no longer block the loop's own nets (a15c2e23: loop nets only). Pilot: 8 converter boards, one 600 s route per arm. Re-pilot: hotloop-ab's N recipe (restart portfolio, 900 s × √(fp/40)), seeds 0, 1; evaluator `--scope losses --drc`.
- **Evidence:** pilot opens N0 1,051 vs H 1,459, S 1,442; `starved_thermal` 12 → 49; H/N per cell L 1.03, R 1.15. Re-pilot (interim, some evaluations missing): opens N0 379, H 528, S 412; errors 72 / 74 / 78; per cell H/N0 L 1.237, R 1.24, loop_ac 1.278; S/N0 L 1.036, R 1.243.
- **Why dead:** exemption costs opens and makes the loops no smaller.
- **Reopen if:** a hot-loop stage shows loops blocked by their own keep-out (cell open only in the keep-out arm).
- **Code:** `archive/hotloop-exempt` 422692f7a6a86733573adb8a4ab6fc502fb56747 (local only; reports `bench/results/2026-11-16-hotloop-exempt-pilot-c226cce.md`, `-repilot-a15c2e23.md`, scripts `tools/research/routing/hotloop_exempt_*.{sh,py}`).

## 8. THT necks sized by short-conductor heating, land caps, grown-loss budget

**Did not work**; fork of `confirm-default-ab`, 2026-11-14.

- **Tried:** after confirm-default-ab failed its THT-overhang gate (A 1.4 mm² vs N 559 mm², 13 of 20 boards higher): `short_neck_width` (ΔT = I²ρL²/(8k w² t²), 10 K at 3× I), loaded pads capped at their land width (d97ff7ab), loss budget as a share of the grown copper's loss (68ffae4e), one DC solve over all rails (12dbbec2, reverted). Finish re-run on A's kept boards of the 20 physics boards: f0 (N's code 4392518) vs f1 (each change), deterministic evaluator `compiled-9867d0b`.
- **Evidence:** THT overhang f1 = f0 = 520.5 mm² for short necks and the grown-loss budget; land caps 349.4 (−33 %) with cm4 loss +4.9 %, drop +10.6 %; joint solve cm4 +13 %. Final f1 vs f0: loss median 1.000, servo +3.2 %, magtag +2.0 %; DRC same except cm4 `solder_mask_bridge` 30 → 24.
- **Why dead:** the remaining overhang is rail copper carrying current (`tht_pad_kept_wide`, 69 entries); removing it costs loss the routed-copper DC model does not see.
- **Reopen if:** necks are priced with the evaluator on the grown board (with/without each neck set).
- **Code:** `archive/power-copper-tht` 63ad94c90ee060c2fc5b1b4580af906eca9ddcd9 (report `bench/results/2026-11-14-tht-short-neck-confirm-fork.md`, summary `tools/research/routing/pc_tht_confirm.py`).

## 9. More seeds of the default recipe on hard boards (seeds16)

**Undecided (dropped)**; experiment `seeds16`, 2026-11-17 to 2026-11-18.

- **Tried:** best-of-k over 16 independent seeds (`--seed {attempt}`) of `merit-restart.sh`'s default (completion-first phase 1, `--alt` M-clock or `--open-alt` windows), kae 2199c12, fork d137fd1, harness 269c292 (`restart.py` keeps each phase's attempt log). Boards nf-dj-netforce-tpu, folknology-mystorm, kicad-demos-stickhub.
- **Evidence:** 25 finished runs: best-of-k diminishing (mystorm 99 → 82 at 9 seeds, stickhub 30 → 26 at 11); no board clean; gain mostly from phase 1. 15 runs ran away (pinned code charged no optimizer or pour-fill work); mystorm seed 10 hit kaeq's 24 h limit. Cancelled by the user 2026-11-18.
- **Why dropped:** compute needed elsewhere; the trend already says seeds alone do not clean these boards.
- **Reopen if:** a best-of-k curve is needed on the current pin (counted work charges the optimizer).
- **Code:** `archive/restart-curve-log` 95598c4b5414ed3ea71ed178e6d28edd49f21b00 (plan `tools/kaeres/experiments/seeds16/PLAN.md`).

## 10. Last mile takes the time once router rounds stop paying (full time split)

**Superseded by** the lite split (`route-timesplit-lite`, merged in `rules-merge2`); branch `route-timesplit`, 2026-10-30.

- **Tried:** `haslam.route` run options (bridge.DEFAULT_OPTS / `--set`): `repair_open_rounds="auto"` (one repair round when only open connections are left, then the last mile); `last_mile_max_open=None` (no bound on open connections taken); `last_mile_rounds="auto"` (rip-up rounds until FAILS in a row are not better); `repair_passes="auto"` (Freerouting pass cap 2 per repair round, doubled while still gaining); round overhead (export, import, fills, DRC) reserved from the router budget; last-mile joins stop in time for the measured DRC; the nested reroute's final DRC reused. `haslam.route.cli`, same seed and budget.
- **Evidence** [C] (commit message 07c6038): Freerouting passes after the first rarely gain (297 rounds on 11 boards: fewest unrouted at pass 1 in 231, by pass 4 in 270; 2/3 of router time after it). heypcb kestrel 1,000 s, seeds 1-3: 28/25/15 → 14/6/0 open; usbarmory 1,060 s 136 → 119; bastardkb dilemma 1,245 s 73 → 63; transistorfet 568 s 105/105 → 59/105; kata0510 10/11/12 → 11/12/9; six small boards unchanged; errors beyond the input unchanged (transistorfet 0/9 → 1/7). Restart wrapper, merit budget, seed 0: heypcb 10 → 1, kata0510 6 → 6, zephray 128 → 125.
- **Why dead:** the lite variant (first two options only) gave the same heypcb gain (28/25/15 → 14/6/0) and was merged; `repair_passes="auto"` and the overhead accounting were never measured alone and are not on main.
- **Reopen if:** Freerouting's later passes cost a large share of route time again (profile the pass at which unrouted is lowest).
- **Code:** `archive/route-timesplit` e60c32e104d9ccb321f3ec424f858dbb9b4572f6 (no writeup; the evidence is the message of 07c60385f).

## 11. Escape pre-pass: dog-bones for grid packages before Freerouting

**Superseded by** the 134-line ball-grid dog-bones laid with the plane escapes (`rules-bga`, in `rules-merge3`); branch `rules-escape`, 2026-10-30.

- **Tried:** `--set escapes=soft` (`haslam/route/escape.py`, 411 lines): a pre-pass lays dog-bones and zero-slack row stubs for BGA / WLCSP / pitch ≤ 0.65 mm packages before Freerouting; two checks of the escapes (a spoke margin; KiCad's DRC). `haslam.route.cli` single attempt, `--set passes=8`, 1,800 s, seeds 1-3, Freerouting on private slots. Study scripts (dump, opens, compare, slack, sites, corridor, walls, runopens).
- **Evidence** [C] (opens per seed, base → spoke-margin → DRC-checked): gecko5education (6 L, BGA-381) 123/99/94 → 66/71/81 → 79/70/80, 0 errors; nekoink (4 L, BGA-289) 119/105/114 → 100/94/97 → 115/99/97, errors 11 → 11-14 → 11. Opens at ring ≥ 2 balls: gecko5 38/34/35 → 0/0/3, nekoink 37/26/41 → 15/15/12. sdi-mipi (8 L, 3 BGAs, seed 1) 202 → 179, ring ≥ 2 107 → 58. 2,400 s seed 1: gecko5 129 → 83, nekoink 124 → 98. Row stubs alone (kata0510, edison, 2 seeds): no change (opens move to the stub's far end).
- **Why dead:** the simpler dog-bones in `rules-bga` keep most of the gain (gecko5 101 → 69, nekoink 99 → 77 mean open; [closing-open-connections § What worked](routing/haslam-closing-open-connections.md#what-worked)).
- **Reopen if:** a board class where fixed dog-bones leave ring ≥ 2 balls open that the DRC-checked pre-pass closes.
- **Code:** `archive/rules-escape` 08cee9405a61384496d671716b92193a5919f93c (writeup on the branch: `tools/research/escape/README.md`).

## 12. Freerouting layer directions and widest-span-first net order

**Undecided (dropped)**; branch `rules-congestion`, 2026-10-30. No A/B result found in git, docs or the host's experiment folders.

- **Tried:** `layer_directions` (`flip` | `aspect` | explicit `F.Cu=v,B.Cu=h`): preferred directions written into the Freerouting rules file; `net_order=span`: nets with the widest pad span first in the DSN network (Freerouting's order from its second pass on). Both off by default. The same commit's `last_mile_txn` (transactional last-mile rip-up) was merged in `rules-merge2`.
- **Evidence** [C]: only the motivation: Freerouting picks directions by the board's aspect ratio, which matches the human layout's split on 48 % of 73 two-layer boards with a clear split.
- **Why dead:** never measured; the congestion work moved to the last mile and restarts.
- **Reopen if:** two-layer boards whose open connections cluster on the layer the human routes the other way.
- **Code:** `archive/rules-congestion` f5a75c590afa9c163b9806d7a09d28c9eda15210 (prototype: 880a4d886, `haslam/route/translate.py`, `lastmile.py` in old paths `kae/src/kae/route/`).
