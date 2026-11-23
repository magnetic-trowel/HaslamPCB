<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# lastmile-retry-smoke

Proof of a bug fix, not an A/B of a method. Branch `lastmile-retry`.

- **Decision.** Whether the last-mile fix (no retry without progress, connectivity passes charged,
  nets rotated across rounds) removes the two failures seen on main: the endless D+ retry on
  atrivatech ch32v003 (wall ceiling, 26 open) and the unreached tail of nets on alphaonex86 socket7.
- **Arms.** Before: kae main 44041bc. After: 582b9a0 (main + the fix). Both: kae bridge, counted work
  900 s, Freerouting fork pin f1c41d3, KAE_BUDGET_PROFILE=1 KAE_BUDGET_GAP=5, KiCad 10.0.7.
- **Boards.** The two boards where the failures were seen, seeds 0 and 1.
- **Read.** Delivered opens and DRC errors by type; whether the run ended within its budget
  (no wall ceiling); last-mile turns per net and nets reached per round in the log; the clock's
  charged vs wall seconds per kind.
- **Expected.** atrivatech: back near the 3 open of earlier builds, no ceiling. alphaonex86: eth_* and
  tsen_* nets reached; fewer opens than the before arm.
- **Cost.** 8 runs, about 15-60 min each on 1-2 CPUs.
