# Experiment tiers

Scope: the four experiment tiers, their board suites and CPU limits, the weekly baseline tag, the rules. Not here: how the suites are built -> [bench/README](../../../bench/README.md#experiment-tier-suites); the guard's estimate -> [kaeres](../../../tools/kaeres/README.md#tiers).
Keys: experiment tiers, tier, puzzles, sprint, ladder, canary, sprint-frontier, sprint-quality, tier guard, --tier, weekly tag, baseline tag, baseline/2026-w47, stored control, control-w47, undecided, near-miss closure, signal per CPU-hour

## Why tiers

Measured on 45 two-arm A/Bs (5,087 board pairs):

1. The costliest 5 % of boards used 62 % of the CPU and never finished clean.
2. 320 of 601 boards never differed between arms; they took 17 % of the CPU.
3. Boards chosen by past response per CPU-hour kept 56 % of the responding boards for 20 % of the CPU (held-out).

## Tiers

| Tier | Boards | Limits | Used for |
|---|---|---|---|
| **puzzles** | windows cut from human-clean boards, the human routing as known solution (not built yet) | seconds each | does the mechanism work at all; every change |
| **sprint** | `sprint-frontier.txt` (60: cheap boards that responded in past A/Bs, a fifth random) and `sprint-quality.txt` (80: small human-clean boards with a converter, rich decoupling or a crystal) | 40 CPU-h per campaign; no board whose history is over 0.5 CPU-h per method-run; queue priority 5 or higher | every experiment |
| **ladder** | `ladder.txt` (300 human-clean boards by footprints and layers, up to 400 footprints) | `--tier ladder`; needs a sprint result | confirming what passed sprint |
| **canary** | `canary.txt` (28: merit boards over 1,000 pads, human-clean boards over 400 footprints) | `--tier canary`; weekly, one deep run per board | scaling regressions, router-engine work |

Suites: `bench/suites/`. `merit-213.txt` is an archived regression set, not a tier.

## Weekly tag and stored control

- Tag: `baseline/<year>-w<week>` on main, with its Freerouting fork pin and evaluators. Current: `baseline/2026-w47` = `c2dd008a`.
- An experiment is the tag plus one change. Queued or running work is not migrated when main or the fork pin moves. Adopted changes are confirmed again at the next tag.
- Stored control: experiment `control-w<week>` (`tools/kaeres/experiments/control-tag.sh`) holds two control methods at the tag on both sprint suites, one attempt per seed, no restart wrapper, no operating facts, counted-work budgets (`KAE_BUDGET=work`), so runs are paired per board and seed. `control-w47`, seeds 0-1: bridge on the human placement `71e60a91475d`; staged place-and-route `716e9b11e0f4`.
- A sprint experiment (`kaeres sprint`) reuses the control's stored runs (`--reuse-runs`) and runs only its new arm.
- Ladder runs use the restart-wrapped recipes (`RECIPE=restart`); these need operating facts, which only the 213 merit boards have.

## Rules

1. Sprint first. Big boards run only in the canary.
2. `kaeres exp create` and `exp submit` print the estimated CPU-hours and refuse what does not fit the tier (default `sprint`); the refusal's second line says what to do.
3. Verdicts: worked, did not work, or **undecided** ([status legend](../../research/README.md#status-legend)). Report near-miss closure (boards within 5 open connections of clean) and big-board open connections separately, paired per board and seed.
4. A trimmed or waiting experiment still gets a verdict from its kept boards.
5. State lives in the experiment's folder. No session-to-session messages; `kaeq note` only when a job's owner must act.

## Commands

Procedure: [bench/suites/README.md](../../../bench/suites/README.md).

```bash
K="python3 tools/kaeres/kaeres.py"
$K sprint my-ab --base bridge --commit SHA [--set KEY=VALUE]     # one arm against the stored control, priority 5
$K exp report my-ab && $K quality my-ab --control '<control name>'
$K exp create my-ab-ladder ... --boards @bench/suites/ladder.txt --tier ladder
```

## Sources

Results index of 2026-11-20. Code: `tools/kaeres/suites.py`, `tier_guard` in `tools/kaeres/kaeres.py`.
