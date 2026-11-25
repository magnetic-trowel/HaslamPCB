# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compiled kernels of the greedy legalizer (kae.place.legalize.greedy), used when numba is
installed (`kae[fast]`); the numpy window search in legalize.py is the fallback.

Occupancy lives in one summed-area table per side over the grid padded by `pad` cells
(courtyards may overhang the board). A rectangle query is O(1); placing a part updates the
table in place (O(cells after the rectangle)). The nearest free origin is found by walking
L1 rings outwards from the wanted origin, so a part that fits nearby costs a few hundred
queries.
"""
from __future__ import annotations

import numpy as np

try:
    import numba
    HAVE_NUMBA = True
except ImportError:          # pragma: no cover - exercised without kae[fast]
    numba = None
    HAVE_NUMBA = False


def _jit(f):
    return numba.njit(cache=True)(f) if HAVE_NUMBA else f


@_jit
def sat_add_rect(S, i0, i1, j0, j1, v):
    """Add v to every cell of [i0, i1) x [j0, j1) (padded coordinates) in the summed-area
    table S (S[i, j] = sum of cells [0, i) x [0, j))."""
    ni = S.shape[0] - 1
    nj = S.shape[1] - 1
    if i0 < 0:
        i0 = 0
    if j0 < 0:
        j0 = 0
    if i1 > ni:
        i1 = ni
    if j1 > nj:
        j1 = nj
    if i1 <= i0 or j1 <= j0:
        return 0
    for i in range(i0 + 1, ni + 1):
        wi = (i if i < i1 else i1) - i0
        for j in range(j0 + 1, nj + 1):
            wj = (j if j < j1 else j1) - j0
            S[i, j] += v * wi * wj
    return (ni - i0) * (nj - j0)


@_jit
def _q(S, i0, i1, j0, j1):
    """Cells of [i0, i1) x [j0, j1) in S's table (clipped: cells beyond count as empty)."""
    ni = S.shape[0] - 1
    nj = S.shape[1] - 1
    if i0 < 0:
        i0 = 0
    if j0 < 0:
        j0 = 0
    if i1 > ni:
        i1 = ni
    if j1 > nj:
        j1 = nj
    if i1 <= i0 or j1 <= j0:
        return 0
    return S[i1, j1] - S[i0, j1] - S[i1, j0] + S[i0, j0]


@_jit
def _outside(SO, ncx, ncy, i0, i1, j0, j1):
    """Cells of [i0, i1) x [j0, j1) (board grid) not inside the outline; cells beyond the
    grid count as outside."""
    area = (i1 - i0) * (j1 - j0)
    if area <= 0:
        return 0
    a0 = min(max(i0, 0), ncx)
    a1 = min(max(i1, 0), ncx)
    b0 = min(max(j0, 0), ncy)
    b1 = min(max(j1, 0), ncy)
    inside = (a1 - a0) * (b1 - b0)
    cnt = 0
    if inside > 0:
        cnt = SO[a1, b1] - SO[a0, b1] - SO[a1, b0] + SO[a0, b0]
    return cnt + (area - inside)


@_jit
def _fits(T0, T1, SO, ncx, ncy, pad, si, X, Y, k, own, own_n, opp, opp_n, brd, brd_n):
    """Part at origin (X, Y), rotation k: board rectangles inside the outline, own pieces
    free in its side's table and far rectangles free in the other side's (T0 front, T1 back)."""
    for m in range(brd_n[k]):
        if _outside(SO, ncx, ncy, X + brd[k, m, 0], X + brd[k, m, 1], Y + brd[k, m, 2], Y + brd[k, m, 3]) > 0:
            return False
    A = T0 if si == 0 else T1
    B = T1 if si == 0 else T0
    for m in range(own_n[k]):
        if _q(A, X + own[k, m, 0] + pad, X + own[k, m, 1] + pad, Y + own[k, m, 2] + pad,
              Y + own[k, m, 3] + pad) > 0:
            return False
    for m in range(opp_n[k]):
        if _q(B, X + opp[k, m, 0] + pad, X + opp[k, m, 1] + pad, Y + opp[k, m, 2] + pad, Y + opp[k, m, 3] + pad) > 0:
            return False
    return True


