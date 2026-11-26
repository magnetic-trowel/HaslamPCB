# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where 2-pad passives sit relative to the pins they serve: one row per passive per layout.

    python passive_poses.py BOARD.kicad_pcb[.gz] [--layout NAME] [--board ID] [-o rows.jsonl]
    python passive_poses.py --batch LIST.tsv -o rows.jsonl     # LIST: board_id<TAB>layout<TAB>path

Roles come from the netlist only (haslam.circuit.roles / structures; positions never read), so the
human layout and a placer's layout of the same board get the same role and the same candidate pins.
The served pin is position-based and the same rule on every layout: among the pins of non-passive parts
(ICs, modules, connectors, LEDs, crystals, transistors, diodes) on the passive's serving net, the one
nearest the passive's pad on that net. The serving net is the passive's non-ground, non-rail net if it
has one (a pull-up serves its signal), else its rail net (a decap serves its rail pin); a ground net never.
Feedback dividers serve the regulator's FB pin, crystal load caps the crystal's pad.

Row fields (mm, degrees):
  role       refined role: decoupling, bulk, filter_to_ground, crystal_load, pull_up, pull_down, series,
             series_termination, termination, zero_ohm, led_resistor, feedback_divider, divider, inductor, ferrite, ...
  pkg        imperial chip code ('0402') or 'th'/'other'; pitch = pad-centre distance of the passive
  d          served pad centre -> served pin centre
  facing     the served pad is nearer the served pin than the other pad
  cosax      |cos| between the passive's pad axis and the served-pad -> pin vector (1 radial, 0 tangential)
  relrot     passive rotation minus served part rotation, mod 180, folded to [0, 90]
  same_side  passive on the served part's side
  g          (rail-to-ground caps) ground pad -> nearest pin of the served part on the cap's ground net
  loop       (rail-to-ground caps) area of the polygon served pin, cap rail pad, cap ground pad, served ground pin
  via        (rail-to-ground caps) ground pad -> nearest via on the ground net (None if the layout has none)
  grp        served part + serving net: caps sharing a group are checked for value ordering
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / 'haslam' / 'src'))

from haslam.board.kicad_file import load  # noqa: E402
from haslam.circuit.netlist import Netlist  # noqa: E402
from haslam.circuit.roles import infer_roles  # noqa: E402
from haslam.circuit.structures import find_structures  # noqa: E402
from haslam.circuit import values as V  # noqa: E402

PASSIVE_KINDS = {'resistor', 'capacitor', 'inductor', 'ferrite'}
SERVED_KINDS = {'ic', 'module', 'connector', 'led', 'crystal', 'oscillator', 'transistor', 'diode', 'optocoupler',
                'relay', 'switch', 'sensor', 'mosfet', 'regulator', 'fuse', 'unknown'}


def _load(path: str):
    if path.endswith('.gz'):
        with tempfile.TemporaryDirectory(dir=os.environ.get('HASLAMQ_SCRATCH') or None) as td:
            p = Path(td) / 'board.kicad_pcb'
            with gzip.open(path, 'rb') as f, open(p, 'wb') as g:
                shutil.copyfileobj(f, g)
            return load(str(p), rules=False)
    return load(path, rules=False)


def _shoelace(pts):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def _fold(a):
    a = a % 180.0
    return min(a, 180.0 - a)


