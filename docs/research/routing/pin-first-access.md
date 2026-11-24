<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Pin-first access: TraceMaker's strict crowded-end search in kae

Scope: design note for porting TraceMaker's pin-first strict search into kae's grid router as a pre-pass before Freerouting (setting `pin_first`, `kae/src/kae/route/pin_access.py`). Not here: the dog-bones and escape plans -> `kae/src/kae/route/escape.py` docstring; the last mile -> [kae-last-mile](kae-last-mile.md).
Keys: pin_first, pin-first access, crowded source, end_crowding, boxed in, walled-in pin, strict first pass, TraceMaker, pin_access

## What TraceMaker does (v0.12.1, GPL-3.0-or-later; paths under its `src/`)

1. **Pad access off the lattice.** A pin's start cells are the lattice nodes inside its copper; where none is free, straight escapes in 8 directions from the pad centre (step max(pitch/2, 10 um)) to the first free lattice cell, each piece checked (`route/router.cpp` `pad_cells`, `escapes`).
2. **Exact check before commit.** Every merged segment and via is checked as a capsule against tracks, pads, vias, fills, holes and the edge with the per-pair rule; a failure rejects the path (`commit`, `obstacles.cpp` `segment_state`).
3. **Crowded source.** In the strict pass the connection's ends are swapped so the search starts at the end with the larger `end_crowding` = other-net pads of the same footprint plus other-net routed items in the box pad centre +- (max half size + 1 mm). A walled-in source runs its open list dry before the window edge: "boxed in" in a few expansions. Portfolio variants 1, 5, 6, 7 of 8 use it.
4. **Strict first pass.** Pass 0: other nets' copper is a hard block, no rip-up; failures queue for PathFinder passes (40 rips per connection, 40 passes). Strict routes are not locked.

Measured: on 15 BGA boards TraceMaker left 254 open signal connections against the bridge's 465; the hybrid (TraceMaker first, kae's stages after) beat the bridge by -15.2 opens per pair [-29.7, -3.2] (experiment `tm-hybrid`). It runs on wall clock (600 s x 8 threads).

## What kae already has

| TraceMaker part | kae equivalent |
|---|---|
| off-lattice pad access | `GridRouter._escapes` (straight legal piece along the pad's axes to a free cell; overlap entry) |
| exact check before commit | `GridRouter._geometry` (`Space.track_violations`, `via_violations`) and `lastmile._commit` |
| search from the source | A* from the source cells (`critical_kernels.astar`) |
| strict pass | `lastmile._try` and the plane escapes: no rip-up |
| boxed-in test | `GridRouter.boxes_in` (after a route; not used for ordering) |

Missing: an ordering of a dense part's pins by crowding, and a pass that leads every walled-in signal pin out before the bulk router takes the exits.

## What to port: the smallest useful version

- **Where: kae, not the Freerouting fork.** The pieces above are in kae, Python, with counted work; the pre-pass slot exists (`lastmile.plane_escapes`, after the dog-bones, unlocked copper to Freerouting). The fork would need the strict pass inside its batch autorouter, a Java port of the crowding and a GPL-3.0-only combination; it is the place for the full crowded-source search later (every connection, not only access), once the kae pass shows the effect.
- **Pass** (`pin_access.run`): dense parts (>= 16 single-layer SMD pads, n / area(hull + pitch/2) >= 1/1.3^2 per mm^2); walled-in signal pins (pads of the part within 2.5 pitches all round, no own copper yet, a pad of the net outside the part, not a zone net); most crowded first (TraceMaker's measure, updated as copper lands); each pin a strict GridRouter search from the pin to the free-space band (0.5-1.1 mm outside the pads' hull; the half facing the net's other pads first), widths opt then min, inner plane layers excluded, at most 300k expansions. What fails stays for Freerouting.
- **Not ported:** the 8-variant portfolio, PathFinder rip-up (kae's last mile does it after Freerouting), TraceMaker's internal zone model (its measured weakness), wall-clock budgets.
- **Budget:** counted work (`lastmile_try`, `lastmile_cells`, `crit_search`, `crit_expansion`), at most `pin_first_s` = 60 nominal s.
- **Off by default; bit-identical when off** (the bridge does not import the module).

## Open questions

- Whether unlocked stubs survive Freerouting, or whether it rips them as it rips other unlocked copper.
- Whether pins already dog-boned should also get an inner-layer access stub.

## Sources

TraceMaker trial and hybrid: `TRACEMAKER.md`, `TM-HYBRID.md` in the gap-audit folder (not in the repository); experiment `tm-hybrid` in the results store.
