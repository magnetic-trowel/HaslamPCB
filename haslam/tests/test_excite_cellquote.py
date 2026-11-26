# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.excite.cellquote: the cell window alone ranks two layouts of one cell as the evaluator does."""
import math

from hotloop_fixtures import plane_fills, write_hotloop_board
from haslam.excite import cellquote as CQ

CELL = "cell:cell:buck:U1"


def _q(tmp_path, variant, monkeypatch):
    import haslam.route.critical_recheck as CRR
    monkeypatch.setattr(CRR, "fills_of", lambda p: plane_fills())
    p = write_hotloop_board(tmp_path / variant, variant)
    (r,) = [r for r in CQ.quote_cells(str(p), pitch=0.125, log=lambda *a: None) if r["source"] == CELL]
    return r


def test_the_quote_ranks_a_longer_loop_worse_and_an_open_one_open(tmp_path, monkeypatch):
    a, b, c = (_q(tmp_path, v, monkeypatch) for v in ("closed", "long", "open"))
    assert a["state"] == b["state"] == "ok" and c["state"] == "open"
    assert b["L_nH"] > a["L_nH"] > 0 and b["R_mohm"] > a["R_mohm"] > 0
    verdict, total = CQ.compare([a], [b])
    assert verdict[CELL] == -1 and total < 0          # a (closed) is the better layout
    assert CQ.compare([b], [c])[0][CELL] == -1        # an open cell loses to any closed one


def test_a_non_physical_quote_gives_no_score():
    ok = dict(source="a", state="ok", L_nH=1.0, R_mohm=5.0)
    assert CQ.score([ok]) == round(math.log(5.0), 4)
    assert CQ.score([ok, dict(source="b", state="invalid")]) is None
    assert CQ.score([ok, dict(source="b", state="open")]) > CQ.score([ok, dict(ok, source="b")])


def test_the_quote_takes_the_evaluators_l_and_r_through_a_cap_resonance(tmp_path, monkeypatch):
    """The multi-cap fixture of test_excite_hotloop (a 150 nF cap at U1's pins beside C1): the quote's L_loop is
    the evaluator's (stored energy with the caps at ESR + ESL), so it is positive and agrees with the evaluator's
    raw window at the same pitch; R likewise (the copper's dissipation). With the layout's share Im z / w the
    quote read a negative L there and the cells stage would have ranked layouts by a value the evaluator never
    scores."""
    from haslam.excite import models as M
    from haslam.excite.evaluate import evaluate
    build = M.build

    def with_cap(b, brief):
        bd = build(b, brief)
        bd.circuit.z("Cx", "GND", "VIN", M._rlc(0.005, 0.3e-9, 150e-9), pa="U1.4", pb="U1.3", kind="C")
        return bd
    monkeypatch.setattr(M, "build", with_cap)
    q = _q(tmp_path, "closed", monkeypatch)
    p = write_hotloop_board(tmp_path / "ev", "closed")
    ev = evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125,
                  scope="losses")
    (c,) = [r for r in ev["cells"] if r["source"] == CELL]
    assert q["state"] == "ok" and c["state"] == "ok"
    assert q["L_nH"] > 0
    assert math.isclose(q["L_nH"], c["window"]["L_raw_nH"], rel_tol=0.02, abs_tol=0.005)
    assert math.isclose(q["R_mohm"], c["window"]["R_raw_mohm"], rel_tol=0.02, abs_tol=0.01)


def test_a_quote_warm_started_from_the_cell_before_its_change_agrees_and_iterates_less(tmp_path, monkeypatch):
    """haslam.route.hotloop.clear quotes a cell before and after its copper changes; the after quote's window solves start
    from the before quote's (warm): the same values within the COCG tolerance, fewer iterations (em_iter charged;
    a modest gain: COCG's rate, not its start, sets most of the count)."""
    import haslam.route.critical_recheck as CRR
    from haslam import budget as BU
    monkeypatch.setattr(CRR, "fills_of", lambda p: plane_fills())
    a = str(write_hotloop_board(tmp_path / "closed", "closed"))
    b = str(write_hotloop_board(tmp_path / "axis", "axis"))       # the ground hop re-drawn: the same window

    def q(p, warm):
        BU.set_mode("time")
        (r,) = [r for r in CQ.quote_cells(p, pitch=0.125, log=lambda *a: None, warm=warm) if r["source"] == CELL]
        return r, BU.clock().units.get("em_iter", 0)
    cold, it_cold = q(b, None)
    warm = {}
    q(a, warm)
    assert warm                                                     # the before quote left its states
    hot, it_hot = q(b, warm)
    for k in ("L_nH", "R_mohm"):
        assert abs(hot[k] / cold[k] - 1) < 1e-3, (k, hot[k], cold[k])
    assert it_hot < it_cold, (it_hot, it_cold)


def test_the_pruned_fft_matvec_equals_the_full_circulant_one(tmp_path, monkeypatch):
    """Operator.L_apply transforms only the filled ny x nx corner of its (Ny, Nx) circulant grid: the product equals
    the full rfft2 / irfft2 one to rounding."""
    import numpy as np
    import scipy.fft as sfft
    from haslam.board.kicad_file import load
    from haslam.em import solve as ES
    from haslam.em.kicad import BoardMesh
    p = str(write_hotloop_board(tmp_path / "c", "closed"))
    bm = BoardMesh(p, (111.745, 104.02, 127.37, 115.98), 0.125, nsub=2, b=load(p), fills=plane_fills())
    net = ES.Network(bm.m)
    op = ES.Operator(net)
    rng = np.random.default_rng(1)
    I = rng.standard_normal((net.n_br, 2)) + 1j * rng.standard_normal((net.n_br, 2))
    got = op.L_apply(I)
    ref = np.zeros_like(I)
    for o, (S, slot, Kh) in op._index().items():
        f, a0 = net.fil[o], net.off[o]
        n = len(f["a"])
        seg = I[a0:a0 + n]
        G = np.zeros((2, 2, S, op.Ny, op.Nx))
        G[:, 0, slot, f["j"], f["i"]] = seg.real.T
        G[:, 1, slot, f["j"], f["i"]] = seg.imag.T
        X = sfft.rfft2(G.reshape(4, S, op.Ny, op.Nx))
        Y = np.einsum("rsm,csm->crm", Kh, X.reshape(4, S, -1)).reshape(X.shape)
        Y = sfft.irfft2(Y, s=(op.Ny, op.Nx)).reshape(2, 2, S, op.Ny, op.Nx)
        ref[a0:a0 + n] = (Y[:, 0, slot, f["j"], f["i"]] + 1j * Y[:, 1, slot, f["j"], f["i"]]).T
    nv = len(net.vseg)
    if nv:
        ref[net.off["v"]:net.off["v"] + nv] = op.Lv @ I[net.off["v"]:net.off["v"] + nv]
    assert np.abs(got - ref).max() <= 1e-12 * np.abs(ref).max()


def test_an_open_window_is_judged_without_a_solve(tmp_path, monkeypatch):
    """A window whose copper leaves the loop open (the quote then grows it) is judged by connectivity alone: no
    COCG system is built for it (forestierr's quote grew twice, each open window a full factorisation and solve)."""
    from haslam.em import solve as ES
    built = []
    orig = ES.System.__init__

    def spy(self, op, f):
        built.append(f)
        orig(self, op, f)
    monkeypatch.setattr(ES.System, "__init__", spy)
    r = _q(tmp_path, "open", monkeypatch)
    assert r["state"] == "open" and built == []
