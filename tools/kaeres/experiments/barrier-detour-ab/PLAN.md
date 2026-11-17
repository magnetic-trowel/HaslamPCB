<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# barrier-detour-ab: weight barrier crossings by their real detour (pre-registered plan)

Written 2026-11-17, before any run of these arms. This follows `barrier-avoid-ab-m`, whose readout is in the
explore-2611 results note of that name. There, a flat 3x weight on avoidable crossings gave −3.0 % avoidable
crossings (CI −10.6 % to +4.3 %, MDE 11 %) and a credible HPWL harm of +2.4 % (CI +0.9 % to +4.0 %). The losses sat
on keyboards with small holes: about 0.3 mm of detour per crossing, yet the nets were weighted 3x and HPWL rose
about 11 %. That test is not extended, because even a significant −3 % alongside that harm would not be adopted.

The code is branch `place-barrier-detour`, off `place-barrier-avoidable-m2` (main c81770e plus the barrier stack,
which is not on main). Both arms run 2f33ef6.

## Change since barrier-avoid-ab-m
- **2f33ef6:** `detour()` now goes round the holes of a barrier piece. A keepout frame along the edge with spurs
  into the board is one piece whose hole holds both pins (ohwr fmc-dio). The old code read every such crossing as
  0 mm; with the fix, ohwr's 59 edges come to 146 mm.
- **No path:** when an end is truly enclosed, the detour is unknown, counted in `detour_unknown`, not reported as 0.
- **Arm:** `barrier_weight_mode=detour` multiplies only nets with an avoidable crossing, by
  `min(3, 1 + avoidable detour / net HPWL)`. A 0.3 mm crossing on a 30 mm net gets 1.01x.

## Boards (rule fixed here, from barrier-avoid-ab-m's control arm, before any run)
For each board, take the control arm's `avoidable_detour_mm / avoidable_edges` (mm per avoidable crossing, summed
over seeds 0-2). The distribution has a gap: 13 boards sit at 0.00-0.43 mm and the rest at 1.11 mm and above.
- **Screen set (`boards.txt`, 19 boards):** threshold **at least 1.0 mm per avoidable crossing**. That gives 18 boards
  from 1.11 mm (stacklight) to 41 mm (espoir).
  - Plus ohwr fmc-dio: it read 0.01 mm only because of the bug; with the fix it measures 2.5 mm per crossing on its
    seed-1 control output.
  - The 9 boards with no avoidable crossing are inert by construction and left out.
- **Keyboard guard stratum (`guard.boards.txt`, 5 boards):** the small-hole keyboards with avoidable crossings
  (rhymestone, knuckle, captouchkeyboard, buttonmatrix, thumb-cluster, all 0.0-0.43 mm per crossing). crkbd
  (1.20 mm) and plate-flex (8.9 mm) are in the screen set and are also reported as keyboards.

## Arms (one commit; interleaved per board; placement only, no routing, no Freerouting)
The chassis is as in barrier-avoid-ab. `kae.cli place --drc off` on the place-fixed input, with counted work
(`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`) and 300 nominal s x sqrt(fp/40).
- **C:** control (`barrier_net_weight` 1).
- **W-detour:** `--set barrier_net_weight=3 --set barrier_weight_mode=detour`.

Experiments:
- `barrier-detour-ab`: the screen set, seeds 0-11.
- `barrier-detour-kb`: the guard stratum, seeds 0-2. HPWL has an SD of only 0.07 per run.

## Metrics (paired by board and seed; `analyze.py` of barrier-avoid-ab)
- **Primary:** avoidable crossings (`avoidable_edges`) on the screen set. The statistic is the mean Δlog1p with a
  board-clustered bootstrap 95 % CI.
- **Secondary:** total detour, all crossing edges, crossing nets, and the reweighting factors W-detour used.
- **Guards:**
  - HPWL (kaebench `hpwl_mm`, unweighted) on the screen set and on the keyboard stratum separately.
  - Placement errors, `legal` (McNemar), `valid`, and ceiling hits.

## Size
- **Inputs:** SD per run of Δlog1p avoidable crossings is 0.40 (barrier-avoid-ab-m). That run's board-clustered SE
  (0.039 at 120 runs on 40 boards, against 0.0365 if independent) implies an intra-board correlation of about 0.07.
- **Sizing:** 19 boards x 12 seeds = 228 paired runs gives a design effect of about 1.8 and an SE of about 0.035,
  so an **MDE of about 10 %** at 80 % power.
- **Floor:** with many seeds the MDE cannot fall below about 7 % on 19 boards. In barrier-avoid-ab-m the
  large-detour half of the boards showed −7.8 % (post hoc), so this design has about 60-70 % power for that size.
- **Guard power:** the HPWL guard, at SD 0.07, detects about 2 % on the screen set and about 4.5 % on the keyboard
  stratum (15 runs).

## Decision rule (pre-registered)
- **Gain:** the 95 % CI of the primary lies wholly below 0, the HPWL CI on the screen set does not lie wholly above
  0, and the keyboard stratum's HPWL CI does not lie wholly above 0. A gain leads to the routed confirmation,
  pre-registered in barrier-avoid-ab's PLAN, with arms C and W-detour.
- **Trade-off:** a fall with a credible HPWL harm. It is reported; it is not adopted and not routed.
- **No effect within X %:** the CI spans 0 and lies inside ±X %; X is reported.
- **One look at seeds 0-11, one pre-registered extension:** if the point estimate is −5 % or lower, the CI spans 0
  and the guards hold, extend to seeds 12-19 (`--attempts 20`, MDE about 9 %). That is the last look.
- **Otherwise:** the barrier-weight line closes. ab2, avoid-ab-m and this test would then all be without a usable
  gain, and the work moves to placement terms that see the voids directly.

## Worth it
- **What it decides:** whether weighting a crossing by what it actually costs cuts avoidable crossings where they
  cost real length (at least 1 mm each), without the HPWL harm the flat weight had. That is the only form of the
  mechanism not yet tested.
- **If it gains:** the routed confirmation is justified.
- **If it does not:** three tests (ab2, avoid-ab-m, this one) cover the barrier-weight idea well enough to stop
  spending on it.
- **Cost:** barrier-avoid-ab-m measured 14.5 CPU-h for 240 runs (median 184 s wall, about 1 CPU each, 48 % of the
  2 CPUs declared). Here there are 456 + 30 runs, about 30 CPU-h; the extension adds about 20 CPU-h. This is cheap
  next to the routed test it gates (about 100 CPU-h or more).

## Smoke and profile
The chassis is unchanged from barrier-avoid-ab-m: same command, flags and budget, with one setting changed. Its
240 runs are the smoke for job size: median wall 184 s, at most 619 s, about one CPU per job, and no ceiling hits.
No new py-spy profile: the placement stage under this chassis has run in full already, and each extra stage
here (`classify`, `detour`) takes under 1 s per run (0.8 s on ohwr, the largest barrier set).
