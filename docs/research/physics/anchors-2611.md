# Physics anchors 2026-11: three checks against published data

**Status:** criteria fixed, checks not run yet (this revision is the pre-registration; results follow in the next commit).
**First published:** 2026-11-20, branch `physics-anchors`.

Scope: first checks of the project's physics against published measurements and shipped products, with pass and fail lines written before each run: AN-139 loop inductance vs plane distance, budget utilisation on boards of vendors that sell assembled products, track heating by IPC-2221 and IPC-2152. Not here: the validation plan with fabricated coupons -> [validation-program](validation-program.md); the measured tables -> [hot-loops](../../topics/rules/power/hot-loops.md), [high-current](../../topics/rules/power/high-current.md).
Keys: anchors, published measurement, AN-139, fixture inductance, L0, resonance method, image plane, shipped-product quantile, survivorship anchor, practice quantile, P(u > 2), vendor-sold boards, IPC-2221, IPC-2152, Brooks-Adam, HASLAM_TRACK_HEAT, an139_fit.py, shipped_quantiles.py, track_heating.py

Scripts: `tools/research/physics/anchors/{an139_fit,shipped_quantiles,track_heating}.py`. Each prints its numbers and one verdict line, and exits 0 on pass, 1 on fail, 2 when the result lies between the two lines.

## Criteria, fixed before the runs

The pass and fail lines are the ones of the 2026-11 gap audit's validation plan (checks 1, 2 and 7); the modelling choices each line needs are fixed here too. A failed check is a result: no constant is tuned to pass.

### Check 1 criteria: AN-139 loop inductance vs plane distance

- Data: the seven rows of AN-139 Table 1 ([hot-loops](../../topics/rules/power/hot-loops.md#measured-loop-inductance-vs-plane-distance)): a 10 × 10 cm loop, resonated with C = 400 pF; the table prints d, f, C and L.
- Model: `haslam.physics.kernels.loop_L` (partial inductances with a perfect image plane, Hammerstad-Jensen strip term), the law the placer's and router's loop terms use. Geometry as in the earlier comparison in [pdn-and-commutation](../../topics/physics/pdn-and-commutation.md#1-commutation-loop-geometry): square loop, 100 mm centreline side, 3 mm trace, 35 µm copper, infinite plane at distance d; no plane for the open loop.
- The two rows without a plane under the trace are shorted turns: L = L1 − M²/L2, the shorted ring perfectly conducting, same trace width, concentric, its outer edge 1 mm inside the loop's inner edge; coplanar for "inner copper short-circuit loop", 1.5 mm below for "rectangular loop no overlap".
- One free parameter: a fixture inductance L0 ≥ 0 in series with every row (capacitor and its connection), fitted by least squares on ln(model / measured).
- **Pass:** all seven rows within ±15 %. **Fail:** any row beyond ±30 %: the plane-distance law, as applied with this geometry, is wrong. Between the lines: undecided.
- Exploratory, announced here, not part of the verdict: the trace width as a second free parameter (the note does not give it), with 100 mm read as centreline or as outer edge; the four plane rows alone.

### Check 2 criteria: shipped-product quantile audit

- Terms: the placer's budgeted commutation loop, decap loop, antenna feed, ESD path and crystal. u = spend / allocation per structure.
- Groups: *vendor-sold* = corpus boards whose repository owner is sparkfun, sparkfunx, adafruit, olimex, antmicro or arduino; *rest* = every other board. The rest contains other sellers (Tinkerforge, Watterott, Soldered and others), which pulls the group difference toward zero.
- Data set A (stored): the human layouts' routed physics evaluations in the results store (`$HASLAM_RESULTS`), by the evaluator with the most human evaluations, and by each later one on its subset. It has commutation, decap, ESD and crystal on routed copper; structures with a value and no open hop.
- Data set B (computed, current code): the place terms (`haslam.physics.place_terms`) at the human placement on a seeded sample of 150 vendor-sold and 150 other boards, drawn in rotation over the structure kinds data set A found on them. It has all five terms under today's allocations. All valued structures; the *credible* subset (hops within 15 mm, as `pt_human_perturb.py`) beside it.
- Reported per term and group: structures, boards, median u, P(u > 1), P(u > 2), each with a 95 % bootstrap interval that resamples repositories.
- **Reading (fixed):** a real limit is exceeded at 2× by under 10 % of products sold for years. P(u > 2) < 10 % on vendor-sold boards: the budget behaves as a limit. Otherwise the budget is a prior and is labelled so. An interval that contains 10 % is reported as uncertain. The verdict is taken on data set B (today's allocations); data set A shows whether it depends on the code version and on routed against placed copper.
- **Kill rule:** where vendor-sold and other boards have the same u distribution (the intervals of the differences in P(u > 1) and in P(u > 2) both contain 0), the audit carries no information for that term beyond "human practice".

### Check 3 criteria: track heating

- Functions: IPC-2221 (`ipc_dT`, `ipc2221_width`) and the Brooks-Adam fit of IPC-2152's external chart, ΔT = 215.3·I²·W^−1.15·Th^−1 (mils).
- Points: every tabulated value in [high-current](../../topics/rules/power/high-current.md#trace-width): 0.30 mm at 1 A and 2.77 mm at 5 A (10 K, 1 oz, IPC-2221); the 3 mm table (1 oz and 2 oz, 5/8/10/12/15 A, both formulas: 20 values); the widths at 10 K, 1 oz (IPC-2152 4.6 mm at 5 A and 15 mm at 10 A; IPC-2221 2.8 and 7.2 mm).
- **Pass:** each function reproduces each printed value to its last printed digit (±0.5 of that digit; rises under 10 K, printed without a decimal, ±1 K). **Fail:** any value outside: the doc or the code is wrong.
- Claim test: "IPC-2221 is conservative against IPC-2152" holds only if the IPC-2221 rise is at least the Brooks-Adam rise at every tabulated point. Where it fails, the comment in `haslam/src/haslam/excite/dc.py` states where each formula is the hotter one.
- What this check is not: both formulas are published fits and the table is this project's own arithmetic, so a pass shows the code and the doc agree with the published fit, not that either meets a measurement of ours.

## Check 1 result: AN-139

Not run yet.

## Check 2 result: shipped-product quantiles

Not run yet.

## Check 3 result: track heating

Not run yet.

## Sources

- Linear Technology AN-139, "Power Supply Layout and EMI" (C. Kueck), Table 1 [P].
- Brooks and Adam, "PCB Trace Current/Temperature Relationships and their Dependencies", Signal Integrity Journal, 2019 ([article](https://www.signalintegrityjournal.com/articles/1406)), Eq. 1 [P].
