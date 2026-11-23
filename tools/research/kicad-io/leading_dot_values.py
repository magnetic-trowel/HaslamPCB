# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Survey: parts whose value fields write a leading-dot number ('.1uF', '.33uH', '.5MHz'), and what the
kae.circuit.values fix changes for them.

  python leading_dot_values.py OLD_VALUES_PY OUT.jsonl BOARD...

OLD_VALUES_PY is kae/src/kae/circuit/values.py before the fix (git show origin/main:...). For each board
whose text has such a field, one JSON line: per part, its ref, value, the parser its refdes calls for
(capacitance, resistance, inductance, frequency), the value before and after, and for capacitors the
brief's capacitor class (kae.circuit.roles.cap_class) before and after. Boards without one: a line with
parts = [] (so the count of boards scanned is in the output).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys

LEAD = re.compile(r'(?<![\w.])\.\d')
FIELD = re.compile(r'\((?:property|fp_text)\s+"?(?:Value|value|Capacitance|Val)"?\s+"(\.\d[^"]*)"')
PARSER = {"C": "capacitance", "R": "resistance", "L": "inductance", "Y": "frequency", "X": "frequency"}


def _old(path):
    spec = importlib.util.spec_from_file_location("kae_values_old", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kae_values_old"] = mod
    spec.loader.exec_module(mod)
    return mod


def scan(old, board_path):
    from kae.board.kicad_file import load
    from kae.circuit import roles as RO
    from kae.circuit import values as NEW
    from kae.circuit.netlist import Netlist
    text = open(board_path, errors="replace").read()
    rec = dict(board=board_path, parts=[])
    if not FIELD.search(text):
        return rec
    nl = Netlist.from_board(load(board_path))
    for ref, p in nl.parts.items():
        vals = [p.value] + [str(v) for k, v in (p.fields or {}).items() if k in ("Capacitance", "Val")]
        hit = next((v for v in vals if v and LEAD.search(v)), None)
        if hit is None:
            continue
        pre = re.match(r"[A-Za-z]+", ref)
        fn = PARSER.get((pre.group(0) if pre else "")[:1].upper())
        row = dict(ref=ref, value=hit, parser=fn)
        if fn:
            row["old"], row["new"] = getattr(old, fn)(hit), getattr(NEW, fn)(hit)
        if fn == "capacitance":
            RO.V = old
            row["class_old"] = RO.cap_class(p)[0]
            RO.V = NEW
            row["class_new"] = RO.cap_class(p)[0]
        rec["parts"].append(row)
    return rec


if __name__ == "__main__":
    old = _old(sys.argv[1])
    with open(sys.argv[2], "a") as fo:
        for b in sys.argv[3:]:
            try:
                r = scan(old, b)
            except Exception as e:  # noqa: BLE001 - one board's failure is a row
                r = dict(board=b, error=f"{type(e).__name__}: {e}")
            fo.write(json.dumps(r) + "\n")
