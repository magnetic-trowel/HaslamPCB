# Mechanism suites: the table

Written by `tools/kaeres/mechsuites.py`; read [README](README.md) first.

| suite | boards have | boards | human-clean | 4+ layers | footprints, median (range) | CPU-h per arm | stored control | tier | corpus: usable boards / owners / human-clean |
|---|---|---|---|---|---|---|---|---|---|
| **packages** | | | | | | | | | |
| `bga` | a ball grid of 9+ balls | 60 | 12 (20 %) | 47 | 52 (5-379) | 13.8 | 5 | sprint | 428 / 216 / 33 |
| `bga-balls-9-64` | largest ball grid 9-64 balls (mostly wafer-level parts) | 37 | 6 (16 %) | 24 | 54 (5-247) | 11.6 | 1 | sprint | 89 / 56 / 8 |
| `bga-balls-65-144` | largest ball grid 65-144 balls | 30 | 5 (16 %) | 26 | 88 (11-577) | 12.5 | 0 | ladder | 57 / 37 / 6 |
| `bga-balls-145-324` | largest ball grid 145-324 balls | 36 | 1 (2 %) | 35 | 108 (9-379) | 12.3 | 1 | sprint | 148 / 89 / 11 |
| `bga-balls-325plus` | largest ball grid 325+ balls | 30 | 3 (10 %) | 30 | 204 (5-595) | 9.4 | 3 | ladder | 134 / 84 / 8 |
| `bga-pitch-0.4` | finest ball pitch up to 0.4 mm | 30 | 3 (10 %) | 22 | 61 (6-287) | 9.4 | 0 | sprint | 72 / 55 / 5 |
| `bga-pitch-0.5` | finest ball pitch 0.4-0.5 mm | 30 | 5 (16 %) | 22 | 70 (5-1364) | 10.1 | 1 | ladder | 83 / 48 / 6 |
| `bga-pitch-0.65` | finest ball pitch 0.5-0.65 mm | 20 | 0 (0 %) | 18 | 208 (17-741) | 11.1 | 0 | ladder | 32 / 20 / 0 |
| `bga-pitch-0.8` | finest ball pitch 0.65-0.8 mm | 38 | 3 (7 %) | 38 | 135 (26-379) | 12 | 1 | sprint | 170 / 106 / 15 |
| `bga-pitch-1.0-1.27` | finest ball pitch 0.8-1.27 mm | 30 | 4 (13 %) | 28 | 90 (5-922) | 12.7 | 3 | ladder | 71 / 40 / 7 |
| `fine-pitch` | QFN, DFN or QFP parts on a board whose finest pad pitch is 0.5 mm or less, no ball grid | 60 | 53 (88 %) | 29 | 61 (7-257) | 15 | 35 | sprint | 3690 / 1512 / 397 |
| **signals** | | | | | | | | | |
| `diffpairs` | differential pairs (P/N net names) | 60 | 50 (83 %) | 27 | 60 (5-257) | 13.5 | 24 | sprint | 2057 / 967 / 235 |
| `parallel-bus` | a bus of 16+ nets between two parts | 60 | 40 (66 %) | 30 | 62 (6-290) | 13.7 | 9 | sprint | 849 / 467 / 92 |
| **structure** | | | | | | | | | |
| `pours` | a copper pour over at least a fifth of the board | 60 | 60 (100 %) | 18 | 57 (6-176) | 12.8 | 45 | sprint | 11402 / 3492 / 1854 |
| `inner-planes` | an inner layer with a plane over most of the board | 60 | 55 (91 %) | 60 | 60 (5-257) | 14.3 | 34 | sprint | 2219 / 974 / 355 |
| `double-sided` | parts on both sides, at least 5 and 30 % on the back | 60 | 60 (100 %) | 10 | 57 (6-219) | 9.3 | 15 | sprint | 2668 / 1299 / 385 |
| `cutouts-slots` | cut-outs inside the outline or slotted holes | 60 | 60 (100 %) | 17 | 59 (5-176) | 11.4 | 29 | sprint | 5175 / 2404 / 853 |
| `arrays` | 16+ identical footprints on a lattice, or on a circle | 60 | 28 (46 %) | 5 | 58 (17-325) | 15.3 | 3 | sprint | 427 / 284 / 63 |
| `connectors` | at least 4 connectors, and half of the parts are connectors | 60 | 44 (73 %) | 6 | 39 (5-100) | 14.4 | 2 | sprint | 921 / 551 / 261 |
| `decoupling` | many IC power pins with decoupling capacitors | 60 | 59 (98 %) | 27 | 59 (11-219) | 15.8 | 33 | sprint | 3476 / 1605 / 433 |
| **power conversion and distribution** | | | | | | | | | |
| `buck` | a buck converter cell | 60 | 51 (85 %) | 25 | 59 (10-313) | 14.4 | 28 | sprint | 1440 / 764 / 228 |
| `boost` | a boost converter cell | 60 | 28 (46 %) | 20 | 51 (9-379) | 15 | 7 | sprint | 485 / 299 / 49 |
| `ldo` | a linear regulator | 60 | 53 (88 %) | 19 | 59 (9-257) | 12.6 | 27 | sprint | 3611 / 1561 / 464 |
| `power-distribution` | four or more rail voltages, or load switches | 60 | 46 (76 %) | 23 | 59 (13-313) | 14.4 | 18 | sprint | 1328 / 684 / 189 |
| **battery and charging** | | | | | | | | | |
| `battery-charging` | a battery charger | 60 | 24 (40 %) | 21 | 53 (6-359) | 13.9 | 5 | sprint | 598 / 307 / 42 |
| **microcontroller core** | | | | | | | | | |
| `mcu-core` | a microcontroller | 60 | 54 (90 %) | 21 | 59 (9-257) | 13.4 | 37 | sprint | 3116 / 1568 / 378 |
| **clocking** | | | | | | | | | |
| `crystal` | a crystal or oscillator with its load network | 60 | 51 (85 %) | 25 | 59 (7-257) | 14.5 | 34 | sprint | 2766 / 1360 / 264 |
| **memory** | | | | | | | | | |
| `ddr` | SDRAM or DDR memory (any generation) | 52 | 5 (9 %) | 43 | 150 (5-379) | 15.9 | 1 | sprint | 198 / 119 / 16 |
| `ddr3` | DDR3 memory | 30 | 1 (3 %) | 30 | 285 (129-1020) | 12.4 | 1 | ladder | 76 / 56 / 5 |
| `ddr4-ddr5` | DDR4 or DDR5 memory | 6 | 2 (33 %) | 6 | 237 (65-4546) | 5.1 | 0 | ladder | 8 / 6 / 2 |
| `flash-sd` | QSPI flash, SD card or eMMC | 60 | 24 (40 %) | 33 | 66 (6-313) | 13.5 | 11 | sprint | 621 / 355 / 61 |
| **wired interfaces** | | | | | | | | | |
| `field-bus` | CAN or RS-485 (low speed, long cable) | 60 | 23 (38 %) | 16 | 42 (5-377) | 16.1 | 4 | sprint | 380 / 199 / 51 |
| `usb` | USB data pairs or a USB-C connector | 60 | 55 (91 %) | 27 | 56 (8-257) | 13.4 | 32 | sprint | 3269 / 1546 / 329 |
| `ethernet` | Ethernet (10/100 or 1G) | 60 | 9 (15 %) | 26 | 70 (5-366) | 17.1 | 3 | sprint | 340 / 177 / 26 |
| `multi-gigabit` | USB 3, PCIe, SATA or HDMI pairs (5 Gbit/s class) | 56 | 9 (16 %) | 44 | 71 (14-379) | 19 | 3 | sprint | 246 / 129 / 22 |
| `sata` | SATA | 11 | 1 (9 %) | 10 | 366 (41-4546) | 6.4 | 1 | ladder | 13 / 11 / 1 |
| **wireless** | | | | | | | | | |
| `rf-antenna` | RF copper on the board: a feed line to an antenna connector or an antenna part | 60 | 45 (75 %) | 27 | 60 (8-377) | 15 | 12 | sprint | 1063 / 459 / 124 |
| `radio-module` | a radio IC or module (WiFi/BLE, LoRa or other sub-GHz, 802.15.4, GNSS) | 60 | 47 (78 %) | 17 | 61 (7-257) | 11.3 | 20 | sprint | 2000 / 1131 / 292 |
| **analog signal chain** | | | | | | | | | |
| `analog-opamp` | op-amps | 60 | 52 (86 %) | 11 | 61 (9-205) | 11.2 | 13 | sprint | 1414 / 655 / 254 |
| `adc-dac` | a discrete ADC or DAC | 60 | 34 (56 %) | 17 | 55 (7-299) | 13.6 | 6 | sprint | 632 / 366 / 77 |
| **sensing** | | | | | | | | | |
| `sensors` | a sensor IC | 60 | 47 (78 %) | 22 | 57 (5-359) | 14.4 | 8 | sprint | 1301 / 603 / 161 |
| **audio** | | | | | | | | | |
| `audio` | an audio board (codec, amplifier, jacks) or an I2S link | 60 | 50 (83 %) | 11 | 61 (7-313) | 11.6 | 8 | sprint | 1043 / 487 / 203 |
| **display and camera** | | | | | | | | | |
| `video-links` | HDMI, MIPI or LVDS pairs | 60 | 9 (15 %) | 42 | 70 (6-379) | 18.9 | 1 | sprint | 295 / 129 / 22 |
| `displays` | a display part or display connector | 60 | 50 (83 %) | 4 | 58 (7-227) | 11.9 | 8 | sprint | 1440 / 885 / 230 |
| **motor and power stages** | | | | | | | | | |
| `motor-gate-drivers` | a motor driver or gate driver IC | 60 | 29 (48 %) | 14 | 45 (12-356) | 14.7 | 6 | sprint | 393 / 260 / 60 |
| **isolation and mains** | | | | | | | | | |
| `isolation` | an optocoupler or digital isolator, or an isolated DC-DC or AC-DC module | 60 | 50 (83 %) | 13 | 49 (5-305) | 13.9 | 12 | sprint | 721 / 430 / 149 |
| `mains` | an AC-DC module on the mains (other mains inputs are not detected reliably) | 49 | 17 (34 %) | 5 | 41 (8-305) | 13.1 | 3 | sprint | 81 / 61 / 19 |
| **protection and connectors** | | | | | | | | | |
| `protection` | ESD or TVS parts on the pins of cable connectors | 60 | 47 (78 %) | 22 | 59 (7-379) | 14.9 | 10 | sprint | 583 / 361 / 109 |
| **arrays and human interface** | | | | | | | | | |
| `keyboards` | a key-switch matrix | 60 | 57 (95 %) | 2 | 58 (6-197) | 10.5 | 3 | sprint | 1134 / 683 / 208 |
| `led-arrays` | 16+ addressable LEDs in a matrix, rows or a ring | 57 | 17 (29 %) | 2 | 72 (26-201) | 19.9 | 2 | sprint | 225 / 155 / 33 |
| **programmable logic** | | | | | | | | | |
| `fpga` | an FPGA or CPLD | 60 | 11 (18 %) | 27 | 60 (5-276) | 14.1 | 3 | sprint | 340 / 207 / 34 |
| **thin in the corpus** | | | | | | | | | |
| `flex` | a flex or rigid-flex stackup | 8 | 3 (37 %) | 2 | 24 (5-651) | 1.9 | 0 | ladder | 13 / 8 / 4 |
| `passive-01005` | 01005 passives | 17 | 2 (11 %) | 12 | 118 (22-2482) | 9.7 | 1 | ladder | 18 / 17 / 2 |
| `microvias` | microvias, blind or buried vias | 30 | 2 (6 %) | 22 | 67 (10-258) | 10.8 | 0 | ladder | 99 / 50 / 5 |

