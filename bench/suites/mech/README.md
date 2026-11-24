# Mechanism suites

Scope: one board list per mechanism and per standard kind of circuit, so that work on a mechanism runs only on boards that have it. Not here: the tiers and their limits -> [experiment tiers](../../../docs/topics/verification/experiment-tiers.md); how well each kind is covered -> [COVERAGE](../COVERAGE.md).
Keys: mechanism suite, mech suite, bench/suites/mech, mechsuites.py, suites.json, tag expression, bga suite, tag precision, dropped tags, ladder-tier suite, --boards @bench/suites/mech

## Rule

An experiment on one mechanism (BGA escape, differential pairs, converters, pours, arrays, ...) runs on the suite of that mechanism. The general sprint suites are for changes that act on every board.

## Use

Suites, their sizes, cost and tier: [TABLE](TABLE.md) (generated), `suites.json` (the same, for programs).

```bash
K="python3 tools/haslamres/haslamres.py"
# sprint on a mechanism: the suite named in the experiment's PLAN.md, the control arm side by side
$K exp create bga-escape-x --method CONTROL --method NEW --boards @bench/suites/mech/bga.txt \
   --harness baseline/2026-w47 --haslam baseline/2026-w47 --description "mechanism: bga; ..."
$K exp submit bga-escape-x && haslamq prio 5 --owner exp-bga-escape-x
# a suite whose tier is "ladder" in TABLE.md (the mechanism exists only on costly boards): after a sprint result
$K exp create bga-escape-x-325 ... --boards @bench/suites/mech/bga-balls-325plus.txt --tier ladder
```

- Name the mechanism in the description: there is no `--mechanism` option yet (the sprint command it belongs to was not on `experiment-tiers` on 2026-11-20). Until then `--boards @bench/suites/mech/NAME.txt` is the form.
- Control runs: the `stored control` column of the table counts the suite's boards that are in a sprint suite. Once a weekly control is stored (`control-w<week>`), only the other boards need a control arm; today all do.
- Two mechanisms at once: intersect the lists (`comm -12 <(sort a.txt) <(sort b.txt)`), or write a new expression in `MECHANISMS` and rebuild.

## Hand-made suites

Not from `mechsuites.py`; each was chosen for one experiment's plan.

| Suite | Boards | Chosen by |
|---|---|---|
| `place-fixable-le400` | 35 | design 2 stage 0 (`tools/research/joint/place_fixable.py`): placement-fixable boards up to 400 footprints |
| `ground-pour-2layer` | 65 | ground-side-ab: the 2-layer boards of both sprint suites on which `haslam.route.ground_side` names a pour side |
| `ground-pour-2layer-ladder` | 95 | ground-side-ladder: the 146 2-layer boards of `ladder.txt` on which `haslam.route.ground_side` names a pour side (67 B.Cu, 28 F.Cu; none in a sprint suite) |
| `layer-oracle-multilayer` | 70 | layer-oracle: the first 70 of its candidates (4+ layers, DRC-clean human layout, opens under the fork alone) |

## How a suite is built

`python3 tools/haslamres/mechsuites.py --tags DIR` (seed 20261120; `--dry-run` prints the table). Same inputs and seed, same lists.

1. Members: the boards of the suite's tag expression (`MECHANISMS` in `tools/haslamres/mechsuites.py`; tags joined by `|`, `&`, `-`).
2. Usable: can run as a route task (netlist, prepared task) and as a place task (closed outline), 5+ footprints.
3. One board per owner (the account of the board's repository).
4. Order: human-clean layouts first, then boards of the sprint suites (stored control), then cheapest. Cost: the tier guard's estimate (the board's mean CPU-h per method-run in the results index, else the mean of its footprint band). A board that no placing method has run on costs at least its band's mean: route-only history understates it (a bus router alone took 0.001 CPU-h on 300-footprint boards). Ties: the board's cost in the corpus sweep, then seeded random.
5. Sprint boards: history and cost at most 0.5 CPU-h per method-run, at most 400 footprints. Up to 60, drawn evenly over four footprint bands (5-30, 31-60, 61-100, 101-400); `bga` evenly over ball-count bands instead. Costliest dropped while the suite is over 20 CPU-h per arm, so that a new arm and a control arm fit one 40 CPU-h sprint.
6. Fewer than 30 sprint boards: the cheapest boards past the cap fill the suite to 30 and its tier is `ladder`.

