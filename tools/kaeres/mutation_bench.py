# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mutation benchmark for physics rows: plant known faults in a board and check each row responds.

A row may steer the placer or judge a layout only after it passes this gate (design 3, approach e).
Operators (all edit the .kicad_pcb text; nets stay connected, no KiCad needed to build a mutant):
  stretch REF D      move part REF D mm away from the parts it serves and bridge each old pad centre to
                     its new one with a track on the pad's layer, so connectivity is unchanged.
                     Expected: that part's rows up (inductance, hop length), monotone in D (1, 2, 4 mm).
  narrow NET F       scale every track width of NET by F (0.5, 0.25). Expected: rail resistance up,
                     loop rows never down.
  slot_under I       add a copper-pour keep-out (rule area, 0.6 x 12 mm) on the opposite outer layer
                     across signal track I's midpoint. Expected: return coverage down.
  benign             an unrelated part moved 1 mm (bridged), the title renamed, the file re-saved.
                     Expected: every row within 1 %.
Gate per row kind (section 4, T1 micro): right sign on >= 90 % of mutants, monotone in dose on >= 80 % of
targets, benign response (rows moving > 1 %) at most 5 %, modules lost at most 10 %.

The measure is pluggable: --measure physics uses physics_board.measure (module rows u/value); a
measure is any callable path -> {row_id: {"kind": str, "value": float|None}}.

  python mutation_bench.py --board BOARD.kicad_pcb --input TASK_INPUT.kicad_pcb --out OUT.json
                           [--targets REF,REF] [--measure physics] [--keep DIR]
"""
import argparse
import json
import math
import os
import re
import shutil
import sys
import tempfile

GND_RE = re.compile(r'(^|[^A-Z])(A|D|P|S|C)?GND|^/?VSS|^0V$', re.I)
TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')

STRETCH_DOSES = (1.0, 2.0, 4.0)
NARROW_DOSES = (0.5, 0.25)
BENIGN_TOL = 0.01
GATE = dict(sign=0.90, monotone=0.80, benign=0.05, lost=0.10)


# ----------------------------------------------------------------------------- s-expressions
class Q(str):
    """A token that was quoted in the file (written back quoted)."""


def parse(text):
    stack = [[]]
    for m in TOK.finditer(text):
        t = m.group(0)
        if t == '(':
            stack.append([])
        elif t == ')':
            x = stack.pop()
            stack[-1].append(x)
        elif t[0] == '"':
            stack[-1].append(Q(t[1:-1]))
        else:
            stack[-1].append(t)
    return stack[0][0]


def dump(node, ind=0):
    if not isinstance(node, list):
        return f'"{node}"' if isinstance(node, Q) else str(node)
    flat = all(not isinstance(c, list) for c in node)
    if flat or len(node) <= 3 and all(not isinstance(c, list) or all(not isinstance(d, list) for d in c) for c in node):
        return '(' + ' '.join(dump(c) for c in node) + ')'
    pad = '\t' * (ind + 1)
    out = '(' + ' '.join(dump(c) for c in node if not isinstance(c, list))
    for c in node:
        if isinstance(c, list):
            out += '\n' + pad + dump(c, ind + 1)
    return out + '\n' + '\t' * ind + ')'


def kids(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def first(node, name):
    for c in node:
        if isinstance(c, list) and c and c[0] == name:
            return c
    return None


def fnum(x):
    return f'{x:.6f}'.rstrip('0').rstrip('.') or '0'


def netmap(tree):
    """Net number -> name from the board's top-level (net N "name") declarations."""
    return {str(n[1]): str(n[2]) for n in kids(tree, 'net') if len(n) > 2}


def net_name(node, nets=None):
    """Net name of a pad/segment/via node: (net N "name"), (net "name") or (net N) resolved by NETS; '' when none."""
    n = first(node, 'net')
    if not n or len(n) < 2:
        return ''
    if isinstance(n[-1], Q) or len(n) > 2:
        return str(n[-1])
    return (nets or {}).get(str(n[1]), '')


def rot(x, y, deg):
    a = math.radians(deg)  # KiCad: y down, positive angle = counter-clockwise on screen
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)


def ref_of(fp):
    for p in kids(fp, 'property'):
        if len(p) > 2 and p[1] == 'Reference':
            return str(p[2])
    for t in kids(fp, 'fp_text'):
        if len(t) > 2 and t[1] == 'reference':
            return str(t[2])
    return ''


def footprints(tree):
    return {ref_of(fp): fp for fp in kids(tree, 'footprint')}


def fp_at(fp):
    a = first(fp, 'at')
    return float(a[1]), float(a[2]), float(a[3]) if len(a) > 3 else 0.0


def fp_layer(fp):
    ly = first(fp, 'layer')
    return str(ly[1]) if ly else 'F.Cu'


