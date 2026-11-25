# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.place.repack: the CP-SAT repack of what the closed loop leaves illegal, on synthetic crowded boards."""
import numpy as np
import shapely
from shapely.geometry import Polygon, box

from haslam import budget
from haslam.board.kicad_file import load
from haslam.place import repack
from haslam.place.legalize import exact_check
from haslam.place.problem import Problem
from haslam.place.state import State


def _fp(ref, n, x, y, cw, ch, pads):
    """A front SMD footprint: a cw x ch courtyard around its origin, pads [(number, x, y, w, h, net)]."""
    uid = f"00000000-0000-4000-8000-{n:012d}"
    s = [f'(footprint "t:{ref}" (layer "F.Cu") (uuid "{uid}") (at {x} {y})',
         f'(property "Reference" "{ref}" (at 0 0 0) (layer "F.Fab") (uuid "{uid[:-4]}ffff"))', '(attr smd)',
         f'(fp_rect (start {-cw / 2} {-ch / 2}) (end {cw / 2} {ch / 2}) (stroke (width 0.05) (type solid)) '
         '(layer "F.CrtYd"))']
    for num, px, py, w, h, net in pads:
        s.append(f'(pad "{num}" smd rect (at {px} {py}) (size {w} {h}) (layers "F.Cu" "F.Paste" "F.Mask") '
                 f'(net {net} "N{net}"))')
    return "\n".join(s + [")"])


def _board(tmp_path, W, H, fps, nets=4):
    s = ['(kicad_pcb (version 20240108) (generator "pcbnew")',
         '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user) (37 "F.SilkS" user) (39 "F.Mask" user) '
         '(49 "F.Fab" user) (46 "B.CrtYd" user) (47 "F.CrtYd" user))',
         '(setup (pad_to_mask_clearance 0))', '(net 0 "")'] + [f'(net {k} "N{k}")' for k in range(1, nets + 1)]
    for a, b in (((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))):
        s.append(f'(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (stroke (width 0.05) (type solid)) '
                 '(layer "Edge.Cuts"))')
    path = tmp_path / "crowded.kicad_pcb"
    path.write_text("\n".join(s + fps + [")"]))
    return load(path)


def _resistor(ref, n, net_a, net_b, x=0.0, y=0.0):
    return _fp(ref, n, x, y, 3.4, 1.8, [("1", -0.9, 0, 1.0, 1.2, net_a), ("2", 0.9, 0, 1.0, 1.2, net_b)])


def _pile(P, x, y):
    st = State(P)
    for i in P.mov:
        st.X[i], st.Y[i] = P.grid_of(x, y)
        st.K[i] = 0
    return st


def _header_board(tmp_path):
    """An 18 x 7 mm board: a 16.4 mm 8-pin edge header and six 0805-size resistors, about 72 % of
    the area in courtyards, every part piled on the middle."""
    fps = [_fp("J1", 1000, 9, 3, 16.4, 2.6, [(str(k + 1), -7 + 2 * k, 0, 1.7, 1.7, k % 4 + 1) for k in range(8)])]
    fps += [_resistor(f"R{j + 1}", 2000 + 10 * j, j % 4 + 1, (j + 1) % 4 + 1) for j in range(6)]
    P = Problem.build(_board(tmp_path, 18, 7, fps))
    return P, _pile(P, 9, 3.5)


def test_disjoint_keeps_the_union_without_overlaps():
    rects = [(0, 0, 10, 10), (5, 5, 15, 15), (12, 0, 20, 4), (0, 0, 3, 3), (30, 30, 31, 31)]
    out = repack.disjoint(rects)
    union = shapely.union_all([box(*r) for r in rects])
    assert abs(sum((r[2] - r[0]) * (r[3] - r[1]) for r in out) - union.area) < 1e-9
    assert shapely.union_all([box(*r) for r in out]).equals(union)
    for a in range(len(out)):
        for b in range(a + 1, len(out)):
            assert box(*out[a]).intersection(box(*out[b])).area == 0


def test_cover_rects_is_exact_on_axis_aligned_shapes_and_covers_slanted_ones():
    ell = Polygon([(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)])
    rs = repack.cover_rects(ell)
    assert abs(shapely.union_all([box(*r) for r in rs]).area - ell.area) < 1e-9
    tri = Polygon([(0, 0), (5, 0), (0, 5)])
    rs = repack.cover_rects(tri)
    cover = shapely.union_all([box(*r) for r in rs])
    assert cover.contains(tri) and cover.area < 1.2 * tri.area


