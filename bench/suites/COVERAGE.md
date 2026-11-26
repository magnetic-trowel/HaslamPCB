# Coverage of mechanisms and standard circuit kinds

Written by `tools/haslamres/coverage.py` from the board tags, the corpus manifest and the results index; do not edit. Kinds and their tag expressions: `tools/haslamres/mechsuites.py` (`MECHANISMS`); the suites: [mech/README](mech/README.md).

- **usable**: can run as a route and as a place task (netlist, prepared task, closed outline, 5+ footprints). **human-clean**: usable, and the human layout is complete with no DRC error. **owners**: accounts of the repositories of the usable boards.
- **hole**: fewer than 20 owners of usable boards, or fewer than 10 human-clean boards.
- Suite columns count the kind's boards in `sprint-frontier`, `sprint-quality`, `ladder`, `canary` (`+n`: in the suite's `-additions.txt`) and in the kind's own suite `mech/<kind>.txt`.

## Summary

| group | kind | usable | human-clean | owners | frontier | quality | ladder | canary | own suite (tier) | hole |
|---|---|---|---|---|---|---|---|---|---|---|
| packages | `bga` | 428 | 33 | 216 | 3 | 2 | 12+2 | 12 | 60 (sprint) | - |
| packages | `bga-balls-9-64` | 89 | 8 | 56 | 0 | 1 | 2+2 | 0 | 37 (sprint) | 8 human-clean |
| packages | `bga-balls-65-144` | 57 | 6 | 37 | 0 | 0 | 3 | 0 | 30 (ladder) | 6 human-clean |
| packages | `bga-balls-145-324` | 148 | 11 | 89 | 1 | 0 | 6 | 6 | 36 (sprint) | - |
| packages | `bga-balls-325plus` | 134 | 8 | 84 | 2 | 1 | 1 | 6 | 30 (ladder) | 8 human-clean |
| packages | `bga-pitch-0.4` | 72 | 5 | 55 | 0 | 0 | 2+1 | 1 | 30 (sprint) | 5 human-clean |
| packages | `bga-pitch-0.5` | 83 | 6 | 48 | 0 | 1 | 0+1 | 2 | 30 (ladder) | 6 human-clean |
| packages | `bga-pitch-0.65` | 32 | 0 | 20 | 0 | 0 | 0 | 1 | 20 (ladder) | 0 human-clean |
| packages | `bga-pitch-0.8` | 170 | 15 | 106 | 1 | 0 | 8 | 7 | 38 (sprint) | - |
| packages | `bga-pitch-1.0-1.27` | 71 | 7 | 40 | 2 | 1 | 2 | 1 | 30 (ladder) | 7 human-clean |
| packages | `fine-pitch` | 3690 | 397 | 1512 | 32 | 36+6 | 108+2 | 9 | 60 (sprint) | - |
| signals | `diffpairs` | 2057 | 235 | 967 | 20 | 23+4 | 73+2 | 17 | 60 (sprint) | - |
| signals | `parallel-bus` | 849 | 92 | 467 | 5 | 6+2 | 25 | 11 | 60 (sprint) | - |
| structure | `pours` | 11402 | 1854 | 3492 | 52 | 75+17 | 254+10 | 26 | 60 (sprint) | - |
| structure | `inner-planes` | 2219 | 355 | 974 | 19 | 37 | 136+1 | 20 | 60 (sprint) | - |
| structure | `double-sided` | 2668 | 385 | 1299 | 20 | 13+6 | 67+2 | 14 | 60 (sprint) | - |
| structure | `cutouts-slots` | 5175 | 853 | 2404 | 32 | 41+4 | 147+5 | 15 | 60 (sprint) | - |
| structure | `arrays` | 427 | 63 | 284 | 3 | 1+4 | 19 | 8 | 60 (sprint) | - |
| structure | `connectors` | 921 | 261 | 551 | 1 | 2+4 | 12+1 | 1 | 60 (sprint) | - |
| structure | `decoupling` | 3476 | 433 | 1605 | 26 | 49+2 | 122+2 | 21 | 60 (sprint) | - |
| power conversion and distribution | `buck` | 1440 | 228 | 764 | 10 | 29+1 | 60+2 | 16 | 60 (sprint) | - |
| power conversion and distribution | `boost` | 485 | 49 | 299 | 4 | 4+2 | 14 | 3 | 60 (sprint) | - |
| power conversion and distribution | `ldo` | 3611 | 464 | 1561 | 17 | 30+3 | 97+2 | 13 | 60 (sprint) | - |
| power conversion and distribution | `power-distribution` | 1328 | 189 | 684 | 6 | 21+2 | 58+1 | 18 | 60 (sprint) | - |
| battery and charging | `battery-charging` | 598 | 42 | 307 | 4 | 2+3 | 12+1 | 1 | 60 (sprint) | - |
| microcontroller core | `mcu-core` | 3116 | 378 | 1568 | 21 | 35+1 | 88+3 | 10 | 60 (sprint) | - |
| clocking | `crystal` | 2766 | 264 | 1360 | 20 | 34 | 78+2 | 15 | 60 (sprint) | - |
| memory | `ddr` | 198 | 16 | 119 | 1 | 0+1 | 5 | 9 | 52 (sprint) | - |
| memory | `ddr3` | 76 | 5 | 56 | 1 | 0 | 1 | 6 | 30 (ladder) | 5 human-clean |
| memory | `ddr4-ddr5` | 8 | 2 | 6 | 0 | 0 | 1 | 0 | 6 (ladder) | 6 owners; 2 human-clean |
| memory | `flash-sd` | 621 | 61 | 355 | 6 | 7+1 | 23 | 9 | 60 (sprint) | - |
| wired interfaces | `field-bus` | 380 | 51 | 199 | 2 | 3+2 | 16 | 2 | 60 (sprint) | - |
| wired interfaces | `usb` | 3269 | 329 | 1546 | 25 | 34+2 | 94+2 | 15 | 60 (sprint) | - |
| wired interfaces | `ethernet` | 340 | 26 | 177 | 2 | 2+3 | 12 | 9 | 60 (sprint) | - |
| wired interfaces | `multi-gigabit` | 246 | 22 | 129 | 2 | 3+1 | 10 | 7 | 56 (sprint) | - |
| wired interfaces | `sata` | 13 | 1 | 11 | 0 | 1 | 0 | 1 | 11 (ladder) | 11 owners; 1 human-clean |
| wireless | `rf-antenna` | 1063 | 124 | 459 | 10 | 7 | 25+1 | 9 | 60 (sprint) | - |
| wireless | `radio-module` | 2000 | 292 | 1131 | 17 | 16+6 | 55+5 | 4 | 60 (sprint) | - |
| analog signal chain | `analog-opamp` | 1414 | 254 | 655 | 2 | 15 | 39+1 | 11 | 60 (sprint) | - |
| analog signal chain | `adc-dac` | 632 | 77 | 366 | 1 | 6 | 18 | 5 | 60 (sprint) | - |
| sensing | `sensors` | 1301 | 161 | 603 | 8 | 8+1 | 29+1 | 3 | 60 (sprint) | - |
| audio | `audio` | 1043 | 203 | 487 | 3 | 12+1 | 32+1 | 5 | 60 (sprint) | - |
| display and camera | `video-links` | 295 | 22 | 129 | 1 | 0+1 | 8+1 | 10 | 60 (sprint) | - |
| display and camera | `displays` | 1440 | 230 | 885 | 6 | 7 | 39+1 | 4 | 60 (sprint) | - |
| motor and power stages | `motor-gate-drivers` | 393 | 60 | 260 | 2 | 5 | 13+1 | 1 | 60 (sprint) | - |
| isolation and mains | `isolation` | 721 | 149 | 430 | 3 | 13+2 | 21+8 | 1 | 60 (sprint) | - |
| isolation and mains | `mains` | 81 | 19 | 61 | 0 | 3+2 | 2+8 | 0 | 49 (sprint) | - |
| protection and connectors | `protection` | 583 | 109 | 361 | 6 | 8 | 32+1 | 1 | 60 (sprint) | - |
| arrays and human interface | `keyboards` | 1134 | 208 | 683 | 5 | 3+4 | 51 | 2 | 60 (sprint) | - |
| arrays and human interface | `led-arrays` | 225 | 33 | 155 | 2 | 0+5 | 15 | 1 | 57 (sprint) | - |
| programmable logic | `fpga` | 340 | 34 | 207 | 2 | 2+3 | 12 | 7 | 60 (sprint) | - |
| thin in the corpus | `flex` | 13 | 4 | 8 | 0 | 0 | 1+1 | 0 | 8 (ladder) | 8 owners; 4 human-clean |
| thin in the corpus | `passive-01005` | 18 | 2 | 17 | 1 | 0+1 | 0+1 | 0 | 17 (ladder) | 17 owners; 2 human-clean |
| thin in the corpus | `microvias` | 99 | 5 | 50 | 0 | 1 | 2 | 0 | 30 (ladder) | 5 human-clean |

