# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""return_check.py: an independent check of return_board.py's `cov_opp` against KiCad's own geometry.

return_board.py measures on a pseudo-fill built from zone outlines with shapely. This script measures the same
quantity a different way: KiCad (pcbnew) refills every zone, builds each copper layer's ground copper from the real
fill plus the ground nets' tracks, vias and pads (KiCad's own shape-to-polygon code), and samples every signal track
every STEP mm against the adjacent layers' ground copper. Only the net roles (which nets are signal, which ground)
come from return_board, so both measure the same tracks.

Two halves, because the KiCad image has no shapely and the shapely venv has no pcbnew:

  driver (python with shapely):
    return_check.py check BOARD... --kicad "$KAE_KICAD_WRAP python3" [--json OUT] [--mutate]
  KiCad side (called by the driver):
    return_check.py kicad-measure BOARD NETS.json OUT.json
    return_check.py kicad-mutate BOARD TARGET.json OUT.kicad_pcb

--mutate also cuts a ground slot (1 mm each side) under the longest signal track covered by pour only, and adds a
ground track under the longest uncovered one, then measures both mutants with both measures: cov_opp must fall after
the slot and rise after the added ground, in both. Report-only tooling; it judges nothing.
"""
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

STEP = 0.05      # mm between samples along a track
SLOT = 1.0       # mm of pour removed on each side of the slot's track
ADD_W = 1.0      # mm added to the track width for the added ground track
MIN_LEN = 2.0    # mm: shortest track a mutation is placed under


# ------------------------------------------------------------------ KiCad side (no shapely here)
def _mm(v):
    return v / 1e6


def kicad_measure(board_path, nets_path, out_path):
    import pcbnew
    nets = json.loads(Path(nets_path).read_text())
    gnd, sig = set(nets['gnd']), set(nets['signal'])
    b = pcbnew.LoadBoard(board_path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    layers = list(b.GetEnabledLayers().CuStack())
    names = [b.GetLayerName(l) for l in layers]
    err = pcbnew.FromMM(0.005)
    g = {l: pcbnew.SHAPE_POLY_SET() for l in layers}       # all ground copper
    gi = {l: pcbnew.SHAPE_POLY_SET() for l in layers}      # ground items only (no pour)
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() not in gnd:
            continue
        for l in layers:
            if z.IsOnLayer(l) and z.HasFilledPolysForLayer(l):
                z.TransformSolidAreasShapesToPolygon(l, g[l])
    items = [t for t in b.GetTracks() if t.GetNetname() in gnd] + [p for p in b.GetPads() if p.GetNetname() in gnd]
    for it in items:
        for l in layers:
            if it.IsOnLayer(l):
                it.TransformShapeToPolygon(g[l], l, 0, err, pcbnew.ERROR_INSIDE)
                it.TransformShapeToPolygon(gi[l], l, 0, err, pcbnew.ERROR_INSIDE)
    adj = {l: [layers[j] for j in (i - 1, i + 1) if 0 <= j < len(layers)] for i, l in enumerate(layers)}

    def hit(sets, x, y):
        p = pcbnew.VECTOR2I(int(round(x)), int(round(y)))
        return any(s.OutlineCount() and s.Contains(p) for s in sets)

    segs, tot, cov = [], 0.0, 0.0
    for t in b.GetTracks():
        if t.GetClass() not in ('PCB_TRACK', 'PCB_ARC') or t.GetNetname() not in sig or t.GetLayer() not in adj:
            continue
        a, e = t.GetStart(), t.GetEnd()
        if t.GetClass() == 'PCB_ARC':
            m = t.GetMid()
            pts = [(a.x, a.y), (m.x, m.y), (e.x, e.y)]
        else:
            pts = [(a.x, a.y), (e.x, e.y)]
        under = [g[l] for l in adj[t.GetLayer()]]
        under_i = [gi[l] for l in adj[t.GetLayer()]]
        ln = c = ci = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            L = _mm(math.hypot(x1 - x0, y1 - y0))
            n = max(1, int(math.ceil(L / STEP)))
            for k in range(n):
                f = (k + 0.5) / n
                x, y = x0 + f * (x1 - x0), y0 + f * (y1 - y0)
                if hit(under, x, y):
                    c += L / n
                    if hit(under_i, x, y):
                        ci += L / n
            ln += L
        if ln <= 0:
            continue
        tot, cov = tot + ln, cov + c
        segs.append(dict(net=t.GetNetname(), layer=b.GetLayerName(t.GetLayer()), len=ln, cov=c, cov_items=ci,
                         start=[_mm(pts[0][0]), _mm(pts[0][1])], end=[_mm(pts[-1][0]), _mm(pts[-1][1])],
                         width=_mm(t.GetWidth()), under=[b.GetLayerName(l) for l in adj[t.GetLayer()]]))
    Path(out_path).write_text(json.dumps(dict(sig_mm=tot, cov_opp=cov / tot if tot else None, layers=names,
                                              segments=segs)))


def kicad_mutate(board_path, target_path, out_path):
    import pcbnew
    t = json.loads(Path(target_path).read_text())
    b = pcbnew.LoadBoard(board_path)
    (x0, y0), (x1, y1) = t['start'], t['end']
    lids = [b.GetLayerID(n) for n in t['under']]
    if t['kind'] == 'slot':
        L = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        h = t['width'] / 2 + SLOT
        nx, ny = -uy * h, ux * h
        ex, ey = ux * h, uy * h
        corners = [(x0 - ex + nx, y0 - ey + ny), (x1 + ex + nx, y1 + ey + ny),
                   (x1 + ex - nx, y1 + ey - ny), (x0 - ex - nx, y0 - ey - ny)]
        cut = pcbnew.SHAPE_POLY_SET()
        cut.NewOutline()
        for x, y in corners:
            cut.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        n = 0
        for z in b.Zones():
            if z.GetIsRuleArea() or z.GetNetname() not in t['gnd']:
                continue
            if any(z.IsOnLayer(l) for l in lids):
                z.Outline().BooleanSubtract(cut)
                n += 1
        if not n:
            raise SystemExit('slot: no ground zone on the layer under the target')
    else:
        net = b.FindNet(t['gnd_net'])
        for l in lids:
            tr = pcbnew.PCB_TRACK(b)
            tr.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
            tr.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
            tr.SetWidth(pcbnew.FromMM(t['width'] + ADD_W))
            tr.SetLayer(l)
            tr.SetNet(net)
            b.Add(tr)
    for z in b.Zones():
        z.UnFill()
    pcbnew.SaveBoard(out_path, b)


# ------------------------------------------------------------------ driver (shapely side)
def _plain(path, tmp):
    """A plain .kicad_pcb copy of PATH in TMP (pcbnew reads no .gz)."""
    import gzip
    out = Path(tmp) / (Path(path).name.replace('.gz', '') if str(path).endswith('.gz') else Path(path).name)
    if str(path).endswith('.gz'):
        with gzip.open(path, 'rb') as f:
            out.write_bytes(f.read())
    else:
        out.write_bytes(Path(path).read_bytes())
    return out


def _kicad(kicad, *args):
    me = str(Path(__file__).resolve())
    subprocess.run(shlex.split(kicad) + [me, *map(str, args)], check=True, stdout=subprocess.DEVNULL)


def _both(kicad, path, tmp, tag):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import return_board as R
    b = R.load(path)
    names = {s['net'] for s in b.segments} | {p['net'] for p in b.pads} | {v['net'] for v in b.vias}
    names |= {b._net(z) for z in R.P.kids(b.tree, 'zone') if b._net(z)}
    nets = dict(gnd=sorted(n for n in names if n and b.role(n) == 'gnd'),
                signal=sorted(n for n in names if n and b.role(n) == 'signal'))
    nf, out = Path(tmp) / f'{tag}.nets.json', Path(tmp) / f'{tag}.kicad.json'
    nf.write_text(json.dumps(nets))
    _kicad(kicad, 'kicad-measure', path, nf, out)
    k = json.loads(out.read_text())
    r = R.measure_board(b)
    return dict(return_board=r['cov_opp'], kicad=k['cov_opp'], sig_mm_rb=r['sig_mm'], sig_mm_kicad=round(k['sig_mm'], 2)), k, nets


def check(paths, kicad, mutate=False):
    res = {}
    for i, p in enumerate(paths):
        with tempfile.TemporaryDirectory(dir=os.environ.get("KAE_CHECK_TMP")) as tmp:
            plain = _plain(p, tmp)
            row, k, nets = _both(kicad, plain, tmp, 'base')
            if mutate and nets['gnd']:
                segs = [s for s in k['segments'] if s['len'] >= MIN_LEN]
                slot = max((s for s in segs if s['cov'] >= 0.99 * s['len'] and s['cov_items'] <= 0.01 * s['len']),
                           key=lambda s: s['len'], default=None)
                add = max((s for s in segs if s['cov'] <= 0.01 * s['len']), key=lambda s: s['len'], default=None)
                for kind, s in (('slot', slot), ('add', add)):
                    if s is None:
                        row[kind] = 'no target'
                        continue
                    tf, mp = Path(tmp) / f'{kind}.target.json', Path(tmp) / f'{kind}.kicad_pcb'
                    tf.write_text(json.dumps(dict(s, kind=kind, gnd=nets['gnd'], gnd_net=nets['gnd'][0])))
                    _kicad(kicad, 'kicad-mutate', plain, tf, mp)
                    m, _, _ = _both(kicad, mp, tmp, kind)
                    sign = -1 if kind == 'slot' else 1
                    row[kind] = dict(target=dict(net=s['net'], layer=s['layer'], len=round(s['len'], 2)),
                                     return_board=m['return_board'], kicad=m['kicad'],
                                     ok_return_board=sign * (m['return_board'] - row['return_board']) > 0,
                                     ok_kicad=sign * (m['kicad'] - row['kicad']) > 0)
        res[str(p)] = row
        print(f'[{i + 1}/{len(paths)}] {p}: {json.dumps(row)}', file=sys.stderr)
    return res


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'kicad-measure':
        return kicad_measure(*argv[1:4])
    if argv and argv[0] == 'kicad-mutate':
        return kicad_mutate(*argv[1:4])
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=['check'])
    ap.add_argument('boards', nargs='+')
    ap.add_argument('--kicad', default=os.environ.get('KAE_KICAD_PY', 'python3'),
                    help='command that runs a python with pcbnew, e.g. "$KAE_KICAD_WRAP python3"')
    ap.add_argument('--mutate', action='store_true')
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    res = check(a.boards, a.kicad, a.mutate)
    text = json.dumps(res, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    else:
        print(text)


if __name__ == '__main__':
    main()
