# Experiment tiers

Scope: the four tiers an experiment passes through, their board suites and CPU limits, the weekly baseline tag, the rules. Not here: how the suites are built -> [bench/README](../../../bench/README.md#experiment-tier-suites); the guard's estimate -> [kaeres](../../../tools/kaeres/README.md#tiers).
Keys: experiment tiers, tier, puzzles, sprint, ladder, canary, sprint-frontier, sprint-quality, tier guard, --tier, weekly tag, baseline tag, baseline/2026-w47, stored control, control-w47, undecided, near-miss closure, signal per CPU-hour

## Why tiers

Measured on 45 two-arm A/Bs (5,087 board pairs):

1. The costliest 5 % of boards used 62 % of the CPU; they respond to almost every change and never finish clean.
2. 320 of 601 boards never differed between arms; they took 17 % of the CPU.
3. Boards chosen by past response per CPU-hour kept 56 % of the responding boards for 20 % of the CPU (held-out experiments, range 39-66 %).

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
- An experiment is the tag plus one change. Queued or running work is not migrated when main or the fork pin moves. An adopted change is confirmed again at the next tag.
- Stored control: experiment `control-w<week>` holds the control methods (bridge on the human placement; staged place-and-route) at the tag on both sprint suites, seeds 0-3. A sprint experiment names the control method and its new arm, with `--reuse-runs`, and runs only the new arm. Counted-work budgets (`KAE_BUDGET=work`) make stored runs comparable.

## Rules

1. Sprint first. Big boards run only in the canary.
2. `kaeres exp create` and `exp submit` print the estimated CPU-hours and refuse what does not fit the tier; the refusal's second line says what to do. `sprint` is the default tier.
3. Verdicts: worked, did not work, or **undecided** ([status legend](../../research/README.md#status-legend)). Report near-miss closure (boards within 5 open connections of clean) and big-board open connections separately, paired per board and seed.
4. A trimmed or waiting experiment still gets a verdict from the boards it kept.
5. State lives in the experiment's folder. No session-to-session messages; `kaeq note` only when a job's owner must act, written so that no reply is needed.

## Commands

```bash
K="python3 tools/kaeres/kaeres.py"
cat bench/suites/sprint-frontier.txt bench/suites/sprint-quality.txt > /tmp/sprint.txt
$K exp create my-ab --method CONTROL --method NEW --boards @/tmp/sprint.txt --reuse-runs \
   --harness baseline/2026-w47 --kae baseline/2026-w47
$K exp submit my-ab && kaeq prio 5 --owner exp-my-ab
$K exp create my-ab-ladder --method CONTROL --method NEW --boards @bench/suites/ladder.txt --tier ladder
```

## Sources

Results index of 2026-11-20 (two-arm experiments of 15-1,500 boards; boards with 3+ pairs). Code: `tools/kaeres/suites.py`, `tier_guard` in `tools/kaeres/kaeres.py`.
