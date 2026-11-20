# PLAN: d2-cutflow-rank (offline; no queue beyond one single-core job per experiment)

## Hypothesis

A placement-only cut-overflow measure (triangulation of the pads, cut capacities from the board's own clearance
and track width, nets routed over the dual graph with negotiated prices) ranks the placements of one board by
their routed KiCad opens better than HPWL and RUDY computed on the same placements, and at a median within-board
Spearman of at least 0.3. Reference from project docs: RUDY 0.13, a 60 s real route 0.53.

## Measured failure it targets

Every static routability term in the placer has been a null, and the placer's objective cannot tell two of its
own placements apart by routability. A term is worth building into the global placer only if it ranks.

## Data (stored, no new routing)

Experiments whose arms share one routing recipe and differ only in placement: `bus-pose-ab` (4 arms x 3 seeds,
up to 12 placements per board, 143 boards) and `placement-routability` (5 arms x 3 seeds, 46 boards). Opens are
`evals.unconnected` of each stored output board. Placements with identical poses are one placement.

## Arms (measures)

`ovfK` (overflow after 8 negotiated rounds; the pre-registered measure), `ovf0` (no prices), `hpwl`, `rudy`,
`crowd` (other parts' pads within 2 mm of a pad). Tool: `tools/research/joint/cut_rank.py` on branch `d2-cutflow`.
Second question on the same module: on s2-merit213, does the measure point the right way between the human
placement and ours on the boards where the same router leaves different opens (sign agreement, rank correlation
of the differences)?

## Endpoints

Median and mean within-board Spearman with a board-bootstrap 95 % interval; pooled pair concordance; partial
correlation of `ovfK` given `hpwl`; the same by pad band and layer count.

## Deciding result and kill rule

- Build the term into the placer only if `ovfK` reaches a median of 0.3 with the interval's lower bound above the
  same-data HPWL and RUDY medians, or its partial correlation given HPWL is above 0.15 with an interval excluding 0.
- Otherwise kill the predicted term. The module stays as the shared geometry model (cut capacities, per-part
  pressure) for measured feedback from routed boards, where demand is real copper, not a prediction.
- Variants worth one more offline pass before the kill is final: true pad edge-to-edge gaps with body-corner
  vertices; per-layer assignment with a via price; demand from a 60 s real route instead of the dual route.

## Cost

About 20 single-core minutes per experiment. No sprint, no ladder.

## Result (2026-11-20, prototype `cutrank.py`, single core)

| Measure | `bus-pose-ab`, 103 boards, 1,209 placements | `placement-routability`, 41 boards, 623 placements |
|---|---|---|
| `ovfK` | 0.275 [0.18, 0.39] | 0.21 [0.16, 0.32] |
| `ovf0` | 0.25 [0.13, 0.35] | 0.21 [0.13, 0.31] |
| `hpwl` | 0.28 [0.15, 0.36] | 0.07 [-0.14, 0.34] |
| `rudy` | 0.25 [0.16, 0.40] | 0.31 [0.23, 0.42] |
| `crowd` | 0.12 [0.07, 0.18] | 0.26 [0.16, 0.34] |

Median within-board Spearman with routed opens, board-bootstrap 95 %. Partial of `ovfK` given `hpwl`: 0.19
[0.12, 0.28] and 0.16 [0.06, 0.30]. Two-layer boards of `bus-pose-ab` (32): `ovfK` 0.42 [0.27, 0.58], `hpwl` 0.44.
Human against our placement on s2-merit213: on the boards where staged is worse, `ovfK` is higher on ours on 23
and lower on 8, but it is also higher on ours where opens are equal (17 vs 9); rank correlation of the measure
difference with the open difference 0.07 (54 boards).

Verdict: the first deciding line is not met (median under 0.3, not above HPWL or RUDY). The partial correlation
line is met narrowly. Decision: no placer term now; the module is kept as the geometry model and as the producer
of the optional predicted-halo arm P of `d2-halo-feedback`, which tests the prediction where it matters.
The variants listed above remain one cheap offline pass.
