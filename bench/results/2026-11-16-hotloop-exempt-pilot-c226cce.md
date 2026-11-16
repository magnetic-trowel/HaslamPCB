<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Net-exempt hot-loop keep-outs: pilot (fork c226cce, kae 35eade1a)

Eight converter boards, route tasks (corpus board, routing stripped), one `kae.route.cli route --seed 0 --time 600` attempt per arm (no restart portfolio), operating facts compiled-9867d0b, KiCad 10.0.7. Arms: N production fork 2e1125a, no hot-loop stage; N0 this build (base d137fd1), no stage; H `KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_KEEPOUT_EXEMPT=hard`; S the same with `soft` (cost 4). Physics: `kae.excite.evaluate --scope losses --drc` at hotloop-eval 5de3cc65, per cell L_loop (nH) / R_loop (mOhm) at f_sw. sstv physics was still running. Scripts: `tools/research/routing/hotloop_exempt_pilot.sh`, `hotloop_exempt_summary.py`.

```
## antmicro-arvsom-arvsom
  N   unconnected  752 errors  238 route     580 s {'shorting_items': 21, 'clearance': 3, 'zones_intersect': 1, 'courtyards_overlap': 2, 'copper_edge_clearance': 44, 'starved_thermal': 3, 'solder_mask_bridge': 164}
  N0  unconnected  663 errors  237 route     592 s {'shorting_items': 21, 'clearance': 3, 'zones_intersect': 1, 'courtyards_overlap': 2, 'copper_edge_clearance': 44, 'starved_thermal': 2, 'solder_mask_bridge': 164}
  H   unconnected 1020 errors  238 route     594 s {'shorting_items': 21, 'clearance': 3, 'zones_intersect': 1, 'courtyards_overlap': 2, 'copper_edge_clearance': 44, 'starved_thermal': 3, 'solder_mask_bridge': 164}
  S   unconnected  866 errors  238 route     591 s {'shorting_items': 21, 'clearance': 3, 'zones_intersect': 1, 'courtyards_overlap': 2, 'copper_edge_clearance': 44, 'starved_thermal': 3, 'solder_mask_bridge': 164}
    cell:cell:buck:U2:3          N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U2:4          N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U2:5          N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U4            N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U6            N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:half_bridge:U2     N OPEN  N0 OPEN  H OPEN  S OPEN
## buildacubesat-project-bac-hardware-bq25306-charger-module-v1
  N   unconnected    0 errors    1 route     169 s {'copper_edge_clearance': 1}
  N0  unconnected    0 errors    1 route     153 s {'copper_edge_clearance': 1}
  H   unconnected    1 errors    1 route     496 s {'copper_edge_clearance': 1}
  S   unconnected    0 errors    1 route     183 s {'copper_edge_clearance': 1}
    cell:cell:buck:U1            N 4.26/9.8  N0 4.26/9.8  H 4.39/10.5  S 2.60/6.7
## govish-fusion-pack-buck-converter-subboard-0-2
  N   unconnected    0 errors    5 route      31 s {'courtyards_overlap': 5}
  N0  unconnected    0 errors    5 route      27 s {'courtyards_overlap': 5}
  H   unconnected    0 errors    5 route      34 s {'courtyards_overlap': 5}
  S   unconnected    0 errors    5 route      33 s {'courtyards_overlap': 5}
    cell:cell:buck:U1            N 1.64/3.6  N0 1.64/3.6  H 1.83/4.1  S 1.83/4.1
## livitup-hrv-sstv-badge-defcon-sstv-badge
  N   unconnected   34 errors    4 route     602 s {'hole_clearance': 4}
  N0  unconnected   33 errors    4 route     588 s {'hole_clearance': 4}
  H   unconnected   40 errors    4 route     594 s {'hole_clearance': 4}
  S   unconnected   45 errors    4 route     615 s {'hole_clearance': 4}
## logisim-evolution-gecko5education-gecko5education
  N   unconnected  255 errors    0 route     553 s {}
  N0  unconnected  189 errors    0 route     557 s {}
  H   unconnected  187 errors    0 route     582 s {}
  S   unconnected  308 errors    0 route     581 s {}
    cell:cell:buck:U13           N 3.58/14.0  N0 2.14/16.1  H 1.88/15.4  S OPEN
    cell:cell:buck:U14           N 3.14/10.5  N0 1.27/26.5  H 1.91/13.7  S -19388.17/99185693.7
## seniordesignmay1607-pcb-hdmi2rgb-hdmi2rgb
  N   unconnected   12 errors   23 route     673 s {'annular_width': 6, 'zones_intersect': 1, 'courtyards_overlap': 7, 'copper_edge_clearance': 4, 'starved_thermal': 5}
  N0  unconnected   12 errors   23 route     698 s {'annular_width': 6, 'zones_intersect': 1, 'courtyards_overlap': 7, 'copper_edge_clearance': 4, 'starved_thermal': 5}
  H   unconnected   11 errors   23 route     630 s {'annular_width': 6, 'zones_intersect': 1, 'courtyards_overlap': 7, 'copper_edge_clearance': 4, 'starved_thermal': 5}
  S   unconnected   12 errors   23 route     620 s {'annular_width': 6, 'zones_intersect': 1, 'courtyards_overlap': 7, 'copper_edge_clearance': 4, 'starved_thermal': 5}
    cell:cell:buck:U10           N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U11           N OPEN  N0 OPEN  H OPEN  S OPEN
## shazmeenshz-esp32-flight-controller-flight-controller-rev2
  N   unconnected    0 errors    0 route     157 s {}
  N0  unconnected    0 errors    0 route     138 s {}
  H   unconnected    1 errors    0 route     256 s {}
  S   unconnected    1 errors    0 route     242 s {}
    cell:cell:buck:U6            N 8.83/56.7  N0 9.46/60.0  H 7.66/16.7  S 8.00/19.4
## zephray-nekoink-pcb-2
  N   unconnected  156 errors   20 route     572 s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 9, 'solder_mask_bridge': 2}
  N0  unconnected  154 errors   16 route     575 s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 5, 'solder_mask_bridge': 2}
  H   unconnected  199 errors   52 route     594 s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 41, 'solder_mask_bridge': 2}
  S   unconnected  210 errors   51 route     580 s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 40, 'solder_mask_bridge': 2}
    cell:cell:boost:U2           N 2.90/22.4  N0 1.98/14.3  H OPEN  S OPEN
    cell:cell:buck:U1            N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U1:2          N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U1:3          N OPEN  N0 OPEN  H OPEN  S OPEN
    cell:cell:buck:U3            N OPEN  N0 OPEN  H OPEN  S OPEN

## totals
  N   unconnected 1209 errors 291 route 3337 s {'shorting_items': 23, 'clearance': 3, 'zones_intersect': 3, 'courtyards_overlap': 14, 'copper_edge_clearance': 49, 'starved_thermal': 17, 'solder_mask_bridge': 166, 'hole_clearance': 4, 'annular_width': 6, 'footprint_type_mismatch': 6}
  N0  unconnected 1051 errors 286 route 3328 s {'shorting_items': 23, 'clearance': 3, 'zones_intersect': 3, 'courtyards_overlap': 14, 'copper_edge_clearance': 49, 'starved_thermal': 12, 'solder_mask_bridge': 166, 'hole_clearance': 4, 'annular_width': 6, 'footprint_type_mismatch': 6}
  H   unconnected 1459 errors 323 route 3780 s {'shorting_items': 23, 'clearance': 3, 'zones_intersect': 3, 'courtyards_overlap': 14, 'copper_edge_clearance': 49, 'starved_thermal': 49, 'solder_mask_bridge': 166, 'hole_clearance': 4, 'annular_width': 6, 'footprint_type_mismatch': 6}
  S   unconnected 1442 errors 322 route 3446 s {'shorting_items': 23, 'clearance': 3, 'zones_intersect': 3, 'courtyards_overlap': 14, 'copper_edge_clearance': 49, 'starved_thermal': 48, 'solder_mask_bridge': 166, 'hole_clearance': 4, 'annular_width': 6, 'footprint_type_mismatch': 6}
  N0/N median per cell: L 1.0, R 1.0587387037560012 over 6 cells
  H/N median per cell: L 1.0301244423573608, R 1.1467874657135733 over 6 cells
  S/N median per cell: L 1.1175643455401358, R 9477215.447050842 over 6 cells
```
