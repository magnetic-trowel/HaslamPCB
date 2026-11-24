# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""return_board.py: return-path rows of one board file, without KiCad (fill-independent).

Stored method outputs carry zone outlines but no saved fills, so a fill-based critic would need a KiCad refill.
This module builds a pseudo-fill instead, identically for every arm (human, control, treatment):

  ground fill(layer) = ground-zone outline - keep-out areas that forbid copper pour
                       - other-net copper on that layer grown by the zone clearance,
                       opened by 0.125 mm, keeping only pieces that touch ground copper on that layer.
  ground copper(layer) = pseudo-fill + ground tracks + ground pads and vias.

Signal nets come from pc_refplane's name regexes (power and ground excluded). Rows:

  cov_opp    share of signal track length directly over ground copper on an adjacent copper layer
             (on a 2-layer board: the opposite layer)
  cov_same   share with same-layer ground copper within D mm of the track centre line
  cov_any    either
  unc_mm     signal track length with neither
  fast_*     the same four rows on fast nets only (pc_refplane.FAST_RE); None without fast tracks
  worst_net, worst_unc_mm   the signal net with the most uncovered length; nets_unc: top nets by uncovered mm
  gfill      connected ground fill area / (layers x board area); gpieces, islands (unconnected pieces dropped)

Prototype and its stage 0 numbers: design 3 of the 2026-11-20 gap audit (`s0_return.py`). Report only: these rows
judge nothing until they pass the mutation benchmark.

