<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Polish replay: P-late's finish on restarts' kept boards, at 11 % of the allowance

**Status:** gain, -9.4 % open connections [-13.4 %, -5.9 %], DRC errors unchanged. Most of it comes from one
more bridge pass on the kept board, not from the windows.
**First published:** 2026-11-16 on branch `polish-replay` (plan, analysis and result in
`tools/kaeres/experiments/polish-replay/`).

Keys: polish-merit, P-late, P-k3, windows finish, restart k = 3, resume from best, J13

## Question
polish-merit found that P-late's windows finish removes 21 % of opens. But P-late pays for that by cutting the
restarts to 55 %, which truncates the 4x attempt, so the net effect was zero. R's last restart (k = 3, about 11 % of
the allowance) was worth almost nothing. The candidate P-k3 keeps R's schedule through k = 2 and polishes in the
k = 3 slot. This replay measures how much polish survives at 11 %.

## Method
- **Boards:** the 75 merit boards where polish-merit's restarts arm R (76fae3c, Freerouting d137fd1, counted work)
  left open connections.
- **Arms**, side by side:
  - copy: R's kept board, rescored;
  - polish: `kae.joint.cli run --start <kept board> --no-modules`, P-late's finish command, at 11 % of the
    allowance.
- **Rule:** the polish board is kept only when KiCad ranks it no worse (restart.py's rule for `--finish`).
- **Primary:** per-board log ratio of opens, bootstrap CI (pre-registered).

## Result
- **Opens:** 1,594 -> 1,428 on 73 boards; geometric mean 0.906 [0.866, 0.941]. 34 boards better, 0 worse.
  MDE 5.8 %.
- **DRC errors:** 3,062 -> 3,058. CPU 13.8 h.
- **By size:** boards over 1,000 pads gain most (gm 0.827, n = 4; zotino 132 -> 87, usbarmory 157 -> 130).
  Boards under 1,000 pads gain about 9 %.
- **R's k = 3** was a fresh attempt on every board that had one, and it never improved the kept board.

**Mechanism.** `--start` begins with a full bridge pass on the kept board: Freerouting from its copper, repair
rounds and the last mile. That pass gives 73 % of the gain (1,594 -> 1,472). The windows and finish give the rest
(-> 1,428), on 13 boards: kestrel 13 -> 8, undercontrol 29 -> 22. So the time in R's last slot is worth about
10 % when it goes to the kept board, and nothing as a short fresh attempt.

**Failures.**
- **arvsom and sdi-mipi wrote no board.** Their bridge pass ran Freerouting for 2,700-4,100 s, past the 4x
  wall ceiling. Work mode does not yet charge Freerouting; fork #11 and kae #97 add that.
- **rhymestone and bestelampe:** the polish board had more errors, and the keep rule rejected it.

## Verdict and next
- **Verdict:** P-k3 passes the plan's gate (the gain's CI excludes 0 and beats k = 3's contribution).
- **Next, a confirmatory A/B on fresh boards, on the work-counting pin, with three arms:**
  - R;
  - R with a resumed bridge pass (`route @BEST@`) in the k = 3 slot;
  - P-k3.
  The resumed-pass arm tells whether the windows earn their 27 % share beyond a plain resume.