def analyse(board, roles=None, structures=None):
    """Rows for the 2-pad passives of `board` (a haslam.board.model.Board). `roles`/`structures` may be
    passed in (from another layout of the same netlist) so every layout gets the same roles."""
    nl = Netlist.from_board(board)
    if roles is None:
        roles = infer_roles(nl)
        structures = find_structures(nl, roles)
    fps = list(board.footprints)
    keys = list(nl.parts)
    if len(keys) != len(fps):
        raise ValueError('netlist/footprint mismatch')
    fp_of = dict(zip(keys, fps))
    grounds = set(roles.grounds)
    rails = set(roles.rails)

    def kind(k):
        r = roles.parts.get(k)
        return r.kind if r else 'unknown'

    # role refinements from structures
    special = {}       # passive key -> (role, served key, served pad number or None)
    for v in structures.get('victims', []):
        div = v.get('divider') or {}
        if not div:
            continue
        top = div.get('top')
        top = top[0] if isinstance(top, (list, tuple)) else top
        bot = div.get('bottom')
        bot = bot[0] if isinstance(bot, (list, tuple)) else bot
        if v.get('class') == 'feedback':
            for r in (top, bot):
                if r in nl.parts:
                    special[r] = ('feedback_divider', v.get('ic'), v.get('fb_pin'))
        else:
            for r in (top, bot):
                if r in nl.parts and r not in special:
                    special[r] = ('divider', None, None)
    led_nets = set()
    for k, p in nl.parts.items():
        if kind(k) == 'led':
            led_nets |= set(p.nets)

    # served-pin candidates: net -> [(key, pad)]
    cand = {}
    for k, fp in fp_of.items():
        if kind(k) in PASSIVE_KINDS or not fp.on_board:
            continue
        for pd in fp.pads:
            if pd.net and pd.kind != 'np_thru_hole':
                cand.setdefault(pd.net, []).append((k, pd))
    vias_by_net = {}
    for v in board.vias:
        n = getattr(v, 'net', '')
        if n:
            vias_by_net.setdefault(n, []).append((v.x, v.y))
    ncu = sum(1 for n, t in (board.layers or {}).items() if n.endswith('.Cu'))
    rows = []
    for k, fp in fp_of.items():
        kd = kind(k)
        if kd not in PASSIVE_KINDS or not fp.on_board:
            continue
        pads = [p for p in fp.pads if p.kind != 'np_thru_hole']
        if len(pads) != 2 or not pads[0].net or not pads[1].net or pads[0].net == pads[1].net:
            continue
        part = nl.parts[k]
        role = roles.parts[k].role
        sk = special.get(k)
        if sk:
            role = sk[0]
        elif kd == 'resistor' and role in ('series', 'pull_up', 'pull_down') and \
                any(p.net in led_nets and len(nl.pins(p.net)) <= 3 for p in pads):
            role = 'led_resistor'
        # serving net
        sig = [p for p in pads if p.net not in grounds and p.net not in rails]
        rl = [p for p in pads if p.net in rails and p.net not in grounds]
        serve_pads = sig or rl
        if not serve_pads:
            continue
        best = None
        for sp in serve_pads:
            for ck, cp in cand.get(sp.net, []):
                if sk and sk[0] == 'feedback_divider' and sk[1] and (ck != sk[1] or (sk[2] and cp.number != sk[2])):
                    continue
                if role == 'crystal_load' and kind(ck) not in ('crystal', 'oscillator'):
                    continue
                dd = math.hypot(cp.x - sp.x, cp.y - sp.y)
                if best is None or dd < best[0]:
                    best = (dd, sp, ck, cp)
        if best is None:
            continue
        d, sp, ck, cp = best
        op = pads[1] if sp is pads[0] else pads[0]
        ax, ay = op.x - sp.x, op.y - sp.y
        vx, vy = cp.x - sp.x, cp.y - sp.y
        la, lv = math.hypot(ax, ay), math.hypot(vx, vy)
        cosax = abs(ax * vx + ay * vy) / (la * lv) if la > 1e-9 and lv > 1e-9 else None
        sfp = fp_of[ck]
        pk = part.package
        row = {
            'ref': fp.ref, 'kind': kd, 'role': role, 'pkg': pk.size or ('th' if pk.through_hole else 'other'),
            'pitch': round(la, 3), 'value': part.value, 'layers': ncu, 'side': fp.side,
            'served': sfp.ref, 'served_kind': kind(ck), 'served_npads': len(sfp.pads), 'served_pin': cp.number,
            'served_side': sfp.side, 'net_class': 'signal' if sig else 'rail',
            'd': round(d, 3), 'facing': math.hypot(cp.x - op.x, cp.y - op.y) > d, 'cosax': None if cosax is None else round(cosax, 3),
            'relrot': round(_fold(fp.rot - sfp.rot), 1), 'same_side': fp.side == sfp.side,
            'x': round(fp.x, 3), 'y': round(fp.y, 3), 'rot': fp.rot, 'served_x': round(sfp.x, 3), 'served_y': round(sfp.y, 3),
            'served_rot': sfp.rot, 'grp': f"{sfp.ref}|{sp.net}",
        }
        if kd == 'capacitor':
            row['farads'] = V.capacitance(part.value)
        elif kd == 'resistor':
            row['ohms'] = V.resistance(part.value)
        gp = op if op.net in grounds else None
        if gp is not None:
            gpins = [p for p in sfp.pads if p.net == gp.net]
            if gpins:
                gq = min(gpins, key=lambda p: math.hypot(p.x - gp.x, p.y - gp.y))
                row['g'] = round(math.hypot(gq.x - gp.x, gq.y - gp.y), 3)
                row['loop'] = round(_shoelace([(cp.x, cp.y), (sp.x, sp.y), (gp.x, gp.y), (gq.x, gq.y)]), 3)
            vs = vias_by_net.get(gp.net)
            row['via'] = round(min(math.hypot(x - gp.x, y - gp.y) for x, y in vs), 3) if vs else None
            vs = vias_by_net.get(sp.net)
            row['via_rail'] = round(min(math.hypot(x - sp.x, y - sp.y) for x, y in vs), 3) if vs else None
        rows.append(row)
    return rows, roles, structures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('board', nargs='?')
    ap.add_argument('--layout', default='human')
    ap.add_argument('--board-id', default=None)
    ap.add_argument('--batch', help='TSV: board_id, layout, path; layouts of one board share the first layout\'s roles')
    ap.add_argument('-o', '--out', default='-')
    a = ap.parse_args(argv)
    out = sys.stdout if a.out == '-' else open(a.out, 'a')
    jobs = []
    if a.batch:
        for line in open(a.batch):
            if line.strip():
                jobs.append(line.rstrip('\n').split('\t')[:3])
    else:
        jobs.append([a.board_id or Path(a.board).parent.name, a.layout, a.board])
    cache = {}
    import signal

    def _alarm(*_):
        raise TimeoutError('board over the time limit')
    signal.signal(signal.SIGALRM, _alarm)
    for bid, layout, path in jobs:
        signal.alarm(int(os.environ.get('PASSIVE_POSES_TIMEOUT', '300')))
        try:
            b = _load(path)
            r0 = cache.get(bid)
            rows, roles, st = analyse(b, *(r0 or (None, None)))
            if r0 is None:
                cache.clear()
                cache[bid] = (roles, st)
            for r in rows:
                out.write(json.dumps({'board': bid, 'layout': layout, **r}) + '\n')
        except Exception as e:    # one bad board must not stop a batch
            out.write(json.dumps({'board': bid, 'layout': layout, 'error': f"{type(e).__name__}: {e}",
                                  'tb': traceback.format_exc()[-600:]}) + '\n')
        signal.alarm(0)
        out.flush()


if __name__ == '__main__':
    main()
