<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# barrier-avoid-ab: reweight only avoidable barrier crossings (pre-registered plan)

Written 2026-11-16, before any run of these arms. Follow-up to `barrier-weight-ab2` (C `d944e2cc20da`, W
`9591ed794c5d`, `barrier_net_weight=3`, kae 4087578): no effect on opens within about +-12 %, and the mechanism
signature was missing. Crossing nets on the 40 reweighted boards went 370 -> 377. On keyboards the reweighted
nets were matrix rows and columns between locked switches. Those crossings cannot be avoided, and multiplying
their weight pulled the diodes along the matrix lines. Code: branch `place-barrier-avoidable`, at the commit
`setup.sh` records.

## Mechanism (`barrier_weight_mode`: `all` is unchanged and the default; `avoidable` and `detour` are new)
`kae.place.barriers.classify` looks at each signal-net MST edge whose straight line crosses a void or an
all-copper track keepout. The crossing is **avoidable** when a movable endpoint part has a free spot within its
half-size + 15 mm of its partner's pin: inside the outline, off fixed parts and barriers, at its current
rotation. From that spot its pin must see the partner pin without crossing a barrier, and the move must add
no crossing to the nearest fixed pin of each of its other signal nets. An edge between two fixed parts is
**anchored**. **Detour** is the shortest path around the crossed barrier pieces, less the straight line. The
pieces are taken by their convex hull, or by their simplified outline when an end lies inside the hull.
- `avoidable`: only nets with an avoidable crossing are multiplied by `barrier_net_weight` (3). This is P1's rule.
- `detour`: those nets are multiplied by `min(barrier_net_weight, 1 + avoidable detour / net HPWL)`, so the
  annealer sees the detour as wirelength. This is P1's "better still".
- In both modes, nets between fixed parts (a keyboard's matrix between locked switches) and parts with no spot
  by their partner keep their weight.

`barriers.crossings` (the final report, every arm) adds `avoidable_edges`, `avoidable_nets`, `anchored_edges`,
`detour_mm`, `avoidable_detour_mm` and `straight_mm`.

Why two modes (decided before any run of these arms): a 40 s trial on marksard rhymestone (seed state, before
the annealer; the trial hit its wall ceiling, so its final placement means nothing) found 18 crossing edges,
16 of them avoidable and 2 anchored. Their total detour was only 5.1 mm, because the voids there are small
holes, and the detour factor came to 1.004 on average. Where the voids are small, `detour` is close to the
control and `avoidable` is close to `all`, so the two modes bracket the question.

## Boards
The 40 boards on which the ab2 seed reweighted at least one net (a local analysis file, not in the repo,
`reweight.nets > 0`), listed in `boards.txt`: the boards where the mechanism exists. The 39 inert ab2 boards
are left out, because the weight cannot act on them. Domains: 9 keyboards, 5 LED/display, 9 MCU, the rest mixed.

## Arms (one commit; interleaved per board; placement only, no routing)
`kae.cli place` on the place-fixed task input with `--drc off`: seed, anneal and legalize, with no KiCad DRC
repair loop, no router and no probe. Counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), nominal
`--time $(( {timeout} / 4 ))` with timeout 1200 s x sqrt(fp/40), so 300 nominal s x sqrt(fp/40) and a wall
ceiling of 4x. Seeds 0, 1, 2 (`--attempts 3`).
- **C** (control): `barrier_net_weight` 1 (off).
- **W-old**: `--set barrier_net_weight=3` (mode `all`, as tested in ab2).
- **W-avoid**: `--set barrier_net_weight=3 --set barrier_weight_mode=avoidable`.
- **W-detour**: `--set barrier_net_weight=3 --set barrier_weight_mode=detour`.

The scorer is kaebench's place-fixed scoring (legal, placement errors, `hpwl_mm`), unchanged.

## Metrics (paired by board and seed)
Read from each run's own report (`barrier_crossings`, the same code in every arm) and kaebench's score.
- **Primary 1:** avoidable crossings (`avoidable_edges`), mean over runs of
  Delta = log1p(W-avoid) - log1p(C), with board-clustered bootstrap (5,000 resamples of boards) 95 % CI.
- **Primary 2:** total detour (`detour_mm`, all crossing edges), the same statistic.
- **Secondary:** the same for W-detour vs C, W-old vs C and W-avoid vs W-old; all crossing edges; crossing nets; anchored edges
  (should not move); by domain (keyboard / LED / other).
- **Guards:** kaebench `legal` (discordant board-seed pairs, McNemar), placement errors (total
  `courtyards_overlap` and other `placement_errors`, paired delta and CI), `hpwl_mm` (unweighted, Delta log with CI),
  integrity `valid`, and `ceiling_hit` / failed runs.
- **Mechanism:** the `barrier_reweight` of W-avoid and W-detour: avoidable and anchored edges at the seed, nets
  reweighted, mean factor, and the time it took.

## Noise and size
- n = 120 paired runs on 40 boards. Seeds within a board are correlated, so the effective n lies between 40 and
  120, and the bootstrap resamples boards.
