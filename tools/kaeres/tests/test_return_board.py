# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""return_board.py on synthetic boards (needs shapely; no KiCad, no board files)."""
import gzip
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely", minversion="2.0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import return_board as R  # noqa: E402

TWO = ['F.Cu', 'B.Cu']
FOUR = ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']


def board(tmp_path, items, layers=TWO, name='b.kicad_pcb'):
    ids = {'F.Cu': 0, 'In1.Cu': 1, 'In2.Cu': 2, 'B.Cu': 31}
    lt = ' '.join(f'({ids[l]} "{l}" signal)' for l in layers)
    nets = ['GND', 'SIG', 'USB_DP', 'OTHER']
    text = (f'(kicad_pcb (version 20221018) (layers {lt} (44 "Edge.Cuts" user)) (net 0 "") '
            + ' '.join(f'(net {i + 1} "{n}")' for i, n in enumerate(nets))
            + ' (gr_rect (start 0 0) (end 40 20) (layer "Edge.Cuts") (width 0.1)) ' + ' '.join(items) + ')')
    p = tmp_path / name
    if name.endswith('.gz'):
        with gzip.open(p, 'wt') as f:
            f.write(text)
    else:
        p.write_text(text)
    return p


def seg(x1, y1, x2, y2, layer, net, w=0.25):
    return f'(segment (start {x1} {y1}) (end {x2} {y2}) (width {w}) (layer "{layer}") (net {net}))'


def zone(layer, x1, y1, x2, y2, net=1, name='GND'):
    return (f'(zone (net {net}) (net_name "{name}") (layer "{layer}") (connect_pads (clearance 0.2)) '
            f'(polygon (pts (xy {x1} {y1}) (xy {x2} {y1}) (xy {x2} {y2}) (xy {x1} {y2}))))')


def keepout(layer, x1, y1, x2, y2):
    return (f'(zone (net 0) (net_name "") (layer "{layer}") (keepout (tracks allowed) (vias allowed) '
            f'(pads allowed) (copperpour not_allowed) (footprints allowed)) '
            f'(polygon (pts (xy {x1} {y1}) (xy {x2} {y1}) (xy {x2} {y2}) (xy {x1} {y2}))))')


ANCHOR = seg(2, 18, 6, 18, 'B.Cu', 1, 0.5)   # ground track that connects the B.Cu pour


def test_full_pour_under_signal(tmp_path):
    r = R.measure(board(tmp_path, [zone('B.Cu', 0, 0, 40, 20), ANCHOR, seg(5, 5, 35, 5, 'F.Cu', 2)]))
    assert r['cov_opp'] == pytest.approx(1.0, abs=0.02)
    assert r['cov_any'] == pytest.approx(1.0, abs=0.02)
    assert r['unc_mm'] < 0.5 and r['islands'] == 0 and r['gpieces'] == 1


def test_half_pour_and_worst_net(tmp_path):
    r = R.measure(board(tmp_path, [zone('B.Cu', 0, 0, 20, 20), seg(2, 18, 6, 18, 'B.Cu', 1, 0.5),
                                   seg(5, 5, 35, 5, 'F.Cu', 2)]))
    # pour reaches x = 19.7 (edge pull-back is only at the board edge, x = 20 is inside)
    assert r['cov_opp'] == pytest.approx(15 / 30, abs=0.03)
    assert r['worst_net'] == 'SIG' and r['worst_unc_mm'] == pytest.approx(r['unc_mm'], abs=0.01)
    assert r['nets_unc'][0]['net'] == 'SIG'


def test_unconnected_pour_is_island(tmp_path):
    r = R.measure(board(tmp_path, [zone('B.Cu', 0, 0, 40, 20), seg(5, 5, 35, 5, 'F.Cu', 2)]))
    assert r['islands'] == 1 and r['cov_opp'] == 0.0 and r['unc_mm'] == pytest.approx(30, abs=0.1)


def test_keepout_cuts_pour(tmp_path):
    items = [zone('B.Cu', 0, 0, 40, 20), ANCHOR, seg(5, 5, 35, 5, 'F.Cu', 2)]
    base = R.measure(board(tmp_path, items))
    cut = R.measure(board(tmp_path, items + [keepout('B.Cu', 10, 0, 20, 10)], name='k.kicad_pcb'))
    assert base['cov_opp'] - cut['cov_opp'] == pytest.approx(10 / 30, abs=0.03)
    assert cut['zone_area'] < base['zone_area']


def test_fast_rows_and_same_layer(tmp_path):
    # USB_DP runs 0.5 mm beside a same-layer ground track, SIG runs far from any ground; no pour.
    r = R.measure(board(tmp_path, [seg(5, 5, 35, 5, 'F.Cu', 1, 0.5), seg(5, 5.6, 35, 5.6, 'F.Cu', 3),
                                   seg(5, 15, 35, 15, 'F.Cu', 2)], name='f.kicad_pcb.gz'))
    assert r['fast_sig_mm'] == pytest.approx(30, abs=0.1)
    assert r['fast_cov_same'] == pytest.approx(1.0, abs=0.02) and r['fast_cov_opp'] == 0.0
    assert r['cov_any'] == pytest.approx(0.5, abs=0.02)
    assert r['worst_net'] == 'SIG'


def test_four_layer_adjacent_only(tmp_path):
    # Ground on In1 is adjacent to F.Cu; ground on In2 is not.
    a = R.measure(board(tmp_path, [zone('In1.Cu', 0, 0, 40, 20), seg(2, 18, 6, 18, 'In1.Cu', 1, 0.5),
                                   seg(5, 5, 35, 5, 'F.Cu', 2)], FOUR))
    b = R.measure(board(tmp_path, [zone('In2.Cu', 0, 0, 40, 20), seg(2, 18, 6, 18, 'In2.Cu', 1, 0.5),
                                   seg(5, 5, 35, 5, 'F.Cu', 2)], FOUR, name='n.kicad_pcb'))
    assert a['layers'] == 4 and a['cov_opp'] == pytest.approx(1.0, abs=0.02)
    assert b['cov_opp'] == 0.0 and b['fast_sig_mm'] == 0.0 and b['fast_cov_opp'] is None


def test_paired_hook(tmp_path):
    good = board(tmp_path, [zone('B.Cu', 0, 0, 40, 20), ANCHOR, seg(5, 5, 35, 5, 'F.Cu', 2)])
    bare = board(tmp_path, [seg(5, 5, 35, 5, 'F.Cu', 2)], name='bare.kicad_pcb')
    A = {'x': {'owner': 'o', 'path': bare}, 'y': {'owner': 'o', 'path': tmp_path / 'missing.kicad_pcb'}}
    B = {'x': {'owner': 'o', 'path': good}, 'y': {'owner': 'o', 'path': good}}
    d = R.paired(A, B, ['x', 'y'], lambda r: r['path'])
    assert [b for _, b, _ in d['cov_opp']] == ['x'] and d['cov_opp'][0][2] == pytest.approx(1.0, abs=0.02)
    assert d['fast_cov_opp'] == []
    assert R.stored_path('S', {'board': 'b', 'run': 'r'}) == Path('S/boards/b/runs/r/output.kicad_pcb.gz')