## Holes: what the corpus cannot supply

Nothing was fetched. To close a hole, source boards of other owners (one board per owner counts):

| kind | boards have | usable / human-clean / owners | source |
|---|---|---|---|
| `bga-balls-9-64` | largest ball grid 9-64 balls (mostly wafer-level parts) | 89 / 8 / 56 | boards with wafer-level or small ball grids and a DRC-clean human layout |
| `bga-balls-65-144` | largest ball grid 65-144 balls | 57 / 6 / 37 | boards with 65-144 ball grids and a DRC-clean human layout |
| `bga-balls-325plus` | largest ball grid 325+ balls | 134 / 8 / 84 | FPGA, SoC and DDR boards (325+ balls) with a DRC-clean human layout |
| `bga-pitch-0.4` | finest ball pitch up to 0.4 mm | 72 / 5 / 55 | boards with a 0.4 mm ball grid and a DRC-clean human layout (HDI rules in the project) |
| `bga-pitch-0.5` | finest ball pitch 0.4-0.5 mm | 83 / 6 / 48 | boards with a 0.5 mm ball grid and a DRC-clean human layout |
| `bga-pitch-0.65` | finest ball pitch 0.5-0.65 mm | 32 / 0 / 20 | boards with a 0.65 mm ball grid; none has a DRC-clean human layout |
| `bga-pitch-1.0-1.27` | finest ball pitch 0.8-1.27 mm | 71 / 7 / 40 | boards with a 1.0 or 1.27 mm ball grid and a DRC-clean human layout |
| `ddr3` | DDR3 memory | 76 / 5 / 56 | DDR3 boards with a DRC-clean human layout |
| `ddr4-ddr5` | DDR4 or DDR5 memory | 8 / 2 / 6 | boards with DDR4 or DDR5 memory-down or (SO-)DIMM routing: SBCs, FPGA and SoM carriers; 8 exist |
| `sata` | SATA | 13 / 1 / 11 | boards with a SATA host or device port (NAS, SBC and M.2 carriers) that route the pairs |
| `flex` | a flex or rigid-flex stackup | 13 / 4 / 8 | flex and rigid-flex designs with a stackup that says polyimide |
| `passive-01005` | 01005 passives | 18 / 2 / 17 | phone-class or wearable designs with 01005 passives |
| `microvias` | microvias, blind or buried vias | 99 / 5 / 50 | HDI designs (microvias, blind or buried vias) whose human layout is DRC-clean; 5 clean ones exist |

## Additions to the tier suites

A suite should hold at least 5 (`sprint-quality`) or 10 (`ladder`) boards of every kind. Where it held fewer and the corpus has boards that meet the suite's own rules (human-clean, its footprint and layer range, an owner not yet in a sprint suite or the ladder), boards were added, each step taking the board that serves the most kinds still short, the cheapest first. The additions are separate lists: the originals are unchanged.

| list | boards | CPU-h per method-run of all |
|---|---|---|
| `sprint-quality-additions.txt` | 23 | 5.9 |
| `ladder-additions.txt` | 13 | 3.7 |

| kind | sprint-quality before | after | ladder before | after | still short because |
|---|---|---|---|---|---|
| `bga` | 2 | 2 | 12 | 14 | 33 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-balls-9-64` | 1 | 1 | 2 | 4 | 8 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-balls-65-144` | 0 | 0 | 3 | 3 | 6 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-balls-145-324` | 0 | 0 | 6 | 6 | 11 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-balls-325plus` | 1 | 1 | 1 | 1 | 8 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-pitch-0.4` | 0 | 0 | 2 | 3 | 5 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-pitch-0.5` | 1 | 1 | 0 | 1 | 6 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-pitch-0.65` | 0 | 0 | 0 | 0 | 0 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-pitch-0.8` | 0 | 0 | 8 | 8 | 15 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `bga-pitch-1.0-1.27` | 1 | 1 | 2 | 2 | 7 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `fine-pitch` | 36 | 42 | 108 | 110 | - |
| `diffpairs` | 23 | 27 | 73 | 75 | - |
| `parallel-bus` | 6 | 8 | 25 | 25 | - |
| `pours` | 75 | 92 | 254 | 264 | - |
| `inner-planes` | 37 | 37 | 136 | 137 | - |
| `double-sided` | 13 | 19 | 67 | 69 | - |
| `cutouts-slots` | 41 | 45 | 147 | 152 | - |
| `arrays` | 1 | 5 | 19 | 19 | - |
| `connectors` | 2 | 6 | 12 | 13 | - |
| `decoupling` | 49 | 51 | 122 | 124 | - |
| `buck` | 29 | 30 | 60 | 62 | - |
| `boost` | 4 | 6 | 14 | 14 | - |
| `ldo` | 30 | 33 | 97 | 99 | - |
| `power-distribution` | 21 | 23 | 58 | 59 | - |
| `battery-charging` | 2 | 5 | 12 | 13 | - |
| `mcu-core` | 35 | 36 | 88 | 91 | - |
| `crystal` | 34 | 34 | 78 | 80 | - |
| `ddr` | 0 | 1 | 5 | 5 | 16 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `ddr3` | 0 | 0 | 1 | 1 | 5 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `ddr4-ddr5` | 0 | 0 | 1 | 1 | 2 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `flash-sd` | 7 | 8 | 23 | 23 | - |
| `field-bus` | 3 | 5 | 16 | 16 | - |
| `usb` | 34 | 36 | 94 | 96 | - |
| `ethernet` | 2 | 5 | 12 | 12 | - |
| `multi-gigabit` | 3 | 4 | 10 | 10 | 22 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `sata` | 1 | 1 | 0 | 0 | 1 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `rf-antenna` | 7 | 7 | 25 | 26 | - |
| `radio-module` | 16 | 22 | 55 | 60 | - |
| `analog-opamp` | 15 | 15 | 39 | 40 | - |
| `sensors` | 8 | 9 | 29 | 30 | - |
| `audio` | 12 | 13 | 32 | 33 | - |
| `video-links` | 0 | 1 | 8 | 9 | 22 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `displays` | 7 | 7 | 39 | 40 | - |
| `motor-gate-drivers` | 5 | 5 | 13 | 14 | - |
| `isolation` | 13 | 15 | 21 | 29 | - |
| `mains` | 3 | 5 | 2 | 10 | - |
| `protection` | 8 | 8 | 32 | 33 | - |
| `keyboards` | 3 | 7 | 51 | 51 | - |
| `led-arrays` | 0 | 5 | 15 | 15 | - |
| `fpga` | 2 | 5 | 12 | 12 | - |
| `flex` | 0 | 0 | 1 | 2 | 4 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `passive-01005` | 0 | 1 | 0 | 1 | 2 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |
| `microvias` | 1 | 1 | 2 | 2 | 5 human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken |

