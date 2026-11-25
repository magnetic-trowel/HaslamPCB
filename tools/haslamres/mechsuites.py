#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""mechsuites: one board suite per mechanism and per standard kind of circuit, so that work on a
mechanism runs only on boards that have it.

  python3 tools/haslamres/mechsuites.py --tags DIR [--index FILE] [--corpus DIR] [--suites bench/suites] [--seed N] [--dry-run]

Writes bench/suites/mech/<name>.txt for every entry of MECHANISMS, suites.json (expression, tier, cost)
and README.md (how to use them, the table, the tag checks). Inputs are those of suites.py, plus
functional/features.jsonl of the tag folder (part classes) and the sprint suites (their boards have
stored control runs). The same inputs and seed give the same lists.

A suite is defined by a tag expression: tag names joined by ` | ` (or), ` & ` (and), ` - ` (and not),
with parentheses; operators stand alone between spaces, & and - bind tighter than |. A tag is a file
suites/<tag>.txt of the tag folder, or one of
  sub:NAME  kind:NAME  hit:NAME  net:NAME   a key of that field in functional/features.jsonl
  x_NAME                                    a rule of DERIVED over a features row
"""
import argparse
import json
import os
import random
import statistics
from pathlib import Path

import suites as S

REPO = Path(__file__).resolve().parents[2]
SEED = S.SEED
SIZE, MIN_SIZE = 60, 30          # boards per suite; under MIN_SIZE the suite is filled past the sprint cap
MIN_FOOTPRINTS = 5
BANDS = ((5, 30), (31, 60), (61, 100), (101, S.FRONTIER_FOOTPRINTS))  # footprints; a suite draws evenly over them
SPRINT_CPU_H = 40.0              # the sprint tier's limit (haslamres.TIERS)
ARM_CPU_H = SPRINT_CPU_H / 2     # a sprint suite's cost per arm: the new arm and a control arm fit one sprint
# a board can be a place task when its outline closes (the placer needs the area); route tasks need no more
PLACEABLE = ("outline_shape.rectangular | outline_shape.rounded_rect | outline_shape.round_or_oval | "
             "outline_shape.curved | outline_shape.polygonal | outline_shape.complex")
STORED_CONTROL = ("sprint-frontier", "sprint-quality")  # suites whose control runs are stored per weekly tag
FIELDS = dict(sub="subtypes", kind="kinds", hit="hits", net="nhits")
NOT_PARTS = ("mounting_hole", "graphic", "fiducial", "test_point", "mechanical", "net_tie")


def _connector_dominated(row):
    kinds = row.get("kinds") or {}
    parts = sum(n for k, n in kinds.items() if k not in NOT_PARTS)
    return kinds.get("connector", 0) >= 4 and 2 * kinds.get("connector", 0) >= parts


DERIVED = {"x_connector_dominated": _connector_dominated,  # at least 4 connectors, and half of the parts
           "x_addressable_leds_16": lambda row: (row.get("hits") or {}).get("led_addressable", 0) >= 16}

_BALLS = ("bga_balls.9-24 | bga_balls.25-64", "bga_balls.65-144", "bga_balls.145-324", "bga_balls.325plus")
_MATRIX = "repeated_matrix.16-35 | repeated_matrix.36-63 | repeated_matrix.64-99 | repeated_matrix.100plus"
# (name, group, tag expression, what the boards have[, expressions to draw evenly over instead of BANDS])
MECHANISMS = [
    # ---- packages and their escape
    ("bga", "packages", "bga", "a ball grid of 9+ balls", _BALLS),
    ("bga-balls-9-64", "packages", _BALLS[0], "largest ball grid 9-64 balls (mostly wafer-level parts)"),
    ("bga-balls-65-144", "packages", _BALLS[1], "largest ball grid 65-144 balls"),
    ("bga-balls-145-324", "packages", _BALLS[2], "largest ball grid 145-324 balls"),
    ("bga-balls-325plus", "packages", _BALLS[3], "largest ball grid 325+ balls"),
    ("bga-pitch-0.4", "packages", "bga_pitch.0.4", "finest ball pitch up to 0.4 mm"),
    ("bga-pitch-0.5", "packages", "bga_pitch.0.5", "finest ball pitch 0.4-0.5 mm"),
    ("bga-pitch-0.65", "packages", "bga_pitch.0.65", "finest ball pitch 0.5-0.65 mm"),
    ("bga-pitch-0.8", "packages", "bga_pitch.0.8", "finest ball pitch 0.65-0.8 mm"),
    ("bga-pitch-1.0-1.27", "packages", "bga_pitch.1.0 | bga_pitch.1.27", "finest ball pitch 0.8-1.27 mm"),
    ("fine-pitch", "packages", "( fine_pitch.le0.4 | fine_pitch.0.5 ) & ( qfn_dfn_leadless | qfp_leaded_quad ) - ball_grid_any",
     "QFN, DFN or QFP parts on a board whose finest pad pitch is 0.5 mm or less, no ball grid"),
    # ---- signal classes
    ("diffpairs", "signals", "diffpair_nets", "differential pairs (P/N net names)"),
    ("parallel-bus", "signals", "bus_width.16-31 | bus_width.32-63 | bus_width.64plus", "a bus of 16+ nets between two parts"),
    # ---- board structure
    ("pours", "structure", "power_pours", "a copper pour over at least a fifth of the board"),
    ("inner-planes", "structure", "inner_planes", "an inner layer with a plane over most of the board"),
    ("double-sided", "structure", "back_heavy", "parts on both sides, at least 5 and 30 % on the back"),
    ("cutouts-slots", "structure", "outline_cutouts | slots", "cut-outs inside the outline or slotted holes"),
    ("arrays", "structure", f"{_MATRIX} | radial_array", "16+ identical footprints on a lattice, or on a circle"),
    ("connectors", "structure", "x_connector_dominated", "at least 4 connectors, and half of the parts are connectors"),
    ("decoupling", "structure", "dec_rich", "many IC power pins with decoupling capacitors"),
    # ---- power conversion and distribution
    ("buck", "power conversion and distribution", "pw_cell_buck", "a buck converter cell"),
    ("boost", "power conversion and distribution", "pw_cell_boost", "a boost converter cell"),
    ("ldo", "power conversion and distribution", "pw_ldo", "a linear regulator"),
    ("power-distribution", "power conversion and distribution", "pw_multi_rail | pw_load_switch",
     "four or more rail voltages, or load switches"),
    # ---- battery and charging
    ("battery-charging", "battery and charging", "pw_charger", "a battery charger"),
    # ---- microcontroller core
    ("mcu-core", "microcontroller core", "sub:mcu", "a microcontroller"),
    # ---- clocking
    ("crystal", "clocking", "an_crystal", "a crystal or oscillator with its load network"),
    # ---- memory
    ("ddr", "memory", "if_ddr", "SDRAM or DDR memory (any generation)"),
    ("ddr3", "memory", "if_ddr.ddr3", "DDR3 memory"),
    ("ddr4-ddr5", "memory", "if_ddr.ddr4 | if_ddr.ddr5", "DDR4 or DDR5 memory"),
    ("flash-sd", "memory", "if_qspi | if_sd_emmc", "QSPI flash, SD card or eMMC"),
    # ---- wired interfaces by speed class
    ("field-bus", "wired interfaces", "if_can | if_rs485", "CAN or RS-485 (low speed, long cable)"),
    ("usb", "wired interfaces", "if_usb2 | if_usb_c", "USB data pairs or a USB-C connector"),
    ("ethernet", "wired interfaces", "if_ethernet", "Ethernet (10/100 or 1G)"),
    ("multi-gigabit", "wired interfaces", "( if_usb3 & net:usb3_ss ) | if_pcie | if_sata | if_hdmi.tmds_pairs",
     "USB 3, PCIe, SATA or HDMI pairs (5 Gbit/s class)"),
    ("sata", "wired interfaces", "if_sata", "SATA"),
    # ---- wireless
    ("rf-antenna", "wireless", "rf_antenna.connector | rf_antenna.discrete_part",
     "RF copper on the board: a feed line to an antenna connector or an antenna part"),
    ("radio-module", "wireless", "rf_wifi_ble | rf_lora | rf_gnss", "a radio IC or module (WiFi/BLE, LoRa or other sub-GHz, 802.15.4, GNSS)"),
    # ---- analog signal chain
    ("analog-opamp", "analog signal chain", "an_opamp", "op-amps"),
    ("adc-dac", "analog signal chain", "sub:adc_dac", "a discrete ADC or DAC"),
    # ---- sensing
    ("sensors", "sensing", "sub:sensor", "a sensor IC"),
    # ---- audio
    ("audio", "audio", "dom_audio | if_i2s", "an audio board (codec, amplifier, jacks) or an I2S link"),
    # ---- display and camera
    ("video-links", "display and camera", "if_hdmi.tmds_pairs | if_mipi | if_lvds", "HDMI, MIPI or LVDS pairs"),
    ("displays", "display and camera", "hit:display_part", "a display part or display connector"),
    # ---- motor and power stages
    ("motor-gate-drivers", "motor and power stages", "pw_motor_driver | pw_gate_driver", "a motor driver or gate driver IC"),
    # ---- isolation and mains
    ("isolation", "isolation and mains", "iso_isolator | iso_dcdc_module | hit:iso_dcdc | hit:acdc_module",
     "an optocoupler or digital isolator, or an isolated DC-DC or AC-DC module"),
    ("mains", "isolation and mains", "hit:acdc_module", "an AC-DC module on the mains (other mains inputs are not detected reliably)"),
    # ---- protection and connectors
    ("protection", "protection and connectors", "pr_connector_esd", "ESD or TVS parts on the pins of cable connectors"),
    # ---- arrays and human interface
    ("keyboards", "arrays and human interface", "dom_keyboard", "a key-switch matrix"),
    ("led-arrays", "arrays and human interface", f"( {_MATRIX} | radial_array | repeated_cells.aligned_rows ) & x_addressable_leds_16",
     "16+ addressable LEDs in a matrix, rows or a ring"),
    # ---- programmable logic
    ("fpga", "programmable logic", "hit:fpga | hit:cpld_only", "an FPGA or CPLD"),
    # ---- kinds the corpus is thin on (kept so that the coverage table shows them)
    ("flex", "thin in the corpus", "flex_hint", "a flex or rigid-flex stackup"),
    ("passive-01005", "thin in the corpus", "passive_01005", "01005 passives"),
    ("microvias", "thin in the corpus", "microvias | blind_buried_vias", "microvias, blind or buried vias"),
]


# ------------------------------------------------------------------ tags
class Tags:
    """The tag folder: board sets by tag name, read when first asked for."""

    def __init__(self, folder):
        self.folder, self._sets, self._rows = Path(folder), {}, None

    def rows(self):
        if self._rows is None:
            self._rows = S.jsonl(self.folder / "functional" / "features.jsonl")
        return self._rows

    def tag(self, name):
        if name not in self._sets:
            field, _, key = name.partition(":")
            if name in DERIVED:
                self._sets[name] = {r["id"] for r in self.rows() if DERIVED[name](r)}
            elif key and field in FIELDS:
                self._sets[name] = {r["id"] for r in self.rows() if key in (r.get(FIELDS[field]) or {})}
            else:
                self._sets[name] = set(S.read_ids(self.folder / "suites" / f"{name}.txt"))
        return self._sets[name]


def atoms(expr):
    """The tag names of an expression."""
    return [w for w in expr.replace("(", " ( ").replace(")", " ) ").split() if w not in "()|&-"]


def members(expr, tag):
    """The boards of a tag expression; tag: name -> set of boards."""
    words = expr.replace("(", " ( ").replace(")", " ) ").split()
    pos = 0

    def factor():
        nonlocal pos
        if pos >= len(words) or words[pos] in ("|", "&", "-", ")"):
            raise ValueError(f"tag expected at word {pos + 1} of {expr!r}")
        w = words[pos]
        pos += 1
        if w != "(":
            return set(tag(w))
        s = union()
        if pos >= len(words) or words[pos] != ")":
            raise ValueError(f"unclosed ( in {expr!r}")
        pos += 1
        return s

    def term():
        nonlocal pos
        s = factor()
        while pos < len(words) and words[pos] in ("&", "-"):
            op = words[pos]
            pos += 1
            s = s & factor() if op == "&" else s - factor()
        return s

    def union():
        nonlocal pos
        s = term()
        while pos < len(words) and words[pos] == "|":
            pos += 1
            s = s | term()
        return s

    out = union()
    if pos != len(words):
        raise ValueError(f"unexpected {words[pos]!r} in {expr!r}")
    return out


# ------------------------------------------------------------------ inputs
def sweep(c):
    """board -> mean CPU-h per run in the corpus sweeps (experiments over SWEEP_BOARDS boards, the
    human reference left out): the one cost every board has, used to order boards of equal estimate."""
    size = dict(c.execute("SELECT experiment, COUNT(DISTINCT board) FROM runs GROUP BY 1"))
    tot = {}
    for b, e, cpu in c.execute(f"SELECT r.board, r.experiment, r.cpu_s {S._RUNS} AND r.cpu_s > 0 ORDER BY r.board, r.run"):
        if size[e] > S.SWEEP_BOARDS:
            t = tot.setdefault(b, [0.0, 0])
            t[0] += cpu
            t[1] += 1
    return {b: s / n / 3600 for b, (s, n) in tot.items()}


class Inputs(S.Inputs):
    """suites.Inputs plus the tag sets, the sweep cost and the boards with a stored control."""

    def __init__(self, index, tags, corpus, merit, suites_dir):
        super().__init__(index, tags, corpus, merit)
        c = S.open_index(index)
        self.sweep = sweep(c)
        c.close()
        self.tags = Tags(tags)
        self.placeable = members(PLACEABLE, self.tags.tag)
        self.fixed = {p.stem: S.read_ids(p) for p in sorted(Path(suites_dir).glob("*.txt"))}
        self.stored = {b for n in STORED_CONTROL for b in self.fixed.get(n, [])}

    def members(self, expr):
        return members(expr, self.tags.tag)


# ------------------------------------------------------------------ one suite
def usable(inp, boards):
    """The boards that can run as route and as place tasks."""
    return {b for b in boards if b in inp.routable and b in inp.placeable and inp.footprints.get(b, 0) >= MIN_FOOTPRINTS}


def costs(inp):
    """cost(board) -> CPU-h per method-run: the tier guard's estimate (suites.estimator), except that a
    board no placing method has run on costs at least the mean of its footprint band: its history is
    route-only runs (a bus router alone took 0.001 CPU-h on boards of 300 footprints), far under an arm
    that places and routes."""
    est = S.estimator(inp.hist, inp.footprints)
    band = S.estimator({("band", b): h for b, h in inp.hist.items()}, {("band", b): inp.footprints.get(b) for b in inp.hist} | inp.footprints)
    return lambda b: est(b)[0] if b in inp.placed else max(est(b)[0], band(b)[0])


def pick(inp, boards, rng, n=SIZE, cells=None):
    """(ids, tier) of a mechanism suite from the boards that have the mechanism.

    Usable boards only, one per owner. Order: human-clean first, then boards with a stored control, then
    cheapest (`costs`; boards of equal cost by their sweep cost; costs under COST_FLOOR_H alike, in seeded
    random order). Up to n boards within the sprint cap and FRONTIER_FOOTPRINTS, drawn evenly over `cells`
    (sets of boards; default the footprint BANDS), costliest dropped while the suite is over ARM_CPU_H.
    If fewer than MIN_SIZE fit, the cheapest boards past the cap fill the suite to MIN_SIZE and the tier
    is "ladder"."""
    cost = costs(inp)
    rank = lambda b: (max(cost(b), S.COST_FLOOR_H), max(inp.sweep.get(b, 0.0), S.COST_FLOOR_H))  # noqa: E731
    sprint = lambda b: (inp.hist.get(b, 0.0) <= S.SPRINT_BOARD_CPU_H and cost(b) <= S.SPRINT_BOARD_CPU_H  # noqa: E731
                        and inp.footprints[b] <= S.FRONTIER_FOOTPRINTS)
    pool = sorted(usable(inp, boards))
    rng.shuffle(pool)
    pool.sort(key=lambda b: (b not in inp.human_clean, b not in inp.stored) + rank(b))
    cheap = [b for b in pool if sprint(b)]
    if cells is None:
        cells = [{b for b in cheap if lo <= inp.footprints[b] <= hi} for lo, hi in BANDS]
    owners = set()
    out = S.round_robin(cheap, range(len(cells)), lambda b: {i for i, c in enumerate(cells) if b in c}, n, owners, inp.owner)
    while len(out) > MIN_SIZE and sum(map(cost, out)) > ARM_CPU_H:
        out.remove(max(out, key=lambda b: (cost(b), b)))
    if len(out) >= MIN_SIZE:
        return out, "sprint"
    rest = sorted((b for b in pool if b not in out), key=lambda b: rank(b) + (b not in inp.human_clean,))
    out += S.round_robin(rest, [0], lambda b: (0,), MIN_SIZE - len(out), owners, inp.owner)
    return out, "sprint" if all(map(sprint, out)) and sum(map(cost, out)) <= SPRINT_CPU_H else "ladder"




def build(inp, seed=SEED, mechanisms=MECHANISMS):
    """name -> dict(ids, tier, expr, group, about, pool): every mechanism's suite and what it was drawn from."""
    out = {}
    for name, group, expr, about, *cells in mechanisms:
        boards = inp.members(expr)
        ok = usable(inp, boards)
        ids, tier = pick(inp, boards, random.Random(f"{seed}:mech:{name}"),
                         cells=[inp.members(e) for e in cells[0]] if cells else None)
        out[name] = dict(ids=ids, tier=tier, expr=expr, group=group, about=about,
                         pool=dict(boards=len(boards), usable=len(ok), owners=len({inp.owner[b] for b in ok}),
                                   human_clean=len(ok & inp.human_clean)))
    return out


