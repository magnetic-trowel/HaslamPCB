# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Legalization: windowed CP-SAT minimum displacement on the grid, then an exact check.

`legalize(P, st, budget)` repairs grid violations window by window (after
tools/research/solver-bench/legalize_clusters.py): violators near each other form a group;
the group and its k nearest movable parts are freed inside a window, everything else is a
fixed obstacle, and CP-SAT minimizes L1 displacement plus a rotation-change charge. A
window that fails grows (k x 1.6, larger margin); if rounds run out, every movable part is
freed at once. Physics structures survive it: a window reaches where a violator must go,
physics macros move as blocks, and physics breaks exact displacement ties (`legalize`).

`exact_check(P, st)` re-checks the result with KiCad's shapes (shapely): courtyards per
side (deflated by max_error, as KiCad does), holes inside other courtyards, pad-to-pad
copper clearance, pads inside the outline at the copper-to-edge clearance, and rule areas
that keep out footprints or pads. It reports what remains illegal; DRC on the re-opened
board stays the judge.
"""
from __future__ import annotations

from haslam.budget import Deadline, charge
import math
import os
import time

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon

from haslam.board import transform

from . import cpsat
from .problem import is_drilled
from .state import grid_violations


# ----------------------------------------------------------------------------- grid repair
def _groups(st, bad, radius_mm, viol=None, cap=8):
    """Violators near each other (centres within radius_mm, L1), and violators that overlap
    each other (`viol` reasons ('overlap', j)), form one group. Without the overlap rule a big
    part and a small part on its courtyard (centres far apart) went to separate windows, each
    holding the other fixed (tinkerforge temperature: a connector over a fiducial, two windows
    moving 9 parts 15 mm in all; one window moves 7 parts 3 mm). Overlap merges stop at `cap`
    violators a group (machdyne blaustahl, an overfull board: 36 violators in one chain)."""
    pts = {i: st.center(i) for i in bad}
    groups = []
    for b in sorted(bad):
        bx, by = pts[b]
        for gr in groups:
            if any(abs(bx - pts[o][0]) + abs(by - pts[o][1]) < radius_mm for o in gr):
                gr.append(b)
                break
        else:
            groups.append([b])
    if not viol:
        return groups
    parent = list(range(len(groups)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    root = {b: gi for gi, gr in enumerate(groups) for b in gr}
    size = [len(gr) for gr in groups]
    for b in sorted(bad):
        for why, j in viol.get(b, ()):
            if why == "overlap" and j in root:
                ra, rb = find(root[b]), find(root[j])
                # pairs only up to `cap` violators a group: on a crowded board the overlaps chain
                # every violator into one window that cannot be solved
                if ra != rb and size[ra] + size[rb] <= cap:
                    parent[max(ra, rb)] = min(ra, rb)
                    size[min(ra, rb)] += size[max(ra, rb)]
    merged = {}
    for gi, gr in enumerate(groups):
        merged.setdefault(find(gi), []).extend(gr)
    return [sorted(merged[k]) for k in sorted(merged)]


def _rigid_ok(P, st, members):
    """A group may move as one block at its current offsets: every member movable and no two
    members' rectangles meeting (a block cannot repair an overlap inside itself)."""
    if len(members) < 2 or not all(P.parts[i].movable for i in members):
        return False
    rs = [(i, s, r) for i in members for s, r, _ in st.grid_rects(i)]
    return not any(i != j and s == t and a[1] > b[0] and b[1] > a[0] and a[3] > b[2] and b[3] > a[2]
                   for k, (i, s, a) in enumerate(rs) for (j, t, b) in rs[k + 1:])


def _block(P, st, members):
    """cpsat.Item moving `members` together at their current offsets and rotations (one
    variant), anchored on the largest; displacement weighs as many parts as it holds."""
    a = max(members, key=lambda i: (P.parts[i].area, -i))
    X0, Y0 = int(st.X[a]), int(st.Y[a])
    v = {i: (int(st.X[i]) - X0, int(st.Y[i]) - Y0, int(st.K[i])) for i in members}
    return cpsat.Item(members=list(members), variants=[v], X0=X0, Y0=Y0, v0=0, weight=float(len(members)),
                      name=f"B_{P.parts[a].ref}")


def _escape_rects(P, st, i):
    """Grid rectangles of part i at the nearest pose clear of the fixed obstacles and inside
    the outline, ignoring movable parts (where it must go at least), or [] when it is
    already clear of them or has no such pose. A window that cannot reach this pose can
    never legalize i, however many neighbours it frees."""
    p = P.parts[i]
    pad = 1
    for r in p.rots:
        for (a, b, c, d) in (r.g_own,) + tuple(r.g_opp):
            pad = max(pad, -a, b, -c, d)
    pad += 1
    occ = _occupancy(P, st, set(P.mov), pad)
    span = max(P.ncx, P.ncy) + 2 * pad
    best = _nearest_spot(P, p, int(st.X[i]), int(st.Y[i]), int(st.K[i]), occ, pad, 2.0 / P.g, span)
    if best is None or (best[1], best[2], best[3]) == (int(st.X[i]), int(st.Y[i]), int(st.K[i])):
        return []
    t = st.copy()
    t.X[i], t.Y[i], t.K[i] = best[1], best[2], best[3]
    return [r for _, r, _ in t.grid_rects(i)]


