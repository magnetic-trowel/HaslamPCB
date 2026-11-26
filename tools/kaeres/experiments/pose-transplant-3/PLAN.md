<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: pose-transplant-3 (arm P: the 2-pad parts held at their human poses)

Diagnostic (human poses are an oracle, never a method). Written 2026-11-26, before any run. Follows
pose-transplant-2 (VERDICT.md there: K − H +0.880 [+0.231, +1.415] log1p opens; g_B 0.266 [0.015, 1.118], g_M 0.392
[0.135, 1.233]: undecided, the point estimates leaning to the 2-pad parts). The design's next step: arm P.

## Hypotheses
- H3: the non-connector 2-terminal parts carry most of the K-to-H gap (kae's passives crowd pads and corridors).
- not-H3: holding them closes little of the gap; the gap is in the >= 3-terminal parts or their interaction.

## Arm (one change)
- P: the pose-transplant-2 recipe (staged control `716e9b11e0f4` at kae c50478c, `kae.joint.cli run --max-iters 0
  --no-modules`) with `--set pose_tier=small --set pose_source=<oracle>`: every non-connector 2-terminal part held at its
  human pose (`kae.place.pose_tiers`, tier small; disjoint from tier mid), kae places the rest.
- Controls reused from pose-transplant-2 / control-w47: K (`716e9b11e0f4`), H (`71e60a91475d`), and for the
  complement check B and M (`3434cb72a315`, `0f4c8a49cfcb`). Seeds 0 and 1. Priority 5.

## Boards
pose-transplant-2's 27 boards (`mech/place-fixable-le400` minus its 8 exclusions). The pose oracle is rebuilt for tier
small (`pose_oracle.py build --tiers small`, harness c2dd008) into `~/.cache/haslambench/pose-oracle/pose-transplant-3`;
a board whose held 2-pad poses add placement errors over the task input's own or put parts outside is excluded with its
reason (`exclusions.json`), before any arm run. The deciding analysis uses the boards left.

## Sandbox path
The control recipe names `$HOME/.cache/kaebench/...` (Freerouting fork); since the 2026-11-25 rename that is a symlink
the sandbox does not show. The experiment sets the result-neutral `KAE_STEP_CACHE=$HOME/.cache/kaebench`, which binds
that path inside the sandbox. The oracle path is given resolved (`$HOME/.cache/haslambench/...`).

## Smoke
2 boards x 2 seeds first. Continue only if every P run has output, every held part is at its oracle pose (within 1e-3 mm,
1e-3 deg, same side) and no run has a part outside.

## Deciding result
g_P = (K − P) / (K − H) in log1p(opens), paired per board and seed, estimator mean(K − P) / mean(K − H), owner bootstrap
(5,000 resamples, seed 0, 95 %), as in pose-transplant-2's `verdict_analysis.py`.
1. K − H interval including 0 on these boards: stop, nothing to explain.
2. **H3 supported** (2-pad parts bind): g_P >= 0.5 with its interval's lower bound above 0.25.
3. **H3 rejected**: g_P <= 0.25 with its interval's upper bound below 0.5.
4. Otherwise **undecided**.
Reported, not decided on: g_P + g_M (complementary tiers; near 1 if the tiers add up), the same on legal board-seeds
only, near-miss closure (zero-open runs and runs with 1-5 opens), cp1. Legality: no placement error beyond the task
input's own, no part outside, held parts on their oracle poses.

## Kill rule
Cancel if, after the smoke, any P run has a held part moved or a part outside, or more than a quarter of P runs add
placement errors over the input's. Cancel if the campaign projects over 60 CPU-h (pose-transplant-2's arms used about
5.5 CPU-h each).

## Oracle result (2026-11-26, before any arm run)
Tier-small oracle (haslamq #127565): 18 of the 27 boards usable; 9 excluded because the held human 2-pad poses add
placement errors over the task input's own (`exclusions.json`: copper_edge_clearance 1-7, courtyards_overlap 1-9,
shorting_items 2-17, clearance 1). Together with pose-transplant-2's 8: `exclusions-all.json`, 17 boards excluded from
the 35-board suite. On bcecoop-rmlv1616a tier small holds no part, so P is the control there (kept, as the oracle
rules). The deciding analysis uses these 18 boards; K, H, B and M are pose-transplant-2's runs on them.
