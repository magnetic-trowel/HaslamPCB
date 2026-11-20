<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# d4-sched-width: does a fixed-placement router need a restart portfolio, and how wide?

Hypothesis. At equal counted budget, fewer and deeper lanes leave fewer opens than the four-lane doubling schedule.
Measured failure. Replay of s2-merit213 attempt logs (tools/research/effort/replay.py): two lanes after the probe
reach 152 of 157 clean boards on 56 % of the CPU and beat a four-lane schedule of equal CPU by 21 boards [13, 31].
Mechanism. tools/kaeres/sched.py behind `restart.py --sched return` (branch d4-sched): probe 2 seeds, then one fresh
and one resumed lane per batch, unused lane time charged to depth. Default `--sched ""` is the old schedule.
Suite. bench/suites/sprint-frontier.txt + sprint-quality.txt (acts on every board), seeds 0 and 1, tag baseline/2026-w47.
Arms, all with nominal counted budget W = 900 s x sqrt(footprints/40) per board and seed (report actual CPU too):
  C  stored control-w47, base bridge (71e60a91475d): one attempt, no wrapper. Not re-run.
  A  bridge under restart.py, fixed schedule: --parallel 4 --first-s 60 --scale-first --growth 2 --resume 0.5 --time W/4
  B  as A with --sched return --sched-opts '{"fixed_placement": true}'
A and B need the wrapper recipe (the s2 "bridge (restarts)" recipe at the tag). If `kaeres sprint` cannot register
it, create by hand as bench/suites/README.md shows (`kaeres exp create d4-sched-width --method 71e60a91475d --method A
--method B --boards @FILE --attempts 2 --reuse-runs --harness baseline/2026-w47 --kae baseline/2026-w47`), tier
sprint, priority 5. Smoke first: on three boards the summed lane budgets of A and of B are within 10 % of W.
Endpoints (kaeres quality, paired per board and seed): (1) log1p(opens), B against A and C against B; (2) near-miss
closure: boards within 5 opens of clean in the comparator that become clean; (3) from restarts.json, CPU at which B
first reaches A's final rank (ratio B/A; boards never reaching it counted as 1.5).
Deciding result. B better than A on (1), interval excluding 0, or ratio (3) under 0.8 with (1) not worse: adopt
two lanes. C not worse than B on (1) and (2): drop the wrapper for fixed-placement methods; the controller moves
inside the attempt. Interval includes 0: undecided (smallest detectable difference .09 log units on the frontier
boards, .055 with both suites).
Kill rule. B worse than A on (1), or B loses more than 2 clean boards net: stop, keep the fixed schedule.
CPU-h. A and B at about 10-12 each: 25 at most. Cap 40.
