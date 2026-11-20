# PLAN: ground-side-ab (ground-side price on 2-layer boards)

**Hypothesis.** On 2-layer boards with a ground pour, pricing signal tracks on the pour side 4x makes the router keep the pour whole under the signals, raising the share of signal track length that lies directly over ground copper to the human layout's level, without losing completion.

**Measured failure it targets.** Stored s2-merit213 outputs, 43 two-layer boards: `cov_opp` human 0.533, bridge -3.7 points [-6.3, -1.0], staged -9.8 [-13.7, -6.1]. The router prices inner planes only (`translate.plane_layers`).

**Mechanism and suite.** Mechanism: ground pour on a 2-layer board. Boards: the 2-layer boards of `sprint-quality` and `sprint-frontier` that have a ground zone covering at least 30 % of the outline on an outer layer (expect about 60-70; the run's `ground_side` summary entry lists where the price applied; boards where it did not apply are dropped as out of reach before paying). No board over 0.5 CPU-h per method-run.

**Arms.** Control: stored `control-w47` bridge at tag `baseline/2026-w47`. Treatment: the same method built from branch `d3-ground-side` with `--set ground_side_cost=4` on its `haslam.route.cli route` and `lastmile` commands. Seeds paired with the control's. One change. A second arm `ground_side_cost=2` is run only if the completion guard fails at 4.

**Endpoints.** Primary: paired difference of `cov_opp` (return rows; until `return_board.py` is merged, `measure()` of the stage 0 prototype), treatment minus control, mean with a board-bootstrap 95 % interval, on boards both finish. Guard: clean net of input and near-miss closure from `haslamres quality`. Secondary: `cov_any`, vias, track length, decap and chain module ratios, errors added.

**Deciding result.** Adopt as the 2-layer default candidate (to be confirmed on the ladder) if `cov_opp` rises by at least 5 points with the interval above 0, and clean net of input is not lower by more than 2 boards. Smallest effect the design detects: 5 points at 40 boards (paired sd 0.09-0.12). "Undecided" if the interval includes both 0 and +5.

**Kill rule.** Gain under 3 points, or the completion guard fails at both 4 and 2. Then the price form is dropped and the reserved skeleton is the only remaining form of the idea.

**CPU.** One new arm on about 65 small 2-layer boards: 15-25 CPU-h by `haslamres exp create`'s estimate; if over 40, drop the costliest boards first. Priority 5.

