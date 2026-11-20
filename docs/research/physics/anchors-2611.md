# Physics anchors 2026-11: three checks against published data

**Status:** worked as a check: AN-139 fails as posed and anchors only the trend; shipped boards mark the commutation and ESD budgets as priors, decap at the line, crystal and antenna as limits; track heating passes after two doc cells were corrected, and "IPC-2221 is conservative" is rejected.
**First published:** 2026-11-20, branch `physics-anchors`; criteria in commit 825e4e95, before any run.

Scope: first checks of the project's physics against published measurements and shipped products, with pass and fail lines written before each run: AN-139 loop inductance vs plane distance, budget utilisation on boards of vendors that sell assembled products, track heating by IPC-2221 and IPC-2152. Not here: the validation plan with fabricated coupons -> [validation-program](validation-program.md); the measured tables -> [hot-loops](../../topics/rules/power/hot-loops.md), [high-current](../../topics/rules/power/high-current.md).
Keys: anchors, published measurement, AN-139, fixture inductance, L0, resonance method, image plane, shipped-product quantile, survivorship anchor, practice quantile, P(u > 2), vendor-sold boards, IPC-2221, IPC-2152, Brooks-Adam, KAE_TRACK_HEAT, an139_fit.py, shipped_quantiles.py, track_heating.py

Scripts: `tools/research/physics/anchors/{an139_fit,shipped_quantiles,track_heating}.py`; each prints its numbers and a verdict line and exits 0 on pass, 1 on fail, 2 between the lines.

## Criteria, fixed before the runs

Pass and fail lines: the 2026-11 gap audit's validation plan (its checks 1, 2 and 7), with the modelling choices each needs. A failed check is a result: no constant is tuned to pass.

### Check 1 criteria: AN-139 loop inductance vs plane distance

