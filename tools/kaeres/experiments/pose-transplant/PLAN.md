<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Pose transplant: which placement decision costs kae its routing (diagnostic plan)

Written 2026-11-20, before any run. Not submitted. Diagnostic only: the human's poses are an oracle that
tells us where kae's placement loses; no arm is a method and none is ever a candidate for main.

## Question and hypothesis
kae placements route worse than the human placements of the same boards (more open connections after the same
bridge). Which tier of placement decisions carries that gap? Hypothesis: the floorplan of the big parts
(ICs with many pads and the connectors) carries the human advantage, not the passives. If so, arm B (big parts
held) recovers most of the gap between K and H, and arm P (passives held, kae floorplan) recovers little.

## Arms (one setting each: the tier of parts held at their input pose)
All arms start from the prepared task board (the human placement, routing stripped) and run the stored staged
control (`716e9b11e0f4`: `kae.joint.cli run --max-iters 0 --no-modules`, place then the bridge) through
`tools/research/diagnostics/pose_tiers.py run-arm`, which passes the tier to the placer as fixed parts
(`kae.place.pipeline.place(fixed=...)`, the mechanism of `kae place --fix`). Same budget as the control:
counted work, 3600 s x sqrt(footprints/40) / 4, capped at 57600 s, `KAE_WORKERS=1`, KiCad 2 threads,
Freerouting fork 37b1a8b. Parts locked in the input stay put in every arm, as in the control.

A part's size is its terminal count (distinct non-empty pad numbers over copper pads; split paste pads count
once, NPTH holes not at all). Connectors are those `kae place --fix-class connectors` holds.

| Arm | `--tier` | Held at the human pose | kae places |
|---|---|---|---|
| K | `none` | nothing (control; the placer is not touched) | everything |
| B | `big` | parts with >= 16 terminals, and connectors | the rest |
| M | `mid` | every part except non-connector 2-terminal parts | only 2-terminal parts |
| P | `small` | non-connector 2-terminal parts (M's complement) | every other part |
| H | `all` | every part | nothing (the bridge on the human placement) |

Tiers nest (none < big < mid < all); P mirrors M. In P the held passives may block kae's floorplan: the
placer treats them as fixed obstacles and does not move them, so an illegal or refused P placement is a finding,
reported per board (the placement's `legal` flag in the joint report, iteration 0 `stages.place.legal`), not
repaired. H routes the human placement through the same placer call (nothing movable) and the same route stage,
so all five arms differ only in what the placer was allowed to move; the stored `control-w47` bridge
(`71e60a91475d`) is a cross-check of H.

`pose_tiers.py refs BOARD --tier T` prints the held refs; `pose_tiers.py pose-diff IN OUT --tier T` checks that
no held part moved (exit 1 if one did).

## Registration (exact lines; `K="python3 tools/kaeres/kaeres.py"`, code at commit 859397c8)

```bash
TPL='cp -r $HOME/.cache/kaebench/numba-default-c2dd008 numba 2>/dev/null; env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$HOME/.cache/kaebench/kae-freerouting-fork-37b1a8b/bin/freerouting KAE_FREEROUTING=$HOME/.cache/kaebench/kae-freerouting-fork-37b1a8b/bin/freerouting {py:kae} {code:kae}/tools/research/diagnostics/pose_tiers.py run-arm {input} {output} --seed {attempt} --time $(( {timeout} / 4 ))'
P='--kind joint-fixed --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --kicad-threads 2 --code kae=https://github.com/magnetic-trowel/kicad-auto-everything@859397c8'
for arm in K:none B:big M:mid P:small H:all; do
  $K method add "pose-transplant ${arm%%:*} tier=${arm#*:} 859397c" $P \
     --command "$TPL --tier ${arm#*:}" \
     --description "pose-transplant diagnostic arm ${arm%%:*}: staged control with tier ${arm#*:} held at the human poses (oracle, not a method)"
done
$K exp create pose-transplant --method "pose-transplant K tier=none 859397c" --method "pose-transplant B tier=big 859397c" \
   --method "pose-transplant M tier=mid 859397c" --method "pose-transplant P tier=small 859397c" \
   --method "pose-transplant H tier=all 859397c" --boards @BOARDS --attempts 3 \
   --description "pose-transplant diagnostic, see PLAN.md"
```

Arm K re-runs the control inside this experiment (same day, same host load) instead of reusing `control-w47`:
the decision rule below needs K and H re-run side by side.

## Boards
The boards where kae's staged placement routes worse than the human's in `control-w47` (more open connections,
paired per seed), listed by the design session in `transplant_boards.txt` when it exists; else the sprint suites
(`sprint-frontier.txt` + `sprint-quality.txt`) restricted to those boards. 3 seeds (attempts 0-2).

## Endpoints
- Primary: open connections (unconnected items in KiCad's DRC of the routed board), paired per board and seed,
  for each arm against K and against H. Gap closed by arm X = (opens_K - opens_X) / (opens_K - opens_H), on boards
  where K is worse than H; reported with a bootstrap interval over boards.
- Near-miss closure (boards with 1-5 opens under K that close under X) separately from big-board opens.
- Placement legality per arm (count of boards where the arm's placement is illegal or refused), P especially.
- Read the per-type errors in `drc.json` before concluding anything.

## Decision rule (diagnostic, no kill rule)
- K not worse than H on the re-run: the gap was noise; stop.
- B closes most of the gap and P little: the big-part floorplan carries it (hypothesis holds); work goes to
  kae's big-part floorplan.
- P closes most and B little: the passives carry it; work goes to passive placement / escapes.
- M closes it but neither B nor P alone: the interaction of mid-size parts (SOT, small ICs) matters; split the
  mid tier next.
Mixed per-board results get a per-board look, not a verdict.

## Budget
5 arms x 3 seeds x boards x the control's per-board budget. Estimate the CPU-hours from `control-w47`'s staged
runs on the chosen boards before submitting; the coordinator decides.