def stats(inp, ids):
    """What the table and suites.json say about a list of boards."""
    cost = costs(inp)
    fp = [inp.footprints[b] for b in ids] or [0]
    return dict(boards=len(ids), owners=len({inp.owner[b] for b in ids}), human_clean=sum(b in inp.human_clean for b in ids),
                layers4=sum(inp.layers[b] >= 4 for b in ids), footprints=[min(fp), int(statistics.median(fp)), max(fp)],
                cpu_h_per_arm=round(sum(map(cost, ids)), 1), own_history=sum(b in inp.hist for b in ids),
                stored_control=sum(b in inp.stored for b in ids), placed=sum(b in inp.placed for b in ids))


def manifest(inp, suites, seed):
    return dict(schema="haslam-mech-suites/1", seed=seed,
                suites={n: dict(expr=s["expr"], group=s["group"], about=s["about"], tier=s["tier"], pool=s["pool"],
                                **stats(inp, s["ids"])) for n, s in suites.items()})


def table(man):
    lines = ["| suite | boards have | boards | human-clean | 4+ layers | footprints, median (range) | CPU-h per arm | stored control | tier | corpus: usable boards / owners / human-clean |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    group = None
    for name, s in man["suites"].items():
        if s["group"] != group:
            group = s["group"]
            lines.append(f"| **{group}** | | | | | | | | | |")
        lo, med, hi = s["footprints"]
        clean = f"{s['human_clean']} ({100 * s['human_clean'] // max(s['boards'], 1)} %)"
        p = s["pool"]
        lines.append(f"| `{name}` | {s['about']} | {s['boards']} | {clean} | {s['layers4']} | {med} ({lo}-{hi}) | {s['cpu_h_per_arm']:g} "
                     f"| {s['stored_control']} | {s['tier']} | {p['usable']} / {p['owners']} / {p['human_clean']} |")
    return "\n".join(lines)


def expressions(man):
    return "\n".join(["| suite | tag expression |", "|---|---|"]
                     + [f"| `{n}` | `{s['expr'].replace('|', chr(92) + '|')}` |" for n, s in man["suites"].items()])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tags", required=True, help="board-tag folder (suites/, structural/, functional/features.jsonl)")
    ap.add_argument("--index", default=os.path.join(os.path.expanduser(os.environ.get("HASLAM_RESULTS", "~/haslam-baselines")), "index.sqlite"))
    ap.add_argument("--corpus", default=os.path.expanduser(os.environ.get("HASLAM_CORPUS", "~/haslam-boards")))
    ap.add_argument("--suites", default=str(REPO / "bench" / "suites"), help="the tier suites; mech/ below it is written")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--dry-run", action="store_true", help="print the table, write nothing")
    a = ap.parse_args()
    inp = Inputs(a.index, a.tags, a.corpus, Path(a.suites) / "merit-213.txt", a.suites)
    suites = build(inp, a.seed)
    man = manifest(inp, suites, a.seed)
    if not a.dry_run:
        out = Path(a.suites) / "mech"
        out.mkdir(exist_ok=True)
        for name, s in suites.items():
            (out / f"{name}.txt").write_text("\n".join(s["ids"]) + "\n")
        (out / "suites.json").write_text(json.dumps(man, indent=1) + "\n")
        (out / "TABLE.md").write_text("# Mechanism suites: the table\n\nWritten by `tools/haslamres/mechsuites.py`; "
                                      "read [README](README.md) first.\n\n" + table(man) + "\n\n## Tag expressions\n\n"
                                      + expressions(man) + "\n")
    print(table(man))


if __name__ == "__main__":
    main()
