# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The routing-channel term (haslam.place.exact.channel_grid) and its addition: the
pad-to-edge part (channel_edge_term, riding on the zone table) and its plumbing
(pipeline._channel_weight). The overlap measure equals the annealer's own pair sum; the edge
part prices pads near the outline and nothing in the middle; merged zone tables price each
part as the sum of their parts; both engines price the merged table alike."""
import random

import numpy as np
import pytest

from haslam.place import exact as X
from haslam.place import zones as Z
from haslam.place.anneal import Annealer
from haslam.place.pipeline import _channel_weight

from test_place_zones import _problem, _put, _ref


def _scatter(P, st, seed=1):
    rng = np.random.default_rng(seed)
    for i in P.mov:
        st.X[i], st.Y[i] = rng.integers(50, 550), rng.integers(50, 350)


def test_overlap_is_the_annealers_pair_sum_over_movable_pairs():
    P, st = _problem()
    g = X.channel_grid(P, weight=1.0)
    mov = set(P.mov)
    for s in range(4):
        _scatter(P, st, s)
        # crowd everything near the middle so halos overlap
        for i in P.mov:
            st.X[i] = 300 + (st.X[i] - 300) // 8
            st.Y[i] = 200 + (st.Y[i] - 200) // 8
        A = Annealer(P, st.copy(), silk=g, w_silk=1.0)
        ks = list(A.silk)
        want = sum(A._silk_pair(ks[a], ks[b]) for a in range(len(ks)) for b in range(a + 1, len(ks))
                   if ks[a] in mov or ks[b] in mov)
        got, pairs = X.channel_overlap(P, g, st.X, st.Y, st.K)
        assert abs(got - want) < 1e-6 * max(1.0, want)
        assert (pairs > 0) == (want > 0)
    assert want > 0


def test_edge_term_prices_pads_at_the_edge_not_in_the_middle():
    P, st = _problem()
    A0 = X.mean_part_area(P)
    T = X.channel_edge_term(P, 1.0, A0, Z.raster_cell(P))
    assert T is not None and T.info["edge_pads"] > 0
    track, clr = X.channel_track_clr(P)
    assert abs(T.info["edge_band_mm"] - (P.edge_clearance + track + clr)) < 1e-9
    i = _ref(P)["R1"]
    k = 0
    _put(P, st, i, k, 30.0, 20.0, 0)            # board 60 x 40 mm: the middle
    assert T.part(i, st.X[i], st.Y[i], k) == 0.0
    # pad 0 just inside the copper-to-edge clearance band at the left edge: in the band
    p = P.parts[i]
    pd = p.fp.pads[0]
    half = max(pd.size) / 2
    _put(P, st, i, k, P.edge_clearance + half + 0.05, 20.0, 0)
    near = T.part(i, st.X[i], st.Y[i], k)
    assert near > 0
    # wholly in the band, a pad costs halo x its long side / A0 (cells), split over its samples
    halo = (track + 2 * clr) / 2.0
    full = (halo / P.g) * (max(pd.size) / P.g) / A0
    assert near <= len(p.fp.pads) * full + 1e-9
    # weight scales it linearly; fixed parts are not tabulated
    T3 = X.channel_edge_term(P, 3.0, A0, Z.raster_cell(P))
    assert abs(T3.part(i, st.X[i], st.Y[i], k) - 3 * near) < 1e-9
    f = next(q.i for q in P.parts if not q.movable)
    h = f * T.kmax
    assert T.ent[h, 1] == 0


def test_edge_term_sees_an_edge_cutout():
    from shapely.geometry import box
    P, st = _problem()
    P.outline = P.outline.difference(box(28.0, 18.0, 32.0, 22.0))      # a 4 mm slot in the middle
    A0 = X.mean_part_area(P)
    T = X.channel_edge_term(P, 1.0, A0, Z.raster_cell(P))
    i = _ref(P)["R1"]
    pd = P.parts[i].fp.pads[0]
    _put(P, st, i, 0, 32.0 + P.edge_clearance + max(pd.size) / 2 + 0.05, 20.0, 0)
    assert T.part(i, st.X[i], st.Y[i], 0) > 0
    _put(P, st, i, 0, 45.0, 20.0, 0)
    assert T.part(i, st.X[i], st.Y[i], 0) == 0.0


def test_merged_tables_price_the_sum_of_their_parts():
    P, st = _problem(mask=0.5)
    T = Z.build(P, pull=1.0, keepout=1.0)
    E = X.channel_edge_term(P, 2.0, X.mean_part_area(P), T.c)
    M = Z.merge(T, E)
    assert Z.merge(None, E) is E and Z.merge(T, None) is T
    assert M.maps.shape[0] == T.maps.shape[0] + 1
    r = random.Random(3)
    for _ in range(400):
        i = r.choice(P.mov)
        k = r.randrange(len(P.parts[i].rots))
        x, y = r.randint(-20, P.ncx + 20), r.randint(-20, P.ncy + 20)
        assert abs(M.part(i, x, y, k) - T.part(i, x, y, k) - E.part(i, x, y, k)) < 1e-12


def test_engine_prices_the_merged_table_like_the_reference():
    engine = pytest.importorskip("haslam.place.engine")
    if not engine.HAVE_NUMBA:
        pytest.skip("numba not installed (haslam[fast])")
    P, st = _problem(mask=0.5)
    T = Z.merge(Z.build(P, pull=1.0, keepout=1.0), X.channel_edge_term(P, 3.0, X.mean_part_area(P),
                                                                        Z.raster_cell(P)))
    _scatter(P, st)
    A = Annealer(P, st.copy(), w_cong=30.0, zones=T, w_zone=1.0)
    F = engine.FastAnnealer(P, st.copy(), w_cong=30.0, zones=T, w_zone=1.0)
    E = F.E
    assert abs(A.cost(3.0) - F.cost(3.0)) < 1e-9
    r = random.Random(2)
    for _ in range(1500):
        i = r.choice(P.mov)
        k = r.randrange(len(P.parts[i].rots))
        x, y = A.X[i] + r.randint(-150, 150), A.Y[i] + r.randint(-150, 150)
        _, da = A.try_move((i,), [(x, y, k)], 1e30, 3.0, "x")
        _, de = engine.try_move(E, np.array([i], np.int64), np.array([x], np.int64), np.array([y], np.int64),
                                np.array([k], np.int64), 1, 1e30, 3.0, 0.0, 0.0, True)
        assert abs(da - de) < 1e-9 * max(1.0, abs(da))


def test_channel_weight_reports_the_seed_and_adds_the_edge_table_only_when_asked():
    P, st = _problem()
    _scatter(P, st)
    for i in P.mov:
        st.X[i] = 300 + (st.X[i] - 300) // 8
        st.Y[i] = 200 + (st.Y[i] - 200) // 8
    w, tab, rep, e1 = _channel_weight(P, st, 3.0, None, {}, None, {})
    assert w == 3.0 and tab is None and e1 is None and rep["seed_overlap"] > 0
    w, tab, rep, e1 = _channel_weight(P, st, 3.0, None, {}, None, {"place_chan_edge": 1})
    assert w == 3.0 and tab is not None and e1 is not None and rep["edge_weight"] == 3.0
    for i in P.mov:
        k = int(st.K[i])
        assert abs(tab.part(i, st.X[i], st.Y[i], k) - 3 * e1.part(i, st.X[i], st.Y[i], k)) < 1e-9


def test_util_gate_scales_the_weight_from_full_to_off():
    from haslam.place import pipeline
    P, st = _problem()
    for u, want in ((0.3, 1.0), (0.65, 1.0), (0.675, 0.5), (0.70, 0.0), (0.9, 0.0)):
        P.utilization = lambda u=u: (u, 0.1)
        assert abs(pipeline.util_gate(P) - want) < 1e-9
        w, tab, rep, _ = _channel_weight(P, st, 3.0, None, {}, None, {"place_chan_util_gate": 1})
        assert abs(w - 3.0 * want) < 1e-9 and rep["w_set"] == 3.0 and rep["util"] == round(u, 4)
    w, *_ = _channel_weight(P, st, 3.0, None, {}, None, {})       # gate off: the weight as set
    assert w == 3.0


def test_gated_off_term_places_like_control():
    from haslam.place import pipeline
    from test_place_zones import _board
    res = []
    for opts in ({}, {"place_w_chan": 3, "place_chan_util_gate": 1}):
        b = _board()
        orig = pipeline.Problem.utilization
        pipeline.Problem.utilization = lambda self: (0.9, 0.9)
        try:
            r = pipeline.place(b, seed=0, time_s=8, physics=False, workers=1, log=lambda m: None, opts=opts)
        finally:
            pipeline.Problem.utilization = orig
        res.append(sorted((f.ref, round(f.x, 4), round(f.y, 4), round(f.rot, 2)) for f in b.footprints))
    assert res[0] == res[1]


def test_header_gate_switches_the_term_off_only_for_a_header_that_fits_nowhere(monkeypatch):
    from haslam.place import crowded
    P, st = _problem()
    opts = {"place_chan_header_gate": 1}
    monkeypatch.setattr(crowded, "edge_headers", lambda P: {P.mov[0]: ("x", 14, 33.0)})
    monkeypatch.setattr(crowded, "fits_nowhere", lambda P, st, i: True)
    w, tab, rep, _ = _channel_weight(P, st, 3.0, None, {}, None, opts)
    assert w == 0.0 and rep["stuck_headers"] == [P.parts[P.mov[0]].ref] and rep["w_set"] == 3.0
    monkeypatch.setattr(crowded, "fits_nowhere", lambda P, st, i: False)    # a header row with room keeps the term
    w, tab, rep, _ = _channel_weight(P, st, 3.0, None, {}, None, opts)
    assert w == 3.0 and rep["stuck_headers"] == []
    monkeypatch.setattr(crowded, "fits_nowhere", lambda P, st, i: True)
    w, *_ = _channel_weight(P, st, 3.0, None, {}, None, {})                 # the gate off: never asked
    assert w == 3.0


def test_header_gate_survives_a_failing_detector(monkeypatch):
    from haslam.place import crowded
    P, st = _problem()

    def boom(P):
        raise ValueError("no outline")
    monkeypatch.setattr(crowded, "edge_headers", boom)
    w, tab, rep, _ = _channel_weight(P, st, 3.0, None, {}, None, {"place_chan_header_gate": 1})
    assert w == 3.0 and rep["stuck_headers"] == []


def test_channel_settings_default_off():
    from haslam.route.constraints import DEFAULTS
    assert DEFAULTS["place_w_chan"] == 0.0
    assert DEFAULTS["place_chan_util_gate"] == 0 and DEFAULTS["place_chan_header_gate"] == 0
