# PLAN: layer-oracle (sprint tier, mechanism suite: multilayer boards)

Status: code on branch `d1-layer-oracle` (`kae.route.layer_assign`, setting `net_layers`, unit tests pass). One
end-to-end smoke ran (NOTES in this folder): the fork obeys the table; kae's own last mile does not read it.
Tag: `baseline/2026-w47` plus that one change. Diagnostic only: an oracle arm never ships.

## Hypothesis

On boards with four or more copper layers the Freerouting fork loses connections because it chooses layers badly, and a
layer plan handed to it as per-class layer sets (`use_layer`, which the pinned fork already honours) removes a useful
share of the open connections. If a perfect plan (the human's) does not help through this channel, no planner will.

## Measured failure it targets

Stored s2 outputs, 45 merit boards with four or more layers: the fork puts a median 28 % of its track length (39 % on
boards over 1,000 pads) on layers the human did not use for that net, the bridge 17 % (28 %). On boards left open the
share is 0.29 (fork) and 0.22 (bridge); on finished boards 0.10 and 0.11. That contrast is board size: per pad, the
share against opens has Spearman -0.13 (fork) and +0.21 (bridge), n = 44, neither distinguishable from zero. So a plan
has reach (a third of nets would change layers), and stored data cannot say whether it helps; only this run can.
Expect 0-15 % fewer opens; a kill is a likely and useful result.

## Boards

`boards.txt` beside this file (120 candidates: four or more copper layers, DRC-clean human layout, opens under the fork
alone, history under 0.5 CPU-h, one per owner, ranked by fork opens per CPU-hour). Reach check: run the control on the
first 70; keep the boards where the control leaves at least one open connection, at most 50, in list order.

## Arms (one deterministic run each, seed 0, counted-work budget, no restart wrapper)

| Arm | Setting |
|---|---|
| control | `kae.route.cli route {input} {output} --seed 0 --time {timeout}` with `KAE_BUDGET=work`, the tag's fork pin, no restart wrapper and no operating facts (the s2 recipe needs operating facts, which these boards lack) |
| role-oracle | control + `KAE_NET_LAYERS=<dir of role tables>`: every net gets the layers on which the human board has any track |
| net-oracle | control + `KAE_NET_LAYERS=<dir of net tables>`: each net gets the layers of its own human tracks (the code adds the layers of its surface-mount pads) |

Tables, written outside the repo, one directory per arm: `tools/research/routing/net_layers.py extract HUMAN.kicad_pcb -o DIR`
(add `--roles` for the role tables). A directory holds `<board stem>.json` and `<net-name fingerprint>.json`; the code
finds the bare board's table by either. Every run's plan notes carry `layer_assign` (found, nets restricted, why not):
a run with `found: false` is a failed lookup, not a result.

## Endpoints (paired per board)

1. Open connections: mean of log((opens+1) / (control opens+1)), with a 95 % interval (primary).
2. Boards finished (zero opens), and near-miss closure (control within 5 opens of clean).
3. Vias and track length on boards both arms finish; first-pass counted work.
4. Check: track length on a layer the table disallows (`net_layers.py reach` against the human board for the
   net-oracle arm). The fork lays none; kae's last mile does not read the table and may (smoke: one plane net,
   4 % of track length). Report the share per run; over 10 % on a board, drop the board from the estimate.

## Size

Stored spread of that log ratio between two near-identical fork arms on multilayer boards with opens: SD 0.338
(`mde.py`). With 50 responding boards the smallest detectable effect is 13 % (80 % power, two-sided 5 %); with 36, 15 %.
CPU: 70 control runs + 2 x 50 oracle runs at about 0.25 CPU-h (median bridge-family history on these boards: 327 CPU-s)
= about 38 CPU-h. Priority 5.

## Deciding result and kill rule

- net-oracle lowers opens by 10 % or more and the interval excludes 0: plans pass through this engine. Build layer
  assignment (design 1, approach c); the fork's cost-field hook starts with per-class layer prices.
- role-oracle gets at least two thirds of net-oracle's gain: build stackup-role inference first (kae only, no fork change).
- net-oracle's interval lies wholly above -10 %: kill. No layer-assignment layer in front of this engine; engine effort
  goes to the second-engine trial and to pin access on puzzles.
- Interval includes both 0 and -10 %: undecided; run boards 71-120 once (about 25 CPU-h) and decide on all boards.
- Either oracle arm raises opens with an interval excluding 0: hard layer sets are too rigid; the soft form (prices)
  becomes the only test left for this question, and the hook's scalar-layer part is built to run it.

## Commands

```bash
K="python3 tools/kaeres/kaeres.py"
$K exp create layer-oracle --method CONTROL --method ROLE --method NET --boards @tools/kaeres/experiments/layer-oracle/boards.txt \
   --harness baseline/2026-w47 --kae origin/d1-layer-oracle
$K exp submit layer-oracle --limit 70 && kaeq prio 5 --owner exp-layer-oracle
$K exp report layer-oracle --baseline CONTROL      # then kaeres quality for the verdict
```