- Data: the seven rows of AN-139 Table 1 ([hot-loops](../../topics/rules/power/hot-loops.md#measured-loop-inductance-vs-plane-distance)): a 10 × 10 cm loop, resonated with C = 400 pF; the table prints d, f, C and L.
- Model: `kae.physics.kernels.loop_L` (partial inductances with a perfect image plane, Hammerstad-Jensen strip term), the law the placer's and router's loop terms use. Geometry as in the earlier comparison in [pdn-and-commutation](../../topics/physics/pdn-and-commutation.md#1-commutation-loop-geometry): square loop, 100 mm centreline side, 3 mm trace, 35 µm copper, infinite plane at distance d; no plane for the open loop.
- The two rows without a plane under the trace are shorted turns: L = L1 − M²/L2, the shorted ring perfectly conducting, same trace width, concentric, its outer edge 1 mm inside the loop's inner edge; coplanar for "inner copper short-circuit loop", 1.5 mm below for "rectangular loop no overlap".
- One free parameter: a fixture inductance L0 ≥ 0 in series with every row (capacitor and its connection), fitted by least squares on ln(model / measured).
- **Pass:** all seven rows within ±15 %. **Fail:** any row beyond ±30 %: the plane-distance law, as applied with this geometry, is wrong. Between the lines: undecided.
- Exploratory, announced here, not part of the verdict: the trace width as a second free parameter (the note does not give it), with 100 mm read as centreline or as outer edge; the four plane rows alone.

### Check 2 criteria: shipped-product quantile audit

- Terms: the placer's budgeted commutation loop, decap loop, antenna feed, ESD path and crystal. u = spend / allocation per structure.
- Groups: *vendor-sold* = repository owner sparkfun, sparkfunx, adafruit, olimex, antmicro or arduino; *rest* = every other board. The rest contains other sellers (Tinkerforge, Watterott, Soldered), which pulls the group difference toward zero.
- Data set A (stored): the human layouts' routed physics evaluations in the results store (`$KAE_RESULTS`), by the evaluator with the most human evaluations and by each later one. Commutation, decap, ESD and crystal on routed copper; structures with a value and no open hop.
- Data set B (computed, current code): the place terms (`kae.physics.place_terms`) at the human placement on a seeded sample of 150 vendor-sold and 150 other boards, drawn in rotation over the structure kinds data set A found. All five terms, today's allocations, all valued structures; the *credible* subset (hops within 15 mm, as `pt_human_perturb.py`) beside it.
- Reported per term and group: structures, boards, median u, P(u > 1), P(u > 2), each with a 95 % bootstrap interval that resamples repositories.
- **Reading (fixed):** a real limit is exceeded at 2× by under 10 % of products sold for years. P(u > 2) < 10 % on vendor-sold boards: the budget behaves as a limit. Otherwise the budget is a prior and is labelled so. An interval that contains 10 % is reported as uncertain. The verdict is taken on data set B (today's allocations); data set A shows whether it depends on the code version and on routed against placed copper.
- **Kill rule:** where vendor-sold and other boards have the same u distribution (the intervals of the differences in P(u > 1) and in P(u > 2) both contain 0), the audit carries no information for that term beyond "human practice".

### Check 3 criteria: track heating

- Functions: IPC-2221 (`ipc_dT`, `ipc2221_width`) and the Brooks-Adam fit of IPC-2152's external chart, ΔT = 215.3·I²·W^−1.15·Th^−1 (mils).
- Points: every tabulated value in [high-current](../../topics/rules/power/high-current.md#trace-width): 0.30 mm at 1 A and 2.77 mm at 5 A (10 K, 1 oz, IPC-2221); the 3 mm table (1 oz and 2 oz, 5/8/10/12/15 A, both formulas: 20 values); the widths at 10 K, 1 oz (IPC-2152 4.6 mm at 5 A and 15 mm at 10 A; IPC-2221 2.8 and 7.2 mm).
- **Pass:** each function reproduces each printed value to its last printed digit (±0.5 of that digit; rises under 10 K, printed without a decimal, ±1 K). **Fail:** any value outside: the doc or the code is wrong.
- Claim test: "IPC-2221 is conservative against IPC-2152" holds only if the IPC-2221 rise is at least the Brooks-Adam rise at every tabulated point. Where it fails, the comment in `kae/src/kae/excite/dc.py` states where each formula is the hotter one.
- Limit of the check: both formulas are published fits and the table is this project's arithmetic; a pass ties code and doc to the fits, not to a measurement.

## Check 1 result: AN-139

Run: `PYTHONPATH=kae/src python tools/research/physics/anchors/an139_fit.py` [C].

**Verdict: fail.** With the geometry our docs assumed, every row reads high and the fitted L0 is 0 (unconstrained it is −8.6 nH, which a series inductance cannot be).

| Row | d (mm) | Measured (nH) | Model, 3 mm trace | Error | Exploratory: 13.5 mm trace + L0 10.4 nH | Error |
|---|---|---|---|---|---|---|
| Single-layer open loop | – | 187 | 338 | +81 % | 191 | +2 % |
| Inner copper short-circuit loop | 0 | 141 | 224 | +59 % | 162 | +15 % |
| Solid plate | 1.5 | 42 | 117 | +178 % | 45 | +8 % |
| Rectangular loop no overlap | 1.5 | 53 | 230 | +334 % | 48 (ring read as under the trace) | −10 % |
| Thin rectangular | 0.5 | 23 | 57 | +148 % | 24 | +5 % |
| (next row) | 0.27 | 21 | 35 | +68 % | 18 | −13 % |
| Paper | 0.12 | 13 | 17.5 | +35 % | 14 | +8 % |

1. **The 3 mm trace is not the fixture.** A 100 mm square of 3 mm trace has 338 nH with no plane; the note measured 187 nH. Our docs' ratios (17.5 / 6.2 / 3.0 / 1.9 against the measured 14.4 / 3.2 / 1.8 / 1.6; `loop_L` gives 19.3 / 6.7 / 3.3 / 2.0) compared a geometry the note does not have.
2. **Method of the note.** Resonance with C = 400 pF: L = 1/((2πf)²C) reproduces every printed L within 0.5 nH from the printed f (18.4–69 MHz). The capacitor and its connection are inside every L: that is L0.
3. **Exploratory fit (announced, not the verdict).** Width free: best 16 mm (100 mm as centreline) or 13.5 mm (as outer edge), L0 = 9.6–10.4 nH. The four plane rows then lie within ±14 %: a pass by the same lines, on two free parameters and four rows.
4. **The shorted-turn rows depend on drawings the note does not give.** The coplanar ring reads +15 to +31 %. "Rectangular loop no overlap" reads +205 % with the ring inside the loop as pre-registered; read as a ring of the loop's own footprint 1.5 mm under the trace (post hoc, after the first run) it reads −10 %, and all seven rows lie within ±15.1 %: undecided by the same lines.
5. **What the table cannot see.** With the plane term halved and width and L0 refitted, the plane rows still fit within 13 % (w = 6.5 mm); doubled, the worst row is 31 %. A law that read 2× low would pass.

Meaning:
- `kae.physics.kernels.loop_L` and the loop terms built on it: no constant changes. The table is consistent with L − L0 ∝ h for h ≪ w; it does not fix the magnitude, because the unknown trace width absorbs any constant factor.
- Evidence class of loop inductance vs plane distance stays cross-model (PEEC, FastHenry, closed forms). AN-139 is a trend anchor only ([hot-loops rule 3](../../topics/rules/power/hot-loops.md#hot-loop-rules-all-topologies)); "anchored within 1.3–2×" cannot cite it.
- The anchors that can test the magnitude have known geometry: the EPC layout matrix and the Antmicro VNA board (gap-audit checks 5 and 3), both open.

## Check 2 result: shipped-product quantiles

Run: `shipped_quantiles.py stored`, `sample`, `compute`, `report` (header of the script) [C]. Vendor-sold boards in the corpus: 1,874 of 14,597 (Adafruit 809, SparkFun 761 + 90, Olimex 116, Antmicro 98, Arduino 0).

**Verdict (data set B, all valued structures, vendor-sold boards): commutation and ESD budgets are priors; decap sits at the line; crystal and antenna behave as limits, antenna on too few structures to exclude 10 %.**

Data set B: place terms of this branch's code, 150 + 150 boards (seed 2611), 0 failed, 10 CPU-min. Intervals: 95 %, repositories resampled.

| Term | Group | Structures (boards) | Median u | p90 u | P(u > 1) | P(u > 2) | P(u > 2), credible only |
|---|---|---|---|---|---|---|---|
| commutation | vendor | 186 (68) | 1.07 | 6.19 | 53 % (43–63) | **29 % (20–39)** | 20 % (13–29) |
| commutation | rest | 161 (77) | 1.35 | 4.57 | 61 % (52–70) | 35 % (27–44) | 33 % (24–43) |
| decap | vendor | 4479 (148) | 0.82 | 1.81 | 37 % (31–42) | **9 % (6–11)** | 5 % (4–7) |
| decap | rest | 3630 (143) | 0.86 | 2.32 | 40 % (36–44) | 13 % (10–16) | 6 % (5–8) |
| antenna | vendor | 29 (19) | 0.28 | 0.49 | 0 % | **0 %** | 0 % |
| antenna | rest | 70 (20) | 0.41 | 3.00 | 20 % (3–37) | 13 % (0–24) | 13 % (0–24) |
| ESD | vendor | 1593 (86) | 0.59 | 8.90 | 35 % (26–44) | **24 % (18–29)** | 1 % (0–2) |
| ESD | rest | 1024 (87) | 0.85 | 6.76 | 44 % (34–55) | 28 % (19–37) | 6 % (3–10) |
| crystal | vendor | 126 (79) | 0.62 | 1.33 | 26 % (18–33) | **1 % (0–3)** | 1 % (0–3) |
| crystal | rest | 138 (82) | 0.58 | 1.92 | 31 % (22–41) | 9 % (4–16) | 9 % (4–16) |

Data set A: stored routed physics of the human layouts, evaluator `0443d04994d6` (kae of 2026-10-25; 14,575 human evaluations, 534 vendor-sold boards with a valued structure); last column: evaluator `7a034daa028b` (2026-10-28, pin types from schematics, 1,857 boards). It has no antenna term.

| Term | Group | Structures (boards) | P(u > 1) | P(u > 2) | P(u > 2), later evaluator |
|---|---|---|---|---|---|
| commutation | vendor | 201 (85) | 37 % (28–47) | 16 % (10–24) | 26 % (19–34) |
| commutation | rest | 1782 (1027) | 51 % (47–54) | 31 % (28–34) | 34 % (26–43) |
| decap | vendor | 1506 (157) | 27 % (24–31) | 11 % (9–13) | 16 % (14–19) |
| decap | rest | 14914 (4131) | 38 % (37–40) | 19 % (18–20) | 23 % (21–25) |
| ESD | vendor | 3253 (263) | 41 % (36–46) | 25 % (21–29) | 23 % (17–29) |
| ESD | rest | 20896 (2061) | 56 % (54–59) | 32 % (29–35) | 26 % (17–37) |
| crystal | vendor | 422 (321) | 14 % (10–18) | 3 % (2–5) | 0 % |
| crystal | rest | 3530 (2544) | 26 % (24–29) | 9 % (8–11) | 12 % (8–18) |

The two 213-board November evaluators hold 30 vendor-sold boards: too few (commutation 5 % (0–20)).

Per term:

| Term | Reading | Basis | What it means for the budget |
|---|---|---|---|
| Commutation loop | **prior** | 29 % over 2× placed (20 % credible), 16–26 % routed | `priors.hot_loop_budget` (overshoot ≤ 0.85·V_abs, 1.25·V_in rating ladder, class C_oss and t_sw) is exceeded at 2× by a fifth to a quarter of structures on sold boards: the allocation is 2–3× tight or the loop L reads high. Vendor p90 spend 9.6 nH against a 2.1 nH median allocation; p90 u = 3.0 among credible structures. |
| ESD path | **prior** as priced; limit among credible structures | 24 % over 2× placed, 23–25 % routed; 1 % (0–2) where the protector is within 15 mm | The excess is the 26 % of structures whose protector sits more than 15 mm from its connector (p90 spend 47 nH against 5.3 nH): a question of the brief's pairing, not of the 5.3 nH. |
| Decap loop | **at the line** | 9 % (6–11) placed, 11–16 % routed, 5 % credible | Undecided between limit and prior; p90 u = 1.8. |
| Crystal | **limit** | 1 % (0–3) placed, 0–3 % routed | Consistent with a real limit near 2× the 5 ppm allocation; other boards exceed it 9–12 %. |
| Antenna feed | **limit, underpowered** | 0 of 29 structures (19 boards) | Zero of 19 boards bounds the share below about 15 % only (rule of three). The earlier census (44 % over 2×, 25 structures, [kae-physics-terms](../placement/kae-physics-terms.md#results)) does not recur under today's code. |

1. **Kill rule.** On data set B it fires for commutation (difference in P(u > 2): −6 pt, −19..+7) and ESD (−4 pt, −15..+7): 150 boards a side cannot separate the groups. On data set A the same differences are −15 pt (−22..−7) and −7 pt (−12..−2), and vendor-sold boards are lower on every term at both thresholds. The groups differ; the audit carries information.
2. **No vendor carries the result.** In data set A each vendor with more than 10 structures has 15–33 % over 2× for commutation, 10–15 % for decap and 18–37 % for ESD; Antmicro supplies 61–76 % of the structures.
3. **Not done:** re-basing the commutation allocation to the shipped 90th percentile ("practice quantile", 3× today's). It changes the placer's objective and needs the sprint A/B; no setting exists yet.

Labels applied: `kae/src/kae/physics/priors.py` (module docstring) and [kae-physics-terms](../placement/kae-physics-terms.md#results) name commutation and ESD as priors that shipped boards exceed.

## Check 3 result: track heating

Run: `PYTHONPATH=kae/src python tools/research/physics/anchors/track_heating.py` [C].

**Verdict: fail on the first run (24 of 26 values), pass after the doc was corrected.** Two cells of the 3 mm table were printed one too high: 146 K (1 oz, 15 A, IPC-2152; the fit gives 145.50) and 14 K (2 oz, 10 A, IPC-2221; 13.49). [high-current](../../topics/rules/power/high-current.md#trace-width) now prints 145 and 13. No constant changed: the code's are the published ones (IPC-2221; 215.3, −1.15, −1 of the article's Eq. 1).

**Claim "IPC-2221 is conservative against IPC-2152": rejected.** IPC-2152 reads the hotter at all 10 tabulated points, by 1.37–1.85× on 1 oz and 2.15–2.90× on 2 oz.

| Sized for | Equal widths at | Above it IPC-2152 asks for | Below it |
|---|---|---|---|
| 10 K, 1 oz | 1.25 A (0.41 mm) | ×1.65 at 5 A, ×2.11 at 10 A | ×0.72 at 0.5 A |
| 40 K, 1 oz | 3.44 A (0.71 mm) | ×1.14, ×1.47 | ×0.50 |
| 10 K, 2 oz | 0.97 A (0.14 mm) | ×1.80, ×2.31 | ×0.79 |

Inner layers: IPC-2221 internal (k = 0.024) asks for 0.78 / 7.2 / 18.7 mm at 1 / 5 / 10 A (10 K, 1 oz), wider than the external-chart fit (0.28 / 4.6 / 15.2 mm).

Changes:
- `kae.excite.dc`: the comment now says where each formula is the hotter; `ipc2152_dT` added beside `ipc_dT`. The heating observer still reports IPC-2221 (an evaluator is not changed by a check).
- `kae.route.critical_physics`: `ipc2152_width`, and `track_width`, which the critical router, the intent widths and `kae.em.pnr` now size with. Setting `KAE_TRACK_HEAT` = `ipc2221` (default, widths unchanged), `ipc2152` (the fit on outer layers) or `hotter` (the wider of the two on outer layers); inner layers keep IPC-2221 internal.
- Tests (`kae/tests/test_excite_dc.py`): both formulas against the tabulated values, the crossing, the default returning `ipc2221_width` exactly.

Meaning:
- `DT_MAX` (10 K) in the DC evaluator and the IPC width in the router: for outer tracks wider than 0.41 mm the evaluator's rise is 1.4–1.9× below the IPC-2152 fit (1 oz, 3 mm, 5–15 A). The fit has no plane under the track; a plane on the far side of a 63 mil board halved the rise in Brooks and Adam's test ([high-current](../../topics/rules/power/high-current.md#trace-width)), so on boards with planes the truth lies between the two formulas.
- Evidence class: unchanged, two published fits (IPC-2221 to 1950s charts, Brooks-Adam to IPC-2152's paid chart).
- Ready for an A/B, not run: `KAE_TRACK_HEAT=hotter` against the default; cost, 1.65–2.1× wider power tracks at 5–10 A.

## Sources

- Linear Technology AN-139 (C. Kueck), Table 1 [P].
- Brooks and Adam, Signal Integrity Journal, 2019, Eq. 1 ([article](https://www.signalintegrityjournal.com/articles/1406)) [P].
