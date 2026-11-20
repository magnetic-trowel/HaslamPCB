# PLAN: canary-engine (canary tier; router-engine work only; needs the coordinator's say)

## Purpose
A big-board yardstick that a router can finish. Of the ten merit boards over 1,000 pads, one board's human layout has
956 open connections and another's has 117 opens and 1,615 errors; those two hold 982 of the ten boards' 1,831 opens
under the bridge. Two of the ten have a DRC-clean human layout; five are complete with 21 to 937 errors under the
stored rules; one has a single open connection.

## Boards
`boards.txt`: the 25 of the 28 canary boards whose human layout has no open connection
(`tools/research/routing/engine_audit/human_status.py --finishable`); 17 of them have four or more copper layers and
are the engine row, the 8 two-layer boards are reported apart. The three unfinished boards (kocer, jetson, polarfire)
may still be run, are reported apart and are never summed with the others.

## Arms (one deep deterministic run per board, counted work, no restarts)
fork alone at the pin; bridge single lineage (resume chain, no parallel fresh seeds); TraceMaker when built;
later: the winner of `layer-oracle`.

## Endpoints
Open connections per board at 1x, 2x, 4x and 8x counted work (the budget curve), the fitted exponent b in
opens ~ work^b per board and engine, boards finished, added DRC errors.

## Size
Stored: fork alone needs 2.0-4.2 CPU-h per board on the ten (29 CPU-h per arm). Between two near-identical fork arms
the log ratio of opens has SD 0.09 on those boards, so 10 boards detect 8 % for a small change; a different engine will
spread more. The stored lineages give b = -0.27 (median of 15): halving the opens costs about 13 times the CPU.

## Deciding result
An engine or a plan matters at this scale if it changes b or shifts the curve by more than a doubling of budget does
(17 % of opens at b = -0.27). Kill for an engine: worse than the fork at equal counted work on two thirds of the boards.
