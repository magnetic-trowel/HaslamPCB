# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which boards' placer physics terms change when build._Ctx.net_volts takes abs(): board ids on
stdin, one JSON line per board (structures whose alloc or volts differ). Run from kae/ with
PYTHONPATH=src on the commit before the fix (it patches the old and new rule in turn).
Corpus: KAE_BOARDS (default ~/kae-boards/boards)."""
import json, os, sys, time
from kae.board.kicad_file import load
from kae.circuit.brief import build as brief_of
from kae.physics import build as B
from kae.physics.place_terms import Terms

BOARDS = os.environ.get("KAE_BOARDS", os.path.expanduser("~/kae-boards/boards"))
old = B._Ctx.net_volts
def new(self, net):
    r = self.nets.get(net) or {}
    v = r.get('volts')
    return abs(float(v)) if v else B._volts(net)

def sig(T):
    out = []
    for s in T.structs:
        a = getattr(s.alloc, 'value', s.alloc)
        info = {k: v for k, v in s.info.items() if k in ('V_in', 'V', 'L_abs_nH', 'V_abs')}
        out.append((s.id, s.kind, a, json.dumps(info, sort_keys=True, default=str)))
    cl = None
    if T.thermal is not None:
        cl = repr(getattr(T.thermal, 'P', None))
    return out, sorted(T.warnings), cl

for bid in sys.stdin.read().split():
    t0 = time.time()
    try:
        b = load(os.path.join(BOARDS, bid, "board.kicad_pcb"))
        br = brief_of(b)
        negs = sorted(n for n, r in (br.get('nets') or {}).items() if (r or {}).get('volts') and float(r['volts']) < 0)
        B._Ctx.net_volts = old
        a = sig(Terms(b, br))
        B._Ctx.net_volts = new
        c = sig(Terms(b, br))
        diff = [(x, y) for x, y in zip(a[0], c[0]) if x != y]
        res = dict(id=bid, neg=negs, n_structs=(len(a[0]), len(c[0])), changed=len(diff) + abs(len(a[0]) - len(c[0])),
                   warn_changed=a[1] != c[1], thermal_changed=a[2] != c[2], ex=[list(map(str, d)) for d in diff[:3]],
                   warn_old=[w for w in a[1] if w not in c[1]][:3], s=round(time.time() - t0, 1))
    except Exception as e:
        res = dict(id=bid, error=f"{type(e).__name__}: {e}"[:200])
    print(json.dumps(res), flush=True)