- MDE (80 % power, two-sided 5 %) is about 2.8 x SE of the mean Delta. If the per-run SD of Delta log crossings
  is at most 0.4 and seeds are nearly independent, the MDE is 2.8 x 0.4 / sqrt(120), about 10 %. With strong
  within-board correlation it approaches 2.8 x 0.4 / sqrt(40), about 18 %. The SD and the board-clustered SE are
  measured from the runs and reported with the result.
- A/A floor: the placement under counted work and `PYTHONHASHSEED=0` is deterministic per seed, so arms differ
  only by the setting. The seed-to-seed spread inside C is reported as the noise each run carries.

## Decision rule (pre-registered)
- **Crossings fall** when the 95 % CI of primary 1 (W-avoid vs C) lies wholly below 0. Primary 2 is reported beside
  it. If the two disagree, neither decides alone: report both and read the boards.
- **Crossings rise** when that CI lies wholly above 0. **Unknown** when it spans 0. If the MDE is above 10 % and the
  point estimate is a fall, extend to seeds 3-5 (`--attempts 6`, same methods) and decide on all six. This is the
  one pre-registered extension.
- **Guards** hold unless a guard's 95 % CI lies wholly on the harmful side. That means more placement errors, a
  higher HPWL, or fewer legal runs (McNemar p < 0.05). A credible harm is reported as a trade-off beside the
  gain; it is not a gain.
- **W-detour** is decided by the same rule against C, as a second hypothesis; with two primary arms each CI is
  also given at 97.5 % (Bonferroni), and a fall that only the 95 % CI shows is reported as such.
- **W-avoid vs W-old** is reported with the same statistics. It tells whether gating on avoidable crossings
  changed what the weight does.
- Boards that move against the trend (by domain and board) are read before any verdict.

## Only if crossings fall: routed confirmation (pre-registered here, not run by this plan)
`barrier-avoid-route`: the boards of this test, the staged joint-fixed chassis of `barrier-fit-ab` (restart
portfolio, counted work, Freerouting fork named explicitly through KAE_BRIDGE_FREEROUTING and KAE_FREEROUTING
at the current pin `d137fd1`; the project control switches to the work-counting build `abefc74` when kae PR
#97 and freerouting PR #11 merge, and this test would then use that pin), arms C and the W arm whose crossings fell most.
- **Primary:** per-attempt opens from `restarts.json`, paired by seed, as Delta log1p with a board-clustered CI.
- **Guards:** delivered opens, DRC by type above the A/A band, `legal`, CPU.
- **Size:** decided from this test's measured SD. At the ab2 per-board SD of 0.37, 120 boards give an MDE of
  about 9.5 %. If 40 boards are too few, the plan adds reweighted boards from the `outline_cutouts` and
  `keepout_zones` suites, after a seed-only scan for avoidable crossings.

## Smoke and profile (before the full run)
`barrier-avoid-smoke`: 3 boards from the test, one keyboard (marksard rhymestone), one LED board (swanmatch altana)
and one MCU board (kbx81 climatesprinkler); all four arms, seed 0. The runs are deterministic under counted work,
so the full experiment reuses them. One board is profiled per arm, with py-spy on the
python process and `prof_stages.py`. The results go in SMOKE.md. Each job's `--cpus` and `--mem` come from
the smoke's peak.

## Cost (information, not a limit)
480 placement runs, each about 300-900 nominal s plus kaebench scoring: about 80-130 CPU-h.

## Addendum 2026-11-17, before any run on the new build: current components and two arms
- **Arms trimmed** (queue triage, approved by the user 2026-11-17; recorded here before any result): W-old (`all`, ab2's
  arm) and W-detour (about the control on small voids, factor 1.004 in the plan's own trial) are dropped. The test is C
  against W-avoid, primary 1 only; no multiplicity correction is needed for one contrast.
- **Current components** (project rule, 2026-11-17: current main, current Freerouting pin; old-build results decide
  nothing). `place-barrier-avoidable` is rebased onto main c81770e1 as `place-barrier-avoidable-m2` (the original branch
  is left as it was). Only documentation conflicted (main's voids-and-barriers page and area README are kept). Both arms
  run kae and harness 6b22e409, the rebased commit before this addendum (`barrier_weight_mode` is a2b62b2e, was part of
  510d8f8). `test_place_barriers.py`, `test_place_pipeline.py` and `test_cli.py` pass. Placement only: no Freerouting
  in this test; the routed confirmation, if it runs, uses the pin 9a5512d.
- **New experiment `barrier-avoid-ab-m`** (owner `exp-barrier-avoid-ab-m`), new method ids, one job per board with both
  arms, seeds 0-2 interleaved. No run of `barrier-avoid-ab` had finished; its queued jobs and the old-build profile
  (owner `exp-barrier-avoid`) are cancelled.
- Boards (40), seeds 0-2, counted work, metrics and the decision rule for primary 1 otherwise unchanged.
- **Still worth running:** barrier-weight ab2 found no effect with the mechanism missing on its boards; this is the
  cheap placement-only screen that decides whether a routed test is worth it. About 50 CPU-h.
