<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# loop-win: windows chosen from evidence, against restarts at the same counted allowance (pre-registered)

Written 2026-11-14, before any run of this experiment.

## Why
`loop-compute-matched` (branch `loop-exp`) found that at the same allowance staged restarts beat the joint loop's windows: 4,485 vs 5,655 opens on 69 boards, 46 boards worse and 13 better, p 0.0001. The window bench and the replays say why:
- 41-53 % of windows repeat a part set already tried;
- about a third end "illegal after repair";
- windows target a connection's two ends, not what blocks it.

Three changes target these, each behind its own flag on branch `loop-win-combo` (merge of `loop-win-evidence`, `loop-win-tabu`, `loop-win-exact` and `loop-win-frcharge`, on `loop-win-base`):
- **evidence** (`window_evidence=1`): each incumbent's open connections are diagnosed by `kae.route.blocked` (nets in window order, within 30 s and 5 % of the budget; the set-up is charged as one DRC). A connection no move frees opens no window (a rule's binding gap against its own footprint, a pad walled in by its own footprint), and neither do J3's DRC types. Congestion adds its free corridor and the movable parts beside it. A rule gap or wall against other parts' pads adds those parts.
- **tabu** (`tabu=1`): a failed part set is not tried again until a window kept after the failure shares a part with it or lies within the loop margin. The next, larger attempt is tried instead.
- **exact** (`legal_exact=1`): a window still grid-illegal after greedy goes to the exact closed loop, and stands if the exact check is clean. Every arm reports `home_grid_illegal`, which says how often the incumbent itself is grid-illegal.

Also in every arm (no flag):
- **Window router budget under counted work** (`loop-win-frcharge`). The window router's budget grows and shrinks on charged work, not wall seconds; before, it moved with host load.
- **Freerouting charging.** Start-up and optimizer charging belong to branch `fr-budget-calibration`, which is not merged and is not used here. Both arms share main's charging, and measured CPU is reported against a guard (below).

## Arms (`setup.sh`, one commit, harness = kae = that commit, Freerouting fork d137fd1, `KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`)
Allowance A = 3.15 × 900 s × sqrt(fp/40) of nominal work. The harness timeout is the 4 × A wall ceiling (cap 57,600 s).
- **R:** staged (`--max-iters 0 --no-modules`) under `restart.py --parallel 1` for A, with polish-merit's wrapper flags. This is the comparison windows lost.
- **W0 (ctl):** `kae.joint.cli run --time B --no-modules --set window_budget_factor=2`, with B = A / 3.15: iteration 0 on its natural shares of B, then two more budgets for windows. This is `loop-compute-matched`'s W without the module stage. R has no module stage either, and the module stage alone costs opens (chassis-soft: +57 %), so leaving it on would confound windows with modules.
- **We, Wt, Wx:** W0 plus one flag each (evidence, tabu, exact).
- **Wall:** W0 plus all three flags.

All six arms of a board and seed run side by side in one kaeq job (timed class). The step cache (`KAE_STEP_CACHE`, result-neutral) lets the W arms share iteration 0.

## Boards and seeds
- **Batch 1:** `boards.txt`, `loop-compute-matched`'s 69 boards. These are boards where the joint loop leaves connections open, one per repo family. Prior W left 82 opens per board, and the A/A between R runs has a per-board d sd of 0.150.
- **Seeds:** all six arms on seed 0 (`loop-win`). R, W0 and Wall also run on seed 1 (`loop-win-k2`, the same methods, attempt 1).
- **Extension:** `boards-extension.txt`, the 157 route_demand hard/extreme corpus boards from `loop-compute-matched`, one per new repo family, in its sha256 order. Batches of 60 (the last 37), with R, W0 and Wall at seeds 0 and 1, while the primary is undecided.