def _window_solve(P, st, free, margin_cells, time_s, workers, seed, w_rot=1.0, blocks=(), reach=(), phys=None):
    """Re-place the `free` parts inside a window around them; others are obstacles. `blocks`:
    groups of free parts that move as one (`_block`); `reach`: extra grid rectangles the
    window must cover (a violator's escape pose). `phys(state) -> float`: when the window is
    solved to optimality, the tie-break among its equal-displacement optima (`TIE_SOLUTIONS`
    of them); displacement stays the objective, physics only chooses between exact ties."""
    g = P.g
    rects = [r for i in free for (_, r, _) in st.grid_rects(i)] + list(reach)
    wi0 = min(r[0] for r in rects) - margin_cells
    wi1 = max(r[1] for r in rects) + margin_cells
    wj0 = min(r[2] for r in rects) - margin_cells
    wj1 = max(r[3] for r in rects) + margin_cells
    # origin box: the window; obstacles: everything that can reach into it
    ext = max(max(r[1] - r[0], r[3] - r[2]) for r in rects) + 2
    for b in blocks:                # a block's members reach as far from its anchor's origin as it spans
        br = [r for i in b for (_, r, _) in st.grid_rects(i)]
        ext = max(ext, max(r[1] for r in br) - min(r[0] for r in br) + 2, max(r[3] for r in br) - min(r[2] for r in br) + 2)
    obstacles = []
    fs = set(free)
    for i in P.mov:
        if i in fs:
            continue
        for side, r, _ in st.grid_rects(i):
            if r[1] > wi0 - ext and r[0] < wi1 + ext and r[3] > wj0 - ext and r[2] < wj1 + ext:
                obstacles.append((side, r))
    for ob in P.obstacles:
        r = ob.g
        if r[1] > wi0 - ext and r[0] < wi1 + ext and r[3] > wj0 - ext and r[2] < wj1 + ext:
            obstacles.append((ob.side, r))
    items = []
    in_block = {i for b in blocks for i in b}
    for b in blocks:
        items.append(_block(P, st, b))
    for i in free:
        if i not in in_block:
            items.append(cpsat.single(P, i, int(st.X[i]), int(st.Y[i]), int(st.K[i])))
    for it in items:
        it.bounds = (wi0, wi1, wj0, wj1)
    model = cpsat.Model(P, items, obstacles, w_disp=1.0, w_rot=w_rot)
    sol = model.solve(time_s, workers=workers, seed=seed)
    _ = g

    def poses(sol):          # per freed part: origin and rotation index
        pos = {}
        for it, (X, Y, v) in zip(items, sol):
            for i, (dx, dy, k) in it.variants[v].items():
                pos[i] = (X + dx, Y + dy, k)
        return [pos[i] for i in free]
    if sol is None:
        return None, model
    sol = poses(sol)
    model.ties = 1
    if phys is not None and model.status == "OPTIMAL":
        cands = [poses(c) for c in model.optima(max(0.05, min(2.0, 0.5 * time_s)), n=TIE_SOLUTIONS, seed=seed)]
        model.ties = len(cands)
        if len(cands) > 1:
            t = st.copy()
            best = None
            for c in cands:
                for i, (X, Y, k) in zip(free, c):
                    t.X[i], t.Y[i], t.K[i] = X, Y, k
                v = float(phys(t))
                if best is None or v < best[0] - 1e-9:
                    best = (v, c)
            model.tie_gain = round(float(phys(_with(st, free, sol))) - best[0], 5)
            sol = best[1]
    return sol, model


def _with(st, free, sol):
    t = st.copy()
    for i, (X, Y, k) in zip(free, sol):
        t.X[i], t.Y[i], t.K[i] = X, Y, k
    return t


MAX_WINDOW = 40          # parts freed in one CP-SAT window
TIE_SOLUTIONS = 16       # equal-displacement optima a window compares by physics
GLOBAL_MAX = 40          # all parts in one CP-SAT model only up to this many