@_jit
def nearest_spot(S0, S1, SO, ncx, ncy, pad, si, X0, Y0, K0, w_rot, own, own_n, opp, opp_n, brd, brd_n, max_d):
    """Nearest origin (L1 + w_rot when turning) where the part fits: (cost, X, Y, k, checks), cost
    -1 when none within max_d; checks = origin-and-rotation fit tests made (the counted work)."""
    nk = own.shape[0]
    best_c = -1.0
    bx = by = bk = 0
    n = 0
    for d in range(max_d + 1):
        if best_c >= 0 and d > best_c:
            break
        for dx in range(-d, d + 1):
            rem = d - abs(dx)
            for sgn in range(2):
                if sgn == 1 and rem == 0:
                    break
                dy = rem if sgn == 0 else -rem
                X = X0 + dx
                Y = Y0 + dy
                for k in range(nk):
                    c = d + (w_rot if k != K0 else 0.0)
                    if best_c >= 0 and c >= best_c:
                        continue
                    n += 1
                    if _fits(S0, S1, SO, ncx, ncy, pad, si, X, Y, k, own, own_n, opp, opp_n, brd, brd_n):
                        best_c = c
                        bx = X
                        by = Y
                        bk = k
    return best_c, bx, by, bk, n


@_jit
def evict_push(X, Y, k, si, own, own_n, opp, opp_n, ev, ev_start, j):
    """Grid cells evictable part j (rectangles ev[ev_start[j]:ev_start[j + 1]], rows side, i0,
    i1, j0, j1) must travel to clear the mover at origin (X, Y), rotation k (own pieces on
    side si, opp rectangles on the other): the shortest straight push, right, left, up or
    down, clearing every overlap on the same side; 0 when they do not overlap. A lower bound
    on its displacement (it may land on something else, or turn)."""
    need_r = need_l = need_u = need_d = 0
    hit = False
    for e in range(ev_start[j], ev_start[j + 1]):
        s = ev[e, 0]
        for m in range(own_n[k] + opp_n[k]):
            if m < own_n[k]:
                if s != si:
                    continue
                a = X + own[k, m, 0]
                b = X + own[k, m, 1]
                c = Y + own[k, m, 2]
                d = Y + own[k, m, 3]
            else:
                if s == si:
                    continue
                q = m - own_n[k]
                a = X + opp[k, q, 0]
                b = X + opp[k, q, 1]
                c = Y + opp[k, q, 2]
                d = Y + opp[k, q, 3]
            if b <= ev[e, 1] or ev[e, 2] <= a or d <= ev[e, 3] or ev[e, 4] <= c:
                continue
            hit = True
            need_r = max(need_r, b - ev[e, 1])
            need_l = max(need_l, ev[e, 2] - a)
            need_u = max(need_u, d - ev[e, 3])
            need_d = max(need_d, ev[e, 4] - c)
    if not hit:
        return 0
    return min(min(need_r, need_l), min(need_u, need_d))


@_jit
def ripup_spot(H0, H1, C0, C1, SO, ncx, ncy, pad, si, X0, Y0, K0, w_rot, own, own_n, opp, opp_n, brd,
               brd_n, ev, ev_start, ev_box, max_d):
    """Origin minimizing the displacement of all it moves, among origins free in the hard
    tables H: the mover's L1 + turning, plus for each evictable part it covers (tables C:
    their cells; ev / ev_start: their rectangles, ev_box: their bounding boxes i0, i1, j0, j1)
    the push that clears it (evict_push). All are lengths in grid cells, so the trade is the
    same at any grid pitch. (cost, X, Y, k, checks, pairs), cost -1 when none within max_d;
    checks = origin-and-rotation fit tests, pairs = evictable-part tests (the counted work)."""
    nk = own.shape[0]
    n_ev = ev_start.shape[0] - 1
    best_c = -1.0
    bx = by = bk = 0
    n = 0
    npair = 0
    for d in range(max_d + 1):
        if best_c >= 0 and d > best_c:
            break
        for dx in range(-d, d + 1):
            rem = d - abs(dx)
            for sgn in range(2):
                if sgn == 1 and rem == 0:
                    break
                dy = rem if sgn == 0 else -rem
                X = X0 + dx
                Y = Y0 + dy
                for k in range(nk):
                    c0 = d + (w_rot if k != K0 else 0.0)
                    if best_c >= 0 and c0 >= best_c:
                        continue
                    n += 1
                    if not _fits(H0, H1, SO, ncx, ncy, pad, si, X, Y, k, own, own_n, opp, opp_n, brd, brd_n):
                        continue
                    # covers nothing evictable: the cheap summed-area test first
                    cov = 0
                    Cs = C0 if si == 0 else C1
                    Co = C1 if si == 0 else C0
                    for m in range(own_n[k]):
                        cov += _q(Cs, X + own[k, m, 0] + pad, X + own[k, m, 1] + pad, Y + own[k, m, 2] + pad,
                                  Y + own[k, m, 3] + pad)
                    for m in range(opp_n[k]):
                        cov += _q(Co, X + opp[k, m, 0] + pad, X + opp[k, m, 1] + pad, Y + opp[k, m, 2] + pad,
                                  Y + opp[k, m, 3] + pad)
                    c = c0
                    if cov > 0:
                        # the mover's bounding box at this origin
                        ma = mb = mc = md = 0
                        first = True
                        for m in range(own_n[k] + opp_n[k]):
                            if m < own_n[k]:
                                r0, r1, r2, r3 = own[k, m, 0], own[k, m, 1], own[k, m, 2], own[k, m, 3]
                            else:
                                q = m - own_n[k]
                                r0, r1, r2, r3 = opp[k, q, 0], opp[k, q, 1], opp[k, q, 2], opp[k, q, 3]
                            if first or X + r0 < ma:
                                ma = X + r0
                            if first or X + r1 > mb:
                                mb = X + r1
                            if first or Y + r2 < mc:
                                mc = Y + r2
                            if first or Y + r3 > md:
                                md = Y + r3
                            first = False
                        for j in range(n_ev):
                            npair += 1
                            if ev_box[j, 0] >= mb or ma >= ev_box[j, 1] or ev_box[j, 2] >= md or mc >= ev_box[j, 3]:
                                continue
                            c += evict_push(X, Y, k, si, own, own_n, opp, opp_n, ev, ev_start, j)
                            if best_c >= 0 and c >= best_c:
                                break
                    if best_c < 0 or c < best_c:
                        best_c = c
                        bx = X
                        by = Y
                        bk = k
    return best_c, bx, by, bk, n, npair