## By size and layer count

Size by footprints: small 5-50, medium 51-150, large 151-400, very large over 400. Each cell: usable / human-clean / owners, then the kind's boards in frontier-quality-ladder-canary-own suite (additions counted in). Empty cells have no usable board.

| kind | size | 2 layers | 4 layers | 6+ layers |
|---|---|---|---|---|
| `bga` | small | 19 / 4 / 16 · 0-0-2-0-11 | 23 / 5 / 21 · 1-1-2-0-16 | 4 / 0 / 4 · 0-0-0-0-2 |
| `bga` | medium | 7 / 0 / 6 · 0-0-0-0-2 | 76 / 5 / 54 · 1-1-1-0-11 | 27 / 3 / 22 · 0-0-1-0-6 |
| `bga` | large | 5 / 1 / 4 · 0-0-1-0-0 | 63 / 5 / 47 · 1-0-3-1-6 | 92 / 5 / 64 · 0-0-4-4-6 |
| `bga` | very large |  | 15 / 0 / 8 · 0-0-0-0-0 | 97 / 5 / 44 · 0-0-0-7-0 |
| `bga-balls-9-64` | small | 14 / 3 / 12 · 0-0-2-0-10 | 11 / 3 / 10 · 0-1-1-0-6 | 1 / 0 / 1 · 0-0-0-0-1 |
| `bga-balls-9-64` | medium | 5 / 0 / 4 · 0-0-0-0-3 | 20 / 1 / 19 · 0-0-0-0-12 | 8 / 0 / 7 · 0-0-0-0-3 |
| `bga-balls-9-64` | large | 3 / 1 / 2 · 0-0-1-0-0 | 6 / 0 / 5 · 0-0-0-0-0 | 9 / 0 / 6 · 0-0-0-0-2 |
| `bga-balls-9-64` | very large |  | 6 / 0 / 3 · 0-0-0-0-0 | 6 / 0 / 6 · 0-0-0-0-0 |
| `bga-balls-65-144` | small | 3 / 1 / 3 · 0-0-0-0-2 | 8 / 2 / 8 · 0-0-1-0-7 |  |
| `bga-balls-65-144` | medium | 2 / 0 / 2 · 0-0-0-0-2 | 18 / 1 / 15 · 0-0-1-0-11 | 3 / 1 / 3 · 0-0-0-0-3 |
| `bga-balls-65-144` | large | 2 / 0 / 2 · 0-0-0-0-0 | 6 / 1 / 6 · 0-0-1-0-2 | 10 / 0 / 6 · 0-0-0-0-2 |
| `bga-balls-65-144` | very large |  | 2 / 0 / 1 · 0-0-0-0-0 | 3 / 0 / 3 · 0-0-0-0-1 |
| `bga-balls-145-324` | small | 2 / 0 / 1 · 0-0-0-0-1 | 3 / 0 / 3 · 1-0-0-0-3 | 2 / 0 / 2 · 0-0-0-0-2 |
| `bga-balls-145-324` | medium |  | 27 / 1 / 18 · 0-0-0-0-9 | 10 / 1 / 9 · 0-0-1-0-7 |
| `bga-balls-145-324` | large |  | 37 / 3 / 27 · 0-0-2-1-6 | 37 / 4 / 30 · 0-0-3-3-8 |
| `bga-balls-145-324` | very large |  | 7 / 0 / 5 · 0-0-0-0-0 | 23 / 2 / 16 · 0-0-0-2-0 |
| `bga-balls-325plus` | small |  | 1 / 0 / 1 · 0-0-0-0-1 | 1 / 0 / 1 · 0-0-0-0-0 |
| `bga-balls-325plus` | medium |  | 11 / 2 / 10 · 1-1-0-0-8 | 6 / 1 / 6 · 0-0-0-0-4 |
| `bga-balls-325plus` | large |  | 14 / 1 / 14 · 1-0-0-0-4 | 36 / 1 / 30 · 0-0-1-1-11 |
| `bga-balls-325plus` | very large |  |  | 65 / 3 / 31 · 0-0-0-5-2 |
| `bga-pitch-0.4` | small | 5 / 1 / 5 · 0-0-1-0-5 | 9 / 2 / 8 · 0-0-1-0-6 | 1 / 0 / 1 · 0-0-0-0-1 |
| `bga-pitch-0.4` | medium | 3 / 0 / 3 · 0-0-0-0-3 | 8 / 1 / 8 · 0-0-0-0-5 | 7 / 0 / 7 · 0-0-0-0-3 |
| `bga-pitch-0.4` | large | 2 / 1 / 1 · 0-0-1-0-0 | 2 / 0 / 2 · 0-0-0-0-1 | 16 / 0 / 13 · 0-0-0-1-6 |
| `bga-pitch-0.4` | very large |  | 3 / 0 / 2 · 0-0-0-0-0 | 16 / 0 / 12 · 0-0-0-0-0 |
| `bga-pitch-0.5` | small | 12 / 2 / 10 · 0-0-1-0-7 | 7 / 2 / 7 · 0-1-0-0-6 |  |
| `bga-pitch-0.5` | medium | 3 / 0 / 2 · 0-0-0-0-1 | 13 / 1 / 12 · 0-0-0-0-7 | 1 / 0 / 1 · 0-0-0-0-1 |
| `bga-pitch-0.5` | large | 1 / 0 / 1 · 0-0-0-0-0 | 11 / 0 / 8 · 0-0-0-0-2 | 14 / 0 / 11 · 0-0-0-0-2 |
| `bga-pitch-0.5` | very large |  | 1 / 0 / 1 · 0-0-0-0-0 | 20 / 1 / 14 · 0-0-0-2-4 |
| `bga-pitch-0.65` | small | 1 / 0 / 1 · 0-0-0-0-1 | 1 / 0 / 1 · 0-0-0-0-1 |  |
| `bga-pitch-0.65` | medium |  | 5 / 0 / 5 · 0-0-0-0-4 | 2 / 0 / 2 · 0-0-0-0-2 |
| `bga-pitch-0.65` | large | 1 / 0 / 1 · 0-0-0-0-1 | 4 / 0 / 4 · 0-0-0-0-2 | 8 / 0 / 6 · 0-0-0-0-3 |
| `bga-pitch-0.65` | very large |  | 1 / 0 / 1 · 0-0-0-0-1 | 9 / 0 / 7 · 0-0-0-1-5 |
| `bga-pitch-0.8` | small |  | 1 / 0 / 1 · 0-0-0-0-1 | 2 / 0 / 2 · 0-0-0-0-2 |
| `bga-pitch-0.8` | medium |  | 35 / 2 / 24 · 1-0-1-0-11 | 14 / 2 / 12 · 0-0-0-0-7 |
| `bga-pitch-0.8` | large |  | 36 / 3 / 32 · 0-0-3-1-8 | 46 / 5 / 39 · 0-0-4-3-9 |
| `bga-pitch-0.8` | very large |  | 1 / 0 / 1 · 0-0-0-0-0 | 35 / 3 / 17 · 0-0-0-3-0 |
| `bga-pitch-1.0-1.27` | small | 1 / 1 / 1 · 0-0-0-0-1 | 5 / 1 / 5 · 1-0-1-0-5 | 1 / 0 / 1 · 0-0-0-0-0 |
| `bga-pitch-1.0-1.27` | medium | 1 / 0 / 1 · 0-0-0-0-1 | 15 / 1 / 14 · 0-1-0-0-12 | 3 / 1 / 3 · 0-0-1-0-1 |
| `bga-pitch-1.0-1.27` | large | 1 / 0 / 1 · 0-0-0-0-0 | 10 / 2 / 7 · 1-0-0-0-1 | 8 / 0 / 7 · 0-0-0-0-3 |
| `bga-pitch-1.0-1.27` | very large |  | 9 / 0 / 4 · 0-0-0-0-1 | 17 / 1 / 9 · 0-0-0-1-5 |
| `fine-pitch` | small | 958 / 94 / 472 · 7-9-3-0-16 | 212 / 32 / 140 · 2-5-13-0-10 | 44 / 4 / 16 · 1-0-2-0-1 |
| `fine-pitch` | medium | 934 / 83 / 523 · 12-8-12-0-14 | 698 / 106 / 434 · 9-20-37-0-15 | 69 / 13 / 45 · 0-0-3-0-0 |
| `fine-pitch` | large | 256 / 11 / 166 · 0-0-10-0-1 | 331 / 34 / 205 · 1-0-22-1-1 | 70 / 14 / 44 · 0-0-8-0-2 |
| `fine-pitch` | very large | 32 / 1 / 29 · 0-0-0-1-0 | 45 / 2 / 29 · 0-0-0-3-0 | 41 / 3 / 20 · 0-0-0-4-0 |
| `diffpairs` | small | 305 / 47 / 207 · 3-6-1-0-22 | 128 / 22 / 81 · 0-3-10-0-6 | 20 / 0 / 12 · 0-0-0-0-0 |
| `diffpairs` | medium | 390 / 44 / 246 · 7-4-6-0-11 | 427 / 63 / 279 · 8-14-20-0-16 | 54 / 10 / 43 · 0-0-4-0-1 |
| `diffpairs` | large | 120 / 4 / 103 · 0-0-3-0-0 | 287 / 26 / 189 · 2-0-22-1-2 | 129 / 11 / 89 · 0-0-9-4-2 |
| `diffpairs` | very large | 13 / 0 / 13 · 0-0-0-0-0 | 48 / 1 / 26 · 0-0-0-2-0 | 136 / 7 / 55 · 0-0-0-10-0 |
| `parallel-bus` | small | 225 / 34 / 171 · 1-1-1-0-23 | 54 / 7 / 39 · 0-1-4-0-4 | 7 / 0 / 7 · 0-0-0-0-0 |
| `parallel-bus` | medium | 104 / 10 / 75 · 1-2-1-0-7 | 112 / 14 / 83 · 3-4-4-0-18 | 20 / 5 / 18 · 0-0-2-0-2 |
| `parallel-bus` | large | 29 / 3 / 23 · 0-0-2-0-0 | 95 / 9 / 74 · 0-0-6-1-1 | 78 / 7 / 58 · 0-0-5-4-5 |
| `parallel-bus` | very large | 4 / 0 / 4 · 0-0-0-0-0 | 13 / 0 / 10 · 0-0-0-1-0 | 108 / 3 / 45 · 0-0-0-5-0 |
| `pours` | small | 5681 / 1102 / 2045 · 15-23-43-0-21 | 583 / 122 / 314 · 7-10-52-0-6 | 168 / 11 / 34 · 1-0-2-0-1 |
| `pours` | medium | 2527 / 314 / 1215 · 14-29-45-0-19 | 1006 / 160 / 577 · 12-30-48-0-9 | 126 / 17 / 70 · 0-0-5-0-1 |
| `pours` | large | 459 / 42 / 323 · 1-0-25-0-2 | 442 / 51 / 271 · 2-0-32-2-1 | 159 / 19 / 101 · 0-0-12-4-0 |
| `pours` | very large | 51 / 6 / 42 · 0-0-0-6-0 | 68 / 2 / 40 · 0-0-0-3-0 | 132 / 8 / 55 · 0-0-0-11-0 |
| `inner-planes` | small |  | 454 / 107 / 282 · 5-8-45-0-26 | 27 / 5 / 19 · 1-0-2-0-1 |
| `inner-planes` | medium |  | 904 / 150 / 533 · 11-29-44-0-26 | 81 / 16 / 56 · 0-0-4-0-1 |
| `inner-planes` | large |  | 413 / 48 / 255 · 2-0-30-2-3 | 148 / 19 / 92 · 0-0-12-4-3 |
| `inner-planes` | very large |  | 63 / 2 / 37 · 0-0-0-3-0 | 129 / 8 / 54 · 0-0-0-11-0 |
| `double-sided` | small | 947 / 174 / 564 · 5-6-6-0-26 | 111 / 17 / 80 · 1-2-7-0-2 | 27 / 6 / 18 · 1-0-2-0-1 |
| `double-sided` | medium | 711 / 98 / 465 · 10-8-13-0-21 | 216 / 25 / 150 · 2-3-8-0-3 | 45 / 11 / 34 · 0-0-5-0-1 |
| `double-sided` | large | 217 / 20 / 162 · 1-0-13-0-3 | 140 / 13 / 100 · 0-0-7-0-0 | 111 / 13 / 70 · 0-0-8-2-3 |
| `double-sided` | very large | 20 / 1 / 18 · 0-0-0-1-0 | 17 / 0 / 11 · 0-0-0-1-0 | 106 / 7 / 45 · 0-0-0-10-0 |
| `cutouts-slots` | small | 1914 / 420 / 1115 · 8-7-18-0-23 | 178 / 38 / 140 · 1-3-16-0-4 | 26 / 2 / 10 · 1-0-0-0-1 |
| `cutouts-slots` | medium | 1451 / 204 / 899 · 14-15-34-0-17 | 586 / 97 / 405 · 6-20-33-0-10 | 70 / 11 / 43 · 0-0-5-0-1 |
| `cutouts-slots` | large | 375 / 35 / 272 · 1-0-20-0-3 | 294 / 30 / 198 · 1-0-20-2-1 | 101 / 8 / 67 · 0-0-6-3-0 |
| `cutouts-slots` | very large | 34 / 1 / 29 · 0-0-0-1-0 | 36 / 1 / 24 · 0-0-0-2-0 | 110 / 6 / 51 · 0-0-0-7-0 |
| `arrays` | small | 57 / 16 / 49 · 0-2-1-0-26 | 6 / 2 / 5 · 0-0-1-0-2 | 3 / 0 / 2 · 0-0-0-0-0 |
| `arrays` | medium | 177 / 24 / 130 · 3-2-6-0-27 | 19 / 3 / 17 · 0-1-1-0-2 | 11 / 0 / 4 · 0-0-0-0-0 |
| `arrays` | large | 78 / 4 / 68 · 0-0-4-0-2 | 20 / 4 / 19 · 0-0-4-0-0 | 8 / 3 / 7 · 0-0-2-1-1 |
| `arrays` | very large | 29 / 6 / 25 · 0-0-0-6-0 | 10 / 0 / 10 · 0-0-0-0-0 | 9 / 1 / 7 · 0-0-0-1-0 |
| `connectors` | small | 759 / 233 / 479 · 1-5-9-0-37 | 67 / 15 / 49 · 0-0-4-0-3 | 7 / 1 / 5 · 0-0-0-0-0 |
| `connectors` | medium | 60 / 10 / 50 · 0-1-0-0-17 | 6 / 0 / 6 · 0-0-0-0-2 | 3 / 0 / 3 · 0-0-0-0-1 |
| `connectors` | large | 13 / 1 / 10 · 0-0-0-0-0 |  |  |
| `connectors` | very large | 6 / 1 / 4 · 0-0-0-1-0 |  |  |
| `decoupling` | small | 370 / 54 / 261 · 1-3-1-0-17 | 103 / 19 / 86 · 2-6-5-0-9 | 9 / 1 / 7 · 0-0-0-0-0 |
| `decoupling` | medium | 1039 / 124 / 634 · 8-17-17-0-14 | 727 / 114 / 477 · 11-25-38-0-12 | 81 / 13 / 51 · 0-0-3-0-1 |
| `decoupling` | large | 313 / 34 / 232 · 1-0-22-0-2 | 423 / 44 / 265 · 2-0-26-2-2 | 162 / 19 / 102 · 0-0-12-4-3 |
| `decoupling` | very large | 40 / 1 / 35 · 0-0-0-1-0 | 69 / 2 / 41 · 0-0-0-3-0 | 140 / 8 / 58 · 0-0-0-11-0 |
| `buck` | small | 203 / 48 / 147 · 2-5-2-0-23 | 36 / 13 / 24 · 1-2-3-0-6 | 6 / 1 / 6 · 0-0-0-0-0 |
| `buck` | medium | 281 / 49 / 201 · 2-11-5-0-11 | 307 / 60 / 216 · 2-12-19-0-12 | 42 / 11 / 35 · 0-0-4-0-1 |
| `buck` | large | 71 / 5 / 60 · 1-0-3-0-1 | 224 / 19 / 148 · 2-0-17-1-3 | 114 / 15 / 81 · 0-0-9-4-3 |
| `buck` | very large | 8 / 0 / 8 · 0-0-0-0-0 | 36 / 0 / 20 · 0-0-0-1-0 | 112 / 7 / 50 · 0-0-0-10-0 |
| `boost` | small | 143 / 14 / 98 · 1-2-1-0-27 | 13 / 4 / 10 · 0-1-2-0-3 | 8 / 0 / 4 · 0-0-0-0-0 |
| `boost` | medium | 133 / 14 / 90 · 1-1-3-0-11 | 68 / 9 / 62 · 1-2-4-0-8 | 16 / 1 / 9 · 0-0-0-0-1 |
| `boost` | large | 18 / 0 / 12 · 0-0-0-0-2 | 47 / 3 / 37 · 1-0-3-1-4 | 18 / 2 / 16 · 0-0-1-0-4 |
| `boost` | very large | 6 / 0 / 5 · 0-0-0-0-0 | 3 / 1 / 3 · 0-0-0-1-0 | 12 / 1 / 9 · 0-0-0-1-0 |
| `ldo` | small | 1207 / 179 / 609 · 0-7-9-0-25 | 160 / 29 / 108 · 2-3-12-0-4 | 55 / 3 / 13 · 0-0-1-0-0 |
| `ldo` | medium | 909 / 105 / 520 · 7-10-19-0-15 | 505 / 85 / 330 · 6-13-28-0-12 | 54 / 9 / 31 · 0-0-1-0-1 |
| `ldo` | large | 184 / 11 / 137 · 0-0-5-0-1 | 259 / 25 / 175 · 1-0-18-1-1 | 96 / 10 / 54 · 0-0-6-3-1 |
| `ldo` | very large | 20 / 0 / 16 · 0-0-0-0-0 | 52 / 2 / 29 · 0-0-0-3-0 | 110 / 6 / 48 · 0-0-0-6-0 |
| `power-distribution` | small | 100 / 32 / 78 · 0-3-1-0-22 | 24 / 7 / 21 · 0-2-1-0-6 | 2 / 1 / 2 · 0-0-0-0-0 |
| `power-distribution` | medium | 274 / 46 / 185 · 2-9-6-0-13 | 256 / 46 / 183 · 2-9-16-0-10 | 40 / 8 / 35 · 0-0-4-0-1 |
| `power-distribution` | large | 73 / 7 / 63 · 1-0-6-0-2 | 247 / 23 / 170 · 1-0-16-1-3 | 123 / 10 / 81 · 0-0-9-4-3 |
| `power-distribution` | very large | 17 / 1 / 16 · 0-0-0-1-0 | 44 / 1 / 24 · 0-0-0-2-0 | 128 / 7 / 54 · 0-0-0-10-0 |
| `battery-charging` | small | 149 / 17 / 80 · 1-3-1-0-27 | 21 / 3 / 14 · 0-0-1-0-3 | 4 / 0 / 3 · 0-0-0-0-0 |
| `battery-charging` | medium | 188 / 10 / 102 · 1-2-2-0-9 | 107 / 7 / 76 · 2-0-5-0-13 | 10 / 0 / 8 · 0-0-0-0-0 |
| `battery-charging` | large | 42 / 1 / 29 · 0-0-1-0-3 | 46 / 2 / 30 · 0-0-2-0-0 | 14 / 1 / 14 · 0-0-1-0-5 |
| `battery-charging` | very large | 4 / 0 / 3 · 0-0-0-0-0 | 4 / 0 / 4 · 0-0-0-0-0 | 9 / 1 / 8 · 0-0-0-1-0 |
| `mcu-core` | small | 1029 / 162 / 648 · 5-10-13-0-22 | 125 / 13 / 80 · 1-4-3-0-4 | 36 / 4 / 13 · 1-0-2-0-1 |
| `mcu-core` | medium | 838 / 70 / 515 · 7-9-10-0-15 | 417 / 65 / 301 · 6-13-26-0-13 | 51 / 11 / 33 · 0-0-1-0-1 |
| `mcu-core` | large | 255 / 19 / 189 · 0-0-15-0-2 | 205 / 18 / 152 · 1-0-15-1-1 | 52 / 10 / 43 · 0-0-5-0-1 |
| `mcu-core` | very large | 22 / 0 / 20 · 0-0-0-0-0 | 33 / 1 / 24 · 0-0-0-2-0 | 53 / 5 / 29 · 0-0-0-7-0 |
| `crystal` | small | 654 / 55 / 417 · 3-6-2-0-23 | 102 / 11 / 77 · 2-4-1-0-5 | 15 / 1 / 6 · 0-0-1-0-0 |
| `crystal` | medium | 718 / 49 / 451 · 6-6-8-0-9 | 470 / 76 / 301 · 8-18-27-0-17 | 52 / 11 / 42 · 0-0-4-0-1 |
| `crystal` | large | 227 / 17 / 167 · 0-0-11-0-3 | 265 / 25 / 192 · 1-0-18-2-1 | 97 / 12 / 69 · 0-0-8-4-1 |
| `crystal` | very large | 22 / 0 / 20 · 0-0-0-0-0 | 36 / 0 / 26 · 0-0-0-0-0 | 108 / 7 / 52 · 0-0-0-9-0 |
| `ddr` | small | 2 / 0 / 2 · 0-0-0-0-2 | 3 / 1 / 2 · 0-0-1-0-1 | 1 / 0 / 1 · 0-0-0-0-1 |
| `ddr` | medium | 8 / 1 / 7 · 0-1-0-0-6 | 31 / 1 / 18 · 1-0-0-0-11 | 11 / 4 / 9 · 0-0-1-0-5 |
| `ddr` | large | 3 / 0 / 3 · 0-0-0-0-1 | 30 / 2 / 26 · 0-0-0-1-9 | 50 / 4 / 42 · 0-0-3-3-16 |
| `ddr` | very large |  | 1 / 0 / 1 · 0-0-0-0-0 | 58 / 3 / 31 · 0-0-0-5-0 |
| `ddr3` | medium |  | 3 / 0 / 3 · 1-0-0-0-3 | 1 / 0 / 1 · 0-0-0-0-1 |
| `ddr3` | large |  | 13 / 0 / 11 · 0-0-0-1-6 | 29 / 2 / 25 · 0-0-1-2-12 |
| `ddr3` | very large |  |  | 30 / 3 / 19 · 0-0-0-3-8 |
| `ddr4-ddr5` | medium |  | 1 / 0 / 1 · 0-0-0-0-1 | 1 / 1 / 1 · 0-0-0-0-1 |
| `ddr4-ddr5` | large |  |  | 4 / 1 / 3 · 0-0-1-0-2 |
| `ddr4-ddr5` | very large |  |  | 2 / 0 / 2 · 0-0-0-0-2 |
| `flash-sd` | small | 58 / 8 / 44 · 0-2-1-0-18 | 23 / 1 / 18 · 1-1-0-0-6 | 2 / 0 / 1 · 0-0-0-0-0 |
| `flash-sd` | medium | 133 / 7 / 89 · 3-1-1-0-9 | 116 / 18 / 84 · 1-4-6-0-15 | 22 / 7 / 17 · 0-0-4-0-4 |
| `flash-sd` | large | 44 / 3 / 30 · 0-0-2-0-0 | 97 / 6 / 75 · 1-0-5-2-2 | 44 / 7 / 37 · 0-0-4-0-6 |
| `flash-sd` | very large | 4 / 0 / 4 · 0-0-0-0-0 | 12 / 0 / 11 · 0-0-0-0-0 | 66 / 4 / 36 · 0-0-0-7-0 |
| `field-bus` | small | 112 / 14 / 73 · 0-3-1-0-32 | 7 / 1 / 7 · 1-0-0-0-4 | 1 / 0 / 1 · 0-0-0-0-0 |
| `field-bus` | medium | 88 / 9 / 62 · 0-0-3-0-12 | 63 / 9 / 50 · 1-2-4-0-10 | 9 / 3 / 8 · 0-0-0-0-1 |
| `field-bus` | large | 20 / 2 / 15 · 0-0-1-0-0 | 42 / 7 / 35 · 0-0-6-0-1 | 16 / 4 / 13 · 0-0-1-0-0 |
| `field-bus` | very large | 2 / 0 / 2 · 0-0-0-0-0 | 7 / 0 / 6 · 0-0-0-0-0 | 13 / 2 / 11 · 0-0-0-2-0 |
| `usb` | small | 787 / 87 / 469 · 3-6-4-0-23 | 162 / 25 / 109 · 2-5-9-0-7 | 25 / 1 / 9 · 0-0-1-0-0 |
| `usb` | medium | 793 / 71 / 474 · 9-7-11-0-8 | 595 / 82 / 381 · 9-18-30-0-16 | 60 / 10 / 43 · 0-0-4-0-1 |
| `usb` | large | 264 / 12 / 181 · 1-0-10-0-2 | 298 / 23 / 203 · 1-0-18-2-1 | 109 / 11 / 76 · 0-0-9-3-2 |
| `usb` | very large | 26 / 0 / 24 · 0-0-0-0-0 | 38 / 0 / 28 · 0-0-0-0-0 | 112 / 7 / 53 · 0-0-0-10-0 |
| `ethernet` | small | 23 / 4 / 20 · 0-3-0-0-19 | 9 / 2 / 7 · 0-0-2-0-6 | 1 / 0 / 1 · 0-0-0-0-0 |
| `ethernet` | medium | 55 / 1 / 39 · 1-0-0-0-14 | 46 / 7 / 35 · 1-2-3-0-6 | 15 / 3 / 14 · 0-0-3-0-4 |
| `ethernet` | large | 8 / 0 / 8 · 0-0-0-0-1 | 57 / 4 / 38 · 0-0-4-0-6 | 33 / 0 / 27 · 0-0-0-1-4 |
| `ethernet` | very large | 3 / 0 / 3 · 0-0-0-0-0 | 16 / 0 / 8 · 0-0-0-0-0 | 74 / 5 / 34 · 0-0-0-8-0 |
| `multi-gigabit` | small | 10 / 1 / 7 · 1-1-0-0-7 | 12 / 2 / 10 · 0-1-0-0-7 | 3 / 0 / 3 · 0-0-0-0-3 |
| `multi-gigabit` | medium | 8 / 1 / 7 · 0-0-0-0-5 | 44 / 6 / 31 · 0-2-2-0-17 | 10 / 2 / 9 · 0-0-2-0-4 |
| `multi-gigabit` | large | 5 / 0 / 4 · 0-0-0-0-0 | 35 / 2 / 26 · 1-0-2-0-5 | 45 / 5 / 32 · 0-0-4-1-8 |
| `multi-gigabit` | very large |  | 1 / 0 / 1 · 0-0-0-0-0 | 73 / 3 / 33 · 0-0-0-6-0 |
| `sata` | small | 1 / 0 / 1 · 0-0-0-0-1 | 1 / 1 / 1 · 0-1-0-0-1 |  |
| `sata` | medium |  | 2 / 0 / 2 · 0-0-0-0-2 |  |
| `sata` | large |  | 2 / 0 / 2 · 0-0-0-0-2 | 1 / 0 / 1 · 0-0-0-0-0 |
| `sata` | very large |  |  | 6 / 0 / 5 · 0-0-0-1-5 |
| `rf-antenna` | small | 276 / 48 / 150 · 2-2-2-0-20 | 96 / 15 / 54 · 0-1-7-0-5 | 9 / 2 / 7 · 0-0-1-0-1 |
| `rf-antenna` | medium | 201 / 17 / 122 · 2-0-2-0-12 | 172 / 21 / 114 · 5-4-7-0-16 | 12 / 2 / 10 · 0-0-0-0-0 |
| `rf-antenna` | large | 39 / 2 / 31 · 0-0-1-0-1 | 114 / 10 / 70 · 1-0-4-1-4 | 38 / 2 / 29 · 0-0-2-2-1 |
| `rf-antenna` | very large | 7 / 0 / 6 · 0-0-0-0-0 | 25 / 1 / 14 · 0-0-0-1-0 | 74 / 4 / 34 · 0-0-0-5-0 |
| `radio-module` | small | 768 / 150 / 500 · 1-9-9-0-27 | 81 / 18 / 60 · 1-1-8-0-2 | 14 / 2 / 7 · 0-0-1-0-0 |
| `radio-module` | medium | 518 / 61 / 347 · 5-4-14-0-13 | 282 / 38 / 209 · 8-8-16-0-12 | 20 / 3 / 16 · 0-0-0-0-0 |
| `radio-module` | large | 96 / 8 / 80 · 1-0-5-0-3 | 124 / 9 / 88 · 1-0-6-1-2 | 36 / 2 / 31 · 0-0-1-1-1 |
| `radio-module` | very large | 8 / 0 / 7 · 0-0-0-0-0 | 14 / 0 / 11 · 0-0-0-0-0 | 39 / 1 / 26 · 0-0-0-2-0 |
| `analog-opamp` | small | 361 / 92 / 231 · 0-0-4-0-25 | 33 / 8 / 24 · 0-1-2-0-3 | 7 / 0 / 5 · 0-0-0-0-0 |
| `analog-opamp` | medium | 511 / 85 / 279 · 2-6-9-0-20 | 143 / 26 / 116 · 0-8-6-0-7 | 9 / 0 / 8 · 0-0-0-0-0 |
| `analog-opamp` | large | 103 / 12 / 80 · 0-0-5-0-4 | 124 / 22 / 91 · 0-0-12-0-1 | 26 / 1 / 20 · 0-0-1-2-0 |
| `analog-opamp` | very large | 16 / 2 / 14 · 0-0-0-2-0 | 41 / 2 / 20 · 0-0-0-3-0 | 40 / 4 / 23 · 0-0-0-4-0 |
| `adc-dac` | small | 166 / 28 / 107 · 0-1-0-0-28 | 12 / 1 / 11 · 0-0-1-0-2 | 6 / 0 / 5 · 0-0-0-0-0 |
| `adc-dac` | medium | 152 / 20 / 115 · 1-2-2-0-13 | 76 / 8 / 66 · 0-3-2-0-6 | 5 / 0 / 5 · 0-0-0-0-1 |
| `adc-dac` | large | 28 / 2 / 27 · 0-0-1-0-2 | 80 / 11 / 61 · 0-0-7-0-6 | 20 / 5 / 16 · 0-0-5-2-2 |
| `adc-dac` | very large | 4 / 0 / 4 · 0-0-0-0-0 | 31 / 0 / 15 · 0-0-0-1-0 | 52 / 2 / 23 · 0-0-0-2-0 |
| `sensors` | small | 526 / 80 / 232 · 1-2-4-0-25 | 52 / 12 / 31 · 1-0-4-0-4 | 17 / 2 / 11 · 1-0-0-0-1 |
| `sensors` | medium | 252 / 25 / 176 · 2-2-3-0-11 | 159 / 21 / 123 · 2-5-7-0-8 | 28 / 3 / 24 · 0-0-2-0-0 |
| `sensors` | large | 46 / 4 / 34 · 1-0-2-0-2 | 85 / 6 / 57 · 0-0-4-0-3 | 46 / 6 / 35 · 0-0-4-0-6 |
| `sensors` | very large | 6 / 0 / 5 · 0-0-0-0-0 | 18 / 0 / 8 · 0-0-0-0-0 | 66 / 2 / 24 · 0-0-0-3-0 |
| `audio` | small | 277 / 80 / 181 · 1-2-5-0-25 | 28 / 7 / 20 · 1-0-3-0-2 | 8 / 0 / 3 · 0-0-0-0-0 |
| `audio` | medium | 379 / 62 / 195 · 1-4-7-0-22 | 119 / 26 / 86 · 0-7-8-0-6 | 17 / 1 / 7 · 0-0-0-0-0 |
| `audio` | large | 72 / 11 / 51 · 0-0-3-0-2 | 75 / 10 / 56 · 0-0-5-0-1 | 21 / 2 / 19 · 0-0-2-0-2 |
| `audio` | very large | 11 / 2 / 9 · 0-0-0-2-0 | 11 / 1 / 11 · 0-0-0-1-0 | 25 / 1 / 15 · 0-0-0-2-0 |
| `video-links` | small | 17 / 4 / 14 · 1-1-1-0-13 | 16 / 3 / 12 · 0-0-1-0-10 | 2 / 0 / 2 · 0-0-0-0-1 |
| `video-links` | medium | 9 / 2 / 8 · 0-0-0-0-5 | 48 / 4 / 29 · 0-0-1-0-12 | 15 / 1 / 14 · 0-0-1-0-7 |
| `video-links` | large | 5 / 0 / 4 · 0-0-0-0-0 | 58 / 3 / 31 · 0-0-3-1-3 | 47 / 2 / 29 · 0-0-2-2-9 |
| `video-links` | very large |  | 10 / 0 / 2 · 0-0-0-1-0 | 68 / 3 / 33 · 0-0-0-6-0 |
| `displays` | small | 550 / 133 / 390 · 2-1-6-0-28 | 29 / 4 / 25 · 0-1-2-0-1 | 32 / 0 / 6 · 0-0-0-0-0 |
| `displays` | medium | 471 / 51 / 332 · 3-2-9-0-23 | 79 / 13 / 75 · 0-3-5-0-2 | 25 / 1 / 7 · 0-0-0-0-0 |
| `displays` | large | 127 / 15 / 114 · 1-0-8-0-5 | 56 / 7 / 46 · 0-0-6-1-1 | 21 / 4 / 17 · 0-0-3-1-0 |
| `displays` | very large | 9 / 0 / 8 · 0-0-0-0-0 | 14 / 0 / 9 · 0-0-0-0-0 | 27 / 2 / 17 · 0-0-0-2-0 |
| `motor-gate-drivers` | small | 95 / 24 / 85 · 0-2-1-0-33 | 18 / 2 / 13 · 0-0-1-0-3 | 9 / 2 / 6 · 1-0-1-0-1 |
| `motor-gate-drivers` | medium | 99 / 8 / 81 · 1-1-1-0-13 | 81 / 12 / 60 · 0-2-5-0-8 | 11 / 2 / 6 · 0-0-0-0-0 |
| `motor-gate-drivers` | large | 18 / 0 / 18 · 0-0-0-0-0 | 37 / 4 / 30 · 0-0-3-0-1 | 15 / 5 / 14 · 0-0-2-0-1 |
| `motor-gate-drivers` | very large | 1 / 0 / 1 · 0-0-0-0-0 | 3 / 0 / 3 · 0-0-0-0-0 | 6 / 1 / 6 · 0-0-0-1-0 |
| `isolation` | small | 244 / 75 / 183 · 0-5-5-0-29 | 21 / 5 / 17 · 0-1-1-0-4 | 1 / 0 / 1 · 0-0-0-0-0 |
| `isolation` | medium | 237 / 37 / 175 · 1-5-6-0-15 | 70 / 14 / 53 · 1-4-6-0-6 | 4 / 1 / 3 · 0-0-0-0-0 |
| `isolation` | large | 40 / 5 / 32 · 1-0-2-0-3 | 60 / 11 / 42 · 0-0-9-0-2 | 12 / 0 / 10 · 0-0-0-0-1 |
| `isolation` | very large | 4 / 0 / 4 · 0-0-0-0-0 | 12 / 0 / 8 · 0-0-0-0-0 | 16 / 1 / 11 · 0-0-0-1-0 |
| `mains` | small | 37 / 13 / 32 · 0-4-5-0-31 | 1 / 1 / 1 · 0-0-1-0-1 |  |
| `mains` | medium | 31 / 3 / 24 · 0-1-2-0-13 | 5 / 1 / 4 · 0-0-1-0-3 |  |
| `mains` | large | 1 / 0 / 1 · 0-0-0-0-0 | 3 / 1 / 3 · 0-0-1-0-1 | 2 / 0 / 1 · 0-0-0-0-0 |
| `mains` | very large | 1 / 0 / 1 · 0-0-0-0-0 |  |  |
| `protection` | small | 128 / 32 / 102 · 1-1-4-0-24 | 29 / 3 / 23 · 0-0-3-0-2 | 2 / 0 / 2 · 0-0-0-0-0 |
| `protection` | medium | 138 / 31 / 109 · 2-3-6-0-14 | 109 / 27 / 77 · 3-4-8-0-14 | 8 / 0 / 8 · 0-0-0-0-1 |
| `protection` | large | 81 / 7 / 52 · 0-0-6-0-0 | 46 / 8 / 38 · 0-0-6-0-2 | 18 / 1 / 13 · 0-0-0-1-3 |
| `protection` | very large | 2 / 0 / 2 · 0-0-0-0-0 | 4 / 0 / 3 · 0-0-0-0-0 | 18 / 0 / 12 · 0-0-0-0-0 |
| `keyboards` | small | 259 / 75 / 202 · 0-2-6-0-28 |  |  |
| `keyboards` | medium | 553 / 97 / 356 · 5-3-22-0-24 | 20 / 5 / 18 · 0-2-1-0-1 | 2 / 0 / 1 · 0-0-0-0-0 |
| `keyboards` | large | 239 / 24 / 178 · 0-0-17-0-6 | 28 / 5 / 27 · 0-0-3-1-0 | 7 / 2 / 6 · 0-0-2-1-1 |
| `keyboards` | very large | 13 / 0 / 12 · 0-0-0-0-0 | 10 / 0 / 7 · 0-0-0-0-0 | 3 / 0 / 3 · 0-0-0-0-0 |
| `led-arrays` | small | 16 / 2 / 14 · 0-0-1-0-12 |  | 1 / 0 / 1 · 0-0-0-0-1 |
| `led-arrays` | medium | 89 / 15 / 70 · 2-5-2-0-38 | 11 / 1 / 11 · 0-0-1-0-1 | 1 / 0 / 1 · 0-0-0-0-0 |
| `led-arrays` | large | 77 / 12 / 59 · 0-0-9-0-5 | 15 / 3 / 14 · 0-0-2-1-0 | 3 / 0 / 3 · 0-0-0-0-0 |
| `led-arrays` | very large | 6 / 0 / 6 · 0-0-0-0-0 | 6 / 0 / 5 · 0-0-0-0-0 |  |
| `fpga` | small | 43 / 5 / 33 · 0-1-0-0-23 | 10 / 0 / 10 · 0-0-0-0-5 | 2 / 0 / 2 · 0-0-0-0-1 |
| `fpga` | medium | 25 / 3 / 23 · 0-2-1-0-10 | 71 / 7 / 50 · 1-2-2-0-11 | 10 / 2 / 10 · 0-0-0-0-4 |
| `fpga` | large | 18 / 1 / 9 · 0-0-1-0-0 | 44 / 6 / 39 · 1-0-3-0-3 | 50 / 6 / 41 · 0-0-5-2-3 |
| `fpga` | very large | 1 / 0 / 1 · 0-0-0-0-0 | 9 / 1 / 8 · 0-0-0-1-0 | 57 / 3 / 27 · 0-0-0-4-0 |
| `flex` | small | 7 / 4 / 5 · 0-0-2-0-5 | 1 / 0 / 1 · 0-0-0-0-1 |  |
| `flex` | medium |  |  | 2 / 0 / 1 · 0-0-0-0-1 |
| `flex` | large | 1 / 0 / 1 · 0-0-0-0-0 |  |  |
| `flex` | very large | 1 / 0 / 1 · 0-0-0-0-1 |  | 1 / 0 / 1 · 0-0-0-0-0 |
| `passive-01005` | small | 2 / 1 / 2 · 0-1-0-0-2 |  |  |
| `passive-01005` | medium | 3 / 1 / 3 · 1-0-1-0-3 | 8 / 0 / 7 · 0-0-0-0-7 | 1 / 0 / 1 · 0-0-0-0-1 |
| `passive-01005` | very large |  |  | 4 / 0 / 4 · 0-0-0-0-4 |
| `microvias` | small | 4 / 0 / 4 · 0-0-0-0-4 | 12 / 1 / 7 · 0-0-0-0-6 |  |
| `microvias` | medium | 6 / 0 / 5 · 0-0-0-0-4 | 39 / 3 / 17 · 0-1-1-0-12 | 5 / 0 / 5 · 0-0-0-0-3 |
| `microvias` | large | 3 / 1 / 3 · 0-0-1-0-0 | 5 / 0 / 2 · 0-0-0-0-0 | 9 / 0 / 8 · 0-0-0-0-1 |
| `microvias` | very large |  | 2 / 0 / 2 · 0-0-0-0-0 | 14 / 0 / 10 · 0-0-0-0-0 |
