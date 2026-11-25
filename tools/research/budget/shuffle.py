#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a copy of a .kicad_pcb whose copper is the same but whose file order and UUIDs are not.

The top-level (segment), (arc) and (via) blocks are put in a seeded random order and given fresh
(seeded) UUIDs; everything else stays byte-identical. The board's project files (.kicad_pro,
.kicad_dru, .kicad_prl) are copied beside the output under its name. KiCad breaks ties (ratsnest
pairs, DRC endpoints, list order) by load order and UUIDs, so a flow whose decisions depend on
them gives another board from this copy: counted-budget runs (HASLAM_BUDGET=work) must not.

    shuffle.py IN.kicad_pcb OUT.kicad_pcb [--seed N]
"""
from __future__ import annotations

import argparse
import random
import re
import shutil
import sys
import uuid
from pathlib import Path

_UUID = re.compile(r'\(uuid "?[0-9a-fA-F-]+"?\)')
_COPPER = ("\t(segment", "\t(arc", "\t(via")


def shuffle_copper(src, dst, seed=1):
    """Write `src` to `dst` with its copper blocks shuffled and re-UUIDed; returns the number of blocks."""
    src, dst = Path(src), Path(dst)
    lines = src.read_text(errors="replace").split("\n")
    rng = random.Random(seed)
    blocks, first, out, i = [], None, [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith(_COPPER) and not ln.startswith("\t(via_"):
            j, depth = i, 0
            while True:
                depth += lines[j].count("(") - lines[j].count(")")
                if depth <= 0:
                    break
                j += 1
            blocks.append(lines[i:j + 1])
            if first is None:
                first = len(out)
            i = j + 1
            continue
        out.append(ln)
        i += 1
    rng.shuffle(blocks)
    for k, blk in enumerate(blocks):
        u = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        blocks[k] = [_UUID.sub(f'(uuid "{u}")', x) for x in blk]
    if blocks:
        out[first:first] = [x for b in blocks for x in b]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out))
    for f in src.parent.glob(src.stem + ".kicad_*"):
        if f.suffix in (".kicad_pro", ".kicad_dru", ".kicad_prl"):
            shutil.copy2(f, dst.parent / (dst.stem + f.suffix))
    return len(blocks)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    n = shuffle_copper(a.input, a.output, a.seed)
    print(f"{n} copper blocks shuffled and re-UUIDed -> {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
