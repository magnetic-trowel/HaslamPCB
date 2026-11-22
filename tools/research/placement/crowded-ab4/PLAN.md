<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# crowded-ab4: edge pins that keep clear of fixed parts (pre-registered)

Written 2026-11-22, before any run. Sprint tier, prio 5, at most 40 CPU-h.
- Code: branch `crowded-pinclear` at df50f967, main dc75d92e plus the crowded helps, plus `place_edge_pose_clear`.
  With that setting an edge pin keeps its pads a clearance from the fixed parts' pads and its courtyard off theirs,
  sliding along the edge from the centre. A part with no such pose is not pinned.
- Motivation: in crowded-ab3, every new short on the do-no-harm boards was the pinned part on a locked connector
  (teeprom U1 on J1; uzsito A1 on J5).
- A check on the inputs: teeprom and uzsito are no longer pinned, qt-py-esp32-c3 is no longer pinned,
  itsybitsy-rp2040 is pinned as before, and xenon's HEAD1 slides 4.5 mm.

## Arms (placement only, counted work, fresh seeds)
- control;
- control2 (the identity check);
- pairs: `place_edge_headers place_edge_slot place_edge_header_pairs`, as crowded-ab3;
- clear: pairs plus `place_edge_pose_clear=1`.

## Boards (`boards.tsv`)
- The 7 failing boards, seeds 14-16.
- The 19 header boards, seeds 14-15. They include teeprom and uzsito, where shorts rose.
- The crowded stratum is left out: every arm was identical on it in crowded-ab2 and crowded-ab3.

## Decision
- **Primary:**
  1. Part-to-part shorts on the failing boards: clear against control. The gain must hold, with its CI below 0.
  2. teeprom and uzsito: clear's shorts no higher than control's on each seed.
  3. The header stratum: no rise in shorts (the CI may not exclude a rise).
- **Guards:** legality under two views, which are reported together:
  1. kae's own flag;
  2. DRC placement-type errors between two footprints (#137), and the same not worse than the human layout per
     kind. The DRC reports are kept.
- Also: placement errors, HPWL. The control twin must be identical.
- **If it holds:** a routed sprint check (the failing boards and the header sample, k = 2, joint chassis, control
  against clear), then the weekly canary. Each gets its own short plan.

## Cost (information)
4 arms x 59 board-seeds at about 4 min: about 16 CPU-h.

## Addendum 2026-11-22: one extension, written before its results
The ab4 shorts CI on the failing boards reached 0 (-220, CI [-624, 0]). One extension, then a decision:
- **Runs:** seeds 17-19 on the 7 failing boards, arms control and clear only (pairs adds nothing), same code and
  settings. About 3 CPU-h, prio 5.
- **Analysis:** pooled with ab4's seeds 14-16, giving 42 board-seeds. The board-cluster bootstrap CI of clear's
  shorts against control.
- **If the CI is below 0:** the routed sprint check is submitted (the 26 boards, control against clear, k = 2,
  about 31 CPU-h).
- **Else:** the fix is recorded as a no-harm, uncertain-gain option, off by default, and the crowded-header line is
  written up. No further extension.

## Result of the extension (2026-11-22)
- **Pooled, 42 board-seeds:** clear against control, part-to-part shorts 583 -> 389, -194 [-575, +42].
- **Legality:** kae's own flag 1 -> 7, all itsybitsy-rp2040.
- **Decision:** the CI includes 0, so by the addendum the fix is recorded as no-harm with an uncertain gain, off by
  default. No routed check. Write-up: `docs/research/placement/crowded-headers-2611.md`.