def legalize(P, st, time_s=30.0, workers=2, seed=0, k=8, max_rounds=8, log=None, force=(), window_share=0.6,
             rigid=(), phys=None):
    """Repair grid violations in place (parts in `force` are re-placed in the first round even
    when the grid finds them legal, e.g. after a KiCad violation). Returns a report dict.

    1. Windows: violators within 4 mm form a group; the group and its nearest movable parts
       (k, growing x1.6 on failure, at most MAX_WINDOW) are re-placed by CP-SAT at minimum
       displacement inside a window around them, everything else fixed; rounds repeat while
       violations remain, for at most `window_share` of the budget.
       - Reach: a violator on a fixed obstacle or over the outline must go at least to its
         nearest pose clear of them (`_escape_rects`); the window covers that pose and also
         frees the k parts nearest to it.
       - Rigid groups (`rigid`: the physics macros, a decap with its IC): a group whose
         members are all freed and do not overlap each other moves as one block at its
         current offsets, so the displacement minimum cannot pull a cap off its pin to save
         a millimetre elsewhere. When such a window fails, the same window is tried again
         with every part single before it grows.
       - Groups: violators that overlap each other share a window however far apart their
         centres are (`_groups`).
       - Ties (`phys`): a window solved to optimality compares up to TIE_SOLUTIONS of its
         equal-displacement optima by placement physics and keeps the lowest.
    2. Greedy: whatever is still illegal goes to the nearest free spot, largest first,
       evicting smaller parts when nothing is free nearby (`greedy`).
    3. Small boards only (<= GLOBAL_MAX parts): one CP-SAT model over every part."""
    dl = Deadline(time_s)
    win = dl.part(window_share * time_s)
    rep = dict(rounds=0, windows=0, solved=0, global_used=False, start_violators=0)
    kk = {}
    singles = set()          # group keys whose rigid window failed at the current k
    escape = {}
    group_of = {}
    for gi, mem in enumerate(rigid or ()):
        mem = [i for i in dict.fromkeys(mem) if P.parts[i].movable]
        if len(mem) >= 2:
            for i in mem:
                group_of.setdefault(i, mem)
    force = {i for i in force if P.parts[i].movable}
    for rnd in range(max_rounds):
        viol = grid_violations(st)
        if rnd == 0:
            rep["start_violators"] = len(viol)
            for i in force:
                viol.setdefault(i, []).append(("kicad", None))
        if not viol or win.passed():
            break
        rep["rounds"] = rnd + 1
        bad = set(viol)
        for gr in _groups(st, bad, radius_mm=4.0, viol=viol):
            win_left = win.left()
            if win_left < 0:
                break
            key = tuple(gr)
            kw = min(kk.get(key, k), MAX_WINDOW)
            cx = np.mean([st.center(b)[0] for b in gr])
            cy = np.mean([st.center(b)[1] for b in gr])
            near = sorted(P.mov, key=lambda c: abs(st.center(c)[0] - cx) + abs(st.center(c)[1] - cy))
            # reach: violators held by fixed geometry, and the parts around where they must go
            reach, near_t = [], []
            for b in gr:
                if not any(r[0] in ("obstacle", "outline") for r in viol.get(b, ())):
                    continue
                if (b, int(st.X[b]), int(st.Y[b]), int(st.K[b])) not in escape:
                    escape[(b, int(st.X[b]), int(st.Y[b]), int(st.K[b]))] = _escape_rects(P, st, b)
                er = escape[(b, int(st.X[b]), int(st.Y[b]), int(st.K[b]))]
                if er:
                    reach += er
                    tx = (min(r[0] for r in er) + max(r[1] for r in er)) / 2 * P.g + P.ox
                    ty = (min(r[2] for r in er) + max(r[3] for r in er)) / 2 * P.g + P.oy
                    near_t += sorted(P.mov, key=lambda c: abs(st.center(c)[0] - tx) + abs(st.center(c)[1] - ty))[:kw]
            cap_n = max(MAX_WINDOW, len(gr[:MAX_WINDOW]))
            budget = min(max(1.0, 0.15 * time_s), win_left)
            if budget <= 0.2:
                break
            free = list(dict.fromkeys(gr[:MAX_WINDOW] + near_t + near[:kw]))[:cap_n]
            blocks = []
            if key not in singles and group_of:
                fs = set(free)
                seen = set()
                for i in list(free):
                    mem = group_of.get(i)
                    if mem is None or id(mem) in seen:
                        continue
                    seen.add(id(mem))
                    # a group with a member in the window comes whole, when it fits
                    if not fs.issuperset(mem) and len(fs | set(mem)) <= cap_n:
                        fs |= set(mem)
                        free += [j for j in mem if j not in free]
                    if fs.issuperset(mem) and _rigid_ok(P, st, mem):
                        blocks.append(list(mem))
            margin = int(math.ceil((2.0 + 0.5 * (kw // k)) / P.g))
            sol, model = _window_solve(P, st, free, margin, budget, workers, seed + rnd, blocks=blocks, reach=reach,
                                       phys=phys)
            rep["windows"] += 1
            if sol is not None:
                rep["solved"] += 1
                if blocks:
                    rep["rigid_solved"] = rep.get("rigid_solved", 0) + 1
                if getattr(model, "tie_gain", 0) > 0:
                    rep["tie_gain"] = round(rep.get("tie_gain", 0.0) + model.tie_gain, 5)
                for i, (X, Y, v) in zip(free, sol):
                    st.X[i], st.Y[i], st.K[i] = X, Y, v
                singles.discard(key)
            elif blocks:
                singles.add(key)            # the same window again, every part single
            else:
                singles.discard(key)
                kk[key] = int(kw * 1.6) + 1
            if log:
                log(f"legalize window {gr[:4]} free={len(free)} blocks={len(blocks)} reach={bool(reach)} "
                    f"status={model.status} {model.wall:.2f}s")
    viol = grid_violations(st)
    if viol:
        rep["greedy"] = greedy(P, st, list(viol), log=log, time_s=max(1.0, dl.left()))
        viol = grid_violations(st)
    if viol and dl.left() > 0 and len(P.mov) <= GLOBAL_MAX:
        rep["global_used"] = True
        items = [cpsat.single(P, i, int(st.X[i]), int(st.Y[i]), int(st.K[i])) for i in P.mov]
        obstacles = [(ob.side, ob.g) for ob in P.obstacles]
        model = cpsat.Model(P, items, obstacles, w_disp=1.0, w_rot=1.0)
        sol = model.solve(max(1.0, dl.left()), workers=workers, seed=seed)
        rep["global_status"] = model.status
        if sol is not None:
            for it, i, (X, Y, v) in zip(items, P.mov, sol):
                st.X[i], st.Y[i], st.K[i] = X, Y, it.variants[v][i][2]
        viol = grid_violations(st)
    rep["end_violators"] = len(viol)
    rep["violations"] = {P.parts[i].ref: [str(r) for r in rs[:3]] for i, rs in list(viol.items())[:20]}
    rep["seconds"] = round(dl.elapsed(), 2)
    return rep


# ----------------------------------------------------------------------------- greedy fallback
def _occupancy(P, st, skip, pad):
    """Per-side cell occupancy counts of obstacles and of movable parts not in `skip`, on the
    grid padded by `pad` cells on every side (courtyards may overhang the board)."""
    occ = [np.zeros((P.ncx + 2 * pad, P.ncy + 2 * pad), dtype=np.int32) for _ in (0, 1)]
    for ob in P.obstacles:
        _mark(occ[ob.side], ob.g, pad, 1)
    n = len(P.obstacles)
    for i in P.mov:
        if i in skip:
            continue
        for side, r, _ in st.grid_rects(i):
            _mark(occ[side], r, pad, 1)
            n += 1
    charge("legal_rect", n)
    return occ


def _mark(a, r, pad, v):
    i0, i1, j0, j1 = r
    i0, i1 = max(0, i0 + pad), min(a.shape[0], i1 + pad)
    j0, j1 = max(0, j0 + pad), min(a.shape[1], j1 + pad)
    if i1 > i0 and j1 > j0:
        a[i0:i1, j0:j1] += v


def _free_origins(occ, rect, pad, xa, xb, ya, yb):
    """Bool map over origins X in [xa, xb], Y in [ya, yb]: rect (relative to the origin) hits
    no occupied cell. Cells beyond the padded grid count as free (nothing is placed there)."""
    a, b, c, d = rect
    nx, ny = xb - xa + 1, yb - ya + 1
    if b <= a or d <= c:
        return np.ones((nx, ny), dtype=bool)
    # region of the padded array the rect can reach from the window, clipped
    r0, r1 = xa + a + pad, xb + b + pad
    s0, s1 = ya + c + pad, yb + d + pad
    q0, q1 = max(0, r0), min(occ.shape[0], r1)
    t0, t1 = max(0, s0), min(occ.shape[1], s1)
    reg = np.zeros((r1 - r0, s1 - s0), dtype=np.int64)
    if q1 > q0 and t1 > t0:
        reg[q0 - r0:q1 - r0, t0 - s0:t1 - s0] = occ[q0:q1, t0:t1]
    L = np.zeros((reg.shape[0] + 1, reg.shape[1] + 1), dtype=np.int64)
    L[1:, 1:] = reg.cumsum(0).cumsum(1)
    w, h = b - a, d - c
    cnt = L[w:w + nx, h:h + ny] - L[0:nx, h:h + ny] - L[w:w + nx, 0:ny] + L[0:nx, 0:ny]
    return cnt == 0


def _inside_origins(P, rect, xa, xb, ya, yb):
    """Bool map over origins: the board rect lies inside the outline (and the grid)."""
    a, b, c, d = rect
    nx, ny = xb - xa + 1, yb - ya + 1
    ok = np.zeros((nx, ny), dtype=bool)
    # origins keeping the rect on the grid
    lo_x, hi_x = max(xa, -a), min(xb, P.ncx - b)
    lo_y, hi_y = max(ya, -c), min(yb, P.ncy - d)
    if hi_x < lo_x or hi_y < lo_y:
        return ok
    S = P.sat_out
    X0, X1 = lo_x + a, hi_x + a
    Y0, Y1 = lo_y + c, hi_y + c
    w, h = b - a, d - c
    cnt = (S[X0 + w:X1 + w + 1, Y0 + h:Y1 + h + 1] - S[X0:X1 + 1, Y0 + h:Y1 + h + 1]
           - S[X0 + w:X1 + w + 1, Y0:Y1 + 1] + S[X0:X1 + 1, Y0:Y1 + 1])
    ok[lo_x - xa:hi_x - xa + 1, lo_y - ya:hi_y - ya + 1] = cnt == 0
    return ok


def _evict_push(r, X, Y, si, ev):
    """Per origin (arrays X, Y): grid cells the evictable part with rectangles ev [(side,
    (i0, i1, j0, j1))] must travel to clear part rotation r at that origin (own pieces on
    side si, opp rectangles on the other): the shortest straight push, right, left, up or
    down, clearing every overlap on its side; 0 where they do not overlap. A lower bound on
    its displacement. Reference of _fastlegal.evict_push."""
    mine = [(si, o) for o in (r.g_own_rects or (r.g_own,))] + [(1 - si, o) for o in r.g_opp]
    need = np.zeros((4,) + X.shape, dtype=np.int64)
    hit = np.zeros(X.shape, dtype=bool)
    for side, (e0, e1, e2, e3) in ev:
        for s2, (a, b, c, d) in mine:
            if s2 != side:
                continue
            ov = (X + b > e0) & (e1 > X + a) & (Y + d > e2) & (e3 > Y + c)
            if not ov.any():
                continue
            hit |= ov
            for q, v in enumerate((X + b - e0, e1 - X - a, Y + d - e2, e3 - Y - c)):
                need[q] = np.where(ov, np.maximum(need[q], v), need[q])
    return np.where(hit, need.min(axis=0), 0)


def _nearest_spot(P, p, X0, Y0, K0, occ, pad, w_rot, span, evict=None):
    """(cost, X, Y, k) of the nearest origin where part p's rectangles are free in `occ` and
    its board rectangles inside the outline, or None. With `evict` (the rectangles of each
    part that may be evicted, [[(side, rect)]]) the cost adds, per such part the spot
    covers, the push that clears it (_evict_push): the displacement of all it moves."""
    si = 0 if p.s > 0 else 1
    size = max(max(r.g_own[1] - r.g_own[0], r.g_own[3] - r.g_own[2]) for r in p.rots)
    R = max(20, 2 * size)
    best = None
    from ._fastlegal import rotations_for_fit
    ks = rotations_for_fit(p, K0)
    while True:
        xa, xb, ya, yb = X0 - R, X0 + R, Y0 - R, Y0 + R
        passes = 0                          # window-sized array passes (the counted work)
        for k in ks:
            r = p.rots[k]
            ok = np.ones((xb - xa + 1, yb - ya + 1), dtype=bool)
            for brd in (r.g_boards or (r.g_board,)):
                ok &= _inside_origins(P, brd, xa, xb, ya, yb)
                passes += 1
                if not ok.any():
                    break
            if not ok.any():
                continue
            for o in (r.g_own_rects or (r.g_own,)):
                ok &= _free_origins(occ[si], o, pad, xa, xb, ya, yb)
                passes += 1
            for o in r.g_opp:
                if not ok.any():
                    break
                ok &= _free_origins(occ[1 - si], o, pad, xa, xb, ya, yb)
                passes += 1
            if not ok.any():
                continue
            xs, ys = np.nonzero(ok)
            cost = (np.abs(xs + xa - X0) + np.abs(ys + ya - Y0) + (w_rot if k != K0 else 0.0)).astype(float)
            passes += 1
            if evict:
                Xs, Ys = xs + xa, ys + ya
                for ev in evict:
                    cost += _evict_push(r, Xs, Ys, si, ev)
                charge("legal_cells", len(evict) * len(xs))     # numpy element passes
            j = int(np.argmin(cost))
            if best is None or cost[j] < best[0]:
                best = (float(cost[j]), int(xs[j] + xa), int(ys[j] + ya), k)
        charge("legal_cells", passes * (xb - xa + 1) * (yb - ya + 1))
        # a spot within R of the origin can still lose to one just outside when the best
        # cost exceeds R (L1 vs the square window): widen once more in that case
        if (best is not None and best[0] <= R) or R >= span:
            return best
        R = min(span, 2 * R)


def _greedy_fast(P, st, parts, log, w_rot, ripup, max_ripups, dl, time_s=None):
    """greedy() on the compiled kernels (summed-area tables updated in place)."""
    from . import _fastlegal as FL
    from .problem import sat
    ext = 1
    for i in P.mov:
        for r in P.parts[i].rots:
            for (a, b, c, d) in (r.g_own,) + tuple(r.g_opp):
                ext = max(ext, -a, b, -c, d)
    pad = ext + 1
    skip = set(parts)
    occ = _occupancy(P, st, skip, pad)
    S = [sat(occ[0]), sat(occ[1])]
    charge("legal_cells", 2 * occ[0].size)
    SO = P.sat_out
    max_d = P.ncx + P.ncy + 4 * pad
    arrs = {}

    def arrays(i):
        key = (i, int(st.K[i]))
        if key not in arrs:
            ks = FL.rotations_for_fit(P.parts[i], int(st.K[i]))
            arrs[key] = (ks,) + FL.part_arrays(P.parts[i], ks)
        return arrs[key]

    def add(i, v):
        n = 0
        for side, (a, b, c, d), _ in st.grid_rects(i):
            n += FL.sat_add_rect(S[side], a + pad, b + pad, c + pad, d + pad, v)
        charge("legal_sat_cells", n)

    def local(i):
        # the ring walk is cheap only nearby (its cost grows with the square of the reach);
        # farther spots come from the global search
        r = P.parts[i].rots[0].g_own
        return int(min(150, max(60, 4 * max(r[1] - r[0], r[3] - r[2]))))

    def spot(i, reach):
        p = P.parts[i]
        if reach >= max_d:
            return _global_spot(i)
        ks, own, own_n, opp, opp_n, brd, brd_n = arrays(i)
        c, X, Y, k, n = FL.nearest_spot(S[0], S[1], SO, P.ncx, P.ncy, pad, 0 if p.s > 0 else 1, int(st.X[i]),
                                        int(st.Y[i]), ks.index(int(st.K[i])), float(w_rot), own, own_n, opp, opp_n,
                                        brd, brd_n, int(min(reach, max_d)))
        charge("legal_fit", n)
        return None if c < 0 else (c, X, Y, ks[k])

    def _global_spot(i):
        """Nearest free origin anywhere: every origin at once from the summed-area tables
        (numpy slices), so a far spot costs a few array passes instead of a ring walk."""
        p = P.parts[i]
        si = 0 if p.s > 0 else 1
        X0, Y0, K0 = int(st.X[i]), int(st.Y[i]), int(st.K[i])
        nx, ny = P.ncx, P.ncy
        xs = np.arange(nx)[:, None]
        ys = np.arange(ny)[None, :]
        dist = np.abs(xs - X0) + np.abs(ys - Y0)
        passes = 1                          # board-sized array passes (the counted work)
        best = None
        for k in FL.rotations_for_fit(p, K0):
            r = p.rots[k]
            ok = np.ones((nx, ny), dtype=bool)
            for brd in (r.g_boards or (r.g_board,)):
                ok &= _inside_origins(P, brd, 0, nx - 1, 0, ny - 1)
                passes += 1
            if not ok.any():
                continue
            for side, rect in [(si, o) for o in (r.g_own_rects or (r.g_own,))] + [(1 - si, o) for o in r.g_opp]:
                a, b, c, d = rect
                T = S[side]
                cnt = (T[b + pad:b + pad + nx, d + pad:d + pad + ny] - T[a + pad:a + pad + nx, d + pad:d + pad + ny]
                       - T[b + pad:b + pad + nx, c + pad:c + pad + ny] + T[a + pad:a + pad + nx, c + pad:c + pad + ny])
                ok &= cnt == 0
                passes += 1
                if not ok.any():
                    break
            if not ok.any():
                continue
            cost = np.where(ok, dist + (w_rot if k != K0 else 0.0), np.inf)
            passes += 1
            j = int(np.argmin(cost))
            c = float(cost.flat[j])
            if best is None or c < best[0]:
                best = (c, j // ny, j % ny, k)
        charge("legal_cells", passes * nx * ny)
        return best
    start = {i: (int(st.X[i]), int(st.Y[i])) for i in parts}
    placed_set, queue = set(), []
    # first pass: a free spot near where the part wants to be
    out_of_time = False
    for i in parts:
        if time_s is not None and dl.passed():
            out_of_time = True
            queue.append(i)
            continue
        best = spot(i, local(i))
        if best is None:
            queue.append(i)
            continue
        _, st.X[i], st.Y[i], st.K[i] = best
        add(i, 1)
        placed_set.add(i)
    ripups = 0
    max_ripups = max_ripups if max_ripups is not None else 4 * len(queue) + 20
    unplaced = []

    def _ripup_at(i, reach):
        """Spot within reach that moves least in all, never onto an obstacle or a part at least
        as big: the mover's displacement plus, per smaller part it covers (evicted), the push
        that clears it (_evict_push). (cost, X, Y, k, 'ripup') or None."""
        p = P.parts[i]
        hard = [np.zeros_like(occ[0]) for _ in (0, 1)]
        soft = [np.zeros_like(occ[0]) for _ in (0, 1)]
        for ob in P.obstacles:
            _mark(hard[ob.side], ob.g, pad, 1)
        n = len(P.obstacles)
        ev = []
        for j in P.mov:
            if j == i or (j in skip and j not in placed_set):
                continue
            small = P.parts[j].area < p.area
            tgt = soft if small else hard
            rs = st.grid_rects(j)
            for side, r, _ in rs:
                _mark(tgt[side], r, pad, 1)
                n += 1
            if small:
                ev.append([(side, r) for side, r, _ in rs])
        charge("legal_rect", n)
        H = [sat(hard[0]), sat(hard[1])]
        C = [sat(soft[0]), sat(soft[1])]
        charge("legal_cells", 4 * hard[0].size)
        ks, own, own_n, opp, opp_n, brd, brd_n = arrays(i)
        E, E0, EB = FL.evict_arrays(ev)
        c, X, Y, k, n, npair = FL.ripup_spot(H[0], H[1], C[0], C[1], SO, P.ncx, P.ncy, pad, 0 if p.s > 0 else 1,
                                             int(st.X[i]), int(st.Y[i]), ks.index(int(st.K[i])), float(w_rot), own,
                                             own_n, opp, opp_n, brd, brd_n, E, E0, EB, int(min(reach, max_d)))
        charge("legal_fit", n)
        charge("legal_pair", npair)
        return None if c < 0 else (c, X, Y, ks[k], "ripup")
    while queue:
        if out_of_time or (time_s is not None and dl.passed()):
            out_of_time = True
            break
        i = queue.pop(0)
        p = P.parts[i]
        # nearby first (the space may have changed), then anywhere on the board (the global
        # search is cheap), then evict smaller parts nearby, then anywhere
        for reach, evict_ok in ((local(i), False), (max_d, False), (local(i), True), (max_d, True)):
            if evict_ok and not (ripup and ripups < max_ripups):
                continue
            if not evict_ok:
                best = spot(i, reach)
                if best is not None:
                    break
                continue
            best = _ripup_at(i, reach)
            if best is not None:
                break
        else:
            unplaced.append(i)
            continue
        if not best[-1:] == ("ripup",):
            _, st.X[i], st.Y[i], st.K[i] = best
            add(i, 1)
            placed_set.add(i)
            continue
        ripups += 1
        st.X[i], st.Y[i], st.K[i] = best[1], best[2], best[3]
        mine = st.grid_rects(i)
        evict = []
        for j in list(placed_set) + [j for j in P.mov if j not in skip]:
            if j == i or P.parts[j].area >= p.area:
                continue
            if any(sa == sb and ra[1] > rb[0] and rb[1] > ra[0] and ra[3] > rb[2] and rb[3] > ra[2]
                   for sa, ra, _ in mine for sb, rb, _ in st.grid_rects(j)):
                evict.append(j)
        for j in evict:
            if j in placed_set or j not in skip:
                add(j, -1)
            placed_set.discard(j)
            skip.add(j)
            start.setdefault(j, (int(st.X[j]), int(st.Y[j])))
        queue.extend(sorted(evict, key=lambda j: -P.parts[j].area))
        add(i, 1)
        placed_set.add(i)
    unplaced += queue
    moved = sum(math.hypot((st.X[i] - x) * P.g, (st.Y[i] - y) * P.g) for i, (x, y) in start.items())
    rep = dict(placed=len(placed_set), unplaced=[P.parts[i].ref for i in unplaced], moved_mm=round(moved, 2),
               ripups=ripups, seconds=round(dl.elapsed(), 2), compiled=True, out_of_time=out_of_time)
    if log:
        log(f"greedy legalization: {len(placed_set)} placed, {len(unplaced)} without a spot, {ripups} rip-ups, "
            f"moved {moved:.1f} mm ({rep['seconds']}s)")
    return rep


def greedy(P, st, parts, log=None, w_rot=None, ripup=True, max_ripups=None, compiled=None, time_s=None):
    """Put `parts` back one by one, largest first, at the nearest grid origin (L1, plus a
    charge for turning) where none of their rectangles meets an obstacle or another part on
    its side and their board rectangles lie inside the outline; every other movable part
    stays where it is. The search window around the current origin doubles until a spot is
    found or it covers the board. A part that finds no spot (a full board, space cut into
    pieces) takes the spot that moves least in all (its own displacement plus, per smaller
    part it covers, the push that clears that part; lengths, so the same at any grid pitch),
    and those parts are evicted and placed again (rip-up; evictions only go to smaller
    parts, so it ends).
    Always ends legal for the parts it places; returns {placed, unplaced: [refs], moved_mm,
    ripups}."""
    dl = Deadline(math.inf if time_s is None else time_s)
    parts = sorted({i for i in parts if P.parts[i].movable}, key=lambda i: -P.parts[i].area)
    if not parts:
        return dict(placed=0, unplaced=[], moved_mm=0.0, ripups=0, seconds=0.0)
    if compiled is None:
        from ._fastlegal import HAVE_NUMBA
        compiled = HAVE_NUMBA and not os.environ.get("HASLAM_NO_NUMBA")
    if compiled:
        return _greedy_fast(P, st, parts, log, (2.0 / P.g) if w_rot is None else w_rot, ripup, max_ripups, dl,
                            time_s=time_s)
    ext = 1
    for i in P.mov:
        for r in P.parts[i].rots:
            for (a, b, c, d) in (r.g_own,) + tuple(r.g_opp):
                ext = max(ext, -a, b, -c, d)
    pad = ext + 1
    skip = set(parts)
    occ = _occupancy(P, st, skip, pad)
    w_rot = (2.0 / P.g) if w_rot is None else w_rot          # turning costs like moving 2 mm
    span = max(P.ncx, P.ncy) + 2 * ext
    start = {i: (int(st.X[i]), int(st.Y[i])) for i in parts}
    placed_set, unplaced = set(), []
    for i in parts:
        p = P.parts[i]
        best = _nearest_spot(P, p, int(st.X[i]), int(st.Y[i]), int(st.K[i]), occ, pad, w_rot, span)
        if best is None:
            unplaced.append(i)
            continue
        _, X, Y, k = best
        st.X[i], st.Y[i], st.K[i] = X, Y, k
        for side, r, _ in st.grid_rects(i):
            _mark(occ[side], r, pad, 1)
        placed_set.add(i)
    ripups = 0
    max_ripups = max_ripups if max_ripups is not None else 4 * len(unplaced) + 20
    queue = list(unplaced)
    unplaced = []
    while queue and ripups < max_ripups and ripup:
        i = queue.pop(0)
        p = P.parts[i]
        best = _nearest_spot(P, p, int(st.X[i]), int(st.Y[i]), int(st.K[i]), occ, pad, w_rot, span)
        if best is None:
            # rip-up: obstacles and parts at least as big are hard, smaller placed parts may go
            hard = [np.zeros_like(occ[0]) for _ in (0, 1)]
            for ob in P.obstacles:
                _mark(hard[ob.side], ob.g, pad, 1)
            n = len(P.obstacles)
            ev = []
            for j in P.mov:
                if j == i or (j in skip and j not in placed_set):
                    continue
                rs = st.grid_rects(j)
                if P.parts[j].area < p.area:
                    ev.append([(side, r) for side, r, _ in rs])
                    continue
                for side, r, _ in rs:
                    _mark(hard[side], r, pad, 1)
                    n += 1
            charge("legal_rect", n)
            best = _nearest_spot(P, p, int(st.X[i]), int(st.Y[i]), int(st.K[i]), hard, pad, w_rot, span, evict=ev)
            if best is None:
                unplaced.append(i)
                continue
            ripups += 1
            _, X, Y, k = best
            st.X[i], st.Y[i], st.K[i] = X, Y, k
            mine = st.grid_rects(i)
            evict = []
            for j in list(placed_set) + [j for j in P.mov if j not in skip]:
                if j == i or P.parts[j].area >= p.area:
                    continue
                if any(sa == sb and ra[1] > rb[0] and rb[1] > ra[0] and ra[3] > rb[2] and rb[3] > ra[2]
                       for sa, ra, _ in mine for sb, rb, _ in st.grid_rects(j)):
                    evict.append(j)
            for j in evict:
                for side, r, _ in st.grid_rects(j):
                    _mark(occ[side], r, pad, -1)
                placed_set.discard(j)
                skip.add(j)
                start.setdefault(j, (int(st.X[j]), int(st.Y[j])))
            queue.extend(sorted(evict, key=lambda j: -P.parts[j].area))
            for side, r, _ in mine:
                _mark(occ[side], r, pad, 1)
            placed_set.add(i)
            continue
        _, X, Y, k = best
        st.X[i], st.Y[i], st.K[i] = X, Y, k
        for side, r, _ in st.grid_rects(i):
            _mark(occ[side], r, pad, 1)
        placed_set.add(i)
    unplaced += queue
    moved = sum(math.hypot((st.X[i] - x) * P.g, (st.Y[i] - y) * P.g) for i, (x, y) in start.items())
    rep = dict(placed=len(placed_set), unplaced=[P.parts[i].ref for i in unplaced], moved_mm=round(moved, 2),
               ripups=ripups, seconds=round(dl.elapsed(), 2))
    if log:
        log(f"greedy legalization: {len(placed_set)} placed, {len(unplaced)} without a spot, {ripups} rip-ups, "
            f"moved {moved:.1f} mm ({rep['seconds']}s)")
    return rep


# ----------------------------------------------------------------------------- KiCad feedback
from haslam.drc_items import PLACER_TYPES, item_ref  # noqa: E402 - the illegal types plus solder mask bridges


def kicad_violations(drc):
    """Violations from a kicad-cli DRC report (path, JSON text or dict): [{type, severity,
    description, items: [{description, pos: {x, y}}]}], placement-relevant types only."""
    import json
    from pathlib import Path
    if isinstance(drc, (str, Path)) and Path(str(drc)).exists():
        drc = json.loads(Path(drc).read_text())
    elif isinstance(drc, str):
        drc = json.loads(drc)
    out = []
    for v in (drc or {}).get("violations", []):
        if v.get("type") in PLACER_TYPES and v.get("severity", "error") == "error":
            # the description names what the items alone do not: a keepout's owner ("Items not
            # allowed (keepout area of REG1)"), which exact._intrinsic reads
            out.append(dict(type=v.get("type"), severity=v.get("severity"), description=v.get("description", ""),
                            items=v.get("items", [])))
    return out


def violation_parts(P, st, v):
    """Part indices a KiCad violation names: by reference in an item's text ('Pad 2 [GND] of
    C3 on F.Cu', 'Footprint U1'); a reference that is unknown or repeats, by the part with a
    pad nearest the item's position. Board-level items (no owner named) name no part."""
    by_ref = {}
    for p in P.parts:
        by_ref.setdefault(p.ref, []).append(p.i)
    out = set()
    for it in v.get("items", []):
        d = it.get("description", "")
        ref = item_ref(d)
        if ref is None:
            # a board-level item ('Segment on Edge.Cuts', "PCB text '...' on B.Cu", 'Rule Area',
            # 'Track', 'Via', 'Zone'): no part; by position it would name whichever part has a
            # pad nearest the item's anchor (paw3222: an edge error became a pair separation)
            continue
        cands = by_ref.get(ref, [])
        pos = it.get("pos") or {}
        if len(cands) == 1:
            out.add(cands[0])
            continue
        if "x" in pos and "y" in pos:
            pool = cands or [p.i for p in P.parts]
            best = min(pool, key=lambda i: float(np.min(np.hypot(*(st.pins_xy(i) - [pos["x"], pos["y"]]).T)))
                       if len(P.parts[i].fp.pads) else math.hypot(st.xy(i)[0] - pos["x"], st.xy(i)[1] - pos["y"]))
            out.add(best)
    return out


# ----------------------------------------------------------------------------- exact shapes
ARC_ERR = 0.001   # mm: most an arc of a pad or hole may sit inside its polygon (the polygon is inscribed)


def arc_segs(r, err=ARC_ERR):
    """Shapely quad_segs (segments per quarter circle) that keep a radius-r arc within `err` of its
    inscribed polygon. A fixed 8 put a 3 mm hole 0.007 mm inside its polygon, so with a 1.7 mm pad
    two shapes measured 0.009 mm further apart than KiCad, which measures arcs exactly:
    melexinvn's hole_clearance 0.2402 mm (rule 0.25) read 0.2491 and passed."""
    if r <= err:
        return 1
    return max(8, min(64, math.ceil(math.pi / (4.0 * math.acos(1.0 - err / r)))))


def pad_shape(p, layer=None):
    """A pad's copper as a library-frame polygon, as KiCad shapes it: circles, ovals, rounded
    rectangles from the pad's fields; trapezoids, chamfered rectangles and custom pads (anchor
    and primitives) from the outline the loader built (Pad.outline). With `layer`, a padstack's
    override for that copper layer (Pad.layer_shapes) when it has one."""
    ov = (getattr(p, "layer_shapes", None) or {}).get(layer) if layer else None
    shape = ov["shape"] if ov else p.shape
    w, h = ov["size"] if ov else p.size
    ox, oy = (ov.get("offset") if ov and ov.get("offset") is not None else p.offset) or (0.0, 0.0)
    rratio = ov["rratio"] if ov else p.rratio
    outline = ov.get("outline") if ov else getattr(p, "outline", None)
    c, s = transform.cos_sin(p.lrot)

    def lib(u, v):
        return (p.lx + u * c + v * s, p.ly - u * s + v * c)
    if outline is not None and not outline.is_empty:
        from shapely import affinity
        geom = affinity.affine_transform(affinity.translate(outline, ox, oy), [c, s, -s, c, p.lx, p.ly])
    elif shape == "circle":
        cx, cy = lib(ox, oy)
        geom = Point(cx, cy).buffer(max(w, h) / 2, quad_segs=arc_segs(max(w, h) / 2))
    elif shape == "oval" and abs(w - h) > 1e-9:
        r = min(w, h) / 2
        if w > h:
            a, b = lib(ox - (w / 2 - r), oy), lib(ox + (w / 2 - r), oy)
        else:
            a, b = lib(ox, oy - (h / 2 - r)), lib(ox, oy + (h / 2 - r))
        geom = LineString([a, b]).buffer(r, quad_segs=arc_segs(r))
    elif shape == "oval":
        cx, cy = lib(ox, oy)
        geom = Point(cx, cy).buffer(w / 2, quad_segs=arc_segs(w / 2))
    elif shape == "roundrect" and rratio > 0:
        # KiCad's rounded rectangle: corner radius rratio x the shorter side (as rectangles
        # the corners sat outside the copper; pingdevkit's 0402s read 0.191 mm apart, not 0.2)
        r = min(0.5, float(rratio)) * min(w, h)
        core = Polygon([(ox - w / 2 + r, oy - h / 2 + r), (ox + w / 2 - r, oy - h / 2 + r),
                        (ox + w / 2 - r, oy + h / 2 - r), (ox - w / 2 + r, oy + h / 2 - r)])
        loc = core.buffer(r, quad_segs=arc_segs(r)) if r > 0 else core
        geom = Polygon([lib(u, v) for u, v in loc.exterior.coords])
    else:
        geom = Polygon([lib(ox - w / 2, oy - h / 2), lib(ox + w / 2, oy - h / 2), lib(ox + w / 2, oy + h / 2),
                        lib(ox - w / 2, oy + h / 2)])
    if p.drill:
        geom = geom.union(hole_shape(p))
    return geom


def hole_shape(p):
    if not p.drill:
        return None
    c, s = transform.cos_sin(p.lrot)
    if p.slot:
        w, h = p.slot
        r = min(w, h) / 2
        if abs(w - h) > 1e-9:
            if w > h:
                u0, u1, v0, v1 = -(w / 2 - r), (w / 2 - r), 0.0, 0.0
            else:
                u0, u1, v0, v1 = 0.0, 0.0, -(h / 2 - r), (h / 2 - r)
            a = (p.lx + u0 * c + v0 * s, p.ly - u0 * s + v0 * c)
            b = (p.lx + u1 * c + v1 * s, p.ly - u1 * s + v1 * c)
            return LineString([a, b]).buffer(r, quad_segs=arc_segs(r))
    return Point(p.lx, p.ly).buffer(p.drill / 2, quad_segs=arc_segs(p.drill / 2))


def _copper_sides(p, part_side):
    """Copper sides (0 front, 1 back) a pad occupies."""
    if is_drilled(p):
        return (0, 1)
    lays = p.layers or []
    sides = set()
    for ly in lays:
        if ly.startswith("F.Cu"):
            sides.add(0)
        elif ly.startswith("B.Cu"):
            sides.add(1)
        elif ly.endswith(".Cu"):
            sides.update((0, 1))
    if not sides:
        sides.add(0 if part_side == "F" else 1)
    return tuple(sorted(sides))


def exact_check(P, st, parts=None, max_items=60):
    """Exact legality of the placement (movable parts against everything). Returns a list of
    violations {type, refs, detail} (haslam.place.exact.ExactModel holds the rules)."""
    from .exact import ExactModel
    return ExactModel(P, st).check(parts=parts, max_items=max_items)


def _net_clr(P, net, cache):
    if net in cache:
        return cache[net]
    v = P.clr_min
    n = P.board.nets.get(net) if net else None
    if n is not None:
        v = P.netclass_clr.get(n.netclass, P.netclass_clr.get(n.netclass.split(",")[0], P.clr_min))
    v = max(v, P.board.rules.clearance if P.board.rules else 0.0)
    cache[net] = v
    return v
