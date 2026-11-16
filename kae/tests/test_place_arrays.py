# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.place.arrays: LED matrices and series buses from the netlist; rigid macros in the annealer."""
from types import SimpleNamespace as NS

from kae.place import arrays as A


def pad(number, net):
    return NS(number=number, net=net, drill=0.0)


def led(ref, row, col, lib="LED:RGB"):
    return NS(uuid=ref, ref=ref, lib_id=lib, pads=[pad("1", f"ROW{row}"), pad("2", f"COLR{col}"), pad("3", f"COLG{col}"), pad("4", f"COLB{col}")])


def test_matrix_found_with_rows_and_columns():
    fps = [led(f"D{(r * 12) + c + 1}", r, c) for r in range(10) for c in range(12)]
    kinds = {}
    groups = A.matrices(fps, kinds)
    assert len(groups) == 1
    g = groups[0]
    assert {g.rows, g.cols} == {10, 12} and len(g.cells) == 120
    assert set(g.cells.values()) == {(r, c) for r in range(g.rows) for c in range(g.cols)}


def test_matrix_needs_a_product_of_signal_nets():
    # a shared power rail on one pin: the other pin alone is not a matrix
    fps = [NS(uuid=f"R{i}", ref=f"R{i}", lib_id="R:0402", pads=[pad("1", "VCC"), pad("2", f"N{i}")]) for i in range(20)]
    assert A.matrices(fps, {"VCC": "power"}) == []


def test_sparse_grid_below_fill_is_rejected():
    fps = [led(f"D{i}", i, i) for i in range(20)]   # a diagonal: 20 rows x 20 cols, fill 0.05
    assert A.matrices(fps, {}) == []


def series(i, a="U1", b="U2", lib="R:0402"):
    n1, n2 = f"A{i}", f"B{i}"
    return NS(uuid=f"R{i}", ref=f"R{i}", lib_id=lib, pads=[pad("1", n1), pad("2", n2)]), n1, n2


def test_bus_found_between_two_parts():
    parts = [series(i) for i in range(8)]
    fps = [p[0] for p in parts] + [
        NS(uuid="U1", ref="U1", lib_id="BGA", pads=[pad(str(i + 1), parts[i][1]) for i in range(8)]),
        NS(uuid="U2", ref="U2", lib_id="BGA2", pads=[pad(str(i + 1), parts[i][2]) for i in range(8)])]
    groups = A.buses(fps, {})
    assert len(groups) == 1 and groups[0].cols == 8 and groups[0].rows == 1


def test_bus_excludes_parts_with_a_third_connection():
    parts = [series(i) for i in range(8)]
    fps = [p[0] for p in parts] + [
        NS(uuid="U1", ref="U1", lib_id="BGA", pads=[pad(str(i + 1), parts[i][1]) for i in range(8)]),
        NS(uuid="U2", ref="U2", lib_id="BGA2", pads=[pad(str(i + 1), parts[i][2]) for i in range(8)]),
        NS(uuid="TP1", ref="TP1", lib_id="TP", pads=[pad("1", parts[0][1])])]   # a third pad on one net: that one drops out
    groups = A.buses(fps, {})
    assert len(groups) == 1 and groups[0].cols == 7


def test_bus_to_a_fixed_part_found_when_all_parts_give_pins():
    # the far end (a connector) is fixed: members are the movable parts, ends come from every part
    parts = [series(i) for i in range(8)]
    u1 = NS(uuid="U1", ref="U1", lib_id="BGA", pads=[pad(str(i + 1), parts[i][1]) for i in range(8)])
    j1 = NS(uuid="J1", ref="J1", lib_id="CONN", pads=[pad(str(i + 1), parts[i][2]) for i in range(8)])
    movable = [p[0] for p in parts] + [u1]
    assert A.buses(movable, {}) == []
    groups = A.buses(movable, {}, pin_fps=movable + [j1])
    assert len(groups) == 1 and groups[0].cols == 8 and set(groups[0].cells) == {f"R{i}" for i in range(8)}


# ----------------------------------------------------------------------------- on a real Problem
import copy
from pathlib import Path

