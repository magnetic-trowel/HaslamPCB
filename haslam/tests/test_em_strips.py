# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.em.strips: the strip-and-tile PEEC cell quote (quick-physics M2; tools/research/physics/quickphys/PLAN.md
items 4 and 5)."""
import math
import time

import numpy as np
import pytest

from hotloop_fixtures import plane_fills, write_hotloop_board
from haslam import budget as BU
from haslam.em import kernels as KN
from haslam.em import strips as ST

CELL = "cell:cell:buck:U1"
# the 0.0625 mm raster window of the fixture (cellquote raw window, design doc section 4)
RASTER = {"closed": (3.5148, 6.4521), "long": (6.2698, 12.9698)}
F_BOUND = (0.0, 0.1e6, 0.3e6, 1e6, 3e6, 10e6, 30e6, 100e6)


@pytest.fixture(scope="module")
def boards(tmp_path_factory):
    d = tmp_path_factory.mktemp("strips")
    out = {}
    for v in ("closed", "long", "open"):
        p = write_hotloop_board(d / v, v)
        out[v] = (str(p), ST.prepare(str(p), fills=plane_fills()))
    return out


def _q(boards, v, P=0.5, **kw):
    p, ctx = boards[v]
    return ST.from_board(p, CELL, pitch=P, ctx=ctx, **kw)


def test_a_bars_self_term_is_the_sum_of_its_halves():
    MM = 1e-3
    bar = (0.0, 0.5 * MM, 0.0, 0.25 * MM, 0.0, 0.035 * MM)
    M = float(KN.bar_mutual(bar, bar))
    # along: two halves in series carry the same current: M = M11 + M22 + 2 M12
    a, b = (0.0, 0.25 * MM, *bar[2:]), (0.25 * MM, 0.5 * MM, *bar[2:])
    along = float(KN.bar_mutual(a, a) + KN.bar_mutual(b, b) + 2 * KN.bar_mutual(a, b))
    # across: two halves side by side share it: M = (M11 + M22 + 2 M12) / 4
    c, e = (*bar[:2], 0.0, 0.125 * MM, *bar[4:]), (*bar[:2], 0.125 * MM, 0.25 * MM, *bar[4:])
    across = float(KN.bar_mutual(c, c) + KN.bar_mutual(e, e) + 2 * KN.bar_mutual(c, e)) / 4
    assert abs(along - M) / M < 1e-10 and abs(across - M) / M < 1e-10
    # and the far rule stays additive to the same order where Hoer-Love's terms no longer cancel
    A = np.array([[0, 0.5 * MM, 0, 0.5 * MM, 0, 0.035 * MM]])
    B = np.array([[30 * MM, 30.5 * MM, 6 * MM, 6.5 * MM, 1.5 * MM, 1.535 * MM]])
    q = 0.25 * MM
    subs = lambda b: np.array([[b[0] + i * q, b[0] + (i + 1) * q, b[2] + j * q, b[2] + (j + 1) * q, b[4], b[5]]
                               for i in (0, 1) for j in (0, 1)])
    whole = ST.pair_mutual(A, B)[0, 0]
    parts = ST.pair_mutual(subs(A[0]), subs(B[0])).sum() / 4
    assert abs(parts - whole) / whole < 1e-9


def test_refine_nests_the_coarse_current_space(boards):
    q = _q(boards, "closed", P=1.0, keep=True)
    se, xe, ne, _ = q.systems["edge"]
    fine = ST.refine(ne)
    Lc, Lf = ST.mutuals(ne), ST.mutuals(fine)
    Ic = xe[:ne.n_bars]
    If = ST.nest(ne, fine, Ic)
    Ec = float(np.real(np.vdot(Ic, Lc @ Ic)))
    Ef = float(np.real(np.vdot(If, Lf @ If)))
    assert abs(Ec - Ef) / Ec < 1e-9
    # the nested currents still satisfy KCL on the refined network (same nodes, a mid node per bar)
    assert fine.n_bars == 4 * sum(1 for a in ne.arrays().ax if a < 2) + sum(1 for a in ne.arrays().ax if a == 2)


def test_open_is_judged_by_connectivity_before_any_solve(boards, monkeypatch):
    def no_solve(*a, **k):
        raise AssertionError("an open loop must not be solved")
    monkeypatch.setattr(ST.System, "factor", no_solve)
    q = _q(boards, "open")
    assert q.state == "open" and q.L_loop is None
    p, ctx = boards["open"]
    s = ST._source(ctx, CELL)
    win, _ = ST.cell_window(ctx, s)
    nf, _, inj, _, _ = ST.build_cell(ctx, s, win, 0.5)
    u13, u14 = nf.pads["U1.3"]["node"], nf.pads["U1.4"]["node"]
    assert not nf.connected(u13, u14)
    ctx_c = boards["closed"][1]
    nc, _, _, _, _ = ST.build_cell(ctx_c, ST._source(ctx_c, CELL), win, 0.5)
    assert nc.connected(nc.pads["U1.3"]["node"], nc.pads["U1.4"]["node"])


def test_closed_is_below_long_and_near_the_fine_raster_window(boards):
    c, l_ = _q(boards, "closed"), _q(boards, "long")
    assert c.state == l_.state == "ok"
    assert c.L_loop < l_.L_loop and c.R_loop < l_.R_loop
    for v, q in (("closed", c), ("long", l_)):
        L0, R0 = RASTER[v]
        assert abs(q.L_loop * 1e9 / L0 - 1) < 0.10, (v, q.L_loop * 1e9, L0)
        assert abs(q.R_loop * 1e3 / R0 - 1) < 0.08, (v, q.R_loop * 1e3, R0)


def test_a_bordered_update_equals_an_independent_build(boards):
    c = _q(boards, "closed", keep=True)
    l_ = _q(boards, "long", keep=True)
    se, _, _, _ = c.systems["edge"]
    _, _, n1, inj1 = l_.systems["edge"]
    BU.set_mode("time")
    t0 = time.perf_counter()
    s2 = ST.System(n1, ST.mutuals(n1), se.f)
    s2.factor()
    t_factor = time.perf_counter() - t0
    x2 = s2.solve(inj=inj1)
    r = ST.bordered(se, n1, inj=inj1)
    full = s2.energy_L(x2)
    assert abs(r.energy_L() - full) / full < 1e-10
    assert abs(r.dissipation_R() - s2.dissipation_R(x2)) / s2.dissipation_R(x2) < 1e-10
    units = BU.clock().units
    assert units["em_border"] < se.N ** 3                     # k N^2 against a refactorisation's N^3
    assert r.t_solve < t_factor, (r.t_solve, t_factor)


def bound_table(boards, P=1.0, freqs=F_BOUND):
    """[(f, L_coarse, L_fine, R_coarse, R_fine)] of the fixture's closed loop at pitch P and its 2 x 2 refinement,
    with the caps at their edge model (ESR + ESL) at every frequency: one network, so the two are nested at each f."""
    q = _q(boards, "closed", P=P, keep=True)
    _, _, ne, inj = q.systems["edge"]
    fine = ST.refine(ne)
    Lc, Lf = ST.mutuals(ne), ST.mutuals(fine)
    out = []
    for f in freqs:
        sc = ST.System(ne, Lc, f).factor()
        x = sc.solve(inj=inj)
        sf = ST.System(fine, Lf, f).factor()
        y = sf.solve(inj=inj)
        out.append((f, sc.energy_L(x), sf.energy_L(y), sc.dissipation_R(x), sf.dissipation_R(y)))
    return out


def test_the_coarse_network_bounds_its_refinement_where_the_theorems_hold(boards, capsys):
    rows = bound_table(boards)
    with capsys.disabled():
        print("\nf_MHz  L_coarse_nH  L_fine_nH  R_coarse_mohm  R_fine_mohm")
        for f, Lc, Lf, Rc, Rf in rows:
            print(f"{f / 1e6:6.1f}  {Lc * 1e9:10.5f}  {Lf * 1e9:9.5f}  {Rc * 1e3:12.5f}  {Rf * 1e3:11.5f}")
    by = {f: r for f, *r in rows}
    Lc, Lf, Rc, Rf = by[0.0]
    assert Rc >= Rf * (1 - 1e-12)                  # Thomson: DC current minimises dissipation
    Lc, Lf, Rc, Rf = by[100e6]
    assert Lc >= Lf                                # high frequency: it minimises magnetic energy


def test_the_cell_quote_engine_switch_and_its_rows(boards, monkeypatch):
    import haslam.route.critical_recheck as CRR
    from haslam.excite import cellquote as CQ
    monkeypatch.setattr(CRR, "fills_of", lambda p: plane_fills())
    monkeypatch.setenv("HASLAM_CELL_QUOTE", "strips")
    rows = {v: CQ.quote_cells(boards[v][0], log=lambda *a: None) for v in ("closed", "long", "open")}
    (a,), (b,), (c,) = rows["closed"], rows["long"], rows["open"]
    assert a["engine"] == b["engine"] == "strips"
    for r in (a, b):
        assert r["state"] == "ok"
        assert {"source", "cell", "state", "L_nH", "R_mohm", "window", "pitch", "grown", "seconds", "engine",
                "unknowns", "work_s"} <= set(r)
        assert r["pitch"] == CQ.STRIP_PITCH and r["unknowns"] > 0 and r["work_s"] > 0
    assert c["state"] == "open"
    verdict, total = CQ.compare([a], [b])
    assert verdict[CELL] == -1 and total < 0
    assert CQ.compare([b], [c])[0][CELL] == -1
    monkeypatch.setenv("HASLAM_CELL_QUOTE", "raster")
    with pytest.raises(ValueError):
        CQ.quote_cells(boards["closed"][0], engine="fem", log=lambda *a: None)


def test_a_strips_quote_charges_counted_work_the_same_each_time(boards):
    out = []
    for _ in range(2):
        BU.set_mode("time")
        p, _ = boards["closed"]
        ctx = ST.prepare(p, fills=plane_fills())          # a fresh board: its tables are computed again
        q = ST.from_board(p, CELL, ctx=ctx)
        out.append(dict(q.units))
    assert out[0].get("em_pair", 0) > 0 and out[0].get("em_dense", 0) > 0
    assert out[0] == out[1]


def _fixture_loop():
    """The buck fixture's closed hot loop as haslam.route.critical_modules.loop_model builds one: the VIN hop, U1's
    body, the ground hop through its two vias and the plane, C1's body; the terminals' pads; the B.Cu pour."""
    from shapely.geometry import box
    from haslam.route.critical_physics import Loop
    h = 1.545                                         # F.Cu to B.Cu, centre to centre
    C11, U13, U14, C12 = (117.0, 110.95), (119.69, 110.95), (122.31, 110.95), (117.0, 109.05)
    lp = Loop()
    for (x, y), (wx, wy) in ((C11, (1.45, 1.0)), (C12, (1.45, 1.0)), (U13, (1.06, 0.65)), (U14, (1.06, 0.65))):
        lp.pad((x, y), box(x - wx / 2, y - wy / 2, x + wx / 2, y + wy / 2))
    lp.strip(C11, U13, 0.5, h)
    lp.body(U13, U14, h, 0.8, 0.3)
    lp.strip(U14, (123.3, 111.9), 0.6, h, "va0")
    lp.vert(123.3, 111.9, h, 0.0, 0.3, "va0", drill=0.3)
    lp.vert(117.0, 108.0, 0.0, h, 0.3, "vb0", drill=0.3)
    lp.strip((117.0, 108.0), C12, 0.6, h, "vb0")
    lp.kcl({"va0": 1.0})
    lp.kcl({"vb0": 1.0})
    lp.body(C12, C11, h, 0.8, 0.8)
    lp.plane_geom = plane_fills()["GND"]["B.Cu"][0]
    return lp


def test_a_cells_stage_loop_on_the_strips_network(boards, monkeypatch):
    from haslam.physics import fastloop as FL
    monkeypatch.setenv("HASLAM_CELL_QUOTE", "strips")
    ST._LOOP_CACHE.clear()
    ST._LOOP_BASE.clear()
    lp = _fixture_loop()
    BU.set_mode("time")
    L, R = lp.value_r()
    assert lp.plane_src == "fills" and R > 0
    bodies = sum(FL.strip_self(math.dist(b[1], b[2]), max(b[5], 0.1), b[3] + b[4]) for b in lp.bodies)
    q = _q(boards, "closed")
    assert abs((L - bodies) / (q.L_loop * 1e9) - 1) < 0.15, (L - bodies, q.L_loop * 1e9)
    before = dict(BU.clock().units)
    assert _fixture_loop().value_r() == (L, R)              # the same loop again: the cache, no work
    after = dict(BU.clock().units)
    assert {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)} == {}
    # without a plane height the closed form stands
    from haslam.route.critical_physics import Loop
    free = Loop()
    free.path([(0, 0), (5, 0), (5, 3), (0, 3), (0, 0)], 0.5, math.inf)
    monkeypatch.delenv("HASLAM_CELL_QUOTE")
    ref = free.value_r()
    monkeypatch.setenv("HASLAM_CELL_QUOTE", "strips")
    assert free.value_r() == ref and free.plane_src == "none"


def test_the_module_stage_routes_alike_with_the_strips_engine(tmp_path, monkeypatch):
    """The critical router's module stage on the synthetic board in every fidelity with the strips engine on: the
    same modules route to the same statuses as with the closed forms."""
    import critical_fixtures as F
    from haslam.physics import exact as EX
    from haslam.route.critical_modules import modules_from_brief, route_module
    res = {}
    for engine in ("raster", "strips"):
        monkeypatch.setenv("HASLAM_CELL_QUOTE", engine)
        for mode in ("fast", "multi", "exact"):
            with EX.scope(mode, k=4):
                s = F.session(tmp_path / f"{engine}-{mode}", kinds=("cell", "decap", "chain"), rails="none")
                mods = modules_from_brief(s.brief, ("cell", "decap", "chain"))
                for m in mods:
                    route_module(s.ctx, m)
                res[(engine, mode)] = {m.id: m.status for m in mods}
                if engine == "strips":
                    cells = [m for m in mods if m.kind == "cell" and m.physics]
                    assert cells and all(m.physics.get("strips_plane") in ("fills", "bbox") for m in cells), \
                        [m.physics for m in cells]
    assert len({tuple(sorted(v.items())) for v in res.values()}) == 1, res


def test_a_cells_loop_takes_r_at_its_switching_frequency(monkeypatch):
    monkeypatch.setenv("HASLAM_CELL_QUOTE", "strips")
    out = {}
    for f in (3e5, 3e6):
        lp = _fixture_loop()
        lp.f_sw = f
        out[f] = lp.value_r()
    (L1, R1), (L2, R2) = out[3e5], out[3e6]
    assert L1 == L2                                  # L_loop at the edge band, whatever f_sw
    assert R2 > R1 * 1.01                            # the return crowds under the strip as f_sw rises