def test_repack_makes_a_crowded_pile_exactly_legal(tmp_path):
    P, st = _header_board(tmp_path)
    start = exact_check(P, st)
    assert {v["type"] for v in start} >= {"courtyards_overlap", "clearance"}
    rep = repack.repack(P, st, time_s=15.0)
    assert rep["start"] > 0 and rep["end"] == 0 and rep["kept"] >= 1
    assert exact_check(P, st) == []
    # every pad on the board, with the copper-to-edge clearance
    inner = P.outline.buffer(-P.edge_clearance + 1e-6)
    for i in P.mov:
        for xy in st.pins_xy(i):
            assert inner.contains(shapely.Point(*xy))


def test_repack_names_what_binds_when_no_packing_exists(tmp_path):
    """Eight resistors (49 mm2 of courtyard) on 40 mm2: the box model has no packing (proved, or none
    found in the time), nothing moves, and the report names the area bound and what frees it."""
    fps = [_resistor(f"R{j + 1}", 2000 + 10 * j, 1, 2) for j in range(8)]
    P = Problem.build(_board(tmp_path, 8, 5, fps, nets=2))
    st = _pile(P, 4, 2.5)
    before = (st.X.copy(), st.Y.copy(), st.K.copy())
    rep = repack.repack(P, st, time_s=8.0)
    assert rep["kept"] == 0 and rep["end"] == rep["start"] > 0
    assert all(a["status"] in ("INFEASIBLE", "UNKNOWN") for a in rep["attempts"])
    assert len(rep["attempts"]) == 1           # every part flagged: only the free level runs
    b = rep["binds"]
    assert "edge" in b["feasible_without"] and "cy" not in b["feasible_without"]
    assert b["area_mm2"]["F"]["need"] > b["area_mm2"]["F"]["free"]
    for a, z in zip(before, (st.X, st.Y, st.K)):
        assert np.array_equal(a, z)


def test_a_solution_that_does_not_cut_findings_is_dropped(tmp_path, monkeypatch):
    P, st = _header_board(tmp_path)
    home = {i: (int(st.X[i]), int(st.Y[i]), int(st.K[i])) for i in P.mov}
    j = P.mov[0]
    # the "solver" piles one more part on the others: more findings, so the poses go back
    monkeypatch.setattr(repack._Model, "solve", lambda self, t, seed=0: (
        "FEASIBLE", {i: (home[i][0] + (5 if i == j else 0), home[i][1], home[i][2]) for i in self.S}, 0.0))
    rep = repack.repack(P, st, time_s=10.0, repair_after=False)
    assert rep["kept"] == 0 and not any(a.get("kept") for a in rep["attempts"])
    assert all((int(st.X[i]), int(st.Y[i]), int(st.K[i])) == home[i] for i in P.mov)


def test_repack_is_repeatable_under_counted_work(tmp_path, monkeypatch):
    """Counted work, one worker: the same poses from two runs (the solver stops at deterministic time)."""
    monkeypatch.setattr(budget, "_clock", None)         # restored after the test
    out = []
    for k in range(2):
        budget.set_mode("work")
        d = tmp_path / str(k)
        d.mkdir()
        with budget.frame():
            P, st = _header_board(d)
            rep = repack.repack(P, st, time_s=10.0, seed=3)
        out.append((rep["end"], st.X.tolist(), st.Y.tolist(), st.K.tolist()))
    assert out[0] == out[1]


def test_repack_after_placement_runs_only_on_findings_and_keeps_only_a_gain(tmp_path):
    """pipeline.repack_after: off, or a placement that ends clean, is left as it is; with findings,
    a kept repack updates the poses, the exact check and HPWL, and drops the caller's stale KiCad
    verdict; its time is min(30 s, 10 % of the next stage)."""
    from haslam.place.pipeline import Result, repack_after
    P, st = _header_board(tmp_path)

    def result():
        return Result(poses=st.poses(), report=dict(exact=exact_check(P, st), hpwl=0.0), state=st, problem=P,
                      verified=dict(clean=False))
    r = result()
    repack_after(r, time_s=60.0)                                   # off by default
    assert "exact_repack" not in r.report and r.verified is not None
    r = result()
    repack_after(r, time_s=60.0, opts=dict(exact_repack=1, next_stage_s=150.0))
    rr = r.report["exact_repack"]
    assert rr["time_s"] == 15.0 and rr["kept"] and r.report["exact"] == [] and r.verified is None
    assert r.poses == st.poses() and r.report["hpwl"] == round(st.hpwl(), 2)
    r = result()                                                   # clean now: nothing to do
    repack_after(r, time_s=60.0, opts=dict(exact_repack=1))
    assert "exact_repack" not in r.report
