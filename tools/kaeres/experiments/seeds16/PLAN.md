<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# seeds16: best-of-k seeds of the default kae place-and-route on three hard boards (descriptive)

Written 2026-11-17, before any run. The question is whether more compute, spent as more independent seeds, helps the boards the default leaves open.

## Method
- The default recipe of `merit-restart.sh`:
  - completion-first, phase 1 staged restarts;
  - on a board clean after phase 1, M-clock as `--alt`;
  - on a board still open, the joint loop's windows on phase 1's board (`--open-alt`);
  - counted work, Freerouting d137fd1, the normal allowance.
- The kae code is as the recipe pins it (2199c12). The harness is 269c292, which is main plus `restart.py` keeping each policy phase's own attempt log in `restarts.json`.
- **Seeds:** 16 independent runs per board, kaeres attempts 0-15 (`--seed {attempt}`), all queued at once at priority 2. Seeds vary kae's placement; Freerouting stays deterministic per input.

## Boards
Three of the 17 boards that `cfw2b` left with 20 or more opens:
- **nf-dj-netforce-tpu:** 153 footprints, 6 layers, BGAs and 32-wide buses, so bus- and BGA-heavy. 38 phase-1 opens.
- **folknology-mystorm:** 142 footprints, 2 layers, the most opens left (121 after phase 1). The large 2-layer board.
- **kicad-demos-stickhub:** 94 footprints, 2 layers, pairs and buses. 33 phase-1 opens. Mid-size.

## Outputs (descriptive; `curves.py`)
- **(a) Expected best-of-k:** best-of-k opens, clean and errors for k = 1..16, averaged over orderings of the 16 runs (exact from order statistics), with the 10-90 % spread.
- **(b) Within each run:** opens against counted work, through the phase-1 attempts and then the windows iterations (`restart-report-windows.json`).
- **(c) Phase-1 versus windows share:** per board, how much of the best-of-k gain comes from phase 1 and how much from the windows.

**Caveat:** before #105, Freerouting's optimizer was uncharged in counted work. The pinned kae code predates #105.
