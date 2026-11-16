<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Net-exempt hot-loop keep-outs, loop nets only: re-pilot with the restart portfolio (fork c226cce, kae a15c2e23)

hotloop-ab N recipe (restart.py, 4 at once, 900 s x sqrt(fp/40), last mile + finish), seeds 0 and 1, operating facts compiled-9867d0b, evaluator hotloop-eval 439fe21a (`--scope losses --drc`). N0: no hot-loop stage; H: keep-out exempt hard; S: soft (cost 4); all on fork c226cce (base d137fd1). Evaluations of sstv, gecko5 (seed 1, H, S), nekoink seed 1 and librewave N0 were still running when this was written. Cells: L nH / R mOhm / loop_ac mW.

```
## berkeleyauv-robosub-hw-noggin
  N0  s0 u0 e8 759s {'footprint_type_mismatch': 8} | s1 u1 e8 963s {'footprint_type_mismatch': 8}
  H   s0 u2 e8 1059s {'footprint_type_mismatch': 8} | s1 u1 e8 1068s {'footprint_type_mismatch': 8}
  S   s0 u1 e8 1064s {'footprint_type_mismatch': 8} | s1 u0 e8 625s {'footprint_type_mismatch': 8}
    cell:half_bridge:U6    N00 0.56/1.5/1.24  N01 0.90/2.9/2.42  H0 0.98/3.1/2.53  H1 1.31/4.7/3.83  S0 0.75/2.3/1.92  S1 0.99/3.4/2.79
## buildacubesat-project-bac-hardware-bq253
  N0  s0 u0 e1 288s {'copper_edge_clearance': 1} | s1 u0 e1 177s {'copper_edge_clearance': 1}
  H   s0 u0 e1 153s {'copper_edge_clearance': 1} | s1 u0 e1 280s {'copper_edge_clearance': 1}
  S   s0 u0 e1 176s {'copper_edge_clearance': 1} | s1 u0 e1 293s {'copper_edge_clearance': 1}
    cell:buck:U1           N00 2.08/5.1/0.32  N01 2.63/6.6/0.406  H0 1.66/5.3/0.293  H1 1.66/5.3/0.294  S0 1.52/4.6/0.267  S1 1.31/3.8/0.219
## dimoustroufis-librewave-ecp5-librewave-e
  N0  s0 u7 e6 1786s {'courtyards_overlap': 6} | s1 u10 e6 1768s {'courtyards_overlap': 6}
  H   s0 u26 e6 1778s {'courtyards_overlap': 6} | s1 u28 e6 1781s {'courtyards_overlap': 6}
  S   s0 u19 e6 1766s {'courtyards_overlap': 6} | s1 u7 e6 1774s {'courtyards_overlap': 6}
    cell:buck:U701         N00 -  N01 -  H0 0.73/4.4/0.327  H1 -  S0 1.38/11.3/0.852  S1 -
    cell:buck:U702         N00 -  N01 -  H0 0.79/4.9/0.286  H1 -  S0 3.34/55.2/3.08  S1 -
    cell:buck:U703         N00 -  N01 -  H0 OPEN  H1 -  S0 OPEN  S1 -
## govish-fusion-pack-buck-converter-subboa
  N0  s0 u0 e5 49s {'courtyards_overlap': 5} | s1 u0 e5 59s {'courtyards_overlap': 5}
  H   s0 u0 e5 45s {'courtyards_overlap': 5} | s1 u0 e5 56s {'courtyards_overlap': 5}
  S   s0 u0 e5 56s {'courtyards_overlap': 5} | s1 u0 e5 67s {'courtyards_overlap': 5}
    cell:buck:U1           N00 1.83/5.2/0.156  N01 1.76/4.9/0.148  H0 1.98/6.5/0.199  H1 2.18/6.5/0.193  S0 1.97/6.5/0.2  S1 1.76/5.0/0.148
## livitup-hrv-sstv-badge-defcon-sstv-badge
  N0  s0 u20 e4 1632s {'hole_clearance': 4} | s1 u22 e4 1631s {'hole_clearance': 4}
  H   s0 u21 e4 1595s {'hole_clearance': 4} | s1 u17 e4 1616s {'hole_clearance': 4}
  S   s0 u19 e4 1625s {'hole_clearance': 4} | s1 u29 e4 1627s {'hole_clearance': 4}
## logisim-evolution-gecko5education-gecko5
  N0  s0 u48 e0 2473s {} | s1 u26 e0 2485s {}
  H   s0 u76 e0 2475s {} | s1 u65 e0 2448s {}
  S   s0 u38 e0 2442s {} | s1 u36 e0 2484s {}
    cell:buck:U13          N00 2.46/15.4/1.75  N01 -  H0 -  H1 -  S0 -  S1 -
    cell:buck:U14          N00 1.84/13.1/1.45  N01 -  H0 -  H1 -  S0 -  S1 -
## shazmeenshz-esp32-flight-controller-flig
  N0  s0 u0 e0 126s {} | s1 u0 e0 269s {}
  H   s0 u0 e0 150s {} | s1 u1 e0 1093s {}
  S   s0 u0 e0 152s {} | s1 u0 e0 721s {}
    cell:buck:U6           N00 8.21/19.6/1.62  N01 20.22/53.5/4.43  H0 20.05/56.6/4.7  H1 17.79/63.1/5.23  S0 8.51/52.7/4.37  S1 6.08/69.4/51.9
## zephray-nekoink-pcb-2
  N0  s0 u105 e11 2157s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'solder_mask_bridge': 2} | s1 u140 e13 2156s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 2, 'solder_mask_bridge': 2}
  H   s0 u145 e13 2139s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 2, 'solder_mask_bridge': 2} | s1 u146 e13 2151s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 2, 'solder_mask_bridge': 2}
  S   s0 u145 e14 2153s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 3, 'solder_mask_bridge': 2} | s1 u118 e16 2149s {'shorting_items': 2, 'zones_intersect': 1, 'footprint_type_mismatch': 6, 'starved_thermal': 5, 'solder_mask_bridge': 2}
    cell:boost:U2          N00 1.92/13.7/0.383  N01 -  H0 2.57/15.8/0.313  H1 -  S0 OPEN  S1 -
    cell:buck:U1           N00 OPEN  N01 -  H0 OPEN  H1 -  S0 OPEN  S1 -
    cell:buck:U1:2         N00 OPEN  N01 -  H0 OPEN  H1 -  S0 OPEN  S1 -
    cell:buck:U1:3         N00 OPEN  N01 -  H0 OPEN  H1 -  S0 OPEN  S1 -
    cell:buck:U3           N00 OPEN  N01 -  H0 OPEN  H1 -  S0 OPEN  S1 -

## totals (seed 0, seed 1)
  N0  unconnected [0, 1, 0, 0, 7, 10, 0, 0, 20, 22, 48, 26, 0, 0, 105, 140] sum 379  errors [8, 8, 1, 1, 6, 6, 5, 5, 4, 4, 0, 0, 0, 0, 11, 13] sum 72  wall 18778 s
  H   unconnected [2, 1, 0, 0, 26, 28, 0, 0, 21, 17, 76, 65, 0, 1, 145, 146] sum 528  errors [8, 8, 1, 1, 6, 6, 5, 5, 4, 4, 0, 0, 0, 0, 13, 13] sum 74  wall 19887 s
  S   unconnected [1, 0, 0, 0, 19, 7, 0, 0, 19, 29, 38, 36, 0, 0, 145, 118] sum 412  errors [8, 8, 1, 1, 6, 6, 5, 5, 4, 4, 0, 0, 0, 0, 14, 16] sum 78  wall 19174 s
  H/N0 median per cell (paired by seed): L 1.237 R 1.24 loop_ac 1.278 over 9 cell-runs
  S/N0 median per cell (paired by seed): L 1.036 R 1.243 loop_ac 1.215 over 9 cell-runs
```