CPU-h per arm = one method-run on every board, in the tier guard's units. A restart-wrapped haslam method costs about 4-5x that ([bench/README](../../README.md#experiment-tier-suites)).

## What the suites show (2026-11-20)

- 54 suites: 43 fit the sprint tier (30-60 boards, 9-20 CPU-h per arm), 11 need the ladder tier.
- BGA: 428 usable boards of 216 owners, 33 with a clean human layout. `bga` (60 boards, 14 CPU-h per arm, 12 clean) fits a sprint because 9-64-ball and breakout boards are cheap; it holds 15 boards of each band from 65 balls up. Work on large arrays needs `bga-balls-325plus` (30 boards, 3 clean, ladder tier). Only `bga-balls-9-64`, `bga-balls-145-324`, `bga-pitch-0.4` and `bga-pitch-0.8` fit a sprint among the sub-suites.
- Ladder tier also: `ddr3`, `ddr4-ddr5` (6 boards), `sata` (11), `flex` (8), `passive-01005` (17), `microvias`.
- Human-clean share: 62 % over the sprint-tier suites; 20 % or less for `bga` and its sub-suites, `ddr*`, `ethernet`, `multi-gigabit`, `video-links`, `fpga`, `microvias`.

## Tag checks

Every tag a suite relies on was checked on 10 usable boards (seeded, one per owner) by reading a compact view of the raw board file (part values, packages, net names, zone and side counts), unless the tag reports already measure it. ok / wrong / doubt, of 10. Kept: at least 7 ok and at most 2 wrong.

| tag | ok / wrong / doubt | note |
|---|---|---|
| `fine_pitch` <= 0.5 with `qfn_dfn_leadless` or `qfp_leaded_quad` | 9 / 1 / 0 | wrong: the fine-pitch part was an M.2 connector |
| `diffpair_nets` | 9 / 0 / 1 | `+`/`-` names also match speaker and battery terminals |
| `bus_width` 16+ | 10 / 0 / 0 | 6 memory or FPGA buses, 4 connector fan-outs |
| `power_pours` | 10 / 0 / 0 | |
| `inner_planes` | 9 / 0 / 1 | |
| `back_heavy` | 9 / 1 / 0 | padless footprints counted once |
| `outline_cutouts` | 7 / 0 / 3 | doubt: the view could not count loops |
| `radial_array` | 9 / 0 / 1 | doubt: panel tabs on a circle |
| connector-dominated (`x_connector_dominated`) | 8 / 0 / 2 | single-pad "connectors" |
| `dec_rich` | 7 / 0 / 3 | counts power pins: two ICs can qualify |
| `pw_cell_buck` | 7 / 1 / 2 | buck-boost parts count as buck and as boost |
| `pw_cell_boost` | 8 / 0 / 2 | |
| `pw_ldo` | 10 / 0 / 0 | |
| `pw_multi_rail` | 8 / 0 / 2 | counts rail nets, some without a voltage |
| `pw_load_switch` | 8 / 0 / 2 | includes ideal-diode controllers |
| `sub:mcu`, `sub:sensor`, `an_crystal`, `if_qspi`, `if_can`, `if_i2s` | 10 / 0 / 0 each | |
| `if_sd_emmc` | 8 / 0 / 2 | |
| `if_rs485`, `if_usb2`, `if_sata`, `an_opamp` | 9 of 10 each | |
| `if_usb3` with `net:usb3_ss` | 8 / 0 / 2 | `if_usb3` alone: 6 / 1 / 3 |
| `sub:adc_dac` | 9 / 0 / 1 | |
| `hit:fpga`, `hit:cpld_only` | 9 / 0 / 1 | |
| `rf_wifi_ble` | 7 / 3 / 0 | 2 of the wrong ones are XBee radios: 9 of 10 are a radio |
| `rf_lora` | 6 / 3 / 1 | 2 of the wrong ones are RFM69 radios: 8 of 10 are a radio |
| `if_lvds` | 7 / 0 / 3 | |
| `hit:display_part` | 7 / 2 / 1 | wrong: "OLED" inside "MX-NoLED" key switches |
| `pw_gate_driver` | 6 / 0 / 4 | a driver IC on all 10; the driven FET not visible on 4 |
| `pr_connector_esd` | 7 / 1 / 2 | |
| isolated module (`iso_dcdc_module`, `hit:iso_dcdc`, `hit:acdc_module`) | 7 / 1 / 2 | wrong: an IR receiver named IRM |
| `led-arrays` expression (16+ addressable LEDs) | 10 / 0 / 0 | without the count: 7 / 3 / 0 |