def pad_abs(fp, pad):
    fx, fy, fr = fp_at(fp)
    a = first(pad, 'at')
    dx, dy = rot(float(a[1]), float(a[2]), fr)
    return fx + dx, fy + dy


def pad_layer(fp, pad):
    """Copper layer for a bridge track at this pad: its own outer layer, F.Cu for through-hole."""
    ly = first(pad, 'layers')
    names = [str(x) for x in ly[1:]] if ly else []
    for want in ('F.Cu', 'B.Cu'):
        if want in names:
            return want
    return 'F.Cu' if any(n.startswith('*') for n in names) else fp_layer(fp)


# ----------------------------------------------------------------------------- operators
def _segment(a, b, width, layer, net_node):
    return ['segment', ['start', fnum(a[0]), fnum(a[1])], ['end', fnum(b[0]), fnum(b[1])],
            ['width', fnum(width)], ['layer', Q(layer)], list(net_node)]


def _away_dir(tree, fp, ref):
    """Unit vector from the centroid of the pads that share REF's nets (ground last resort) to REF."""
    mine = {net_name(p) for p in kids(fp, 'pad')} - {''}
    pref = {n for n in mine if not GND_RE.search(n)} or mine
    pts = [pad_abs(o, p) for r, o in footprints(tree).items() if r != ref
           for p in kids(o, 'pad') if net_name(p) in pref]
    fx, fy, _ = fp_at(fp)
    if not pts:
        return 1.0, 0.0
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    d = math.hypot(fx - cx, fy - cy)
    return ((fx - cx) / d, (fy - cy) / d) if d > 1e-6 else (1.0, 0.0)


def stretch(tree, ref, dist, width=0.25, direction=None):
    """Move REF by DIST mm away from the parts it serves; bridge old to new pad centres. Returns bridges added."""
    fp = footprints(tree).get(ref)
    if fp is None:
        raise KeyError(f'no footprint {ref}')
    ux, uy = direction or _away_dir(tree, fp, ref)
    dx, dy = ux * dist, uy * dist
    bridges = []
    for pad in kids(fp, 'pad'):
        n = first(pad, 'net')
        if not n or not net_name(pad):
            continue
        old = pad_abs(fp, pad)
        bridges.append(_segment(old, (old[0] + dx, old[1] + dy), width, pad_layer(fp, pad), n))
    a = first(fp, 'at')
    a[1], a[2] = fnum(float(a[1]) + dx), fnum(float(a[2]) + dy)
    tree.extend(bridges)
    return len(bridges)


def narrow(tree, net, factor):
    """Scale every track width of NET by FACTOR. Returns tracks changed."""
    k, nets = 0, netmap(tree)
    for s in kids(tree, 'segment') + kids(tree, 'arc'):
        if net_name(s, nets) == net:
            w = first(s, 'width')
            w[1] = fnum(float(w[1]) * factor)
            k += 1
    if not k:
        raise KeyError(f'no tracks on net {net}')
    return k


def signal_segments(tree):
    """Outer-layer signal tracks (not ground, not power-named), longest first: (index into tree, node)."""
    out, nets = [], netmap(tree)
    for i, s in enumerate(tree):
        if not (isinstance(s, list) and s and s[0] == 'segment'):
            continue
        n = net_name(s, nets)
        ly = str(first(s, 'layer')[1])
        if not n or GND_RE.search(n) or re.search(r'^/?(\+|V(CC|DD|IN|BAT|BUS))', n, re.I) or ly not in ('F.Cu', 'B.Cu'):
            continue
        a, b = first(s, 'start'), first(s, 'end')
        out.append((math.dist((float(a[1]), float(a[2])), (float(b[1]), float(b[2]))), i))
    return [i for L, i in sorted(out, reverse=True) if L > 3.0]


