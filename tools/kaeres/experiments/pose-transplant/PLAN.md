<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: pose-transplant (which placement decision binds)

Status: ready for sprint; diagnostic (human poses are an oracle, never a method). Tag `baseline/2026-w47`.
Code: branch `d5-pose-transplant`, commit `1b7c9ffc` (`kae.place.pose_tiers`, the `pose_tier` setting of `kae.joint.stages`,
and `tools/research/diagnostics/pose_tiers.py` for `refs`, `run-arm` and `pose-diff`).

## Hypothesis
kae's placements route worse than the human placement under the same router (s2-merit213: 1,434 vs 1,179 opens on 205
boards, worse on 47, better on 10; first 6 board-seeds of `control-w47`: 85 vs 30). One tier of parts carries most of
that gap. H1: the big-part floorplan (parts with 16 or more pads, and connectors). H2: the 2-pad parts (crowding).
H3: neither alone (interaction or mid-size parts).

## Mechanism under test
The placement to routing boundary, split by part tier. All arms use the stored control's staged recipe (place, then
bridge; counted-work budget 900 s x sqrt(footprints/40); seeds paired with the control).

## Arms (one change each: the set of parts held at the human pose)
| Arm | Held at human pose | kae places | Source |
|---|---|---|---|
| K | nothing beyond the control's defaults | all | stored `control-w47` staged (716e9b11e0f4) |
| B | parts with >= 16 pads, connectors | the rest | new |
| M | parts with >= 3 pads | 2-pad parts | new |
| H | every part | nothing | stored `control-w47` bridge (71e60a91475d) |
| P (second sprint only) | 2-pad parts | parts with >= 3 pads | new |

Parts with fewer than 2 pads (holes, test points, fiducials) and anything the control already holds follow the
control's defaults in every arm; the report lists them. Tier sizes on list A (`transplant_tiers.py`): arm B holds a
median of 4 parts carrying 47 % of the pads; the mid tier adds a median of 4 parts.

## Boards
Sprint suites only (the control's 140 boards). List A (fixed now, from pre-tag stored runs, independent of the control's
seeds): the 22 boards in `boards.txt` (this folder) with staged/joint minus bridge >= 0.3 in mean log1p(opens), plus its
9 neutral boards as an A/A check. List B (fixed when the control finishes): control boards not in list A where
K - H >= 2 opens on SEED 0; they are analysed on SEED 1 only (selection on one seed, estimate on the other, so the
stored K runs are not favoured by regression to the mean). Cap the two lists at 36 boards, smallest footprint count
first. No board over 0.5 CPU-h per run.

## Endpoints
1. Primary: share of the K-to-H gap closed per rung, in log1p(opens), paired per board and seed:
   g_B = (K - B) / (K - H), g_M = (K - M) / (K - H), with owner-bootstrap intervals.
2. Near-miss closure: boards at 0 opens, and boards within 5 opens of clean, per arm.
3. Quality rows (`kaeres quality`): track length and vias against the human, on boards every arm finishes.
4. From the connection ledger (`tools/kaeres/ledger.py`): cause class and end-part size of the opens each rung removes.

## Deciding result
- g_B >= 0.5 with the interval above 0.25: the floorplan binds. Build floorplan-level search and a commander input for
  big-part poses (designs 2 and 7); passives-crowding terms are second.
- g_B <= 0.25 and g_M >= 0.6: mid-size parts bind (3-15 pads): pin-out-driven pose for mid parts.
- g_M <= 0.4: the 2-pad parts bind (kae's passives crowd pads and corridors): satisficing physics and whitespace
  terms first (design 3). Run arm P to confirm.
- K - H not above 0 on the re-run boards (interval includes 0): the gap was selection or noise; stop.

## Size and power
36 boards x 2 new arms x 2 seeds = 144 runs at about 0.27 CPU-h (first control runs: 0.22-0.45 CPU-h on boards with
opens, 0.02-0.11 on clean ones) = about 39 CPU-h. Seed variance of log1p(opens) for a placement-changing arm on
frontier boards 0.147, board-by-arm 0.023 (`var_results.md`): on 30 responding boards x 2 seeds the standard error of an
arm difference is 0.075 and the smallest detectable difference 0.21 log1p (about 19 % of 1 + opens). The expected K - H
gap on list A is about 1.0 log1p, so a rung carrying a fifth of the gap is visible.

## Kill rule
Diagnostic, so none on the idea. Stop the campaign early if after list A's seed 0 the held parts are not at their input
poses in arm B or M (pose diff fails), or more than a quarter of arm runs end with an illegal placement.

## Arm settings (as built)
Every new arm is the stored staged control (`716e9b11e0f4`: `kae.joint.cli run --max-iters 0 --no-modules`) plus one
setting, `--set pose_tier=TIER`. `kae.joint.stages` then passes the tier's parts to the placer as fixed parts
(`kae.place.pipeline.place(fixed=...)`, the mechanism of `kae place --fix`) and keeps them locked. Without the setting
the placer gets no fixed parts: K is the control unchanged.

| Arm | Setting | Held (`kae.place.pose_tiers`; size = distinct numbered copper pads) |
|---|---|---|
| K | none (stored control) | nothing |
| B | `--set pose_tier=big` | >= 16 pads, or a connector (`kae place --fix-class connectors`' rule) |
| M | `--set pose_tier=mid` | B's parts plus every part with >= 3 pads (a 2-pad connector stays held: tiers nest) |
| P | `--set pose_tier=small` | non-connector 2-pad parts |
| H | `--set pose_tier=all` (or the stored bridge `71e60a91475d`) | every part |

Parts with fewer than 2 pads are held only in H. `--set pose_big_pads=N` moves the big threshold (default 16).
Check a board's tiers with `python3 tools/research/diagnostics/pose_tiers.py refs BOARD --tier big`, and that no held
part moved with `pose_tiers.py pose-diff INPUT OUTPUT --tier big` (exit 1 if one did).

## Run
```bash
K="python3 tools/kaeres/kaeres.py"
$K sprint pose-transplant-b --base staged --commit 1b7c9ffc --set pose_tier=big    # arm B
$K sprint pose-transplant-m --base staged --commit 1b7c9ffc --set pose_tier=mid    # arm M
$K sprint pose-transplant-p --base staged --commit 1b7c9ffc --set pose_tier=small  # arm P (second sprint only)
```
The sprint command runs on the sprint suites; for the two board lists above register the arm the same way and create
the experiment by hand on them (`bench/suites/README.md`, "By hand": `kaeres exp create NAME --method 716e9b11e0f4
--method <arm id> --boards @boards.txt --attempts 2 --reuse-runs --harness baseline/2026-w47 --kae baseline/2026-w47`),
priority 5. Without the sprint command, the same arm as a method:
```bash
$K method add "pose-transplant B tier=big 1b7c9ff" --kind joint-fixed --kicad-threads 2 \
   --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 \
   --code kae=https://github.com/magnetic-trowel/kicad-auto-everything@1b7c9ffc \
   --command "<the template of 716e9b11e0f4, numba-default-c2dd008 -> numba-default-1b7c9ff> --set pose_tier=big"
```
Then `kaeres exp report`, `kaeres quality` and `ledger.py reach` against the control. Write the verdict into this
folder.
