<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Notes: state of `tools/research/effort/`

## Reproduction of the stage-0 replay (2026-11-20)

`replay.py --experiment s2-merit213 --methods "s2 bridge 44041bc,critical+bridge,joint loop"` reproduces the
stage-0 scripts' printed numbers for BR, CB and JL **to the digit**: every policy line of the main table, every
line of the equal-CPU table, the budget-response and seed-SD lines, and the BR/CB/JL header lines are identical
text once the method name is replaced by its short label. Two differences in presentation only:

- The wave-cap line lists caps 0 to the last logged wave (4 entries for BR/CB, 2 for JL); the stage-0 script
  printed caps 0 to 5, whose extra entries repeat the full schedule. Equal-CPU interpolation is unchanged.
- The by-size line is printed for both `return v1` variants for every method (stage 0 printed one per method).

Runtime: about 40 s on one core for the three methods.
