<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# d6-place-terms: build notes

Integration branch for the placement-term family, off main c2dd008a. Merged with `--no-ff`, in this order:
`chan-gated-m6`, `xing-ext-m6`, `margin-gate-m6`, `array-macros-gated-m6`, `place-barrier-moves-m6`. The last had one
conflict hunk, in the `DEFAULTS` block of `kae/src/kae/route/constraints.py` (`array_macros` against `barrier_split`
and `barrier_net_weight`); both sides are kept. Every new setting defaults to off.

Left out: `phist-b-m2` (placement history across attempts). It is a restart-level factor, touches `restart.py` and
conflicts in `joint/loop.py`, `place/pipeline.py` and `tests/test_restart.py`; it is tested separately.

The experiment is not run from this branch yet: see `PLAN.md` (arms in `arms.json`), and `IDENTITY.md` for the
default-off check.

## Open point for the arms

`margin-gate`'s gated arm set `place_margin_regions=1` as well as `place_margin=-1 place_margin_gate=4`. The d6 on
settings leave `place_margin_regions` at 0. Decide before registering (`arms.json`, factor `margin`).

## Functions touched in `place/pipeline.py` and `place/anneal.py`

For the later merge with the satisficing-physics branch. Changed lines of this branch against main c2dd008a, by
enclosing function (lines changed in brackets), and which merged branch changed each.

`kae/src/kae/place/pipeline.py` (+162 -5):

| Function | Lines | Branches |
|---|---|---|
| module level (imports, constants near `SILK_W`) | 8 | chan-gated (6), array-macros-gated (2) |
| `_channel_weight` (new) | 24 | chan-gated |
| `_channel_final` (new) | 7 | chan-gated |
| `_pin_arrays` (new, after `_pin_edge_connectors`) | 24 | array-macros-gated |
| `_place_rung` | 67 | chan-gated 40, xing-ext 27, margin-gate 12, array-macros-gated 9, place-barrier-moves 6 (overlapping) |
| `place` | 33 | place-barrier-moves (barrier split / fit probe before the severity ladder) |

`kae/src/kae/place/anneal.py` (+30 -5), all in class `Annealer`:

| Method | Lines | Branches |
|---|---|---|
| `__init__` | 12 | chan-gated, xing-ext (the same lines in both) |
| `try_move` | 8 | chan-gated, xing-ext |
| `run` | 4 | chan-gated, xing-ext |
| `cost`, `evaluate`, `terms_report` | 2 each | chan-gated, xing-ext |

Regenerate with `git diff -U0 c2dd008a HEAD -- <file>` and map the hunks to their enclosing `def` (ast).
