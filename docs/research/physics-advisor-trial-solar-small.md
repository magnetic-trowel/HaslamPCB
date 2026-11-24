<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Physics advisor trial: solar-small L3b, an LLM commanding through the session loop

2026-11-24, branch `physics-advisor` (advisor v2, `kae.intent.session`), evaluator: the facts/mesh/DC scratch
evaluator plus this branch (not pushed). Status: **one trial, two rounds**; the commanding LLM was the agent that
wrote the code, so this log tests the protocol's mechanics and the advice's content, not an independent reader.

Scope: what the advisor said on solar-small's best layout run, what the LLM decided and why, what kae verified, and
the friction found. Not here: the protocol -> [physics-advisor-protocol](physics-advisor-protocol.md); the
advisor's estimates and their validation -> [physics-advisor](physics-advisor.md).
Keys: advisor trial, solar-small L3b, transcript, friction, C312, U302 decoupling, LTC3130 output capacitance,
VCC_CHG, supply pin noise

## T1. Board and starting status

Board `solar-fb-runs/L3b/A0/s1` (branch `solar-small-fb`'s schematic fix: R120 249 k + C117 8.2 pF, R320 100 k +
C307; kae placement; 0 DRC opens), intent `solar-small2/eval-intent.json`. Evaluation: 8 min, 4 threads.
Status: total 199.3 mW_eq (copper loss only), **every term met** (T-FB 0.875 mV / 5, T-FB3 1.015 mV / 16).
Known open issues (from the design agent): LTC3130 output capacitance below its datasheet minimum; C312 (U302's
VDD capacitor) far from U302; +3V3 noise at U302 "implausible" on the A0 board.

## T2. Transcript

