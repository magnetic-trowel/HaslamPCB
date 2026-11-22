# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.em.strips: the strip-and-tile PEEC cell quote (quick-physics M2; tools/research/physics/quickphys/PLAN.md
items 4 and 5)."""
import math
import time

import numpy as np
import pytest

from hotloop_fixtures import island_fills, plane_fills, write_hotloop_board
from kae import budget as BU
from kae.em import kernels as KN
from kae.em import strips as ST

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


def _q(boards, v, P=ST.STRIP_PITCH, **kw):
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
    q = _q(boards, "closed", p0=1.0, keep=True)
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
    # uniform tiles: the two layouts share every tile (a graded plan follows each layout's near region)
    c = _q(boards, "closed", keep=True, grade=False)
    l_ = _q(boards, "long", keep=True, grade=False)
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


def bound_table(boards, P=1.0, freqs=F_BOUND, variant="closed", q=None):
    """[(f, L_coarse, L_fine, R_coarse, R_fine)] of the fixture's loop with graded tiles of near pitch P and its 2 x 2
    refinement (or of the quote q's network, kept), with the caps at their edge model (ESR + ESL) at every frequency:
    one network, so the two are nested at each f."""
    q = q if q is not None else _q(boards, variant, p0=P, keep=True)
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
    for f in F_BOUND[1:]:                          # measured: L keeps the inductive limit's order at every f > 0
        Lc, Lf, Rc, Rf = by[f]
        assert Lc >= Lf, (f, Lc, Lf)


def test_the_cell_quote_engine_switch_and_its_rows(boards, monkeypatch):
    import kae.route.critical_recheck as CRR
    from kae.excite import cellquote as CQ
    monkeypatch.setattr(CRR, "fills_of", lambda p: plane_fills())
    monkeypatch.setenv("KAE_CELL_QUOTE", "strips")
    rows = {v: CQ.quote_cells(boards[v][0], log=lambda *a: None) for v in ("closed", "long", "open")}
    (a,), (b,), (c,) = rows["closed"], rows["long"], rows["open"]
    assert a["engine"] == b["engine"] == "strips"
    for r in (a, b):
        assert r["state"] == "ok"
        assert {"source", "cell", "state", "L_nH", "R_mohm", "window", "pitch", "grown", "seconds", "engine",
                "unknowns", "work_s", "pitch_near", "pitch_far", "repairs"} <= set(r)
        assert r["pitch"] == CQ.STRIP_PITCH and r["unknowns"] > 0 and r["work_s"] > 0
    assert c["state"] == "open"
    verdict, total = CQ.compare([a], [b])
    assert verdict[CELL] == -1 and total < 0
    assert CQ.compare([b], [c])[0][CELL] == -1
    monkeypatch.setenv("KAE_CELL_QUOTE", "raster")
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
    """The buck fixture's closed hot loop as kae.route.critical_modules.loop_model builds one: the VIN hop, U1's
    body, the ground hop through its two vias and the plane, C1's body; the terminals' pads; the B.Cu pour."""
    from shapely.geometry import box
    from kae.route.critical_physics import Loop
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
    from kae.physics import fastloop as FL
    monkeypatch.setenv("KAE_CELL_QUOTE", "strips")
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
    from kae.route.critical_physics import Loop
    free = Loop()
    free.path([(0, 0), (5, 0), (5, 3), (0, 3), (0, 0)], 0.5, math.inf)
    monkeypatch.delenv("KAE_CELL_QUOTE")
    ref = free.value_r()
    monkeypatch.setenv("KAE_CELL_QUOTE", "strips")
    assert free.value_r() == ref and free.plane_src == "none"


def test_the_module_stage_routes_alike_with_the_strips_engine(tmp_path, monkeypatch):
    """The critical router's module stage on the synthetic board in every fidelity with the strips engine on: the
    same modules route to the same statuses as with the closed forms."""
    import critical_fixtures as F
    from kae.physics import exact as EX
    from kae.route.critical_modules import modules_from_brief, route_module
    res = {}
    for engine in ("raster", "strips"):
        monkeypatch.setenv("KAE_CELL_QUOTE", engine)
        for mode in ("fast", "multi", "exact"):
            with EX.scope(mode, k=4):
                s = F.session(tmp_path / f"{engine}-{mode}", kinds=("cell", "decap", "chain"), rails="none")
                mods = modules_from_brief(s.brief, ("cell", "decap", "chain"))
                for m in mods:
                    route_module(s.ctx, m)
                res[(engine, mode)] = {m.id: m.status for m in mods}
                if engine == "strips":
                    cells = [m for m in mods if m.kind == "cell" and m.physics]
                    assert cells and all(m.physics.get("plane_src") in ("fills", "bbox") for m in cells), \
                        [m.physics for m in cells]
    assert len({tuple(sorted(v.items())) for v in res.values()}) == 1, res


def test_a_cells_loop_takes_r_at_its_switching_frequency(monkeypatch):
    monkeypatch.setenv("KAE_CELL_QUOTE", "strips")
    out = {}
    for f in (3e5, 3e6):
        lp = _fixture_loop()
        lp.f_sw = f
        out[f] = lp.value_r()
    (L1, R1), (L2, R2) = out[3e5], out[3e6]
    assert L1 == L2                                  # L_loop at the edge band, whatever f_sw
    assert R2 > R1 * 1.01                            # the return crowds under the strip as f_sw rises


def test_graded_tiles_are_2_to_1_and_tile_the_pour():
    """quadtree: P0 where the near region is, coarser outward up to p_far, no two touching leaves more than 2:1, the
    leaves cover the pour once; the plane's interface bars join a coarse leaf to each fine neighbour as wide as it."""
    from shapely.geometry import Point, box
    poly = box(0, 0, 16, 12)
    near = Point(5, 5).buffer(1.5)
    fine = [(Point(5, 5).buffer(0.3), 0.125)]
    X0, Y0, S = ST.quadtree(poly, (0, 0), 0.25, 2.0, near, 0.5, fine)
    assert S.min() == 0.125 and S.max() == 2.0 and set(np.round(S, 9)) <= {0.125, 0.25, 0.5, 1.0, 2.0}
    assert abs((S ** 2).sum() - poly.area) < 1e-9
    m = np.array([near.intersects(box(x, y, x + s, y + s)) for x, y, s in zip(X0, Y0, S)])
    assert (S[m] <= 0.25).all()
    for k in range(X0.size):                       # touching leaves (sharing an edge) differ at most 2:1
        dx = np.minimum(X0 + S, X0[k] + S[k]) - np.maximum(X0, X0[k])
        dy = np.minimum(Y0 + S, Y0[k] + S[k]) - np.maximum(Y0, Y0[k])
        touch = ((np.abs(dx) < 1e-9) & (dy > 1e-9)) | ((np.abs(dy) < 1e-9) & (dx > 1e-9))
        assert (S[touch] <= 2 * S[k] + 1e-9).all() and (S[touch] >= S[k] / 2 - 1e-9).all()
    net = ST.Network({"B.Cu": (0.0, 35e-6)}, origin=(0, 0))
    pl = net.plane(poly, "B.Cu", "GND", 0.25, near=near, p_far=2.0, beta=0.5, fine=fine)
    a = net.arrays()
    L = np.where(a.ax == 0, a.box[:, 1] - a.box[:, 0], a.box[:, 3] - a.box[:, 2])
    W = np.where(a.ax == 0, a.box[:, 3] - a.box[:, 2], a.box[:, 1] - a.box[:, 0])
    ratio = np.round(L / W, 9)
    assert set(ratio) == {1.0, 1.5}                 # equal leaves, and the 2:1 interface bars
    for axis in (0, 1):            # each axis's bars cover the pour once but for half a leaf at its two far edges
        m = a.ax == axis
        cover = (L[m] * W[m]).sum() / 1e-6
        assert poly.area - 2 * 12 - 1e-9 <= cover <= poly.area + 1e-9
    assert len(pl["nodes"]) == X0.size


def test_no_link_is_free_of_inductance(boards):
    """Every join of a via, a track's end or a pad to the plane tiles is copper with R and L (radial bars of the
    landing's copper), not a resistive well: the network's lumped branches are only the circuit's parts and shorts
    inside one pad."""
    q = _q(boards, "closed", keep=True)
    net = q.net
    assert {lp.kind for lp in net.lumps} <= {"part", "short"}
    a = net.arrays()
    land = np.nonzero(a.grp == "land")[0]
    assert land.size >= 4
    L = ST.mutuals(net)
    assert (np.diag(L)[land] > 0).all() and (a.R[land] > 0).all()
    assert q.breakdown["land"]["L_nH"] > 0


def test_a_quote_coarsened_by_its_budget_reports_it(boards):
    first = _q(boards, "closed", max_unknowns=10 ** 6)
    assert first.state == "ok" and first.grade == ST.GRADES[0]
    q = _q(boards, "closed", max_unknowns=first.unknowns - 1)
    assert q.state == "ok" and q.grade != ST.GRADES[0] and q.unknowns < first.unknowns
    assert q.pitch_far > q.pitch_near == first.pitch_near
    assert abs(q.L_loop / first.L_loop - 1) < 0.05


def test_a_quote_past_the_refusal_line_is_not_computed(boards, tmp_path):
    q = _q(boards, "closed", max_unknowns=500)
    assert q.state == "not_computed" and q.L_loop is None and q.R_loop is None
    assert q.why.startswith("pitch too coarse for the loop: needs P0 <= 0.5 mm, budget allows about")
    # a huge window (500 mm, poured): even at its far cap (16 mm tiles) and the 2:1 rule alone it needs more
    from shapely.geometry import box
    p = write_hotloop_board(tmp_path / "huge", "closed")
    win = (-100, -100, 400, 400)
    ctx = ST.prepare(str(p), fills={"GND": {"B.Cu": [box(*win)]}})
    q = ST.from_board(str(p), CELL, window=win, ctx=ctx)
    assert q.state == "not_computed" and q.grade is None and q.pitch_far == 16 and q.L_loop is None
    assert q.why.startswith("pitch too coarse for the loop") and q.unknowns > ST.MAX_UNKNOWNS
    assert ST.from_board(str(p), CELL, window=win, ctx=ctx, max_unknowns=8000).state == "ok"


def test_a_copper_join_the_tiles_lose_is_repaired_or_not_computed(tmp_path, monkeypatch):
    """The B.Cu ground cut in two halves joined by a 0.15 mm 45-degree neck (island_fills): KiCad's union connects
    the two ground vias, a 0.5 mm tile grid does not. The quote refines there and closes the loop; without repairs it
    is not_computed ("copper join lost"), never "open"; with the neck gone it is open."""
    p = str(write_hotloop_board(tmp_path / "isl", "closed"))
    ctx = ST.prepare(p, fills=island_fills(0.15))
    q = ST.from_board(p, CELL, ctx=ctx)
    assert q.state == "ok" and q.repairs >= 1
    monkeypatch.setattr(ST, "JOIN_TRIES", 0)
    q0 = ST.from_board(p, CELL, ctx=ctx)
    assert q0.state == "not_computed" and q0.why.startswith("copper join lost")
    from shapely.geometry import box
    cut = {"GND": {"B.Cu": [island_fills(0.15)["GND"]["B.Cu"][0].difference(box(119.6, 108.0, 121.0, 111.0))]}}
    q1 = ST.from_board(p, CELL, ctx=ST.prepare(p, fills=cut))
    assert q1.state == "open"


def test_the_tiles_connect_the_fixture_as_its_copper(boards):
    p, ctx = boards["closed"]
    s = ST._source(ctx, CELL)
    win, box_ = ST.cell_window(ctx, s)
    nf, ne, inj_f, inj_e, info = ST.build_cell(ctx, s, win, box=box_, beta=ST.GRADES[0])
    assert ST.check_joins(nf, info, set(inj_f)) is None and ST.check_joins(ne, info, set(inj_e)) is None
    pieces, plab, padlab = ST.copper_islands(nf, info["geo"])
    u13, u14 = nf.pads["U1.3"]["node"], nf.pads["U1.4"]["node"]
    assert padlab[u13] == padlab[u14] and nf.connected(u13, u14)


def test_a_track_end_whose_copper_meets_another_track_joins_it(boards):
    """The fixture's +3V3 track down from (130, 107.5) ends at (130, 110), 0.30 mm from the centre line of the
    0.5 mm L1.2 -> C2.1 track: farther than that track's half width, but their copper overlaps (0.125 + 0.25 mm), as
    KiCad joins them. U1.1 reaches L1.2 through it."""
    p, ctx = boards["closed"]
    s = ST._source(ctx, CELL)
    nf, *_ = ST.build_cell(ctx, s, (107.215, 100.0, 131.9, 120.51), box=ST.cell_window(ctx, s)[1])
    assert nf.connected(nf.pads["U1.1"]["node"], nf.pads["L1.2"]["node"])
