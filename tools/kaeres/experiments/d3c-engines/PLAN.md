# PLAN: d3c-engines (published benchmark, 10 boards, under 2 CPU-h)

## Hypothesis
On PCBWorld D3-C, the only public split where the field is not saturated, kae's bridge is above the published
Freerouting result (0.30 clean pass) and below the human reference and TraceMaker (0.90 each).

## Boards
`bench/suites/pcbworld-d3c-test.txt` (10 boards). The preparation chain, both scorers (ours and PCBWorld's) and the
rivals' per-board results were built for D3-A/B (`docs/research/routing/pcbworld-d3-2611.md`); two D3-C boards were smoked.

## Arms (k = 5 attempts as in the D3-A/B run, same budgets)
bridge at the tag; fork alone at the tag's pin (one run: it is deterministic); pnr route-only; human reference.
Add TraceMaker (`tracemaker route IN -o OUT --work N --no-gpu`) once it is built: C++20, tested with GCC 15; this
host's system compiler is GCC 11.4, and a conda-forge GCC 15.2 with CMake 4.4 exists in the PCBWorld environment.

## Endpoints
Clean pass at 1 and at 5 under both scorers; open connections and added DRC errors per board; vias and length against
the human board.

## Deciding result
Reported, not a kill test. Bridge at or above 0.90: the engine question is confined to boards over 1,000 pads.
Bridge at or below 0.40 with TraceMaker reproduced at 0.90: second-engine trial moves ahead of fork work.

## Protocol note
Published numbers used Freerouting 2.2.4 and 60 s single runs; state our budgets beside every number.
