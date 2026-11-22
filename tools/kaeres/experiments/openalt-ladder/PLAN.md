<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# openalt-ladder: does the default's windows half earn its budget at the default's own budget? (pre-registered, ladder tier)

Written 2026-11-22, before any run. Follows `openalt-ab` (branch `rwx-after-restarts`, results/openalt-ab.md).
- **What openalt-ab found:** at sprint size (one lane, one staged allowance), D ≈ Dbridge (1.008 [0.947, 1.059]) and Dwx ≈ D. But the windows barely ran: about 4 per run.
- **The question here:** the same, at the default's real budget.
- **Tier:** the user approved this ladder-tier run (2026-11-22), so runs may exceed RULES.md's 0.5 CPU-h sprint cap. The 16 CPU-h per board cutoff applies.

## Code and setup (no migration during the run)
- **Code:**
  - main 1cdbf617, which includes #133 (time accounting; the kaeq daemon exports KAE_DEADLINE) and the ranked judge;
  - plus the two `legal_exact` commits (cherry-picked as before);
  - on branch `openalt-ladder`.
- **Freerouting:** fork 37b1a8b (the current pin), set explicitly. Counted work.

## Arms (`setup.sh`): main's default recipe as `merit-restart.sh` defines it
- **Budget:** `--parallel 4`, with `--time` of two staged allowances: {timeout} × 9/40, where timeout = 8,000 s × sqrt(fp/40).
- **Policy:** completion-first with the module stage as `--alt`.
- **D:** `--open-alt` = the joint loop on phase 1's board (`kae.joint.cli run --start @BEST@ --no-modules`).
- **Dbridge:** `--open-alt` = `kae.route.cli route @BEST@`, a resumed bridge pass for the same half (counted work × 4 lanes).
- **Dwx:** D with `--set legal_exact=1`.

## Boards (`boards.txt`, 51) and seeds 0 and 1
Under the 16 CPU-h per board cutoff (6 runs; per-run cost estimated from loop-win3's and pk3-ab-m6's measured CPU, scaled to this budget):
- **20 loop-win3 boards where the windows acted** (W0's windows removed at least one open on some seed).
- **20 window-profile boards from pk3-ab-m6:** two layers, route_demand hard or moderate, pad_density dense or very_dense, 5–25 opens under Rresume.
- **11 near-miss guard boards** (`boards-near-miss.txt`): pk3's two-layer boards at 1–5 opens and loop-win3's.

## Size from power
- **Spread:** openalt-ab's per-board spread of log(Dbridge / D) is SD 0.127 (two seeds averaged).
- **Effect worth detecting:** 5 % opens in either direction, the size that would justify keeping or replacing the windows half.
- **MDE:** with 80 % power at α 0.05, 51 boards give an MDE of about 5.2 %. With loop-win3's Wx vs W0 spread (SD 0.088) it would be about 3.5 %.
- **Cost (information):** about 555 CPU-h (4 lanes per job). Priority 5.

## Outcomes (as openalt-ab)
Per arm against D, paired by board and seed, on board-seeds where D's phase 1 leaves the board open:
- **Primary:** per-attempt and delivered opens, gm of (opens + 1) per board with a 95 % bootstrap CI and a sign-flip p.
- **Decided gain or loss:** the delivered CI excludes 1 and p < 0.05. Otherwise undecided. One look, at the end.
- **If Dbridge is a decided gain:** the default's windows half should be replaced or gated.
- **If Dwx is a decided gain:** it goes to a canary (canary-big, k = 1), then a PR.
- **Guards:**
  - DRC errors by type (starved_thermal is fork noise) and legality;
  - near-miss closure, reported separately (RULES.md 5).
- **Cost:** measured CPU per arm, reported, not gated.
- **Mechanism:** the open-alt phase's windows (count, kept, yield, illegal), and what the resumed pass closed.
