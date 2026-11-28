# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Each switching cell's hot loop, solved again in a window around it at a finer pitch: the per-cell primaries
L_loop, R_loop at f_sw and its odd harmonics, and the switch node's overshoot peak.

The board solve (haslam.excite.evaluate) runs at 0.25 mm, where hot loops read 5-12 % high and tracks narrower than
three cells are under-resolved (docs/research/physics/field-solver-accuracy.md, E7). A cell's loop current
closes within a few millimetres of its parts, so its window is solved at CELL_PITCH (chosen by the convergence
test in tools/research/physics/hl_cell_convergence.py; docs/topics/physics/hot-loop-evaluation.md section 3).

The window is the bounding box of the parts that carry at least SHARE of the cell's peak pad current in the
copper-free circuit solve (input caps, switches, the pads of the overshoot observer), less those with no pad within
FAR_MM of the cell's own loop parts the brief names (window_pads: a rail's far decouplers take a share in the
copper-free circuit but little through the copper), grown by
max(MARGIN_MM, MARGIN_H x h), h the outer layers' depth to their next layer, so the return current spreading in the
planes is mostly held (a loop at height h over its plane returns 1 - (2/pi) atan(x/h) of its current beyond x; on
2-layer boards the raw window reads up to +36 % at 3 mm: the truncation correction below removes it). It
depends only on the placement and the circuit, never on the copper: every layout of one placement is judged in the
same window at the same pitch. When the copper closes the loop only outside the window, the margin doubles until it
closes (reported); a loop open on the whole board is an open cell (haslam.excite.evaluate.open_cell_observations).

The window's truncation (copper beyond it that the return or a bulk cap still uses: up to +12 % on a 2-layer board
24 mm across) is measured at the board's pitch and removed: the cell's value is the fine window solve plus (board
solve minus the same window at the board's pitch), the two-grid correction (truncation and pitch errors add to first
order). Both terms are reported (window.L_raw_nH, window.trunc_L_nH; R likewise at f_sw, whose truncation term is
applied to the harmonics too).