## Primary: Wall against R (opens)
- Per board and seed, `d = (o_W − o_R) / (o_W + o_R + 1)`. A board's d is the mean over its seeds. Sign-flip test over boards.
- **Wall wins** if mean d < 0, p < α, and total opens are at least 3 % lower. **R wins** on the mirror condition.
- Looks come after batch 1 and after each extension batch: at most 4 looks, α = 0.0125 each (Bonferroni over the 4).
- Anything else is undecided and starts the next batch. When the pool is used up, the verdict is reported as undecided.
- **Guards for a Wall win:**
  - DRC errors and placement errors not above R's by more than 5 %. The A/A spread of DRC errors is 3.4 %.
  - cp1 not lower by more than 2 boards.
  - Measured CPU at most 1.10 × R's. Over that, the result is a win at more real compute. It is not adopted until it is rerun with `fr-budget-calibration`'s charging.

## Per change: We, Wt, Wx and Wall against W0 (batch 1, seed 0; Wall also seed 1)
- **Acts** (descriptive, read from the loop reports):
  - We: a diagnosis on at least half of the boards that have windows, and blamed parts on at least 20 % of its windows.
  - Wt: the share of windows on a part set the board already tried is under 10 % (W0: about 40 %).
  - Wx: the share of windows ending "illegal after repair" is at most half of W0's.
- **Window yield** (decides): opens removed by the window phase. That is iteration-0 opens minus the opens of the last kept window, before the finishing stage. Paired per board, sign-flip test. The change pays if its yield is higher, p < 0.05, with these guards:
  - final opens not more than 5 % worse in total;
  - DRC errors not more than 5 % worse in total;
  - window-phase work (nominal) not more than W0's by more than 10 %.
- **Verdicts:** "pays" (acts, higher yield, guards hold); "acts, no gain" (acts, yield not decided); "does not act".
- Final opens, cp1 and the paired d against W0 are reported too.

## Also reported, per arm
- cp1 and cpk;
- completion, open connections, and DRC errors per type;
- CPU (measured and charged), `ceiling_hit`, time-outs;
- windows, kept, repeats, illegal, `home_grid_illegal`, tabu skips, evidence counts by cause;
- results by tag (route_demand, pad_density);
- physics on boards every compared arm routes fully, judged against the J21 floor only at n ≥ 38.

## Smoke and profile (before batch 1)
- **Smoke (`loop-win-smoke`):** `boards-smoke.txt`, two boards of batch 1 that stay in it: lenaschimmel bestelampe (small) and solderedelectronics dasduino coreplus (medium). All six arms, seed 0. Plumbing only: the arms and rules do not change after it unless it shows a plumbing fault, which is recorded here as an addendum.
- **Profile:** one board per arm (the small board for the W arms and R). py-spy on the python process, `--idle`, summed by `prof_stages.py`.

## Costs (information only)
- From `loop-compute-matched`: about 1.3-1.45 measured CPU-h per board and arm.
- Batch 1 is 69 × (6 + 3) runs, about 900 CPU-h with judging and physics.
- An extension batch is 60 × 6 runs, about 500 CPU-h.