import numpy as np
from shapely.geometry import box

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _fp(tpl, ref, lib, x, y, pads, cy, locked, uuid=None):
    f = copy.deepcopy(tpl)
    f.ref, f.lib_id, f.uuid, f.x, f.y, f.rot, f.side, f.locked = ref, lib, uuid or ref, x, y, 0.0, "F", locked
    f.value, f.fields = ref, {}
    f.courtyard, f.courtyard_back, f.body, f.graphics, f.silk, f.silk_text, f.edge_cuts = [cy], [], [], {}, {}, {}, []
    f.pads = []
    for n, (lx, ly, net) in enumerate(pads):
        p = copy.deepcopy(tpl.pads[0])
        p.number, p.net, p.lx, p.ly, p.x, p.y = str(n + 1), net, lx, ly, x + lx, y + ly
        p.size, p.shape, p.uuid, p.layers = (0.5, 0.5), "rect", f"{ref}-{n}", ["F.Cu", "F.Mask"]
        f.pads.append(p)
    return f


def _bus_board(n=8, hole_at=None, a_down=False):
    """A locked IC (U10, pins down its right side) and a locked connector (J10, pins down its left side) with
    n series resistors (0402-like, R1..Rn) between them, staged off the board; hole_at: a locked mounting
    hole (H1, a drilled pad) there."""
    from kae.board.kicad_file import load
    from kae.board.model import Net
    b = load(FIXTURE)
    tpl = next(f for f in b.footprints if f.ref == "U1")
    fps, nets = [], {}
    pitch = 1.0
    for k in range(n):
        ya = (n - 1 - k if a_down else k) * pitch - (n - 1) * pitch / 2
        yb = k * pitch - (n - 1) * pitch / 2
        nets[f"A{k}"], nets[f"B{k}"] = (ya, yb), None
    a_pads = [(1.0, nets[f"A{k}"][0], f"A{k}") for k in range(n)]
    b_pads = [(-1.0, (k - (n - 1) / 2) * 2.54, f"B{k}") for k in range(n)]     # a 2.54 mm header: U10 is denser
    fps.append(_fp(tpl, "U10", "t:IC", 10.0, 20.0, a_pads, box(-2, -n / 2 - 1, 1.5, n / 2 + 1), True))
    fps.append(_fp(tpl, "J10", "t:CONN", 50.0, 20.0, b_pads, box(-1.5, -n * 1.27 - 1, 2, n * 1.27 + 1), True))
    for k in range(n):
        fps.append(_fp(tpl, f"R{k + 1}", "t:R0402", 80.0 + k * 2, 5.0,
                       [(-0.5, 0.0, f"A{k}"), (0.5, 0.0, f"B{k}")], box(-0.95, -0.45, 0.95, 0.45), False))
    if hole_at is not None:
        h = _fp(tpl, "H1", "t:HOLE", hole_at[0], hole_at[1], [(0.0, 0.0, "")], box(-1.6, -1.6, 1.6, 1.6), True)
        h.pads[0].kind, h.pads[0].drill, h.pads[0].size, h.pads[0].shape = "thru_hole", 2.2, (3.0, 3.0), "circle"
        h.pads[0].layers = ["*.Cu", "*.Mask"]
        fps.append(h)
    b.footprints = fps
    b.nets = {}
    for f in fps:
        for p in f.pads:
            if p.net:
                b.nets.setdefault(p.net, Net(name=p.net, netclass="Default", pads=[])).pads.append((f.ref, p.number))
    b.zones, b.keepouts = [], []
    return b


def _pinned(b, kinds=A.BUS):
    from kae.place.problem import Problem
    from kae.place.state import State
    P = Problem.build(b)
    macs, rep = A.macros(P, kinds=kinds)
    st = State(P)
    for i in P.mov:          # a seed: every movable part in the middle of the board
        st.X[i], st.Y[i] = P.grid_of(30.0, 20.0)
    poses, failed, prep = A.pin(P, macs, st)
    return P, macs, poses, failed, prep


