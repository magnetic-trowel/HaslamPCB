# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Feedback-divider pickup on a layout: the place terms' coupling structures whose victim is a regulator's
feedback node (haslam.physics.place_terms.Terms.breakdown, structure ids containing 'feedback'), one row each.

    python fb_pickup.py --batch LIST.tsv -o rows.jsonl     # LIST: board_id<TAB>layout<TAB>path (.kicad_pcb[.gz])

The brief comes from the layout itself (netlist only; positions never read), so every layout of a board is priced by
the same structures. Row: board, layout, id, kind, value (mV), unit, util.
"""
import argparse
import json
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / 'haslam' / 'src'))
sys.path.insert(0, str(HERE.parent))

from passive_poses import _load  # noqa: E402
from haslam.circuit.brief import build  # noqa: E402
from haslam.physics.place_terms import Terms  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', required=True)
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args(argv)
    out = open(a.out, 'a')
    for line in open(a.batch):
        if not line.strip():
            continue
        bid, layout, path = line.rstrip('\n').split('\t')[:3]
        try:
            b = _load(path)
            t = Terms(b, build(b))
            poses = {fp.uuid: (fp.x, fp.y, fp.rot, fp.side) for fp in b.footprints}
            for s in t.breakdown(poses):
                if 'feedback' in s['id']:
                    out.write(json.dumps(dict(board=bid, layout=layout, id=s['id'], kind=s['kind'], value=s['value'],
                                              unit=s['unit'], util=s['util'])) + '\n')
        except Exception as e:
            out.write(json.dumps(dict(board=bid, layout=layout, error=f"{type(e).__name__}: {e}",
                                      tb=traceback.format_exc()[-400:])) + '\n')
        out.flush()


if __name__ == '__main__':
    main()