def slot_under(tree, index, length=12.0, width=0.6):
    """Copper-pour keep-out across the midpoint of segment TREE[INDEX] on the opposite outer layer."""
    s = tree[index]
    a, b = first(s, 'start'), first(s, 'end')
    x0, y0, x1, y1 = float(a[1]), float(a[2]), float(b[1]), float(b[2])
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    ux, uy = (x1 - x0) / L, (y1 - y0) / L          # along the track: slot width
    px, py = -uy, ux                                  # across the track: slot length
    corners = [(mx + sx * ux * width / 2 + sy * px * length / 2, my + sx * uy * width / 2 + sy * py * length / 2)
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    other = 'B.Cu' if str(first(s, 'layer')[1]) == 'F.Cu' else 'F.Cu'
    tree.append(['zone', ['net', '0'], ['net_name', Q('')], ['layer', Q(other)], ['name', Q('kae-mutation-slot')],
                 ['hatch', 'edge', '0.5'], ['connect_pads', ['clearance', '0']], ['min_thickness', '0.25'],
                 ['keepout', ['tracks', 'allowed'], ['vias', 'allowed'], ['pads', 'allowed'],
                  ['copperpour', 'not_allowed'], ['footprints', 'allowed']],
                 ['fill', ['thermal_gap', '0.5'], ['thermal_bridge_width', '0.5']],
                 ['polygon', ['pts'] + [['xy', fnum(x), fnum(y)] for x, y in corners]]])
    return other


def benign_move(tree, targets, dist=1.0):
    """Move the part farthest from every target by DIST mm (bridged). Returns its ref."""
    fps = footprints(tree)
    tpos = [fp_at(fps[t])[:2] for t in targets if t in fps]
    tnets = {net_name(p) for t in targets if t in fps for p in kids(fps[t], 'pad')} - {''}
    best = None
    for r, fp in fps.items():
        if not r or r in targets or not kids(fp, 'pad'):
            continue
        nets = {net_name(p) for p in kids(fp, 'pad')} - {''}
        if nets & {n for n in tnets if not GND_RE.search(n)}:
            continue
        d = min((math.dist(fp_at(fp)[:2], p) for p in tpos), default=0.0)
        if best is None or d > best[0]:
            best = (d, r)
    if best is None:
        return None
    stretch(tree, best[1], dist, direction=(1.0, 0.0))
    return best[1]


def rename_title(tree):
    tb = first(tree, 'title_block')
    if tb is None:
        tb = ['title_block']
        tree.append(tb)
    t = first(tb, 'title')
    if t is None:
        tb.append(['title', Q('kae-mutation-benign')])
    else:
        t[1] = Q(str(t[1]) + ' (benign)')


# ----------------------------------------------------------------------------- mutant plan
def plan(tree, targets, rail_nets=(), n_slots=4):
    """List of (mutant_id, operator, target, dose, expected_sign, apply(tree))."""
    out = []
    for ref in targets:
        for d in STRETCH_DOSES:
            out.append((f'stretch:{ref}:{d:g}', 'stretch', ref, d, +1, lambda t, r=ref, d=d: stretch(t, r, d)))
    for net in rail_nets:
        for f in NARROW_DOSES:
            out.append((f'narrow:{net}:{f:g}', 'narrow', net, 1 / f, +1, lambda t, n=net, f=f: narrow(t, n, f)))
    for i in signal_segments(tree)[:n_slots]:
        out.append((f'slot_under:{i}', 'slot_under', str(i), 1.0, -1, lambda t, i=i: slot_under(t, i)))
    out.append(('benign:move', 'benign', '', 0.0, 0, lambda t: benign_move(t, targets)))
    out.append(('benign:rename', 'benign', '', 0.0, 0, rename_title))
    out.append(('benign:resave', 'benign', '', 0.0, 0, lambda t: None))
    return out


def write_mutants(board, outdir, targets, rail_nets=(), n_slots=4):
    """Write base.kicad_pcb (round-tripped, the reference) and one file per mutant; returns the mutant list."""
    with open(board, encoding='utf-8') as f:
        text = f.read()
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, 'base.kicad_pcb')
    with open(base, 'w', encoding='utf-8') as f:
        f.write(dump(parse(text)) + '\n')
    muts = []
    for mid, op, target, dose, sign, fn in plan(parse(text), targets, rail_nets, n_slots):
        tree = parse(text)
        rec = dict(id=mid, op=op, target=target, dose=dose, sign=sign)
        try:
            rec['detail'] = fn(tree)
        except Exception as e:  # noqa: BLE001  recorded, the mutant is skipped
            rec['error'] = f'{type(e).__name__}: {e}'
            muts.append(rec)
            continue
        rec['path'] = os.path.join(outdir, mid.replace(':', '_') + '.kicad_pcb')
        with open(rec['path'], 'w', encoding='utf-8') as f:
            f.write(dump(tree) + '\n')
        muts.append(rec)
    return base, muts


# ----------------------------------------------------------------------------- gate
def _rel(a, b):
    if a is None or b is None:
        return None
    return (b - a) / abs(a) if a else (0.0 if b == a else math.copysign(math.inf, b - a))


def responses(base_rows, mut_rows):
    """{row_id: relative change} for rows valued in both; and the ids lost (valued in base, not in mutant)."""
    rel, lost = {}, []
    for k, r in base_rows.items():
        if r.get('value') is None:
            continue
        m = mut_rows.get(k) or {}
        if m.get('value') is None:
            lost.append(k)
        else:
            rel[k] = _rel(r['value'], m['value'])
    return rel, lost


