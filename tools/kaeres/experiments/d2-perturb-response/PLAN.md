# PLAN: d2-perturb-response (micro tier, about 8 CPU-h, route-only)

## Hypothesis

The routed result responds smoothly to the placement: moving a tenth of the small parts by 0.05-0.2 mm changes
the open count by much less than re-drawing the whole placement does. If it does not (a 0.05 mm perturbation
changes opens by about as much as a new placement), every coupling that revises a placement and then routes again
from the bare board is a restart under another name, and only two forms can work: terms that shift the whole
distribution of placements, and moves that carry the routed state through the placement change.

## Measured failure it targets

Windows: 28 % of tries end with more opens after re-routing about 10 nets. Restarts fail on different nets but
on the same number. No placement-only measure ranks placements of a board above 0.3-0.4. Stored data cannot
answer the question: among 1,209 stored placements of 103 boards only one pair is closer than 1 % of the board
diagonal without a rotated part (9 against 13 opens; board SD 3.1).

## Suite

20 boards of `bench/suites/mech/place-fixable-le400.txt` with the largest spread of opens across stored fresh
attempts (single route attempts cost about 0.03 CPU-h each on them). The list and each board's reference SD
(1.8 to 10.3 opens, median 3.2) are in `perturb20.tsv`, written by the design session beside its suite drafts;
copy both suite files into `bench/suites/mech/` when filing.

## Arms (per board; start = the stored kept staged placement with all routing stripped)

| Arm | Placement | Routing seed | Runs |
|---|---|---|---|
| base | unchanged | 0 | 1 |
| twin | unchanged | 0 | 1 (determinism check under a counted budget) |
| seeds | unchanged | 1, 2, 3 | 3 (routing-order spread on this placement) |
| e005, e02, e1 | a seeded random 10 % of unlocked parts with at most 4 pads moved by 0.05 / 0.2 / 1.0 mm in a random direction; a move is redrawn until the placement check passes | 0 | 3 perturbation seeds each = 9 |
| all02 | every unlocked part moved by 0.2 mm in one common direction (a rigid shift: nothing changes relative to anything but locked parts and the edge) | 0 | 1 |

14 runs x 20 boards x about 0.03 CPU-h = about 8 CPU-h. Recipe: the bridge route of the control, counted-work
budget, from the bare placement. Tool needed: `tools/research/joint/perturb.py` (load a board, move the named
share of parts, check, write; about 150 lines; not written yet).

## Endpoints

Per board and arm: |opens - base opens| divided by the board's SD of opens between stored fresh placements
(`designs/2/variance.py` gives it); the set of open nets shared with base (Jaccard). Summaries: median over
boards per perturbation size, with a board bootstrap interval; the same for `seeds`.

## Deciding result

- Response at 0.05 and 0.2 mm under 0.3 SD and rising with size: smooth. Local revisions can be credited by a
  fresh route; run `d2-halo-feedback` as planned.
- Response at 0.05 mm above 0.8 SD (the level of independent placements is about 1.1): chaotic. Then in
  `d2-halo-feedback` the sham arm will equal the fresh arm by construction; read H only as a shift of the mean,
  apply halos inside every fresh placement instead of as a revision, and move the build effort to carrying the
  routed state through moves (elastic follow-through) and to making the router less sensitive (topic 1).
- `twin` not identical on more than 1 board in 20: stop, the budget is not counted work; fix that first.

## Kill rule

None for the test itself (diagnostic). It kills "revise, then route again from bare" as a way to credit a local
placement change if the response is chaotic.