Usage: python3 tools/kaeres/return_board.py BOARD.kicad_pcb[.gz] ... [--json OUT]
"""
import argparse
import collections
import gzip
import json
import os
import sys
import tempfile
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'physics'))
import pc_refplane as P  # noqa: E402

D = 1.0           # same-layer reach (mm)
OPEN = 0.125      # opening radius of the pseudo-fill (mm), drops slivers
MIN_PIECE = 0.05  # mm^2
EDGE = 0.3        # zone pulled back from the board edge (mm)
TOP_NETS = 5
EMPTY = Polygon()


class Board(P.Board):
    def _outline(self, tree):
        self.tree = tree
        return super()._outline(tree)


def geoms(g):
    if g.is_empty:
        return []
    return list(g.geoms) if hasattr(g, 'geoms') else [g]


def union(parts):
    return unary_union(parts) if parts else EMPTY


def load(path):
    """A Board from a .kicad_pcb or .kicad_pcb.gz path."""
    path = str(path)
    if not path.endswith('.gz'):
        return Board(path)
    with gzip.open(path, 'rt', encoding='utf-8', errors='replace') as f, \
            tempfile.NamedTemporaryFile('w', suffix='.kicad_pcb', delete=False) as t:
        t.write(f.read())
        tmp = t.name
    try:
        return Board(tmp)
    finally:
        os.unlink(tmp)


def zone_layers(z, layers):
    zl = (P.first(z, 'layer') or [])[1:] + (P.first(z, 'layers') or [])[1:]
    if any(x in ('*.Cu', 'F&B.Cu') for x in zl):
        return list(layers) if '*.Cu' in zl else [x for x in ('F.Cu', 'B.Cu') if x in layers]
    return [x for x in zl if x in layers]


def zone_shape(z):
    """A zone's outline. KiCad reads a zone's first `polygon` as the outline and every later one as a hole in it
    (ZONE::AddPolygon), which is how a cutout is saved; a later polygon that is not inside the outline is added,
    so an odd file loses no area."""
    polys = []
    for pg in P.kids(z, 'polygon'):
        pts = [P.xy(q) for q in (P.first(pg, 'pts') or []) if isinstance(q, list) and q[0] == 'xy']
        if len(pts) >= 3:
            polys.append(Polygon(pts).buffer(0))
    if not polys:
        return EMPTY
    out = polys[0]
    for p in polys[1:]:
        out = out.difference(p) if polys[0].buffer(1e-6).contains(p) else out.union(p)
    return out


def no_pour(z):
    """True for a keep-out rule area that forbids copper pour (KiCad 5 and 6+ syntax)."""
    k = P.first(z, 'keepout')
    if not k:
        return False
    cp = P.first(k, 'copperpour')
    return bool(cp) and len(cp) > 1 and cp[1] == 'not_allowed'


def copper_by_net(b, layers):
    cu = {l: collections.defaultdict(list) for l in layers}   # layer -> net -> [geom]
    for s in b.segments:
        if s['layer'] in cu and len(s['pts']) >= 2:
            cu[s['layer']][s['net']].append(LineString(s['pts']).buffer(s['w'] / 2, quad_segs=4))
    for v in b.vias:
        for l in v['layers']:
            if l in cu:
                cu[l][v['net']].append(Point(v['x'], v['y']).buffer(v['size'] / 2, quad_segs=4))
    for p in b.pads:
        for l in p['layers'] & set(layers):
            cu[l][p['net']].append(p['shape'])
    return cu


def pseudo_fill(b, layers, cu):
    keep = collections.defaultdict(list)
    for z in P.kids(b.tree, 'zone'):
        if no_pour(z):
            for l in zone_layers(z, layers):
                keep[l].append(zone_shape(z))
    keep = {l: union(g) for l, g in keep.items()}
    fill = {l: [] for l in layers}
    islands, zone_area = 0, 0.0
    for z in P.kids(b.tree, 'zone'):
        net = b._net(z) or (P.first(z, 'net_name') or [None, ''])[1]
        if not net or P.first(z, 'keepout') or b.role(net) != 'gnd':
            continue
        cp = P.first(z, 'connect_pads')
        cl = 0.2
        if cp and P.first(cp, 'clearance'):
            cl = max(0.1, float(P.first(cp, 'clearance')[1]))
        out = zone_shape(z)
        if out.is_empty:
            continue
        if b.outline is not None:
            out = out.intersection(b.outline.buffer(-EDGE))
        for l in zone_layers(z, layers):
            f = out.difference(keep[l]) if l in keep else out
            zone_area += f.area
            other = union([g for n, gs in cu[l].items() if n != net for g in gs])
            if not other.is_empty:
                f = f.difference(other.buffer(cl, quad_segs=4))
            f = f.buffer(-OPEN).buffer(OPEN, quad_segs=4)
            own = union(cu[l].get(net, []))
            for piece in geoms(f):
                if piece.area < MIN_PIECE:
                    continue
                if not own.is_empty and piece.intersects(own):
                    fill[l].append(piece)
                else:
                    islands += 1
    return fill, islands, zone_area


def _share(x, tot):
    return x / tot if tot else None


def measure_board(b):
    """Return rows of a parsed Board (see the module docstring)."""
    layers = list(b.cu)
    idx = {l: i for i, l in enumerate(layers)}
    adj = {l: [layers[j] for j in (idx[l] - 1, idx[l] + 1) if 0 <= j < len(layers)] for l in layers}
    cu = copper_by_net(b, layers)
    gnd_nets = {n for l in layers for n in cu[l] if b.role(n) == 'gnd'}
    fill, islands, zone_area = pseudo_fill(b, layers, cu)
    gnd = {l: union(fill[l] + [g for n in gnd_nets for g in cu[l].get(n, [])]) for l in layers}
    under = {l: union([gnd[a] for a in adj[l] if not gnd[a].is_empty]) for l in layers}
    near = {l: gnd[l].buffer(D, quad_segs=4) if not gnd[l].is_empty else EMPTY for l in layers}
    anyreg = {l: union([g for g in (near[l], under[l]) if not g.is_empty]) for l in layers}

    def cut(ln, reg):
        return ln.intersection(reg).length if not reg.is_empty else 0.0

    acc = {k: [0.0, 0.0, 0.0, 0.0] for k in ('all', 'fast')}   # tot, opp, same, any
    per_net = collections.defaultdict(float)
    signals = {s['net'] for s in b.segments if b.role(s['net']) == 'signal'}
    for s in b.segments:
        l = s['layer']
        if l not in idx or b.role(s['net']) != 'signal' or len(s['pts']) < 2:
            continue
        ln = LineString(s['pts'])
        if ln.length <= 0:
            continue
        v = (ln.length, cut(ln, under[l]), cut(ln, near[l]), cut(ln, anyreg[l]))
        keys = ('all', 'fast') if P.is_fast(b, s['net'], False) else ('all',)
        for k in keys:
            acc[k] = [a + x for a, x in zip(acc[k], v)]
        per_net[s['net']] += v[0] - v[3]
    out = {}
    for k, pre in (('all', ''), ('fast', 'fast_')):
        tot, o, sm, an = acc[k]
        out.update({pre + 'sig_mm': round(tot, 2), pre + 'cov_opp': _share(o, tot), pre + 'cov_same': _share(sm, tot),
                    pre + 'cov_any': _share(an, tot), pre + 'unc_mm': round(tot - an, 2)})
    worst = sorted(((round(mm, 2), n) for n, mm in per_net.items() if mm > 1e-6), reverse=True)
    pieces = sum(len(geoms(union(fill[l]))) for l in layers if fill[l])
    garea = sum(union(fill[l]).area for l in layers if fill[l])
    out.update(worst_net=worst[0][1] if worst else None, worst_unc_mm=worst[0][0] if worst else 0.0,
               nets_unc=[{'net': n, 'unc_mm': mm} for mm, n in worst[:TOP_NETS]],
               gfill=_share(garea, len(layers) * b.area), gpieces=pieces, islands=islands,
               zone_area=round(zone_area, 1), pseudo_area=round(garea, 1), layers=len(layers), ngnd=len(gnd_nets),
               nsignal_nets=len(signals), nseg=len(b.segments), area=round(b.area, 1))
    return out


def measure(path):
    """Return rows of one board file (.kicad_pcb or .kicad_pcb.gz)."""
    return measure_board(load(path))


_CACHE = {}


def measure_cached(path):
    """measure() once per path and process: the quality report pairs the control with every arm and the human."""
    key = str(path)
    if key not in _CACHE:
        _CACHE[key] = measure(path)
    return _CACHE[key]


PAIRED_KEYS = ('cov_opp', 'cov_any', 'fast_cov_opp', 'fast_cov_any', 'unc_mm')


def stored_path(store, row):
    """The stored output of a results.csv row: STORE/boards/<board>/runs/<run>/output.kicad_pcb.gz."""
    return Path(store) / 'boards' / row['board'] / 'runs' / row['run'] / 'output.kicad_pcb.gz'


def paired(A, B, boards, path_of, keys=PAIRED_KEYS, measure_fn=None):
    """{key: [(owner, board, B - A)]} on `boards` (rows of arm A and B by board, as in kaeres quality), skipping
    boards where either value is None or either board fails to parse. Meant for one hook line in the quality report:
      rows += [dict(diff_row(d, min_n, lower_better=k == 'unc_mm'), key=f'return: {k}', unit='mean B - A per board')
               for k, d in return_board.paired(A, B, fin, path_of).items()]"""
    measure_fn = measure_fn or measure
    out = {k: [] for k in keys}
    for b in boards:
        try:
            ra, rb = measure_fn(path_of(A[b])), measure_fn(path_of(B[b]))
        except Exception as e:  # noqa: BLE001  a board the parser cannot read drops out of the pairing, said on stderr
            print(f'return_board: {b} dropped from the pairing: {type(e).__name__}: {e}', file=sys.stderr)
            continue
        for k in keys:
            if ra.get(k) is not None and rb.get(k) is not None:
                out[k].append((A[b].get('owner'), b, rb[k] - ra[k]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('boards', nargs='+')
    ap.add_argument('--json', help='write {path: rows} here instead of printing')
    a = ap.parse_args(argv)
    res = {}
    for p in a.boards:
        try:
            res[p] = measure(p)
        except Exception as e:  # recorded, not hidden
            res[p] = {'error': f'{type(e).__name__}: {e}'}
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    else:
        print(json.dumps(res, indent=1))
    return 0 if all('error' not in r for r in res.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