def evict_arrays(rects_by_part):
    """(ev (m, 5), ev_start (np + 1,), ev_box (np, 4)) int64 arrays for ripup_spot from
    [[(side, (i0, i1, j0, j1)), ...] per evictable part] (absolute grid rectangles)."""
    rows, start, box = [], [0], []
    for rs in rects_by_part:
        for side, (a, b, c, d) in rs:
            rows.append((side, a, b, c, d))
        start.append(len(rows))
        if rs:
            box.append((min(r[0] for _, r in rs), max(r[1] for _, r in rs), min(r[2] for _, r in rs),
                        max(r[3] for _, r in rs)))
        else:
            box.append((0, 0, 0, 0))
    ev = np.array(rows, np.int64).reshape(-1, 5)
    return ev, np.array(start, np.int64), np.array(box, np.int64).reshape(-1, 4)


def rotations_for_fit(p, k_now):
    """Rotation indices the greedy fit may use: the right angles, plus the current rotation
    when the part was turned to an odd angle (repaired where it is turned)."""
    ks = list(range(getattr(p, "n_ortho", len(p.rots))))
    if 0 <= k_now < len(p.rots) and k_now not in ks:
        ks.append(int(k_now))
    return ks


def part_arrays(p, ks=None):
    """(own (nk, m, 4), own_n (nk,), opp (nk, m, 4), opp_n (nk,), brd (nk, m, 4), brd_n (nk,)) int64 arrays
    of a Problem part's grid rectangles for the rotation indices ks (default: all)."""
    ks = list(range(len(p.rots))) if ks is None else list(ks)
    rots = [p.rots[k] for k in ks]
    nk = len(rots)
    mo = max(1, max(len(r.g_opp) for r in rots))
    mb = max(1, max(len(r.g_boards or (r.g_board,)) for r in rots))
    mp = max(1, max(len(r.g_own_rects or (r.g_own,)) for r in rots))
    own = np.zeros((nk, mp, 4), np.int64)
    own_n = np.zeros(nk, np.int64)
    opp = np.zeros((nk, mo, 4), np.int64)
    opp_n = np.zeros(nk, np.int64)
    brd = np.zeros((nk, mb, 4), np.int64)
    brd_n = np.zeros(nk, np.int64)
    for k, r in enumerate(rots):
        pieces = r.g_own_rects or (r.g_own,)
        for m, o in enumerate(pieces):
            own[k, m] = o
        own_n[k] = len(pieces)
        for m, o in enumerate(r.g_opp):
            opp[k, m] = o
        opp_n[k] = len(r.g_opp)
        bs = r.g_boards or (r.g_board,)
        for m, b in enumerate(bs):
            brd[k, m] = b
        brd_n[k] = len(bs)
    return own, own_n, opp, opp_n, brd, brd_n
