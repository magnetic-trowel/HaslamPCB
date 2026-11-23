# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the synthetic inverter boards (our own design: kae/tests/hotloop_fixtures.inverting_parts) as route-CLI
inputs, unrouted, each with its operating facts:

  inv-dedicated-2l   a dedicated inverter (TPS63700-style: the IC on ground, its rectifier from the switch node
                     into -5V), 2 layers, 0.3 A out
  inv-direct-4l      a buck IC as an inverter (its GND pin on -5V, L from SW to ground, CIN from +12V straight to
                     -5V and COUT from ground to -5V, TI SLVA721), 4 layers (a GND plane on In1.Cu), 1.5 A out
  inv-ground-2l      the same IC with CIN to ground, 2 layers, 0.5 A out

  python tools/kaeres/experiments/inverters/make_boards.py OUT_DIR
writes OUT_DIR/<name>/board.kicad_pcb (+ .kicad_pro) and OUT_DIR/<name>.operating.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "kae" / "tests"))
from hotloop_fixtures import write_inverting_board  # noqa: E402

BOARDS = {
    "inv-dedicated-2l": dict(variant="dedicated", layers=2, I_out=0.3),
    "inv-direct-4l": dict(variant="direct", layers=4, I_out=1.5),
    "inv-ground-2l": dict(variant="ground", layers=2, I_out=0.5),
}


def facts(I_out):
    return {"nets": {"+12V": {"source": "J1", "V_V": 12.0},
                     "-5V": {"source": "U1", "from": "+12V", "kind": "switching", "V_V": -5.0, "eta": [0.8, 0.9]}},
            "parts": {"J2": {"I_A": [0.5 * I_out, I_out]}},
            "cells": {"cell:inverting:U1": {"V_in_V": 12.0, "V_out_V": -5.0, "I_out_A": [0.5 * I_out, I_out],
                                            "f_sw_Hz": [0.9e6, 1.1e6], "eta": [0.8, 0.9]}}}


def main(out):
    out = Path(out)
    for name, b in BOARDS.items():
        write_inverting_board(out / name, b["variant"], routed=False, load=True, layers=b["layers"])
        (out / f"{name}.operating.json").write_text(json.dumps(facts(b["I_out"]), indent=1) + "\n")
        print(out / name / "board.kicad_pcb")


if __name__ == "__main__":
    main(sys.argv[1])
