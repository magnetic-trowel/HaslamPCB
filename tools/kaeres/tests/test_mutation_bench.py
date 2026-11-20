# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import mutation_bench as M  # noqa: E402

BOARD = '''(kicad_pcb (version 20240108) (generator "pcbnew")
  (title_block (title "demo"))
  (net 0 "") (net 1 "GND") (net 2 "+3V3") (net 3 "CLK")
  (footprint "C_0402" (layer "F.Cu") (at 10 10)
    (property "Reference" "C1" (at 0 0 0))
    (pad "1" smd rect (at -0.5 0) (size 0.5 0.5) (layers "F.Cu" "F.Mask") (net 2 "+3V3"))
    (pad "2" smd rect (at 0.5 0) (size 0.5 0.5) (layers "F.Cu" "F.Mask") (net 1 "GND")))
  (footprint "QFN" (layer "F.Cu") (at 20 10 90)
    (property "Reference" "U1" (at 0 0 0))
    (pad "1" smd rect (at 0 -1) (size 0.3 0.3) (layers "F.Cu") (net 2 "+3V3"))
    (pad "2" smd rect (at 0 1) (size 0.3 0.3) (layers "F.Cu") (net 3 "CLK")))
  (footprint "R_0402" (layer "B.Cu") (at 60 40)
    (property "Reference" "R9" (at 0 0 0))
    (pad "1" thru_hole circle (at 0 0) (size 1 1) (drill 0.6) (layers "*.Cu" "*.Mask") (net 3 "CLK")))
  (segment (start 9.5 10) (end 19 10) (width 0.3) (layer "F.Cu") (net 2) (uuid "a"))
  (segment (start 21 10) (end 40 10) (width 0.2) (layer "F.Cu") (net 3 "CLK") (uuid "b"))
)
'''


def tree():
    return M.parse(BOARD)


def test_roundtrip_is_stable():
    t = tree()
    assert M.parse(M.dump(t)) == t
    assert isinstance(M.first(M.footprints(t)['C1'], 'property')[2], M.Q)


def test_pad_abs_rotation():
    t = tree()
    u = M.footprints(t)['U1']
    pads = M.kids(u, 'pad')
    x, y = M.pad_abs(u, pads[0])  # (0,-1) rotated 90 deg CCW (y down) -> (-1, 0)
    assert math.isclose(x, 19.0, abs_tol=1e-9) and math.isclose(y, 10.0, abs_tol=1e-9)


def test_stretch_moves_away_and_bridges():
    t = tree()
    n0 = len(M.kids(t, 'segment'))
    k = M.stretch(t, 'C1', 2.0)
    c1 = M.footprints(t)['C1']
    assert k == 2 and len(M.kids(t, 'segment')) == n0 + 2
    x, y, _ = M.fp_at(c1)
    assert math.isclose(x, 8.0) and math.isclose(y, 10.0)  # away from U1 (served via +3V3, ground ignored)
    br = M.kids(t, 'segment')[-2:]
    for s, old in zip(br, ((9.5, 10.0), (10.5, 10.0))):
        a, b = M.first(s, 'start'), M.first(s, 'end')
        assert (float(a[1]), float(a[2])) == old
        assert math.isclose(float(b[1]), old[0] - 2.0)
        assert M.net_name(s) in ('+3V3', 'GND') and str(M.first(s, 'layer')[1]) == 'F.Cu'


def test_narrow_scales_only_that_net():
    t = tree()
    assert M.narrow(t, 'CLK', 0.5) == 1
    w = [float(M.first(s, 'width')[1]) for s in M.kids(t, 'segment')]
    assert w == [0.3, 0.1]


def test_net_name_numbered_only():
    t = tree()
    seg = M.kids(t, 'segment')[0]  # (net 2): number only
    assert M.net_name(seg) == '' and M.net_name(seg, M.netmap(t)) == '+3V3'


