# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.excite.beliefs.corners: each parameter's samples are its own, and the worst corner holds the extremes."""
import pytest

from haslam.excite.beliefs import EXTRA_POINTS, Param, corners, n_points


def _p(subject, name, typ, lo, hi):
    return Param(subject, name, typ, lo, hi, "", "prior", "test")


PS = [_p("heat", "T_amb_C", 25.0, 25.0, 50.0), _p("heat", "h_W_m2K", 10.0, 8.0, 20.0),
      _p("heat:U1", "theta_jb", 60.0, 30.0, 120.0), _p("dc:U2@3V3", "I_A", 0.1, 0.03, 0.3)]


def test_adding_a_parameter_leaves_every_other_parameters_samples_as_they_were():
    """The corners drew every column from one stream: a new parameter (an inductor's theta_jb) re-drew all of them, and
    martinberlin's D1 read a worst T_j of 133 C, then 117 C, with no physics changed."""
    a = corners(PS, n=16, seed=3)
    b = corners(PS + [_p("heat:L1", "theta_jb", 60.0, 30.0, 120.0)], n=16, seed=3)
    for pa, pb in zip(a, b):
        assert all(pb[k] == v for k, v in pa.items())
    # the order of the parameters does not matter either
    c = corners(list(reversed(PS)), n=16, seed=3)
    assert all(pa == pc for pa, pc in zip(a, c))
    assert len(a) == n_points(16) == 16 + EXTRA_POINTS


def test_each_parameter_is_a_latin_hypercube_column():
    pts = corners(PS, n=16, seed=0)[1:17]
    for p in PS:
        import math
        xs = sorted((math.log(q[(p.subject, p.name)]) - math.log(p.lo)) / (math.log(p.hi) - math.log(p.lo)) for q in pts)
        assert all(i / 16 <= x < (i + 1) / 16 for i, x in enumerate(xs))


def test_the_adverse_vertex_holds_each_parameters_harmful_end():
    """By the named directions (cooling, efficiency, edge times harmful at their low end), and by a measured score."""
    pts = corners(PS, n=8, seed=0)
    adverse, benign = pts[-1], pts[-2]
    assert adverse == {("heat", "T_amb_C"): 50.0, ("heat", "h_W_m2K"): 8.0, ("heat:U1", "theta_jb"): 120.0,
                       ("dc:U2@3V3", "I_A"): 0.3}
    assert benign == {("heat", "T_amb_C"): 25.0, ("heat", "h_W_m2K"): 20.0, ("heat:U1", "theta_jb"): 30.0,
                      ("dc:U2@3V3", "I_A"): 0.03}
    assert pts[-4] == {(p.subject, p.name): p.lo for p in PS} and pts[-3] == {(p.subject, p.name): p.hi for p in PS}
    # a junction temperature, monotone in each: T_amb + theta (P) + P / (h A); the adverse vertex is its exact worst
    # over the box, for every seed, while the worst hypercube sample is not
    T = lambda q: q[("heat", "T_amb_C")] + q[("heat:U1", "theta_jb")] * 0.5 + 0.5 / (q[("heat", "h_W_m2K")] * 0.01)
    worst = 50.0 + 120.0 * 0.5 + 0.5 / 0.08
    for seed in range(5):
        pts = corners(PS, n=16, seed=seed, score=T)
        assert max(T(q) for q in pts) == pytest.approx(worst) and T(pts[-1]) == pytest.approx(worst)
        assert max(T(q) for q in pts[1:17]) < worst
    # a measured direction overrides the named one: a harm that falls with the ambient
    pts = corners(PS, n=4, seed=0, score=lambda q: -q[("heat", "T_amb_C")])
    assert pts[-1][("heat", "T_amb_C")] == 25.0
