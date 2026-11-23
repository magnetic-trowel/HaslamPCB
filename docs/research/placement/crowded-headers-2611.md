<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Crowded boards and edge headers: why kae's placements fail there, and what pinning does

Scope: crowded boards (movable-part utilization at or above about 0.7) where kae's placements end illegal or with
stacked parts, and the edge-header pinning tried against it. Not here: legality in general ->
[kae-exact-legality](kae-exact-legality.md); big parts with no free spot -> [anchor-tight-parts](anchor-tight-parts.md).
Keys: crowded boards, utilization, edge header, Feather, ItsyBitsy, QT Py, kae.place.crowded, place_edge_headers,
place_edge_slot, place_edge_header_pairs, place_edge_pose_clear, place_fine_grid_util, edge_pose, score 13.

**Status:** no-harm, uncertain gain. The fixed version (`place_edge_pose_clear`) leaves every do-no-harm board as
control left it. It cuts part-to-part shorts on the failing boards, but the pooled CI includes 0. Off by default,
branch `crowded-pinclear`. Not proposed for default.
**First published:** 2026-11-22, branch `crowded-pinclear`.

## How this was found
In the chan-gated-m6 A/B, the channel term (`place_w_chan` 3) added shorting_items and clearance errors on three
crowded boards: xenon, qt-py-esp32-c3 and itsybitsy-rp2040. The errors were not tight spacing. They were whole parts
stacked on each other in placements left illegal.

The first idea was utilization: give the boards more room and see where each arm starts to fail. chan-room did
that on 7 boards, with outlines scaled from native down to 0.45 utilization, 396 placements:
- below 0.65, no placement failed in either arm (0 of 168);
- from 0.70 about a third failed, in both arms alike;
- chan3 did not start failing earlier. It made failures worse: 752 part-to-part shorts against 568.

Utilization was a proxy, though. Three of the boards never failed even at 0.88-0.98, and fercus failed only at
native size. Reading the placer's own reports on the failing runs (crowded-diag, 85 placements with full reports)
showed two patterns.

## Two failure patterns
1. **Long movable edge headers (4 of the 7 failing boards).**
   - The boards: itsybitsy-rp2040 and itsybitsy-esp32 (JP2/JP4, 14 pins over 33 mm on a 35.6 mm board),
     qt-py-esp32-c3 (JP1/JP3, castellated 7-pin rows), and xenon (HEAD1/HEAD2, Feather rows).
   - In the place-fixed task these headers are movable and start off the board. By design they are fixed: they are
     the module's pinout along its edges.
   - Their courtyards do not fit the board, and the floorplan is infeasible. The greedy legaliser leaves the headers
     unplaced in every failing run, and the closed loop ends with them stuck against the edge or a fixed part.
2. **Crowded passives (doorman, olimex-lora, fercus).** Small parts are left unplaced, and the diagnosis says
   "room exists but its region is full".