## Tag expressions

| suite | tag expression |
|---|---|
| `bga` | `bga` |
| `bga-balls-9-64` | `bga_balls.9-24 \| bga_balls.25-64` |
| `bga-balls-65-144` | `bga_balls.65-144` |
| `bga-balls-145-324` | `bga_balls.145-324` |
| `bga-balls-325plus` | `bga_balls.325plus` |
| `bga-pitch-0.4` | `bga_pitch.0.4` |
| `bga-pitch-0.5` | `bga_pitch.0.5` |
| `bga-pitch-0.65` | `bga_pitch.0.65` |
| `bga-pitch-0.8` | `bga_pitch.0.8` |
| `bga-pitch-1.0-1.27` | `bga_pitch.1.0 \| bga_pitch.1.27` |
| `fine-pitch` | `( fine_pitch.le0.4 \| fine_pitch.0.5 ) & ( qfn_dfn_leadless \| qfp_leaded_quad ) - ball_grid_any` |
| `diffpairs` | `diffpair_nets` |
| `parallel-bus` | `bus_width.16-31 \| bus_width.32-63 \| bus_width.64plus` |
| `pours` | `power_pours` |
| `inner-planes` | `inner_planes` |
| `double-sided` | `back_heavy` |
| `cutouts-slots` | `outline_cutouts \| slots` |
| `arrays` | `repeated_matrix.16-35 \| repeated_matrix.36-63 \| repeated_matrix.64-99 \| repeated_matrix.100plus \| radial_array` |
| `connectors` | `x_connector_dominated` |
| `decoupling` | `dec_rich` |
| `buck` | `pw_cell_buck` |
| `boost` | `pw_cell_boost` |
| `ldo` | `pw_ldo` |
| `power-distribution` | `pw_multi_rail \| pw_load_switch` |
| `battery-charging` | `pw_charger` |
| `mcu-core` | `sub:mcu` |
| `crystal` | `an_crystal` |
| `ddr` | `if_ddr` |
| `ddr3` | `if_ddr.ddr3` |
| `ddr4-ddr5` | `if_ddr.ddr4 \| if_ddr.ddr5` |
| `flash-sd` | `if_qspi \| if_sd_emmc` |
| `field-bus` | `if_can \| if_rs485` |
| `usb` | `if_usb2 \| if_usb_c` |
| `ethernet` | `if_ethernet` |
| `multi-gigabit` | `( if_usb3 & net:usb3_ss ) \| if_pcie \| if_sata \| if_hdmi.tmds_pairs` |
| `sata` | `if_sata` |
| `rf-antenna` | `rf_antenna.connector \| rf_antenna.discrete_part` |
| `radio-module` | `rf_wifi_ble \| rf_lora \| rf_gnss` |
| `analog-opamp` | `an_opamp` |
| `adc-dac` | `sub:adc_dac` |
| `sensors` | `sub:sensor` |
| `audio` | `dom_audio \| if_i2s` |
| `video-links` | `if_hdmi.tmds_pairs \| if_mipi \| if_lvds` |
| `displays` | `hit:display_part` |
| `motor-gate-drivers` | `pw_motor_driver \| pw_gate_driver` |
| `isolation` | `iso_isolator \| iso_dcdc_module \| hit:iso_dcdc \| hit:acdc_module` |
| `mains` | `hit:acdc_module` |
| `protection` | `pr_connector_esd` |
| `keyboards` | `dom_keyboard` |
| `led-arrays` | `( repeated_matrix.16-35 \| repeated_matrix.36-63 \| repeated_matrix.64-99 \| repeated_matrix.100plus \| radial_array \| repeated_cells.aligned_rows ) & x_addressable_leds_16` |
| `fpga` | `hit:fpga \| hit:cpld_only` |
| `flex` | `flex_hint` |
| `passive-01005` | `passive_01005` |
| `microvias` | `microvias \| blind_buried_vias` |
