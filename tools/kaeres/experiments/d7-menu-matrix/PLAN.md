<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: d7-menu-matrix (sprint tier)

Four sprint campaigns that together form one table: `d7-mm-neck`, `d7-mm-planes`, `d7-mm-margin`, `d7-mm-neck-staged`.
Stage 0 scripts and numbers: `tools/research/commander/stage0/`.

## Hypothesis

The loop-back menu (`kae.commander.menu`, branch `d7-loopback-menu`) names, from the control's own failure report, the
knob that will help that board. If true, (1) some board-by-knob cells improve on both seeds far more often than seed
noise produces, and (2) a rule that applies the menu's top item beats spending the same second invocation on another seed.

Expected result: **no**. Stored A/Bs say per-board selection among today's knobs is worth -2.1 % opens (95 % CI -5.1 to
+0.7, 369 boards), no more than one global setting. The experiment is run to close that question on menu-chosen knobs
with deterministic counted-work runs, and because its table gives the repeat-checked labels that the LLM-versus-table
test needs. No LLM and no API call is involved.

## The measured failure it targets

When opens persist, kae can only repair or re-seed. On a fixed placement about half of the open nets recur on every
seed (stage 0), so a second seed re-fails on the same nets.

## Suite, control, seeds

`sprint-frontier.txt` + `sprint-quality.txt`, seeds 0 and 1, stored control `control-w47` at tag `baseline/2026-w47`
(c2dd008a). These knobs act on any board with opens, so the general sprint suites are the right ones; no mechanism suite.

## Arms (one change each; all are existing settings, no code change, commit = the tag)

```bash
K="python3 tools/kaeres/kaeres.py"
$K sprint d7-mm-neck        --base bridge --commit c2dd008a --set neckdown=true
$K sprint d7-mm-planes      --base bridge --commit c2dd008a --set planes=allow
$K sprint d7-mm-margin      --base staged --commit c2dd008a --set place_margin=-1
$K sprint d7-mm-neck-staged --base staged --commit c2dd008a --set bridge.neckdown=true
```

These are the knobs the menu proposes on stored reports (neck-down on 23 of 84 open boards, placement room on 12-21,
planes on 1) that the scorer allows. `planes=allow` is priced: it gives up reference planes; report it as such.

Before submitting, check on three boards:
1. The staged base accepts `--set bridge.neckdown=true` and the bridge base `--set neckdown=true` (the route CLI does not
   validate keys: confirm `opts.neckdown` is true in the arm's report, or the arm is a silent copy of the control).
2. The control's stored run holds a report with a `blocked` diagnosis. If it does not, compute it for each control run
   with opens: `python -m kae.route.blocked OUTPUT INPUT --time 120` (single core, about 2 min per board).
3. Reach: drop boards that are clean under the control on both seeds from the cell analysis (they stay in the quality rows).

## Endpoints

Per arm, from `kaeres exp report` and `kaeres quality NAME --control '<control name>'`, paired per board and seed:
- log((opens + 1) ratio) on boards open under the control; near-miss closure (control 1-5 opens); quality rows on boards both finish.

Across arms (the matrix), computed by a replay script from the stored scores, no further runs:
- **Repeat cells**: board-by-knob cells where opens fall by at least max(2, 20 %) or the board becomes clean, on both seeds.
- **Rules by replay**: per board, the menu built from the control's seed-0 report picks a knob; its result is that knob's
  stored seed-1 run (the control's seed-1 run if the menu's top item is "more effort"). **Null by replay**: the control's seed-1 run.
  Both are then "best of seed-0 control and one more invocation". Also report hindsight (best knob per board) as the ceiling.
- **Targeting**: each knob's effect on boards where the menu ranks it first against boards where it does not.

## Deciding result

- Noise reference: on two seeds of one recipe the label rule fires on 9.2 % of boards with opens, so about 0.85 % of
  cells repeat by chance if seeds are independent. Calibrate this on the control's own seed pairs across experiments
  before reading the result. With about 25 open boards and 4 knobs (100 cells), **5 or more repeat cells** is p < 0.01.
- Per arm the design detects a 14 % change in (opens + 1) at 25 open boards and two seeds (between-seed SD of the log
  ratio 0.391 on the frontier boards' stored bridge runs). Smaller effects are "undecided", not "no effect".
- **Passes** if there are 5 or more repeat cells and rules-by-replay has fewer opens than null-by-replay with a CI
  excluding 0. Then: build the closed-loop commander test (K = 4) on the ladder, and price the LLM arm on the matrix labels.

## Kill rule

Fewer than 5 repeat cells, and rules-by-replay not better than null-by-replay: today's knobs have no board-specific
authority. Stop commander work on existing knobs; the next step is the relations oracle (`d7-relations-oracle`), which
tests knobs that do not exist yet. Stop any arm early if its first 15 boards are identical to the control on both seeds.

## CPU-hours

Each campaign must pass the sprint command's own limit (40 CPU-h); bridge arms are about 10-15 CPU-h, staged arms about
15-20. About 60 CPU-h in all. Priority 5. Run the four at the same time.

## Outputs

Per campaign: the verdict (better, worse, undecided) in its folder. Shared: `d7-menu-matrix/MATRIX.md` with the cell
table, the replay results, and `labels.jsonl` (board, seed, control report path, knob, delta) for the diagnosis test.