def test_slot_under_adds_keepout_on_opposite_layer():
    t = tree()
    sig = M.signal_segments(t)
    assert len(sig) == 1 and M.net_name(t[sig[0]]) == 'CLK'
    assert M.slot_under(t, sig[0]) == 'B.Cu'
    z = M.kids(t, 'zone')[-1]
    assert M.first(M.first(z, 'keepout'), 'copperpour')[1] == 'not_allowed'
    pts = [(float(p[1]), float(p[2])) for p in M.first(M.first(z, 'polygon'), 'pts')[1:]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert math.isclose(max(xs) - min(xs), 0.6) and math.isclose(max(ys) - min(ys), 12.0)
    assert math.isclose(sum(xs) / 4, 30.5)


def test_benign_move_picks_unrelated_part():
    t = tree()
    assert M.benign_move(t, ['C1']) in ('R9', 'U1')
    t = tree()
    assert M.benign_move(t, ['U1']) is None or M.benign_move(tree(), ['U1']) != 'R9'


def test_write_mutants(tmp_path):
    p = tmp_path / 'b.kicad_pcb'
    p.write_text(BOARD)
    base, muts = M.write_mutants(str(p), str(tmp_path / 'm'), ['C1', 'NOPE'], ['CLK'])
    ids = {m['id'] for m in muts}
    assert {'stretch:C1:1', 'stretch:C1:4', 'narrow:CLK:0.25', 'benign:resave'} <= ids
    assert all('error' in m for m in muts if m['target'] == 'NOPE')
    for m in muts:
        if 'path' in m:
            M.parse(open(m['path']).read())
    assert open(base).read() == open(str(tmp_path / 'm' / 'benign_resave.kicad_pcb')).read()


def fake_results(good=True):
    base = {'m1': dict(kind='decap', value=1.0), 'm2': dict(kind='decap', value=2.0), 'r': dict(kind='rail', value=5.0)}
    res = []
    for d in M.STRETCH_DOSES:
        v = 1.0 + 0.1 * d if good else 1.0 - 0.1 * d
        res.append(dict(op='stretch', target='C1', dose=d, sign=+1,
                        rows={'m1': dict(value=v), 'm2': dict(value=2.0), 'r': dict(value=5.0)}))
    res.append(dict(op='narrow', target='VCC', dose=2.0, sign=+1,
                    rows={'m1': dict(value=1.0), 'm2': dict(value=2.0), 'r': dict(value=10.0)}))
    res.append(dict(op='benign', target='', dose=0, sign=0,
                    rows={'m1': dict(value=1.001), 'm2': dict(value=2.0), 'r': dict(value=5.0)}))
    return base, res


def test_gate_passes_responsive_rows():
    base, res = fake_results()
    g = M.gate(base, res)
    assert g['decap']['pass'] and g['decap']['sign'] == 1.0 and g['decap']['monotone'] == 1.0
    assert g['rail']['pass'] and g['decap']['benign'] == 0.0


def test_gate_fails_wrong_sign_lost_and_benign():
    base, res = fake_results(good=False)
    assert not M.gate(base, res)['decap']['pass']
    base, res = fake_results()
    res[-1]['rows']['m1'] = dict(value=1.5)  # benign moved a row by 50 %
    assert not M.gate(base, res)['decap']['pass']
    base, res = fake_results()
    for r in res:
        r['rows']['m2'] = dict(value=None)
    g = M.gate(base, res)['decap']
    assert g['lost'] == 0.5 and not g['pass']


def test_main_without_measure(tmp_path):
    p = tmp_path / 'b.kicad_pcb'
    p.write_text(BOARD)
    out = tmp_path / 'o.json'
    M.main(['--board', str(p), '--targets', 'C1', '--rails', '+3V3', '--measure', 'none', '--out', str(out)])
    import json
    rec = json.load(open(out))
    assert any(m['id'] == 'narrow:+3V3:0.5' and m.get('detail') == 1 for m in rec['mutants'])  # numbered net resolved