def gate(base_rows, results, row_filter=None):
    """Score each row kind. RESULTS: [{op, target, dose, sign, rows}]. ROW_FILTER(op, target, row_id) picks the
    rows a mutant is meant to move (default: all rows whose response is non-zero for targeted operators)."""
    kinds = sorted({r.get('kind') or '?' for r in base_rows.values()})
    rep = {}
    for kind in kinds:
        ids = {k for k, r in base_rows.items() if (r.get('kind') or '?') == kind}
        sign_n = sign_ok = ben_n = ben_bad = lost = valued = 0
        doses = {}
        for res in results:
            if 'rows' not in res:
                continue
            rel, gone = responses({k: base_rows[k] for k in ids}, res['rows'])
            valued += len(rel) + len(gone)
            lost += len(gone)
            if res['sign'] == 0:
                ben_n += len(rel)
                ben_bad += sum(1 for v in rel.values() if abs(v) > BENIGN_TOL)
                continue
            pick = {k: v for k, v in rel.items() if (row_filter or (lambda o, t, k: True))(res['op'], res['target'], k)}
            if row_filter is None:
                pick = {k: v for k, v in pick.items() if v != 0}
            if not pick:
                continue
            # the mutant's response for this kind: the change of largest magnitude among its rows
            v = max(pick.values(), key=abs)
            sign_n += 1
            sign_ok += (v * res['sign'] > 0)
            doses.setdefault((res['op'], res['target']), []).append((res['dose'], v * res['sign']))
        mono = [all(b[1] >= a[1] for a, b in zip(seq, seq[1:])) for seq in
                (sorted(s) for s in doses.values()) if len(seq) >= 2]
        r = dict(mutants=sign_n, sign=sign_ok / sign_n if sign_n else None,
                 monotone=sum(mono) / len(mono) if mono else None, targets=len(mono),
                 benign=ben_bad / ben_n if ben_n else None, lost=lost / valued if valued else None)
        r['pass'] = bool(sign_n and r['sign'] >= GATE['sign'] and (r['monotone'] is None or r['monotone'] >= GATE['monotone'])
                         and (r['benign'] is None or r['benign'] <= GATE['benign']) and r['lost'] <= GATE['lost'])
        rep[kind] = r
    return rep


# ----------------------------------------------------------------------------- measures
def physics_measure(input_board, pintypes=None):
    """Module rows from physics_board.measure (brief and terms built once from the task input)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import physics_board as PB
    from kae.circuit.brief import build
    from kae.place.stubs import make_terms
    if pintypes and os.path.exists(pintypes):
        with open(pintypes) as f:
            PB.PINS = json.load(f).get('refs') or None
    inp = PB.load_board(input_board)
    brief = build(inp)
    try:
        terms, _ = make_terms(inp, brief)
    except Exception:  # noqa: BLE001
        terms = None

    def measure(path):
        m = PB.measure(path, brief, terms)
        rows = {k: dict(kind=v.get('kind'), value=v.get('value')) for k, v in m['modules'].items()}
        if m.get('worst_rail_mohm') is not None:
            rows['_rail'] = dict(kind='rail', value=m['worst_rail_mohm'])
        return rows
    return measure


def run(board, measure, outdir, targets, rail_nets=(), n_slots=4):
    base, muts = write_mutants(board, outdir, targets, rail_nets, n_slots)
    base_rows = measure(base)
    for m in muts:
        if 'path' in m:
            try:
                m['rows'] = measure(m['path'])
            except Exception as e:  # noqa: BLE001
                m['error'] = f'{type(e).__name__}: {e}'[:500]
    return dict(board=board, base=base_rows, mutants=muts, gate=gate(base_rows, muts))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--board', required=True, help='routed board to mutate (e.g. the human layout)')
    ap.add_argument('--input', help='route task input board (brief source for --measure physics)')
    ap.add_argument('--pintypes')
    ap.add_argument('--targets', default='', help='comma-separated refs to stretch (decap, input cap, crystal, ...)')
    ap.add_argument('--rails', default='', help='comma-separated rail nets to narrow')
    ap.add_argument('--slots', type=int, default=4)
    ap.add_argument('--measure', default='physics', choices=['physics', 'none'])
    ap.add_argument('--keep', help='directory for the mutant boards (default: a temporary one, removed)')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    targets = [t for t in a.targets.split(',') if t]
    rails = [t for t in a.rails.split(',') if t]
    outdir = a.keep or tempfile.mkdtemp(prefix='kae-mut-')
    try:
        if a.measure == 'none':
            base, muts = write_mutants(a.board, outdir, targets, rails, a.slots)
            rec = dict(board=a.board, base_path=base, mutants=muts)
        else:
            rec = run(a.board, physics_measure(a.input or a.board, a.pintypes), outdir, targets, rails, a.slots)
    finally:
        if not a.keep:
            shutil.rmtree(outdir, ignore_errors=True)
    with open(a.out, 'w') as f:
        json.dump(rec, f, indent=1, default=str)
    for kind, r in (rec.get('gate') or {}).items():
        print(kind, r)


if __name__ == '__main__':
    main()