def test_bus_members_side_by_side_across_their_pad_axis():
    b = _bus_board()
    P, macs, poses, failed, _ = _pinned(b)
    assert len(macs) == 1 and not failed and len(poses) == 8
    by = {f.uuid: f for f in b.footprints}
    xs = sorted({round(p[0], 3) for p in poses.values()})
    ys = sorted(p[1] for p in poses.values())
    assert len(xs) == 1                                  # one column: side by side, not end to end
    pitch = np.diff(ys)
    assert np.allclose(pitch, pitch[0]) and 0.9 <= pitch[0] <= 2.0   # short courtyard side (0.9) + a gap
    assert 15.0 < xs[0] < 45.0                           # between its two ends (x 10 and 50)
    for u, (x, y, rot, side) in poses.items():
        f = by[u]
        # the pad on U10's net (pad 1, A*) faces U10, on the left
        r = P.parts[next(p.i for p in P.parts if p.uuid == u)]
        k = next(k for k, rr in enumerate(r.rots) if abs(rr.rot - rot) < 1e-6)
        assert r.rots[k].pins[0, 0] < r.rots[k].pins[1, 0], f.ref


def test_bus_column_follows_the_order_of_the_pins_at_its_end():
    for a_down in (False, True):
        b = _bus_board(a_down=a_down)
        P, macs, poses, failed, _ = _pinned(b)
        by = {f.uuid: f for f in b.footprints}
        u10 = next(f for f in b.footprints if f.ref == "U10")
        pin_y = {p.net: p.ly for p in u10.pads}
        rows = sorted(poses.items(), key=lambda t: t[1][1])
        a_net = [by[u].pads[0].net for u, _ in rows]
        assert [pin_y[n] for n in a_net] == sorted(pin_y[n] for n in a_net)   # no crossing at U10


def test_bus_keeps_clear_of_a_locked_hole():
    b = _bus_board(hole_at=(30.0, 20.0))
    P, macs, poses, failed, prep = _pinned(b)
    assert not failed
    from shapely.geometry import Point
    hole = Point(30.0, 20.0).buffer(1.6)
    for u, (x, y, rot, side) in poses.items():
        assert not box(x - 0.95, y - 0.95, x + 0.95, y + 0.95).intersects(hole)


def test_no_legal_spot_falls_back_to_no_macro():
    b = _bus_board(n=12, hole_at=(30.0, 20.0))
    b.footprints = [f for f in b.footprints if f.ref not in ("U10", "J10")] + [   # ends far apart, the hole between
        f for f in _bus_board(n=12).footprints if f.ref in ("U10", "J10")]
    for f in b.footprints:
        if f.ref.startswith("R"):
            f.pads[0].size = f.pads[1].size = (0.5, 3.0)   # 12 cells of 3.9 mm: a 47 mm column, the board is 40 mm
    P, macs, poses, failed, prep = _pinned(b)
    assert failed and not poses


def test_mask_turns_kinds_off_and_ui_grids_are_left_alone():
    b = _bus_board()
    from kae.place.problem import Problem
    P = Problem.build(b)
    macs, rep = A.macros(P, kinds=A.MATRIX)
    assert macs == [] and rep["skipped"][0]["why"] == "kind off"
    key = NS(ref="KEY_A1", lib_id="Keypad:key", value="KEY", pads=[])
    assert A.is_ui_part(key)
    assert A.is_ui_part(NS(ref="SW3", lib_id="Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB", value="SW", pads=[]))
    assert A.is_ui_part(NS(ref="T3", lib_id="CapTouchKeyboard:TOUCH_PAD", value="TouchPad", pads=[]))
    assert A.is_ui_part(NS(ref="JP3", lib_id="FlexSensorFootprint:10mmPad", value="Jumper_2_Open", pads=[]))
    for led in (NS(ref="D3", lib_id="LED_SMD:LED_0603_1608Metric", value="LED", pads=[]),
                NS(ref="D4", lib_id="LED_THT:LED_D5.0mm", value="LED", pads=[]),
                NS(ref="U4", lib_id="Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm", value="74HC245", pads=[]),
                NS(ref="K1", lib_id="Relay_SMD:Relay_DPDT_Omron_G6K-2F-Y", value="G6K-2F-Y", pads=[])):
        assert not A.is_ui_part(led), led.lib_id