**The human layouts are not legal either.** Each human placement was run through kae's model and exact check
(`human_grid.py`):
- doorman's has 6 courtyard overlaps;
- qt-py's has 13 courtyard overlaps and 35 header pads inside the copper-to-edge clearance;
- itsybitsy's and xenon's have 34 and 46 copper_edge_clearance errors.
Only fercus's human layout is clean, and kae's grid rectangles flag 5 of its parts. So on 6 of 7 boards "legal" asks
more than the human met. That led to two scoring decisions (2026-11-22):
- placement legality counts only errors between footprints (score 13, PR #137);
- a report-only "not worse than the human" column (PR #136, waiting).

## How common the edge-header pattern is
A shape-only detector (`kae.place.crowded.header_row`) looks for a movable footprint with a regular row of at least
7 pins spanning at least 0.6 of the board's long side or 0.8 of its short side. The input gives movable parts no
position, so only the footprint's own pads are used.
- It fires on 90 of 865 cached corpus boards (10 %), 35 of them with two rows (Feather, ItsyBitsy, QT Py style).
- It catches all four pattern-1 boards and none of the other six crowded ones.
- It also fires on rows that are not edge headers: a keyboard MCU, DIP sockets, dev-board rows.

## The helps (kae.place.crowded, all off by default)
- `place_edge_headers`: detected header rows are pinned flush along a board side before the seed, then held like
  fixed parts.
  - The pose is computed, not searched (`edge_pose`). The rows cannot keep the copper-to-edge clearance at their
    ends, so no grid spot exists.
  - It is gated to rows with no grid-legal spot anywhere (`fits_nowhere`).
- `place_edge_slot`: the same pin for any movable part whose courtyard cannot fit the board. A greedy fallback after
  legalisation was planned, but it finds no spot for the same reason.
- `place_fine_grid_util`: one grid step finer above a utilization.
- `place_edge_header_pairs`: if one header fits nowhere, every detected row is pinned.
- `place_edge_pose_clear`: the pin keeps its pads a clearance from the fixed parts' pads and its courtyard off
  theirs. It slides along the edge, and a part with no clear pose is not pinned.

## The four tests
All tests: placement only, counted work, fresh seeds each time, control run twice. The control twin was identical
on every board-seed of every test.
- **Strata:**
  - failing: the 7 boards;
  - crowded: 10 more chan-gated-m6 boards at 0.7 or more;
  - header: 19 detected boards, one per repository, as a do-no-harm sample.
- **Primary:** kae's own legality flag on the failing boards. Part-to-part shorts are the primary from ab4 on.

| test | arm | legal, failing (21) | shorts, failing | do-no-harm |
|---|---|---|---|---|
| crowded-ab | headers (ungated) | 1 -> 8 (+7 [+1, +14]) | 306 -> 122 | header boards: HPWL +10-12 % (keyboard MCU 2.45x) |
| | unfit | 1 -> 4 (+3 [0, +9]) | 306 -> 322 | no change |
| | fine | 1 -> 3 | 306 -> 136 | one crowded run lost |
| | all | 1 -> 9 (+8 [+2, +15]) | 306 -> 110 | as headers |
| crowded-ab2 (main with #134) | gated headers + unfit | 2 -> 5 (+3 [0, +9]) | 206 -> 166 | header shorts +88 [0, +204] |
| crowded-ab3 | gated | 2 -> 5 | 455 -> 240 | header shorts +64 [-8, +180] |
| | pairs | 2 -> 5 | 455 -> 225 | as gated |
| crowded-ab4 + extension | pairs | 1 -> 4 (seeds 14-16) | 400 -> 175 | header shorts +72 [-8, +188] |
| | clear | 1 -> 7 (42 board-seeds) | 583 -> 389 (-194 [-575, +42]) | equal to control: shorts -4 [-12, 0], legal 30/30 |

- The legality gain is itsybitsy-rp2040 in every test from ab2 on.
- The ungated gain in crowded-ab (qt-py, xenon) did not survive gating.

### The edge_pose bug
- **The harm.** On the header stratum, gated pinning added shorts on teeprom (+24 per seed) and uzsito (+10-18).
- **The cause.** Re-placing those runs with the boards kept showed every new short was the pinned part on a locked
  connector: teeprom's U1 on J1, uzsito's A1 on J5. `edge_pose` centred the part along an edge and checked only the
  outline.
- **The fix.** `place_edge_pose_clear` checks the fixed parts as well. With it, teeprom, uzsito and qt-py are no
  longer pinned, and xenon's HEAD1 slides 4.5 mm.
- **The result.** On crowded-ab4 the harm is gone: header boards equal to control under every view and guard.

### Legality under the three views (crowded-ab4, kept DRC reports)
- **Failing boards (control / pairs / clear):** kae's own flag 1 / 4 / 4; no placement-type DRC error between
  footprints 0 / 0 / 0; not worse than the human 1 / 3 / 3.
- **Header boards:** clear equals control in every view (30, 20, 30 of 38). Pairs is worse (32, 16, 26).

## Verdict
**`place_edge_pose_clear` with `place_edge_headers` and `place_edge_slot`: no harm, uncertain gain.**
- On the failing boards, shorts fall from 583 to 389 over 42 board-seeds, with a CI of -575 to +42.
- Legality on the failing boards goes from 1 to 7. All of it is itsybitsy-rp2040, which the pin fixes in every seed.
- No routed check was run, under the pre-registered rule.
- **It is a candidate where the mechanism is certain:** an edge header row that fits nowhere on the board, as on
  ItsyBitsy boards.

**What remains, with other owners:**
- **The crowded-passive boards** need an exact-geometry repack. The grid's rectangles reject fercus's human
  packing. That work is with the placement session.
- **Most failing boards break their own rules even in the human layout.** Judging them by "not worse than the
  human" (PR #136) would be fairer than strict legality.

## Data and code
- **Plans and results:** `tools/research/placement/` (`chan-room`, `crowded-ab`, `crowded-ab2`, `crowded-ab3`,
  `crowded-ab4`), each with `PLAN.md`, addenda and scripts.
- **Branches:**
  - `crowded-fixes` (ce093dc4): crowded-ab;
  - `crowded-fixes2` (66aaa596): crowded-ab2;
  - `crowded-pairs` (5cc939e2): crowded-ab3;
  - `crowded-pinclear` (df50f967): crowded-ab4.
- **Related:** the scoring follow-ups are score 13 (PR #137, merged), `kaeres rescore` (PR #138) and `legal_h`
  (PR #136).