Measured by the tag reports (not repeated): `bga` 95-98 %, `repeated_matrix` 15/15, `slots` 6/6, `microvias` about 100 %, `if_ddr` 15/15, `if_pcie` 13/14, `if_hdmi` 24/27, `if_ethernet` 12/12, `if_usb_c` 12/12, `if_mipi` 12/12, `pw_charger` 10/10, `pw_motor_driver` 10/10, `rf_gnss` 11/12, `rf_antenna` 6/7, `iso_isolator` 10/12, `dom_keyboard` 9/10, `dom_audio` 10/12.

### Dropped tags

Not used by any suite; do not select boards by them without a new check.

| tag | ok / wrong / doubt | what it fires on | used instead |
|---|---|---|---|
| `parallel_bus` | 7 / 3 / 0 | any numbered net family: connector pins, Eagle `N$` nets | `bus_width` 16+ |
| `pw_bms_afe` | 7 / 3 / 0 | isoSPI transceivers, chargers | `pw_charger` |
| `rf_discrete_layout` | 5 / 2 / 3 | any SMA connector (probe inputs, oscillator outputs) | `rf_antenna` rungs `connector`, `discrete_part` |
| `rf_cellular` | 4 / 3 / 3 | SIM holders, `EC20` inside LED names | none |
| `an_inamp` | 2 / 3 / 5 | `PGA` inside `FPGA`, audio op-amps | none |
| `an_adc_dac` | 6 / 1 / 3 | clock ICs named AD95xx | `sub:adc_dac` |
| `sub:audio` | 2 / 6 / 2 | audio jacks, op-amps, speakers | `dom_audio`, `if_i2s` |
| `sub:audio_amp` | 4 / 3 / 3 | codecs without an amplifier | `dom_audio`, `if_i2s` |
| `pw_cell_half_bridge` | 6 / 1 / 3 | integrated synchronous bucks | `pw_motor_driver`, `pw_gate_driver` |
| `iso_hv` | 2 / 4 / 4 | level-shifter nets named HV | none |
| `pw_mains_input` | 6 / 1 / 3, second sample 3 / 5 / 2 | low-voltage AC, polyfuses, `HLK` router modules | `hit:acdc_module` (misses discrete mains supplies) |
| `pw_isolated_converter` | 6 / 3 / 1 | signal, audio and mains-frequency transformers | isolated-module tags |
| `pr_cm_choke` | 6 / 0 / 4 | not confirmed: no choke in view on 4 | none |
| `sub:fpga` | 3 / 4 / 3 | Torex XC62xx regulators, 16V8 PLDs | `hit:fpga`, `hit:cpld_only` |

No suite, for want of a reliable tag: high voltage, discrete mains supplies, instrumentation amplifiers, cellular modems, half-bridge power stages, common-mode chokes.

## Sources

Board tags and their reports (`structural/REPORT.md`, `functional/REPORT.md` of the tag folder, 14,597 boards), corpus manifest, results index of 2026-11-20. Code: `tools/haslamres/mechsuites.py`, tests `tools/haslamres/tests/test_mechsuites.py`.
