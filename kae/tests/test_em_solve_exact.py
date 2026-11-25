# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.em.solve's faster products give the same numbers to the bit as the plain scipy ones they replace
(pnr's output must not change with them)."""
import numpy as np
import pytest
import scipy.fft as sfft
import scipy.sparse as sp

from kae.em import solve as S
from kae.em.mesh import Layer, Mesh


@pytest.mark.parametrize("Ny,Nx,rows", [(729, 960, 361), (45, 75, 23), (64, 81, 30), (9, 10, 5)])
def test_irfft2_rows_is_irfft2_to_the_bit(Ny, Nx, rows):
    rng = np.random.default_rng(Ny + Nx)
    G = np.zeros((3, 2, Ny, Nx))
    G[..., :rows, :(Nx + 1) // 2] = rng.standard_normal((3, 2, rows, (Nx + 1) // 2))
    Y = sfft.rfft2(G) * (0.3 + 1.7j)
    ref = sfft.irfft2(Y, s=(Ny, Nx))[..., :rows, :]
    got = S.irfft2_rows(Y.copy(), Ny, Nx, rows)
    assert got.shape == ref.shape and np.array_equal(got, ref)


def test_spmm_is_scipys_product_to_the_bit():
    rng = np.random.default_rng(1)
    A = sp.random(300, 200, density=0.05, random_state=2, format="csr")
    A = (A + 1j * sp.random(300, 200, density=0.05, random_state=3, format="csr")).tocsr()
    X = rng.standard_normal((200, 8)) + 1j * rng.standard_normal((200, 8))
    assert np.array_equal(S.spmm(A, X), A @ X)
    # a real incidence matrix: its complex copy times complex vectors is what scipy computes from the real one
    D = sp.random(300, 200, density=0.02, random_state=4, format="csr")
    D.data = np.where(D.data > 0.5, 1.0, -1.0)
    assert np.array_equal(S.spmm(D.astype(np.complex128), X), D @ X)
    assert np.array_equal(S.spmm(A, X[:, 0]), A @ X[:, 0])          # one vector: scipy's own
    assert np.array_equal(S.spmm(A, X[:, :1]), A @ X[:, :1])


def _plane_pair():
    m = Mesh.over(0, -2, 6, 2, 0.25, [Layer("T", 0.235, 0.035, 2), Layer("G", 0, 0.035, 2)])
    m.rect(1, "GND", 0, -2, 6, 2)
    m.rect(0, "S", 0.5, -0.25, 5.5, 0.25)
    X, Y = m.centres()
    near = (X < 0.75) & (X > 0.5) & (abs(Y) < 0.25)
    far = (X > 5.25) & (X < 5.5) & (abs(Y) < 0.25)
    m.terminal("s", 0, mask=near)
    m.terminal("g", 1, mask=near)
    m.terminal("se", 0, mask=far)
    m.terminal("ge", 1, mask=far)
    m.part("se", "ge")
    m.port("p", "s", "g")
    return m


def test_the_system_products_are_the_scipy_ones_to_the_bit():
    """matvec and psolve, written with scipy's products and irfft2 as before, against the system's own."""
    net = S.Network(_plane_pair())
    op = S.Operator(net)
    sysm = S.System(op, 1e7)
    rng = np.random.default_rng(0)
    n = net.n_br + sysm.nfree
    u = rng.standard_normal((n, 3)) + 1j * rng.standard_normal((n, 3))
    nb = net.n_br

    def L_ref(I2):
        out = np.zeros_like(I2)
        P = I2.shape[1]
        for o, (Ss, slot, Kh) in op._index().items():
            f = net.fil[o]
            a0, k = net.off[o], len(f["a"])
            if not k:
                continue
            seg = I2[a0:a0 + k]
            G = np.zeros((P, 2, Ss, op.Ny, op.Nx))
            G[:, 0, slot, f["j"], f["i"]] = seg.real.T
            G[:, 1, slot, f["j"], f["i"]] = seg.imag.T
            X = sfft.rfft2(G.reshape(2 * P, Ss, op.Ny, op.Nx))
            Y = S._kmul(Kh, np.ascontiguousarray(X.reshape(2 * P, Ss, -1))).reshape(X.shape)
            Y = sfft.irfft2(Y, s=(op.Ny, op.Nx)).reshape(P, 2, Ss, op.Ny, op.Nx)
            out[a0:a0 + k] = (Y[:, 0, slot, f["j"], f["i"]] + 1j * Y[:, 1, slot, f["j"], f["i"]]).T
        nv = len(net.vseg)
        if nv:
            out[net.off["v"]:net.off["v"] + nv] = op.Lv @ I2[net.off["v"]:net.off["v"] + nv]
        return out

    I, phi = u[:nb], u[nb:]
    LI = L_ref(I)
    if net.Lc_off is not None:
        LI = LI + net.Lc_off @ I
    top = sysm.kap * (sysm.zdiag[:, None] * I + 1j * sysm.w * LI) - sysm.D @ phi
    assert np.array_equal(sysm.matvec(u), np.concatenate([top, -(sysm.DT @ I)]))
    r1, r2 = u[:nb], u[nb:]
    b = sysm.lu.solve(np.ascontiguousarray(-r2 - sysm.DT @ (sysm.Zn_inv @ r1)))
    a = sysm.Zn_inv @ (r1 + sysm.D @ b)
    assert np.array_equal(sysm.psolve(u), np.concatenate([a, b]))
