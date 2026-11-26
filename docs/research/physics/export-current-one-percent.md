<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Connector exports at 1 % of their rating, and the question back (rule B', 2026-11-25)

**Status:** scorer change, measured; model against model, no hardware.
**First published:** 2026-11-25 on branch `facts/dc-loads` (code 770bb6dc, same code as 5243d589 after a docs-only rebase), against its parent c577bbaf (37dea8c0 after the rebase).
Keys: connector export current, EXPORT_SHARE, rule B, export_current question, unstated export, DC band empty, robertpheller U401, sbarabe, qubik

## 1. The rule

A connector export is a connector with a pad on a fed rail and a ground pad (`haslam/src/haslam/excite/dc.py:plan`). When the facts give no `parts.<ref>.I_A` for it:

| | Before (c577bbaf) | Now |
|---|---|---|
| DC band typical | 0.1 × rating | 0.01 × rating (`EXPORT_SHARE`) |
| DC band interval | 0.01 .. 0.5 × rating | 0.001 .. 0.1 × rating (`EXPORT_BAND`, ×/10 .. ×10) |
| heat band (sustained) | interval low end = 0.01 × rating | typical = 0.01 × rating (unchanged value) |
| question to the author | generic ledger prior (`questions[]`, first 8 in status) | `kind: "export_current"`, by name, first ([intent-file-fields](../../topics/workflow/intent-file-fields.md#a4-facts)) |

Why the band: its top (10 %) is the old typical guess, so drop and track heating are still checked at the current the scorer used until now; its bottom (0.1 %, 1 mA through a 1 A pin) covers a sensor or pull-up. A signal line through the same connector is not an export (not on a fed rail). The load is never dropped, so the DC band cannot empty by this rule: dropping unstated exports (7f856c58, rule B) emptied 15 of 210 physics-set boards ([gfix-dc-loads VERDICT](#4-sources)).

## 2. Results: the gfix-dc-loads board set

Same 12 physics-set boards and solar-small A0 as gfix-dc-loads, compiled-9867d0b operating facts and intents (schema renamed to `haslam.intent/1`), `tools/research/physics/eval_intent.sh`, `HASLAM_EM_TOL=1e-4`, 4 threads; full re-evaluations, both arms on the same base. Tiers: hard / limit / cost (mW_eq). "Questions": export questions in the new arm (high priority).

| board | old (c577bbaf) | new (1 %) | changed terms (old → new) | questions |
|---|---|---|---|---|
| 0xpolybit (control) | 0 / 0 / 28.7 | identical | — | 0 |
| adafruit magtag (copper open) | 0 / 2577.7 / 6.6 | identical | — | 2 (1) |
| buildacubesat | 0 / 32.7 / 234.6 | identical | — | 0 |
| jrsteensen | 0 / 704.6 / 358.9 | 0 / 239.8 / 234.5 | P1 loss.copper 138 → 13.8 mW; H1 heat.track 113 → 8.2 K; D3 drop 83.7 → 23.6 mV | 1 (1) |
| qubik (copper open) | 0 / 0 / 27.2 | identical, still copper open (not complete by absence) | — | 6 (5) |
| martinberlin | 0.06 / 492.8 / 517.9 | identical | — | 0 |
| robertpheller | 0 / 2139.4 / 550.0 | 0 / 2103.5 / 305.0 | P1 258 → 13.0 mW; D1 157 → 39.3 mV; H1 20.7 → 0.89 K | 1 (1) |
| sbarabe | 0 / 0 / 7.0 | 0 / 0 / 0.5 (scored) | P1 6.74 → 0.26 mW | 1 (1) |
| shazmeenshz | 0 / 17145.4 / 1888.0 | 0 / 16339.8 / 1506.0 | P1 480 → 97.9 mW; H1 93.7 → 16.4 K; D0 131 → 123 mV | 3 (3) |
| sparkfun moto-bit | 0 / 43744.7 / 1239.7 | 0 / 43689.0 / 1071.7 | P1 224 → 56.1 mW; H1 23.4 → 5.7 K; D1 92.5 → 87.4 mV | 6 (6) |
| sparkfunx qwiic-power | 0 / 3200 / 414.9 | 0 / 3200 / 413.7 | P1 10.3 → 9.1 mW; D0 10.8 → 6.3 mV | 2 (2) |
| therealeuax | no score | no score | — | 0 |
| solar-small A0 (own facts) | 0 / 7787.8 / 61.8 | identical | — (no unstated export) | 0 |

- No board loses its score or completeness; sbarabe keeps its score (rule B lost it), qubik stays copper open (rule B made it complete with an empty DC band).
- Only DC-band terms move (loss.copper, drop.rail, heat.track), all down except four sub-0.1 mV drops of other rails that move a few µV either way (robertpheller D0 63 → 98 µV, moto-bit D2/D3).
- **Heat band unchanged on every board:** `part_power_W` and every temp.junction term identical in both arms (the sustained export current is 1 % of the rating in both).
- **robertpheller U401:** 32.5 mW in both arms. Rule B heated it at 510 mW (Tj 44 → 100 C): its rail /E5V, fed by cell:buck:U401, had no load left, so `heat.evaluate` took the cell's ledger low end (`pi.lo`). With 1 % the rail keeps CN7's export (50 mA of a 5 A rating, the question's `might_differ`: only load, power connector, cell-fed), so the cell current follows its loads. The no-load branch itself is unchanged: a cell rail without any load is still heated at its ledger's low end. (Since fixed: such a cell idles at V_in I_q, [heat-noload-rail](heat-noload-rail.md).)
- Cost: both arms 26 evaluations, about 4.8 CPU-h.

## 3. The question back

`dc.export_questions(plan)` → `evaluate`'s `questions[]` entries (`kind: "export_current"`, `ref`, `rail`, `rating_A`, `assumed_A`, `band_A`, `field: parts.<ref>.I_A`, `also: parts.<ref>.I_sustained_A`, `might_differ`, `priority`, `ask`) → `haslam.intent status` `Q-export-<ref>-<rail>` with a JSON `schema` (number or [lo, hi]), high priority first. Example (sbarabe):

```json
{"id": "Q-export-J1-VOUT", "kind": "export_current", "field": "parts.J1.I_A", "assumed_A": 0.03, "rating_A": 3.0,
 "band_A": [0.003, 0.3], "priority": "high",
 "might_differ": ["it is its rail's only load: the assumption is the rail's whole current", "a 3 A connector is likely a power connector"],
 "ask": "J1 exports VOUT off the board and the facts do not state its current; assumed 30 mA (1 % of its 3 A rating). What does it carry? State parts.J1.I_A in A (a value or [lo, hi]; I_sustained_A for the typical draw), or 0 if only signals or nothing draw from it."}
```

Non-blocking: the status's tiers do not depend on the questions (test `test_an_assumed_connector_export_is_asked_for_by_name_without_changing_the_score`).

## 4. Sources

- Runs: `$HOME/haslam-baselines/experiments/facts-ruleb-1pct/runs/<board>/{old,new}.{ev,status}.json`, the batch files and the table script `table.py` beside them (adapted from gfix-dc-loads' `rescore.py`); haslamq owners `facts-ruleb-old`, `facts-ruleb-new`.
- gfix-dc-loads VERDICT (rule A, rule B and the options): `$HOME/haslam-baselines/experiments/gfix-dc-loads/VERDICT.md`, section "B: why not as is, and the options", option 2.
