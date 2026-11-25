# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Survey: board strings with a leading-dot number ('.5A', '.8V', '.5pF') that the parsers outside
kae.circuit.values read differently after the leading-dot fix (current ratings, net voltages, stated
crystal load, ferrite impedance, provisional-brief frequencies).

  python leading_dot_numbers.py OUT.jsonl BOARD...

Each parser's pattern before and after the fix is applied to every quoted string on the board that holds a
leading-dot number; a row per board lists the strings whose reading changes, with the footprint reference
before them and the parser. Boards without one: a line with hits = [] (so the count scanned is in the
output). Over-counts: the parser is applied whether or not the part is of the kind that parser reads.
"""
from __future__ import annotations

import json
import re
import sys

LEAD = re.compile(r'(?<![\w.])\.\d')
STR = re.compile(r'"([^"\n]{0,200})"')
REF = re.compile(r'\((?:property\s+"Reference"|fp_text\s+reference)\s+"([^"]*)"')
OLD_NUM, NEW_NUM = r'(\d+(?:\.\d+)?)', r'(\d+(?:\.\d+)?|\.\d+)'

# name: (pattern with {N} for the number, flags, how the parser sees the string)
PARSERS = {
    'inductor_current': (r'(?<![\w.]){N}\s*A(?![a-zA-Z])', 0, 'part'),          # circuit.structures
    'fuse_rating': (r'(?<![\d.]){N}\s*(m?)A(?![a-z])', 0, 'part'),               # circuit.structures
    'rail_inductor': ('{N}\\s*A\\b', 0, 'part'),                                  # route.critical_rails
    'stated_load_c': (r'(?:C_?L|load)\s*[=:]?\s*{N}\s*p', re.I, 'part'),          # circuit.structures
    'ferrite_ohms': (r'{N}\s*(R|ohm|Ω)', re.I, 'part'),                           # excite.models
    'brief_hz': (r'{N}\s*([pnumkKM]?)Hz', 0, 'part'),                             # physics.provisional_brief
    'net_volts': ('{N}V', 0, 'net'),                                              # physics.build, route.critical_modules
}
NEW_LB = {'rail_inductor': r'(?<![\d.])', 'ferrite_ohms': r'(?<![\d.])', 'brief_hz': r'(?<![\d.])',
          'net_volts': r'(?<![\d.])'}


def _compile(name):
    pat, fl, _ = PARSERS[name]
    old = re.compile(pat.replace('{N}', OLD_NUM), fl)
    new = re.compile(NEW_LB.get(name, '') + pat.replace('{N}', NEW_NUM), fl)
    return old, new


COMPILED = {k: _compile(k) for k in PARSERS}


def _read(rx, s):
    m = rx.search(s)
    return None if m is None else m.group(0)


def _net_form(s):
    s = s.split('/')[-1].upper().replace('_', '')
    return None if re.search(r'(\d+)V(\d+)', s) else s    # '3V3' is read by the pattern before


def scan(board_path):
    text = open(board_path, errors='replace').read()
    rec = dict(board=board_path, hits=[])
    for m in STR.finditer(text):
        s = m.group(1)
        if not LEAD.search(s):
            continue
        refs = REF.findall(text, max(0, m.start() - 4000), m.start())
        for name, (old, new) in COMPILED.items():
            t = _net_form(s) if PARSERS[name][2] == 'net' else s
            if t is None:
                continue
            a, b = _read(old, t), _read(new, t)
            if a != b:
                rec['hits'].append(dict(parser=name, s=s, ref=refs[-1] if refs else None, old=a, new=b,
                                        ctx=text[max(0, m.start() - 40):m.start()].split('\n')[-1].strip()))
    return rec


if __name__ == '__main__':
    with open(sys.argv[1], 'a') as fo:
        for b in sys.argv[2:]:
            try:
                r = scan(b)
            except Exception as e:  # noqa: BLE001 - one board's failure is a row
                r = dict(board=b, error=f'{type(e).__name__}: {e}')
            fo.write(json.dumps(r) + '\n')