## Addendum before any run (2026-11-14): wall ceiling
A direct plumbing check (Wall's flags, 41-part board, `--time 150`) ran end to end, and the evidence kept a window with a blamed part. It also showed a fault: the W arms' work-mode wall ceiling was 4 × `--time` (4 B). Their windows run to about 3.15 B of nominal work, so the slack was 1.3 ×, against 4 × for R. On that board, Freerouting's first route ran 176 s of wall time for about 40 s charged, and the run hit the ceiling.

The fix: `window_budget_factor` now raises the ceiling to 4 × the extended budget (`loop-win-base`). The methods move to the commit with this fix. The smoke and profile jobs queued at 48ffd89 were cancelled before they ran. Arms and rules are unchanged.

## Addendum after the smoke (2026-11-14, before batch 1)
Smoke `loop-win-smoke2` at ed3f815: 9 of 12 runs scored. The medium board's R, Wt and Wall were still queued or running; one job was requeued three times for memory. Plumbing works: KiCad scored every finished run, there was no `ceiling_hit`, and iteration 0 is identical across the W arms (same seed, counted work).

| board | arm | opens | windows | kept | repeats | illegal (of them, incumbent grid-illegal) | CPU h |
|---|---|---|---|---|---|---|---|
| bestelampe (41 parts) | R | 6 | - | - | - | - | 1.58 |
| | W0 | 3 | 26 | 1 | 16 | 8 (8) | 1.94 |
| | We | 3 | 33 | 1 | 14 | 10 (10) | 1.99 |
| | Wt | 3 | 6 | 0 | 0 | 2 (2) | 1.42 |
| | Wx | 3 | 12 | 0 | 6 | 4 (4) | 1.80 |
| | Wall | 3 | 9 | 1 | 0 | 3 (3) | 1.85 |
| dasduino coreplus | W0 | 20 | 54 | 0 | 12 | 1 (0) | 3.61 |
| | We | 20 | 49 | 0 | 17 | 1 (0) | 3.64 |
| | Wx | 21 | 53 | 0 | 11 | 0 (exact-legal 1) | 3.75 |

What the smoke shows:
- **The flags act.**
  - Tabu cuts repeats to 0 and windows by about 4×.
  - The evidence diagnosed every open connection, all as congestion, and blamed parts on 26 of 33 and 34 of 49 windows. It dropped none.
- **Every illegal window held a grid-illegal incumbent.** The exact model rejected those windows too. Part A1 overlaps fixed J6 and J7 in the input, and the placer's anchoring found no spot for it.
  - Fix (`loop-win-exact` c2dae6f, combo aee3f5e): with `legal_exact`, findings the incumbent already had between the same parts no longer count.
  - This changes the Wx and Wall arms before any batch-1 data.
- **Window time is undercharged against R.** At the same nominal allowance, W0 used 1.94 measured CPU-h on the small board against R's 1.58 (+23 %). Wall time per charged second was 2.85× for W0 and 1.87× for R.
  - The coordinator holds batch 1 until `fr-budget-calibration` is merged (2026-11-14). The methods are then re-registered on main plus these branches, and both seeds run with the CPU guard as written.
- **The joint loop's wall ceiling.** When the ceiling was hit, the window deadline became NaN, and a profiled run went on to 58 windows. Fixed in `loop-win-base` ea7a63c; it changes nothing below the ceiling.

## Addendum (2026-11-17, before any batch-1 run): the arms do not judge boards the same way
On bestelampe in `loop-win-smoke6`, W0's finishing stage reached 5 opens with 14 DRC errors, and the loop reverted it to 7 opens with 4 errors. R kept 3 opens with 25 errors. The two arms decide which board to keep by different rules:
- **R:** `restart.py` judges every attempt and its final last-mile pass with the harness order: illegal, then not clean, then open connections, then new DRC errors. Fewer opens win whatever they cost in DRC errors.
  - Main's default kae method (completion-first, PR #77) uses this judge for its delivered board.
- **W0 and the other W arms:** there is no restart wrapper, so the delivered board is the joint loop's own incumbent. `joint.scorecard.accept` keeps a window, a finishing try or the last mile only if neither placement errors, nor opens, nor DRC errors get worse.

The A/B therefore measures the acceptance rule as well as the windows. The fix is not yet chosen:
- Wrapping the W arms in `restart.py` would give both arms the same judge for the delivered board. It would not change this case, because the 5-open board is rejected inside the loop.
- Matching would need the loop to accept by the harness order too. That trades DRC errors for opens, which is a design question for the user.

Batch 1 waits for that decision.

## Addendum (2026-11-17, before any batch-1 run): one ranked judge in both arms
User decision: the joint loop keeps or reverts each step (windows, finishing tries, the last mile) by the ranked judge the delivered results use. That is `kae.rank.board_rank`, which `restart.py` also uses: legal, clean, open connections, new DRC errors. Routed physics decides only on an equal rank.
- Branch `joint-ranked-accept` (a PR) carries the change; loop-win merges it.
- R and every W arm now judge boards by the same rule, so the A/B measures the windows and not the rule.
- The loop's `phys_slack` option is gone.
- Runs of the loop-win smokes up to smoke7 used the old rule and are not compared with runs made after it.
- The smoke is rerun (`loop-win-smoke8`) on fork f1c41d3 with KAE_BUDGET_PROFILE=1 and KAE_BUDGET_GAP=10.
- Batch 1 (seed 0, then seed 1) goes in only if, on both boards:
  - W0 finishes inside its wall ceiling;
  - W0's measured CPU is in line with R's.

## Addendum (2026-11-17, before any batch-1 run): compute is matched by counted allowance only
User decision: every arm gets the same counted-work allowance, as everywhere else. In the last smoke R stopped well inside its allowance; that is R's own behaviour.
- Measured CPU per arm is reported as a cost, next to opens and DRC errors. It is not a gate, and the "CPU at most 1.10 x R's" guard on a Wall win is withdrawn.
- Smoke8, on fork f1c41d3 with the ranked judge: no run hit its wall ceiling. R / W0 / Wall:

| board | measured CPU (s) | opens | DRC errors |
|---|---|---|---|
| bestelampe | 4,169 / 5,405 / 4,479 | 4 / 2 / 0 | 26 / 25 / 22 |
| dasduino coreplus | 6,916 / 10,979 / 10,739 | 4 / 8 / 11 | 34 / 35 / 35 |

- Main 8a2c748f (#83, physics.build prices a negative rail by its magnitude) reaches the placer's physics terms. It is merged, and batch 1 runs at the commit that includes it.
- Seeds: all six arms run seeds 0 and 1 in one experiment (`loop-win`, attempts 2). A second experiment for seed 1 alone would queue seed 0 again, so the per-change arms get their second seed as well. The primary and every rule above are unchanged.

## Addendum (2026-11-18): big boards held, not dropped
Job #108409 hit kaeq's 24 h job timeout. It ran polarfire SoM (473 footprints), seed 0, arms R, Wall and exact, on 8.1 h of nominal allowance. Its scratch went with the timeout, so the arm and stage that overran are unknown. On another board (alphaonex86, under route.cli), Freerouting was charged 8,588 s of work against a 900 s budget: max_work did not stop it.
- **Held:** the 29 queued jobs on boards with more than 390 footprints were cancelled. Their job lines, with #108409's, are in `held-big-boards.jsonl` (30 lines; 6 boards: polarfire SoM, sdi-mipi, arvsom, jetson J2032, zotino, dvhx). The boards are polarfire SoM 473, sdi-mipi 396, arvsom 452, jetson J2032 833, zotino 722 and dvhx 464 footprints.
- **Why:** at 3x wall per charged second, a three-arm job on these boards passes 24 h.
- **When they come back:** once max_work reliably stops Freerouting on big boards. They are resubmitted from that file (`kaeq submit --jobs`, owner exp-loop-win), with the same methods and harness unless the fix changes kae, in which case every arm reruns at the fixed commit.
- The other 63 boards run as planned. The primary is read on the boards every arm finished, and the held boards are added when they run.

## Addendum (2026-11-19, before any result is read): migrated to main 4c9e5293 (#112)
#112 changes the last mile, which every arm runs:
- `lastmile.close` no longer queues a net again after a turn that made no progress;
- `repair._last_mile` rounds start with the nets no earlier round reached;
- `parts()` is charged as work.

Where the arms reach it:
- R: its final pass, `kae.route.cli lastmile`.
- The W arms: the bridge's and finishing stage's last mile, the windows' last mile, and the kept board's last mile.

Of `loop-win`'s first finished board (librewave, all 12 runs), 4 of 10 joint runs logged a net kept two or three times with no change in its open count. The changed paths are therefore common, not confined to a few boards.

What changes:
- `loop-win` moves to a new commit (main 4c9e5293 merged into `loop-win-v6`) and a new experiment, `loop-win2`, with the same 69 boards, both seeds, six arms and rules.
- `loop-win`'s queued jobs are cancelled. Its finished runs are not read.
- The held big-board jobs are rewritten for `loop-win2` in `held-big-boards.jsonl`; the reasons in the 2026-11-18 addendum stand.
