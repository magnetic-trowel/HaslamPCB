# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""repair_physics (audit P6): the legality repairs and the legalizer's windows see the physics."""
from pathlib import Path

import numpy as np

from kae.board.kicad_file import load
from kae.budget import Deadline
from kae.place import exact
from kae.place.legalize import _window_solve, legalize
from kae.place.problem import Problem
from kae.place.state import State
from kae.route.constraints import DEFAULTS, setting_env

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _legal():
    P = Problem.build(load(FIXTURE))
    st = State(P)
    for i in P.mov:
        st.X[i], st.Y[i], st.K[i] = P.ncx // 2, P.ncy // 2, 0
    legalize(P, st, time_s=30.0, workers=1, seed=0)
    return P, st


class _Terms:
    """A stand-in for the placement terms: the physics of part `uid` is cost[(x, y)] where it stands."""

    def __init__(self, uid, cost):
        self.uid, self.cost = uid, cost

    def parts(self):
        return {self.uid}

    def delta(self, poses, moved, new):
        return self.cost(new[0][:2]) - self.cost(poses[self.uid][:2])


def _spots(P, st, E, i, n):
    cands = exact._candidates(P, st, i, *exact._tables(P, st, {i}), [int(st.K[i])], 0.0, 4000)
    return [(X, Y, k) for c, X, Y, k in cands if not E.findings_at(i, X, Y, k)][:n]


def _move_with(P, st, i, spots, cost, monkeypatch, priced=True):
    E = exact.ExactModel(P, st)
    if priced:
        P.repair_phys = exact.RepairPhysics(P, _Terms(P.parts[i].uuid, cost))
    else:
        P.repair_phys = None
    monkeypatch.setattr(exact, "_candidates", lambda *a, **k: [(float(n), *t) for n, t in enumerate(spots)])
    E.findings_at = lambda *a, **k: []                 # every spot clean: legality ties
    ok, _ = exact.move_clean(P, st, E, i, Deadline(30))
    assert ok
    return (int(st.X[i]), int(st.Y[i]), int(st.K[i]))


def test_setting_is_off_by_default(monkeypatch):
    assert DEFAULTS["repair_physics"] == 0
    monkeypatch.setenv("KAE_REPAIR_PHYSICS", "1")
    assert setting_env("repair_physics") == 1.0


def test_move_clean_takes_the_lowest_physics_spot_when_legality_ties(monkeypatch):
    P, st = _legal()
    i = P.mov[-1]
    E = exact.ExactModel(P, st)
    spots = _spots(P, st, E, i, 3)
    assert len(spots) == 3
    target = spots[2]
    tx, ty = P.ox + target[0] * P.g, P.oy + target[1] * P.g

    def cost(xy):           # physics falls toward the third spot
        return abs(xy[0] - tx) + abs(xy[1] - ty)
    home = (int(st.X[i]), int(st.Y[i]), int(st.K[i]))
    assert _move_with(P, st, i, spots, cost, monkeypatch) == target
    assert P.repair_phys.stats["changed"] == 1 and P.repair_phys.stats["gain"] > 0
    # off: the nearest
    st.X[i], st.Y[i], st.K[i] = home
    assert _move_with(P, st, i, spots, cost, monkeypatch, priced=False) == spots[0]
    # a tie (equal physics): the nearest
    st.X[i], st.Y[i], st.K[i] = home
    assert _move_with(P, st, i, spots, lambda xy: 1.0, monkeypatch) == spots[0]
    assert P.repair_phys.stats["changed"] == 0


def test_move_clean_prices_only_spots_near_the_nearest(monkeypatch):
    """A spot past the window (2 mm of candidate cost beyond the first clean one) is not priced,
    however good its physics."""
    P, st = _legal()
    i = P.mov[-1]
    E = exact.ExactModel(P, st)
    s0, s1 = _spots(P, st, E, i, 2)
    win = 2.0 / P.g
    monkeypatch.setattr(exact, "_candidates", lambda *a, **k: [(0.0, *s0), (win + 1.0, *s1)])
    P.repair_phys = exact.RepairPhysics(P, _Terms(P.parts[i].uuid, lambda xy: 0.0 if xy[0] == P.ox + s1[0] * P.g
                                                  and xy[1] == P.oy + s1[1] * P.g else 5.0))
    E.findings_at = lambda *a, **k: []
    ok, _ = exact.move_clean(P, st, E, i, Deadline(30))
    assert ok and (int(st.X[i]), int(st.Y[i]), int(st.K[i])) == s0
    assert P.repair_phys.stats["evaluated"] == 1


def test_window_keeps_a_decap_by_its_ic():
    """A window that must move the IC (another part now covers it) takes its decap along when
    the pair is in P.repair_pairs; without it the cap stays where it was."""
    def run(pairs):
        P, st = _legal()
        ref = {p.ref: p.i for p in P.parts}
        u, c, other = ref["U1"], ref["R1"], ref["U2"]
        st.X[other], st.Y[other], st.K[other] = st.X[u], st.Y[u], st.K[u]
        if pairs:
            P.repair_pairs = [(c, 0, u, 0, 2.0)]
        sol, model = _window_solve(P, st, [u, c], int(round(6.0 / P.g)), 10.0, 1, 0)
        assert sol is not None
        for i, (X, Y, k) in zip([u, c], sol):
            st.X[i], st.Y[i], st.K[i] = X, Y, k
        return float(np.abs(st.pins_xy(c)[0] - st.pins_xy(u)[0]).sum())
    without, with_pairs = run(False), run(True)
    assert with_pairs < without - 1.0, (without, with_pairs)