| Step | Command (abridged) | kae said | LLM decided, and why |
|---|---|---|---|
| 0 | `open` (first version) | only `datasheet.check` COUT; nothing about U302 | — friction F1: U302's +3V3 noise is 1.32 V here, under the implausible cap (50 % of 3.33 V) and priced by no term, so v2 ignored it. **Fixed in the session**: supply pins whose noise exceeds 10 % of their rail are advised on (`SUPPLY_SUSPECT`) |
| 1 | `open` (fixed) | status flags `supply:U302:+3V3` 1.32 V and `supply:U101:/CHG/VCC_CHG` 0.54 V. A1 `move.part`: C312 (100 nF) to U302.15/U302.14, now 46 mm away (nearest +3V3 capacitor C305 at 26 mm); needs a solve; priced bound 0. A2 `datasheet.check`: SYS at 13.5 V has C115 + C114 = 2 × 10 µF 35 V X5R 1206 → 8.05 µF effective (bias factor 0.40); asks `facts.parts.U101.cout_min_eff_F` | — |
| 2 | `answer --field facts.parts.U101.cout_min_eff_F --value 20u --source "LTC3130 DS Table 3 p.23"` | D1 recorded; re-advised at once: "U101 needs 20 µF effective; kae counts 8.05 µF: add 11.95 µF"; proposes 3 × 10 µF 35 V X5R 1206 beside C115 = 20.12 µF (model) | the design runs Burst Mode at 13.5 V with the feed-forward capacitor, the Table 3 column that asks 20 µF |
| 3 | `solve --id A1` (budget 1/2; 7 min, 4 threads, every aggressor) | priced terms unchanged (T-FB 0.858, T-FB3 1.002 mV); total 199.3 → 199.3 | — friction F2: the solve's report listed no unpriced change (it only looked at implausible observations). **Fixed**: solves and verify report supply-pin moves |
| 4 | `decide --id A1 --adopt --form relation --reason "C312 is U302's VDD decoupling capacitor …"` | D2; relation `adv-C312-U302 near C312 U302.15 tight strong` written to `intent.relations`; edit `move:C312:U302.15:U302.14` pending | the capacitor's job is U302's supply loop; the score cannot price it, the 1.32 V flag says it is broken |
| 5 | `decide --id A2 --adopt --form design --reason "… zero margin on a proxy model; check the vendor curve"` | D3; 3 × `add:C:C115.1:C115.2:10uF:1206:X5R` pending; prediction `needs-solve` (the capacitors carry the cell's current) | take kae's count, flag the vendor DC-bias curve check — friction F3: the LLM wanted 4 for margin and the CLI cannot change a count |
| 6 | `verify` (one full evaluation, 8 min) | total 199.3 → 199.3; T-FB 0.875 → 1.002 mV; T-FB3 1.015 → 0.475 mV; T-OS301 121.6 → 95.9 mV; unpriced: **supply:U302:+3V3 1.32 V → 28.6 mV**, supply:U301:SYS 0.141 → 0.096 V, **supply:U201:SYS 0.119 → 0.226 V**; round 2 opens: COUT 20.12 µF "met" | the C312 relation does what it should; U201's SYS noise doubling is a side effect of one of the round's two edits (F4) |
| 7 | `show --refresh` (round 2) | A1 `node.shunt_c`: 470 nF from U101.7 (VCC) to U101.17 (EP): VCC_CHG noise 0.545 → 0.011 V (first order); priced total unchanged | — friction F5: a first version swept only to 100 nF and ranked by the priced total (zero), so it called the best value "no effect". **Fixed**: an unpriced flagged pin ranks by its own noise, swept to 10 µF |
| 8 | `decide --id A1 --decline --reason "VCC is the LTC3130 gate-drive LDO; C113 4.7 µF already 5 mm away; hold C113 at the pin instead"` | D4 recorded; key suppressed in later rounds | the right fix is the existing 4.7 µF at the pin, which kae did not offer (F6) |

Session files: `S/intent.json` generation 6 (from 1), decisions D1–D4, one relation; `S/log.jsonl` 9 records;
`S/rounds/1/verify/report.json`.

## T3. What the trial shows

1. The loop works end to end with files only: a fact answered, a solve spent, a relation and a design edit adopted,
   one full verify, a decline remembered. Each decision carries the LLM's reason, kae's prediction and the verify.
2. All three open issues surfaced, two only after fixes made during the trial (F1, F5). Both had the same cause: the
   advisor followed the priced total, and on a board where every term is met the remaining problems are unpriced.
3. The relation is not yet used by a layout: kae's placer on this branch does not read `intent.relations` (branch
   `intent-relations`); the move was verified as a zero-copper what-if only.

## T4. Friction and next improvements

| # | Friction | Next improvement |
|---|---|---|
| F1 | unpriced but large supply noise was invisible | done: `SUPPLY_SUSPECT`; better: the intent's defaults add a report term per IC supply pin, so it is priced at a commander-set rate |
| F2 | a solve reported only priced terms | done: `unpriced_moves` in solve and verify |
| F3 | a proposed part count (3 × 10 µF) cannot be changed in `decide` | `--count`, or `--edit` to give the commander's own edit spec, re-predicted by kae |
| F4 | verify measures a round's edits together; U201's SYS noise doubled and the log cannot say which edit did it | an optional per-edit targeted solve inside verify when a round has several edits (costs one solve each) |
| F5 | flagged pins were ranked by the priced total (zero) | done: own-noise ranking, decaps to 10 µF |
| F6 | `move.part` covers decaps of core-current aggressors only; VCC's own 4.7 µF (C113, 5 mm) was not offered | move candidates for every flagged supply pin, including an existing capacitor beyond 3 mm, as a relation |
| F7 | the return-pad note says "no priced term moves" for an unpriced pin | print the own observer's value per pad |
| F8 | the decline in step 8 wanted to adopt an alternative (C113 near U101.7) not in the options | `decide --relation near:C113:U101.7:tight` written by the LLM, verified as a `move:` what-if |
| F9 | the LLM read about 1.2 k tokens per round; each command rebuilds the circuit (5–9 s) | a resident server (option D) once the command set settles |
