<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Physics advisor protocol: how haslam and its commanding LLM decide together

2026-11-24, branch `physics-advisor` (advisor v2 + `haslam.intent.session`). Status: **prototype, trialled once**
(solar-small L3b, [trial log](physics-advisor-trial-solar-small.md)).

Scope: the loop in which haslam proposes physics changes, the commanding LLM decides, and haslam verifies, and how a
decision becomes intent (relations, facts, design edits) that the next layout run uses. Not here: what the advisor
estimates and how well -> [physics-advisor](physics-advisor.md); relations as placer input ->
`docs/topics/llm/llm-relations-input.md` (branch `relations-input`); the intent's terms and status ->
[intent-driven-objectives](../topics/architecture/intent-driven-objectives.md).
Keys: advice protocol, haslam.intent.session, propose decide verify, decisions, decision record, advice key,
options, form, design edit, relation, fact answer, needs, datasheet field, solve budget, verify, round,
status diff, declined advice, LLM-commanded, traceable decision

## P1. Constraints from the project

| Rule | What it forces on the protocol |
|---|---|
| LLM-commanded, not LLM-dependent | haslam never calls a model; every step is a command a human could type, with files in and out |
| Every decision traceable | each decision is a record in the intent: who, which advice, the reason and source, haslam's prediction, haslam's verification |
| Only genuine trade-offs are surfaced | an entry exists only when something is given up; it carries the numbers of both sides and the question that decides |
| Infeasibility comes with relaxations | an entry that cannot meet a term says its floor (no value gets below it) and what would |
| Datasheets are the LLM's | haslam asks for a named field (`needs`), never guesses a datasheet value; an answer is a fact with its source |

## P2. Options compared

| Option | For | Against | Verdict |
|---|---|---|---|
| A. advice inside `haslam.intent status` (v1) | stateless; one command | no record of decisions; declined advice comes back every run; the LLM writes `verify` commands and diffs by hand | kept as the read-only view |
| B. advice + hand-edited intent | no new tool | the LLM types JSON (shape errors), predictions are not attached to decisions, nothing links a decision to its check | rejected |
| **C. a session CLI: propose → decide → verify** | files are the state and the trace; haslam writes the records (the LLM supplies only choice, value and reason); budgets; declines are remembered by key | a folder of state; each command rebuilds the circuit (≈ 8 s on solar-small) | **built** |
| D. a resident tool server (MCP) | no rebuild per call; typed tool schemas | daemon state is harder to trace and replay | later, as a thin layer over C |
| E. haslam adopts what the score prefers | no LLM turn | violates "the LLM decides trade-offs"; the score does not see loop stability, BOM or start-up | rejected |

## P3. The advice entry: the contract the LLM reads

One JSON object per entry (`haslam.intent.advise.advise`), text form for the LLM (`advice_lines`):