Per frequency the quantities are those of the board solve, on the window's copper, for the cell's own pattern (its
current, re-split over the caps by the copper): L_loop = I^H L I at the edge band with the capacitors at their edge
model (ESR + ESL, haslam.excite.circuit.Circuit.edge_model), the copper's stored magnetic energy per A^2
(haslam.em.solve.stored_inductance), and R_loop(f) = sum R |I|^2, its dissipation, at f_sw, 3 f_sw and 5 f_sw (a
trapezoid's odd harmonics), with each copper layer's resistance corrected for skin and proximity crowding beyond the
nsub filaments (haslam.em.skin, one-sided crowding: a loop over its return plane). Neither is the layout's share
z = J_k^T v - J_k^T v_ideal at the overshoot observer k: z also holds the parts' energy as the copper moves current
among the caps, and with the caps' C a small ceramic below its self-resonance at f_e beside a big one above it is a
tank the copper tunes (haslam.excite.evaluate._edge_loops: murex's buck read -3.5 nH at 10 MHz on a connected layout).
z at f_sw stays the overshoot's fundamental term. The overshoot peak per corner is haslam.excite.harm.peak with the window's L_loop and
Z(f_sw): L di/dt with the switch's edge time plus the fundamental's share, the same model the board solve prices.
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

from . import harm as HA
from . import observe as O

CELL_PITCH = 0.0625          # mm: L_loop within 0.5 %, R_loop within 3 % of 0.03125 mm on 3 boards (0.125: up to 11 %)
SHARE = 0.05                 # a pad carrying this share of the cell's peak pad current sets the window
MARGIN_MM = 3.0              # mm around the pads
FAR_MM = 10.0                # mm: a part carrying SHARE whose pads are all this far from the cell's own parts does not
                             # set the window (window_pads; its feed's inductance, ~0.5-1 nH/mm, is several times the
                             # loop's): the truncation correction counts what it takes
MARGIN_H = 3.0               # x the outer layers' depth to their next layer, if larger (the return spreads over a few h)
HARMONICS = (1, 3, 5)        # R_loop at these multiples of f_sw
MAX_CELLS = 1.2e6            # raster budget of one window (cells x copper layers): the pitch doubles past it (5 min)
MAX_GROW = 4                 # margin doublings when the loop closes only outside the window
TRUNC_MAX = 0.5              # the window's truncation (board solve minus the window at the board's pitch) may be
                             # at most this share of the board's L_loop and R_loop: beyond it the window misses where
                             # the loop closes on the board, the two-grid correction is no longer small, and the margin
                             # doubles (nekoink's boost: window 21.7 nH against the board's 2.6, corrected to -0.17)
TRUNC_FLOOR = (0.1e-9, 0.5e-3)  # H, ohm: truncations below these never count as too large (near-zero loops)


def _pad_box(bm, tokens):
    xs, ys = [], []
    for t in tokens:
        for _, g, _ in bm.pads.get(t, []):
            x0, y0, x1, y1 = g.bounds
            xs += [x0, x1]
            ys += [y0, y1]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _own_window_default():
    """HASLAM_HOTLOOP_OWN_WINDOW=1 opts into the own-parts window (e360ef7); off by default until a corpus A/B shows it
    leaves L_loop unbiased: a smaller window truncates coupling to nearby planes and copper (review of e360ef7)."""
    return os.environ.get("HASLAM_HOTLOOP_OWN_WINDOW", "").strip().lower() in ("1", "true", "yes", "on")


def window_pads(bd, s, o, freqs, edge=None, own=None):
    """The pads that set a cell's window: every pad of a part through which SHARE of the peak pad current of the
    cell's own pattern or of its overshoot observer's passes (half its pads' summed |J|: a connector or module
    takes its share over many pins), at any of `freqs`, in the copper-free circuit (the same for every layout; at f == edge its edge model).

    own (default: HASLAM_HOTLOOP_OWN_WINDOW, off): of the other parts, only those with a pad within FAR_MM of the cell's own parts (bd.cell_refs: controller,
    switches, the loop's parts, its hot-side caps, inductor, snubbers; their pad centres' box) when the brief names
    them and any of them passes. The copper-free circuit splits a rail's current over every parallel capacitor alike,
    wherever it sits: 16 sensor decouplers of a boost's output rail took 6 % each and stretched its window over a
    50 x 78 mm board (bme280-array F39: 318 s of a 75 nA converter's evaluation). Through the copper a part FAR_MM
    away takes little of it (its feed's inductance alone is several times a loop's 1-2 nH), and the truncation
    correction (board solve minus the window at the board's pitch) adds back what it takes. Near parts stay whether
    the brief names them or not: a window on the brief's loop pads alone moved L_loop by up to 16 % and was reverted
    (docs/research/physics/hot-loop-evaluation-runs.md section 1). Far parts with an injection pad (the cell solve's
    Ja: ICs, connectors, modules, outside the copper model) stay too: the window solve cannot put their current
    anywhere else."""
    if own is None:
        own = _own_window_default()
    out = set()
    inj = set()          # pads where current enters the copper model in the cell's solve (Ja: ICs, connectors, the source)
    bde = _edge_bd(bd) if edge in freqs else bd
    for f in freqs:
        x = bde if f == edge else bd
        sol = x.circuit.solve(f, [s])[s.name]
        ja = sol.get("Ja") or {}
        top = max((abs(j) for j in ja.values()), default=0.0)
        inj |= {p for p, j in ja.items() if top and abs(j) > 1e-6 * top}
        for J in (sol["J"], O.pattern(x, o, f)):
            big = max((abs(j) for j in J.values()), default=0.0)
            part = {}
            for p, j in J.items():
                part.setdefault(p.rsplit(".", 1)[0], []).append((p, abs(j)))
            for pads in part.values():
                if big and sum(j for _, j in pads) / 2 >= SHARE * big:
                    out |= {p for p, j in pads if j > 0}
    refs = (getattr(bd, "cell_refs", None) or {}).get(s.meta.get("cell")) if own else None
    if not refs:
        return out
    xy = [bd.pad_xy[p] for p in out if p.rsplit(".", 1)[0] in refs and p in bd.pad_xy]
    if not xy:
        return out
    x0, y0 = min(x for x, _ in xy), min(y for _, y in xy)
    x1, y1 = max(x for x, _ in xy), max(y for _, y in xy)

    def near(p):
        if p not in bd.pad_xy:
            return True                  # no position known: kept, as before
        x, y = bd.pad_xy[p]
        return math.hypot(max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1)) <= FAR_MM
    by_part = {}
    for p in out:
        by_part.setdefault(p.rsplit(".", 1)[0], []).append(p)
    # a far part where the cell's current enters the copper model (an injection pad: IC, connector, module) stays: left
    # out, the window solve loses that current outright (dropped_injection; jin-neuron turtlepico's DRV8833 half
    # bridge, whose supply comes in 25 mm away: 51 % dropped, R_loop at 5 f_sw -31 %). Only lumped far parts (a rail's
    # decouplers, whose share the copper's feed inductance takes) are left to the truncation correction.
    return {p for ref, ps in by_part.items() if ref in refs or any(near(q) or q in inj for q in ps) for p in ps}


def _skin_R(net, f, nsub):
    """The network's branch resistances with each layer's filaments scaled by haslam.em.skin.correction at f."""
    from haslam.em.mesh import MM
    from haslam.em.skin import correction
    R = net.R.copy()
    for o in ("x", "y"):
        fl = net.fil[o]
        if not len(fl["a"]):
            continue
        lay = net.layer_of_sub[fl["s"]]
        k = np.array([correction(f, net.m.layers[l].t * MM, nsub) for l in range(len(net.m.layers))])
        R[net.off[o]:net.off[o] + len(fl["a"])] *= k[lay]
    return R


def _edge_bd(bd):
    """bd with its circuit at the edge model (Circuit.edge_model: capacitors at ESR + ESL)."""
    import copy
    out = copy.copy(bd)
    out.circuit = bd.circuit.edge_model()
    return out


def _solve_window(path, b, bd, s, o, win, pitch, nsub, fills, freqs, skin, log, edge=None, warm=None):
    """{f: z} (the layout's share at the overshoot observer) for the cell's pattern in window `win`, or
    (None, why) when the window's copper leaves the pattern open; the info's rcu and lcu: {f: the copper's
    dissipation (ohm) and stored-energy inductance (H) of the pattern}. At f == edge the circuit is at its edge model
    (capacitors at ESR + ESL, haslam.excite.evaluate._edge_loops): lcu[edge] is the window's L_loop. Also the mesh.
    warm: {f: position-keyed solution state} of an earlier solve of this window at this pitch (the same cell before
    its copper changed: haslam.route.hotloop.clear's before quote): the first band's COCG starts there instead of at
    zero; the result differs from a cold start only within the solver's tolerance (TOL). With warm given (even {}), info["states"] returns this solve's."""
    from haslam.em import solve as ES
    from haslam.em.kicad import BoardMesh
    from .circuit import lump_into
    bm = BoardMesh(path, win, pitch, nsub=nsub, b=b, fills=fills)
    bde = _edge_bd(bd) if edge in freqs else bd
    bdf = {f: bde if f == edge else bd for f in freqs}
    sols = {f: bdf[f].circuit.solve(f, [s])[s.name] for f in freqs}
    pats = {f: O.pattern(bdf[f], o, f, active=True) for f in freqs}
    pads = set()
    for f in freqs:
        pads |= {p for p, j in sols[f]["Ja"].items() if abs(j) > 1e-9} | {p for p, j in pats[f].items() if abs(j) > 1e-9}
    pads |= {p for e in bd.circuit.elems if e.pa and e.pb for p in (e.pa, e.pb)}
    for p in sorted(pads):
        try:
            bm.pad(p)
        except (KeyError, ValueError):
            pass

    def tpad(t):
        if t not in bm.m.terminals:
            raise KeyError(t)
        return t
    base = list(bm.m.lumped)
    nets = {}
    for c in {id(x.circuit): x.circuit for x in bdf.values()}.values():
        bm.m.lumped = list(base)
        lump_into(c, tpad, lambda a, c_, zf, nm: bm.m.part(a, c_, name=nm, zf=zf))
        n_ = ES.Network(bm.m)
        nets[id(c)] = [n_, None]          # its Operator (kernel tables) only once a solve needs it
    from .evaluate import _band_start
    out, dropped, prev, rcu, lcu, states = {}, 0.0, None, {}, {}, {}
    for f in freqs:                      # ascending: each starts from the last one's solution (_band_start)
        net, op = nets[id(bdf[f].circuit)]
        R0 = net.R
        Ja = sols[f]["Ja"]
        inj = {p: j for p, j in Ja.items() if p in bm.m.terminals and abs(j) > 1e-12}
        tot = sum(abs(j) for j in Ja.values()) or 1.0
        dropped = max(dropped, sum(abs(j) for p, j in Ja.items() if p not in bm.m.terminals) / tot)
        if skin:
            net.R = _skin_R(net, f, nsub)
        # the first band starts from the earlier solve; later ones from this solve's previous band (measured on the
        # fixture: 29 -> 25 iterations warm at f_fund, but 36 -> 39 at f_edge against the band start)
        st0 = (warm or {}).get(f) if prev is None else None
        try:
            # a pad the window left out carries less than SHARE of the peak (window_pads): its current may leak
            (v, info), = ES.potentials_many(bm.m, [inj], f, net=net, op=op, light=True, leak=SHARE,
                                            x0=[_band_start(prev, inj, f, net.n_br)],
                                            warm=[st0] if st0 is not None else None, keep_state=warm is not None,
                                            skip_open=True)
        finally:
            net.R = R0
        if info["unbalanced"]:
            return None, info, bm.m
        op = nets[id(bdf[f].circuit)][1] = info["op"]
        if warm is not None:
            states[f] = info.pop("state")
        prev = (f, inj, info.pop("x"))
        # the copper's own dissipation of the pattern (the R it was solved with): R_loop, never negative
        R_used = _skin_R(net, f, nsub) if skin else net.R
        nb_cu = net.off["l"]
        I = info.pop("I")
        rcu[f] = float(np.sum(R_used[:nb_cu] * np.abs(I[:nb_cu]) ** 2))
        # the copper's inductance of the pattern: its stored magnetic energy I^H L I, L_loop, never negative
        lcu[f] = ES.stored_inductance(net, op, I)
        Jk = pats[f]
        vid = O.ideal(bdf[f], sols[f])
        out[f] = O.bilinear(Jk, v) - O.bilinear(Jk, vid)
    info = dict(dropped=dropped, rcu=rcu, lcu=lcu)
    if warm is not None:
        info["states"] = states
    return out, info, bm.m


def _truncation_too_large(g, zc, Lc, f_fund):
    """True when the window at the board's pitch (zc, its L_loop Lc) differs from the board solve (g = (Le, Zf)) by
    more than TRUNC_MAX of the board's L_loop or R_loop: the window's copper then closes the loop elsewhere than the
    board's."""
    Rg, Rc = g[1].real, zc[f_fund].real
    return (abs(g[0] - Lc) > max(TRUNC_MAX * abs(g[0]), TRUNC_FLOOR[0])
            or abs(Rg - Rc) > max(TRUNC_MAX * abs(Rg), TRUNC_FLOOR[1]))


def _g_R(g):
    """The board solve's R_loop at f_sw (ohm): its copper dissipation (g[2]) when known, else the layout share Re Zf."""
    return g[2] if len(g) > 2 and g[2] is not None else max(g[1].real, 0.0)


def _corrected_L(g, L, Lc):
    """The window's L_loop L (H) at the edge band with its truncation (board solve minus the window at the board's
    pitch, Lc) removed: the two-grid value cell_rows reports."""
    return L + (g[0] - Lc if Lc is not None else 0.0)


def cell_rows(path, b, bd, bm, srcs, obs, cps, bands, board_window, n_cu, nsub=2, pitch=CELL_PITCH,
              global_pairs=None, global_pitch=None, open_cells=None, uncomputed=(), skin=True, log=print):
    """One row per switching cell: its primaries from the window solve (state "ok"), or state "open" (the loop is
    open on the whole board: priced at its caps by haslam.excite.evaluate) or "not_computed" (its pads are not in the
    board's copper model). bm: the board solve's BoardMesh (its pads' shapes and KiCad's zone fills). global_pairs:
    {source: (Le, Zf)} of the board solve, reported beside the window's."""
    from haslam.em import solve as ES
    from haslam.em.kicad import BoardMesh  # noqa: F401  (import cost before the timers)
    from .evaluate import coarsen_pitch
    open_cells = open_cells or {}
    global_pairs = global_pairs or {}
    gaps = list(getattr(b.stackup, "gaps", None) or [1.5])
    margin0 = max(MARGIN_MM, MARGIN_H * max(gaps[0], gaps[-1]))
    rows = []
    for s in srcs:
        if s.kind != "cell":
            continue
        o = next((x for x in obs if x.kind == "overshoot" and x.meta.get("source") == s.name), None)
        row = dict(cell=s.meta.get("cell"), source=s.name)
        g = global_pairs.get(s.name)
        if g is not None:
            row["global"] = dict(pitch=global_pitch, L_loop_nH=round(g[0] * 1e9, 4),
                                 R_loop_mohm=round(_g_R(g) * 1e3, 4))
        if s.name in open_cells:
            rows.append(dict(row, state="open", why=open_cells[s.name]))
            continue
        if o is None or s.name in uncomputed or g is None:
            rows.append(dict(row, state="not_computed",
                             why="pads outside the copper model" if s.name in uncomputed else "no overshoot observer"))
            continue
        t0 = time.time()
        f_fund, f_edge = bands[s.name]["fund"], bands[s.name]["edge"]
        fh = [n * f_fund for n in HARMONICS]
        freqs = sorted(set(fh) | {f_edge})
        box_ = _pad_box(bm, window_pads(bd, s, o, [f_fund, f_edge], edge=f_edge))
        if box_ is None:
            rows.append(dict(row, state="not_computed", why="no pad of the cell in the copper model"))
            continue
        res, margin, grown, Lw, Lc = None, margin0, 0, None, None
        keys0 = set(ES.Operator._cache)
        while True:
            win = (max(board_window[0], box_[0] - margin), max(board_window[1], box_[1] - margin),
                   min(board_window[2], box_[2] + margin), min(board_window[3], box_[3] + margin))
            pc, _ = coarsen_pitch(win, pitch, n_cu, MAX_CELLS)
            if global_pitch and pc >= global_pitch:
                break                        # no finer than the board solve: nothing to refine
            z, info, m = _solve_window(path, b, bd, s, o, win, pc, nsub, bm.fills, freqs, skin, log, edge=f_edge)
            whole = win == tuple(board_window)
            zc, infc = None, None
            if z is not None and global_pitch:
                # the same window at the board's pitch, for the truncation correction below; it must close too (a
                # neck the fine raster resolves and the coarse one loses: the board solve then closes outside)
                zc, infc, _ = _solve_window(path, b, bd, s, o, win, global_pitch, nsub, bm.fills, [f_fund, f_edge],
                                            False, log, edge=f_edge)
            # the window's L_loop at the edge band at both pitches: the copper's stored energy (lcu)
            Lw = info["lcu"][f_edge] if z is not None else None
            Lc = infc["lcu"][f_edge] if zc is not None else None
            bad = zc is not None and _truncation_too_large(g, zc, Lc, f_fund)
            if (z is not None and (zc is not None or not global_pitch) and not bad) or whole or grown >= MAX_GROW:
                break
            margin *= 2
            grown += 1
        # a window's kernel tables (its own grid) leave the operator cache with its cell: kept, every window of every
        # cell stayed resident to the end of the evaluation
        for k in [k for k in ES.Operator._cache if k not in keys0]:
            del ES.Operator._cache[k]
        why = None
        if global_pitch and pc >= global_pitch:
            why = f"over the budget of {MAX_CELLS:.3g} cells x layers below the board's pitch"
        elif z is not None and zc is not None and _truncation_too_large(g, zc, Lc, f_fund):
            why = (f"the window's truncation exceeds {TRUNC_MAX:g} of the board's value (window grown {grown} times "
                   f"to {margin:g} mm): it misses where the loop closes")
        elif z is not None and _corrected_L(g, Lw, Lc) <= 0 < g[0]:
            why = "the corrected window L_loop is not positive"
        if why:
            # the window over its cell budget (many layers, far parts) at the board's pitch, or a window whose
            # correction cannot be trusted: the board solve's values stand, with no harmonics (reported,
            # layout-independent like the window)
            R0 = round(_g_R(g) * 1e3, 4)
            peaks = [HA.peak(g[1], g[0], v["I_A"], v.get("D", 0.5), v["t_i_s"], v.get("I_pk_A"))[0]
                     for v in ({k[1]: x for k, x in cp.items()} for cp in cps[s.name])]
            rows.append(dict(row, state="ok", L_loop_nH=round(g[0] * 1e9, 4), R_loop_mohm=R0,
                             R_harmonics=[dict(n=1, f_MHz=round(f_fund / 1e6, 4), R_mohm=R0)],
                             overshoot_V=dict(typ=round(peaks[0], 4), worst=round(max(peaks), 4)),
                             f_edge_MHz=round(f_edge / 1e6, 4),
                             window=dict(box=[round(x, 3) for x in win], pitch=pc, refined=False, why=why,
                                         grown=grown, seconds=round(time.time() - t0, 1))))
            log(f"cell {s.name}: window {win[2] - win[0]:.1f} x {win[3] - win[1]:.1f} mm: {why}: board values")
            continue
        if z is None:
            rows.append(dict(row, state="open_in_window", why="the loop closes in the board solve but not in its "
                             f"window grown {grown} times to {margin:g} mm"))
            continue
        # the window's truncation, measured at the board's pitch: the board solve minus the same window at that pitch
        # (no skin correction in either, as the board solve has none). Added to the fine solve, it leaves the fine
        # pitch's correction of the board solve (two-grid: truncation and pitch errors add to first order)
        dLe, dZf, dR = 0.0, 0j, 0.0
        if zc is not None:
            dLe = g[0] - Lc
            dZf = g[1] - zc[f_fund]
            dR = _g_R(g) - (infc or {}).get("rcu", {}).get(f_fund, _g_R(g))
        Le = Lw + dLe
        Zf = z[f_fund] + dZf
        # R_loop: the copper's dissipation of the cell's current (window, skin) with the truncation's (board minus the
        # window at the board's pitch, both without skin) added; never below zero
        rw = info.get("rcu") or {}
        R = [dict(n=n, f_MHz=round(f / 1e6, 4), R_mohm=round(max(rw.get(f, 0.0) + dR, 0.0) * 1e3, 4))
             for n, f in zip(HARMONICS, fh)]
        peaks = []
        for c in range(len(cps[s.name])):
            val = {k[1]: v for k, v in cps[s.name][c].items()}
            peaks.append(HA.peak(Zf, Le, val["I_A"], val.get("D", 0.5), val["t_i_s"], val.get("I_pk_A"))[0])
        val0 = {k[1]: v for k, v in cps[s.name][0].items()}
        rows.append(dict(row, state="ok", L_loop_nH=round(Le * 1e9, 4), R_loop_mohm=R[0]["R_mohm"], R_harmonics=R,
                         overshoot_V=dict(typ=round(peaks[0], 4), worst=round(max(peaks), 4)),
                         di_dt_A_per_ns=round(val0.get("I_pk_A", val0["I_A"]) / val0["t_i_s"] * 1e-9, 4),
                         f_edge_MHz=round(f_edge / 1e6, 4),
                         window=dict(box=[round(x, 3) for x in win], pitch=pc, margin_mm=margin, grown=grown,
                                     L_raw_nH=round(Lw * 1e9, 4), trunc_L_nH=round(dLe * 1e9, 4),
                                     R_raw_mohm=round(rw.get(f_fund, 0.0) * 1e3, 4),
                                     trunc_R_mohm=round(dR * 1e3, 4), corrected=zc is not None, refined=True,
                                     cells=int(m.nx * m.ny * len(m.layers)), dropped_injection=round(info["dropped"], 5),
                                     skin=bool(skin), seconds=round(time.time() - t0, 1))))
        log(f"cell {s.name}: window {win[2] - win[0]:.1f} x {win[3] - win[1]:.1f} mm at {pc:g} mm: L_loop "
            f"{Le * 1e9:.3f} nH (board {g[0] * 1e9:.3f}), R_loop {R[0]['R_mohm']:.3f} mOhm at f_sw, "
            f"{time.time() - t0:.1f}s")
    for r in rows:
        if r.get("state") == "ok" and r.get("L_loop_nH") is not None and r["L_loop_nH"] <= 0:
            flag_invalid(r)
    return rows


N_HARM = 199                 # harmonics summed in the AC loop loss (their weight falls as 1/n^2, faster past the edge)


def r_of_f(row):
    """R_loop(f) (ohm) from a refined cell row's R at f_sw, 3 f_sw, 5 f_sw: log-log interpolation between them, R(f_sw)
    below, and beyond 5 f_sw R(5 f_sw) sqrt(f / 5 f_sw) (the skin regime: delta < t above ~5 MHz in 35 um copper,
    where R grows as sqrt(f) for conductor and return plane alike). None for a row without harmonics."""
    hs = [h for h in row.get("R_harmonics") or [] if h.get("R_mohm") is not None]
    if len(hs) < 2:
        return None
    fs = np.array([h["f_MHz"] * 1e6 for h in hs])
    rs = np.maximum(np.array([h["R_mohm"] * 1e-3 for h in hs]), 1e-12)

    def R(f):
        f = np.asarray(f, float)
        lo = np.interp(np.log(np.clip(f, fs[0], fs[-1])), np.log(fs), np.log(rs))
        out = np.exp(lo)
        hi = f > fs[-1]
        out[hi] = rs[-1] * np.sqrt(f[hi] / fs[-1])
        return out
    return R


def ac_loop_loss(I, D, f_sw, t_i, R):
    """The hot loop's AC conduction loss (W) of a pulsed current of height I, duty D at f_sw with edges t_i through a
    loop of resistance R(f): sum over harmonics n of |c_n|^2 / 2 R(n f_sw), c_n = (2 I / (n pi)) |sin(n pi D)|
    sinc(n f_sw t_i) (the trapezoid's spectrum). With R flat it is I^2 D (1 - D) R (Parseval), the old formula."""
    n = np.arange(1, N_HARM + 1)
    x = n * f_sw * t_i
    c = 2 * I / (n * np.pi) * np.abs(np.sin(n * np.pi * D)) * np.abs(np.sinc(x))
    return float(np.sum(c ** 2 / 2 * R(n * f_sw)))


def flag_invalid(row):
    """A row whose L_loop is not positive. L_loop is the copper's stored energy (never negative), so only a pattern
    that stores none (no copper carries it) gets here; before, L_loop was the layout's share Im z / w, which passes a
    resonance of the capacitor network near the edge band (olimex dcdc: +2.70 nH at 5 MHz, -2.62 at 10, +1.33 at 30
    on the board solve). Its L and overshoot are moved aside (L_invalid_nH), never reported; R_loop stays."""
    row["state"] = "invalid"
    row["L_invalid_nH"] = row.pop("L_loop_nH")
    row.pop("overshoot_V", None)
    row["why"] = (f"L_loop {row['L_invalid_nH']} nH at the edge band is not an inductance: no copper stores the "
                  f"cell's current")
    return row


def summary(rows):
    """{state: count} and the cells' primaries, one line each (for logs and the status)."""
    out = []
    for r in rows:
        if r["state"] == "ok":
            hs = r["R_harmonics"][1:]
            out.append(f"{r['source']}: L_loop {r['L_loop_nH']:.3f} nH, R_loop {r['R_loop_mohm']:.3f} mOhm at f_sw "
                       + (f"({', '.join(str(x['R_mohm']) for x in hs)} at {', '.join(str(x['n']) for x in hs)} f_sw)"
                          if hs else "(no harmonics: board values)") + ", overshoot "
                       f"{r['overshoot_V']['typ']:.3g} V typ, {r['overshoot_V']['worst']:.3g} V worst"
                       + (f" [window {r['window']['pitch']:g} mm, {r['window']['seconds']}s]" if r.get("window") else ""))
        else:
            out.append(f"{r['source']}: {r['state'].upper()}: {r.get('why', '')}")
    return out


PRIMARIES = (("L_loop_nH", lambda r: r["L_loop_nH"]), ("R_loop_mohm", lambda r: r["R_loop_mohm"]),
             ("overshoot_V", lambda r: r["overshoot_V"]["worst"]))


def paired(pairs):
    """Per-cell B/A ratios of the primaries over [(rows of A, rows of B)] (one pair per board): a cell open in one
    arm only ranks worst for that arm (ratio inf or 0), never leaves the table; open in both (or not computed in
    either) it is counted, not compared. Returns (rows, summary {primary: median ratio}, counts)."""
    out, counts = [], dict(cells=0, open_a=0, open_b=0, open_both=0, not_computed=0)
    for ra, rb in pairs:
        a = {r["source"]: r for r in ra}
        for src, x in sorted(a.items()):
            y = next((r for r in rb if r["source"] == src), None)
            counts["cells"] += 1
            if y is None or {"not_computed", "open_in_window", "invalid"} & {x["state"], y["state"]}:
                counts["not_computed"] += 1
                continue
            oa, ob = x["state"] == "open", y["state"] == "open"
            counts["open_a"] += oa
            counts["open_b"] += ob
            if oa and ob:
                counts["open_both"] += 1
                continue
            row = dict(source=src, a=x["state"], b=y["state"])
            for k, get in PRIMARIES:
                row[k] = math.inf if ob else 0.0 if oa else get(y) / get(x) if get(x) > 0 else math.inf
            out.append(row)
    med = {k: (float(np.median([r[k] for r in out])) if out else None) for k, _ in PRIMARIES}
    return out, med, counts


def main(argv=None):
    """python -m haslam.excite.hotloop A.ev.json B.ev.json [A2.ev.json B2.ev.json ...]: the cells of each pair of
    evaluations (arm A, arm B of one board) side by side, B/A per cell and the medians (open cells ranked worst)."""
    import json
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2 or len(argv) % 2:
        print(main.__doc__)
        return 2
    evs = [json.load(open(p)) for p in argv]
    for e, p in zip(evs, argv):
        for line in summary(e.get("cells") or []):
            print(f"{p}: {line}")
    rows, med, counts = paired([(evs[k].get("cells") or [], evs[k + 1].get("cells") or []) for k in range(0, len(evs), 2)])
    for r in rows:
        print(f"{r['source']:32s} {r['a']:5s} {r['b']:5s} " + "  ".join(f"{k} {r[k]:.3g}" for k, _ in PRIMARIES))
    print("median B/A:", {k: (round(v, 3) if v is not None else None) for k, v in med.items()}, counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
