# pk3-ab-m6: what the restarts' last slot should do (2026-11-21)

## Setup
- **Experiment** `pk3-ab-m6`: haslam and harness d150ee47 (branch `pk3-ab-m6`, main 6d726340), Freerouting fork 37b1a8b,
  counted work.
- **Arms**, all sharing k0..k2 and `--final`, then a 10.9 % slot:
  - **R**: polish-merit's restarts; k = 3 is a fresh attempt.
  - **Rresume**: `--max-attempts 3`, then a bridge pass resumed from the kept board.
  - **Pk3**: `--max-attempts 3`, then P-late's windows finish on the kept board.
- **Boards:** 103 of the 160 ran in all three arms. 56 were parked by the 2026-11-20 trim (`TRIM-2026-11-20.json`),
  not resubmitted.
- **Analysis:** `analyze_pk3.py` (pre-registered statistics).

## Determinism check
k0..k2 and `--final` gave identical ranks in all three arms on 85 of 103 boards; 18 differ. The primary is
reported on all boards and on the identical 85.

## Primary: delivered opens, paired by board
On boards R leaves open after k0..k2 and `--final` (95).

| contrast | gm [95 % bootstrap] | better / worse | p | MDE | opens |
|---|---|---|---|---|---|
| **Rresume vs R** | **0.937 [0.908, 0.968]** | 62 / 4 | 0.0002 | 4.7 % | 7,119 -> 6,511 |
| Pk3 vs R | 0.940 [0.911, 0.972] | 59 / 5 | 0.0002 | 4.7 % | 7,119 -> 6,582 |
| Pk3 vs Rresume | 1.003 [0.987, 1.019] | 16 / 27 | 0.71 | 2.4 % | 6,511 -> 6,582 |

On the 77 open boards whose k0..k2 were identical:
- Rresume vs R: 0.928 [0.908, 0.947], **50 better, 0 worse**.
- Pk3 vs R: 0.940 [0.923, 0.956], 48 / 0.
- Pk3 vs Rresume: 1.013 [1.000, 1.027], 9 / 22.

On boards over 1,000 pads (10), Rresume vs R is 0.875.

## Guards
- **DRC errors:** R 5,545; Rresume 5,572 (+0.5 %); Pk3 5,605 (+1.1 %). All are inside the 3.4 % A/A spread.
  - `starved_thermal`: 57 -> 67 (Rresume, +17.5 %) and 57 -> 62 (Pk3).
  - `solder_mask_bridge`: 2,365 -> 2,379 / 2,402.
  - `copper_edge_clearance`: 1,067 -> 1,071 / 1,085.
  - No type of 30 or more errors rose by more than 25 %.
- **Clean boards:** 4 / 3 / 3.
- **CPU:** 116.7 / 116.4 / 117.4 h.
- **Wall vs budget:** median 0.92-0.94, max 2.28; no ceiling hit.
- **Manipulation:** the finish board was kept on 100 of 103 boards (Rresume) and 102 of 103 (Pk3).

## Board by board
- All 4 boards where Rresume is worse than R (embeddedalpha 1 -> 4, prrpls 5 -> 8, librem5 usb-c 62 -> 68,
  dropintappt 16 -> 17) are boards where k0..k2 differed between the arms. Their difference comes before the slot,
  not from it.
- Largest gains: byran carrier 66 -> 46, autopilotpi 107 -> 76, bitmagic 17 -> 12.

## Near-miss closure (boards within 5 opens of clean), reported separately
21 boards.
- Rresume closed 1 (glider 1 -> 0) and opened none. Pk3 likewise.
- Worse near-miss boards (embeddedalpha, prrpls) are among the non-identical ones above.

## Verdict
- **Rresume: decided gain**, -6.3 % [-9.2 %, -3.2 %] delivered opens; on identical k0..k2, -7.2 % with no board
  worse. The guards hold.
- **Pk3: gain vs R**, but no better than Rresume: 1.003 [0.987, 1.019], and 1.013 [1.000, 1.027] on the identical
  set, so the windows add nothing and may cost about 1 %.
- By the plan's rule, **Rresume is the one to ship**: the simpler change, with no windows. This confirms
  polish-replay: the gain is the resumed bridge pass on the kept board, not the polish.
- **Canary submitted:** `pk3-canary` (R vs Rresume, canary-big, 10 boards, k = 1, prio 5, 20 jobs). The PR follows
  the canary.
- **Note for the PR:** R here is polish-merit's plain restart schedule. Main's default place-and-route recipe is
  completion-first with `--open-alt` windows (#96), so the PR has to put "resume the kept board in the last slot"
  into that recipe's schedule. That needs its own small check that it composes with `--open-alt`.

## Canary (pk3-canary, canary-big, 10 boards, k = 1, R vs Rresume, 2026-11-21)
- Opens 4,534 -> 4,365 (-3.7 %): 7 boards lower, 1 higher, 2 the same.
  - Lower: gecko5 170 -> 133, mad5160 1,041 -> 904, zotino 81 -> 63, sdi-mipi 296 -> 271.
  - Higher: glasgow 528 -> 589. Its k2 differed between the arms (535 vs 751) before the slot; the resumed pass
    then took 744 -> 589.
- DRC errors: `copper_edge_clearance` 58 -> 76, almost all on beagleplay. There R's fresh k = 3 matched the opens
  (1,999) with 47 errors, against 65 on the board Rresume kept. A fresh attempt can still win on errors at equal
  opens. Also `starved_thermal` 1 -> 3 and `track_dangling` 0 -> 1.
- No crash, timeout or ceiling hit (wall/budget at most 2.09). The finish board was kept on all 10 boards.
- Bug records: 2, both on Rresume (one `starved_thermal`, one `track_dangling`), of the kind every arm logs.

Nothing contradicts the A/B. The canary is one run per board: a safety check, not a measurement.

## How it composes with main's default recipe
The default haslam place-and-route recipe (`merit-restart.sh`, "completion-first, windows") already does this on
every board that is open after phase 1:
- Its phase 2, `--open-alt`, runs `haslam.joint.cli run --start <phase 1's board>`.
- That run begins with iteration 0, a bridge pass resumed from the kept board's copper, and then windows, with the
  second half of the budget.
- So the mechanism that pk3-ab and polish-replay measured is already in the default. Adding Rresume's
  `--max-attempts 3 --finish route @BEST@` would add nothing, because restart.py passes every non-policy option to
  each phase's wrapper:
  - phase 1 runs 4 parallel lanes, so `--max-attempts 3` would cut it short of one wave;
  - phase 2 already resumes from the same board.
- No change to the default recipe follows. The result applies to plain restart recipes (R).
- At the default's half-budget slot, windows were the tested choice: cf-windows, -15.9 % vs another restart run.
  Whether a plain resumed bridge pass would do as well at that budget is the open question pk3-ab raises (Pk3 vs
  Rresume 1.003 [0.987, 1.019] at a 10.9 % slot).