| Field | Meaning |
|---|---|
| `id`, `key` | `A3` is round-local; `coupling_c.series_r:C117` is stable across rounds (declines and adoptions match on it) |
| `kind` | the remedy class ([physics-advisor](physics-advisor.md#advice-kinds-v2)) |
| `mechanism`, `remedy` | why the harm happens (the coupling path) and the change, in part and pad names |
| `edit` | the change as circuit edits (`add:C:PA:PB:1nF`, `remove:REF`, `series:REF:249k`, `value:REF:8.2pF`, `move:REF:PA:PB`), the grammar `haslam.excite.evaluate --edit` runs |
| `estimate` | terms moved (value, met, cost before/after), status total before/after, `delta`; `unpriced`: flagged observations it moves |
| `confidence.level` | `exact`, `first-order`, `partial`, `needs-solve` (the edit carries an aggressor's current), `solved`, `scaled`, `estimate` |
| `bound` | for `needs-solve`: the most it can buy (the aggressor's priced cost), so it ranks before it is solved |
| `curve`, `return_pads` | the swept values and every return pad tried, with results: the LLM can pick another value or pad |
| `decide` | `question`, `tradeoff` (numbers: zero, pole, corner, phase lead, quiescent current, shortfall), `needs` (datasheet fields: `facts.parts.U101.f_c_Hz` with what to look up, or `known` from the facts) |
| `risks` | what the score does not price (E-field pickup into a raised impedance, copper of a placed part, loop stability) |
| `options` | the forms the LLM can take it in: `design`, `relation`, `fact`, `layout`, `decline` |
| `verify` | the full-solve command for the same edit |

## P4. The loop

```
 haslam.intent.session open S --board B --eval E --intent I        round 1: advice on E (no solves)
   │  LLM reads ≤ 8 entries (≈ 1.5 k tokens)
   ├─ answer S --field facts.parts.U101.cout_min_eff_F --value 20u --source "DS Table 3"
   │      fact written; advice re-run at once (cheap); changed entries printed
   ├─ solve S --id A7            budgeted (2/round): targeted re-solve of the aggressor the edit touches
   ├─ decide S --id A2 --adopt [--value 249k] --reason "DS p.17: RFF ≈ R1/20" --source "LTC3130 DS"
   │      decision record (+ relation) in S/intent.json; haslam re-predicts the exact value chosen
   ├─ decide S --id A5 --decline --reason "C117 is the DS feed-forward cap; keep it"
   └─ verify S                    one full evaluation of B with every adopted edit (zero copper)
          status diff, each decision's prediction vs the solve, round 2 advice on the verified evaluation
```

State: `S/session.json` (board, current evaluation, verified and pending edits, budgets), `S/intent.json` (the working
intent; `generation` counts decisions), `S/rounds/N/advice.json`, `S/rounds/N/verify/{excite,report}.json`,
`S/log.jsonl` (every command with inputs and outputs). Replaying the log's commands reproduces the session.

Budgets (per round, `open --solves --show`): first-order what-ifs are unlimited (milliseconds; already inside the
advice); targeted re-solves 2 (solar-small: about 2 minutes each, 2 threads); one verify (a full evaluation, ~8 min
at 4 threads); 8 entries shown, the rest by id. A budget is a turn's cost cap, not a correctness limit: an exhausted
solve budget says so and points at `verify`.

## P5. The decision record

```json
{"id": "D2", "round": 1, "advice": "A2", "key": "coupling_c.series_r:C117", "kind": "coupling_c.series_r",
 "choice": "adopt", "form": "design", "edit": ["series:C117:249k"], "value": "249k",
 "reason": "LTC3130 DS p.17 gives RFF ~ R1/20 = 249k; zero 1.45 kHz kept, lead capped at 78 kHz", "source": "LTC3130 DS p.17",
 "predicted": {"total_after": 1027.4, "terms": {"T-FB": "2.867 mV"}, "confidence": "first-order"},
 "verified": {"total_after": 1027.3, "terms": {"T-FB": "2.867 mV"}, "eval": "S/rounds/1/verify/excite.json"},
 "status": "verified", "by": "llm", "at": "2026-11-24T..."}
```

`intent.decisions` is ignored by the scorer (it prices terms only); `haslam.intent.objective.load` accepts it. A decline
suppresses its key in later rounds unless the entry's estimated gain has doubled (then it comes back with `reraised`
and the earlier reason).

## P6. How a decision reaches the next layout run

| Form | Written to | Who applies it | Next layout run |
|---|---|---|---|
| `fact` | `intent.facts.*` with its source in `why` | haslam (`haslam.intent.facts` → brief) | every consumer reads the same fact (placer terms, router, evaluator) |
| `relation` | `intent.relations[]` (`near`, `tight`, `strong`, `why` with the decision id) | haslam.place, once it reads intent relations (branch `intent-relations`) | the placer holds the part at its pin; until then the session verifies it as a `move:` what-if |
| `design` | the decision's `edit` (what-if until the board carries it) | the LLM, in its schematic (haslamsynth) | the new board has the part; the edit leaves the session's list when the board carries it |
| `layout` | a note, or a relation the LLM writes (`keep_away`) | haslam.place / haslam.route by their own prices | — |
| `decline` | the decision with its reason | — | suppresses the advice |

A new layout starts a new session on the new board with the same intent: its decisions travel with it, so adopted
keys are not re-proposed and declined ones stay declined.

## P7. Open questions

- Per-decision attribution: `verify` solves all of a round's edits together; a decision's own share is known only when
  it is the round's one edit (or from its first-order prediction). A per-edit targeted solve is a budget choice.
- When does a design edit leave the what-if list? Today the LLM opens a new session on the new board; matching an
  edit to the board (a part on those pads with that value) would let haslam mark it `in-board` itself.
- Relations from advice carry `strength: strong`; whether the placer meets them, and what it gives up, is the
  `intent-relations` branch's status rows.
