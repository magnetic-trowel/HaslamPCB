# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PDN impedance screener: each rail's lumped Z(f) against a target impedance (decoupling-pdn.md, PDN-09/10/11).

The model is kae.excite.models' circuit of the board (ideal copper; the screen does not duplicate it):
capacitors with their bias-derated C, ESR and ESL, regulator outputs and port supplies as R + L, beads,
inductors and resistors between rails. Three changes make it a rail's PDN as seen from its loads' pins:

- the loads come out: every IC's supply-pin package and die (the board's PDN is judged at the pins; the
  package and die take over above F_HI);
- each capacitor's series inductance becomes its mounting loop where a geometry gave one (`loops`,
  {ref: nH}: the place terms' decap loops at a placement, the routed recheck's loops on copper), taken as
  max(ESL, loop) because the loop already runs across the body between the pads; else ESL + MOUNT_PRIOR;
- a rail and a ground with zones facing each other on two layers add their plane capacitance eps A / d.

Per rail, |Z(f)| between the rail and the board's ground is swept over [F_LO, F_HI] (AMD UG933 checks
its decoupling networks "from 100 KHz to 100 MHz"; the place terms' decap budget hands over to the
package at 100 MHz). The target is Z_t = RIPPLE V / I, I the sum of the rail's loads' transient
currents: the place terms' prior by pin count (kae.physics.priors.ic_current_prior), split over each
IC's supply pins, as decap_budget splits it. That current is a guess, so every finding is info or warn,
never block, and says the current was assumed.

Findings (Smith, Sandler and Bogatin, "Target Impedance Is Not Enough", SIJ 2019):
- the worst |Z| / Z_t in the band: a square-wave load at a parallel resonance drives 0.64 I Z_peak, so a
  peak up to 1/0.64 = 1.57 Z_t still meets the tolerance; "many successfully deployed products have a
  peak height as large as 3x". Over Z_t: info. Warn when it stays over PEAK_TOLERATED (3) Z_t with the
  supplies' stand-in halved and doubled (SUPPLY_PROBE), the rail has a capacitor, and the worst point is
  not the inductive top of the band (the decap place term's own budget);
- each anti-resonance peak's Q = Z_peak / Z0, Z0 = sqrt(L/C) of the equivalent tank, read from the slope
  of the susceptance (peaks()); Z0 also sets the step response below ~100 MHz. Two or more peaks with
  Q > Q_ROGUE (2) near the target can stack into a "rogue wave" (info);
- plane-pair cavity modes f_mn = c / (2 sqrt(er)) sqrt((m/a)^2 + (n/b)^2) on the facing zones' extent,
  against the odd harmonics (n <= 7: at least 1/7 of the fundamental) of the clocks the brief knows,
  within +-10 % (info).
"""
from __future__ import annotations

import math

import numpy as np
import scipy.sparse.linalg as sla

from . import models as M
from .circuit import Circuit

F_LO = 100e3            # Hz: below this the regulator holds the rail (UG933: "DC to a few hundred kHz")
F_HI = 100e6            # Hz: above this the package and die capacitance take over (priors.decap_budget f_h)
PTS_PER_DECADE = 60
RIPPLE = 0.05           # share of the rail voltage the transient may take (priors.decap_budget; Intel PDN tool
#                         examples: 5 %); an assumption, stated in every finding
PEAK_ROBUST = 1.57          # 1/0.64: Smith, Sandler, Bogatin: the full tolerance is reached at a peak this high
PEAK_TOLERATED = 3.0        # ibid.: "many successfully deployed products have a peak height as large as 3x"
Q_ROGUE = 2.0           # decoupling-pdn.md PDN-10: "warn if >= 2 peaks have Q > ~2"
Q_PEAK_MIN = 0.5        # a local maximum flatter than this is not a resonance worth naming
MOUNT_PRIOR_NH = 1.0    # nH added to a capacitor's ESL where no geometry gave its loop (AMD UG933: pads, vias
#                         and traces add 0.3-4 nH; Archambeault: 0402 with 10 mil to its via over a 10 mil
#                         deep plane 0.9 nH)
CAVITY_TOL = 0.10       # decoupling-pdn.md PDN-11: a clock harmonic within +-10 % of a mode
CAVITY_HARMONICS = (1, 3, 5, 7)
C0 = 299792458.0
EPS0 = 8.8541878128e-12
LOAD_SKIP = ("die",)
# What feeds a rail is a stand-in on every board (kae.excite.models: a regulator's output R + L, a cable to
# the host, a module's decoupling; or the screen's own when the model has none). A finding warns only when
# it holds with the supplies' impedance halved and doubled; one that needs the stand-in's exact value is info.
SUPPLY_KINDS = ("reg_out", "port", "vrm_assumed")
SUPPLY_PROBE = (0.5, 2.0)    # an IC's die capacitance: inside the package, above F_HI


def _rlc(R, L, C):
    return lambda w: R + 1j * w * L + (1 / (1j * w * C) if C else 0)


def _with_l(z, dl):
    return lambda w: z(w) + 1j * w * dl


def _scaled(z, k):
    return lambda w: k * z(w)


def rail_loads(bd, brief_parts=None):
    """{rail: [(ref, I_A, basis)]}: each IC that draws from a rail (bd.ic_nodes), with its transient current
    split over its supply pins (priors.ic_current_prior by pin count). Regulators are not loads: their input
    current is the converter's (the commutation and power-path terms)."""
    from kae.physics.priors import ic_current_prior
    pins = {}
    for t in bd.net_of:
        pins.setdefault(t.rsplit(".", 1)[0], []).append(t)
    out = {}
    for ref, nodes in bd.ic_nodes.items():
        kind, sub, role = bd.part_kind.get(ref, ("ic", None, ""))
        if kind != "ic" or "regulator" in f"{sub or ''} {role or ''}":
            continue                                  # an unclassified many-pin part is not a known load
        rails = [k for k in nodes if k != "g"]
        if not rails:
            continue
        own = pins.get(ref, [])
        n_sup = {r: sum(1 for t in own if bd.net_of[t] == r) for r in rails}
        tot = sum(n_sup.values()) or 1
        I = ic_current_prior(len(own))
        for r in rails:
            share = n_sup[r] / tot
            out.setdefault(r, []).append((ref, I * share, f"{I * 1e3:.0f} mA ({len(own)}-pin prior) x "
                                                          f"{n_sup[r]}/{tot} supply pins"))
    return out


def screen_circuit(bd, loops=None, planes=None, supply_scale=1.0):
    """The rails' PDN circuit (module docstring) and what was assumed: (Circuit, {cap ref: L_series nH,
    basis}, assumptions). supply_scale multiplies the supplies' impedance (SUPPLY_KINDS: stand-ins, probed
    at SUPPLY_PROBE)."""
    loops = loops or {}
    c = Circuit(bd.ground)
    caps, notes = {}, []
    for e in bd.circuit.elems:
        if e.kind in LOAD_SKIP:
            continue
        if e.kind == "pkg" and e.a in bd.rails:
            continue                                  # an IC's supply pin: the load, judged at its pin
        z = e.z
        if e.kind == "C" and e.par.get("ESL") is not None:
            esl = e.par["ESL"] * 1e9
            lp = loops.get(e.name)
            if lp is not None and math.isfinite(lp):
                ls, basis = max(esl, lp), "loop"
            else:
                ls, basis = esl + MOUNT_PRIOR_NH, "prior"
            if ls > esl:
                z = _with_l(z, (ls - esl) * 1e-9)
            caps[e.name] = (ls, basis)
        if e.kind in SUPPLY_KINDS and supply_scale != 1.0:
            z = _scaled(z, supply_scale)
        c.z(e.name, e.a, e.b, z, e.pa, e.pb, e.kind, e.par)
    for p in planes or []:
        if p["rail"] in bd.rails:
            c.z(f"plane:{p['rail']}:{p['layers']}", p["rail"], bd.ground, _rlc(1e-3, 0.0, p["C_F"]), kind="plane",
                par=dict(C=p["C_F"]))
    for net in bd.rails:
        if net not in c.nodes:
            continue
        if not any(e.kind in ("reg_out", "port") and net in (e.a, e.b) for e in c.elems):
            notes.append(f"{net}: no regulator output or port supplies it in the model; a regulator stand-in "
                         f"(R 50 mOhm + 0.2 uH) is assumed")
            c.z(f"vrm:{net}", net, bd.ground, _rlc(M.REG_R * supply_scale, M.REG_L * supply_scale, 0),
                kind="vrm_assumed")
    return c, caps, notes


def sweep(c, nets, freqs):
    """{net: complex Z(f) array}: the impedance from each net to the circuit's ground."""
    keep = [n for n in nets if n in c.nodes and c.nodes[n] != 0]
    Z = {n: np.zeros(len(freqs), complex) for n in keep}
    if not keep:
        return Z
    idx = [c.nodes[n] - 1 for n in keep]
    rhs = np.zeros((len(c.nodes) - 1, len(keep)), complex)
    for j, i in enumerate(idx):
        rhs[i, j] = 1.0
    for k, f in enumerate(freqs):
        Y, *_ = c._Y(2 * math.pi * f)
        V = sla.splu(Y).solve(rhs)
        for j, (n, i) in enumerate(zip(keep, idx)):
            Z[n][k] = V[i, j]
    return Z


def peaks(c, net, freqs, z, f_lo, f_hi):
    """Anti-resonance peaks of |z| inside [f_lo, f_hi]: [{f, Z, Z0, Q}], each refined on a fine local sweep.
    Z0 is the equivalent tank's sqrt(L/C) = 2 / (w0 dB/dw), B = Im(1/z) (for a parallel L, C, B = wC - 1/(wL)
    and dB/dw = 2C at w0); Q = Z_peak / Z0, Smith and Sandler's peak Q (module docstring)."""
    m = np.abs(z)
    out = []
    for i in range(1, len(freqs) - 1):
        if not (m[i] > m[i - 1] and m[i] >= m[i + 1]) or not (f_lo <= freqs[i] <= f_hi):
            continue
        fine = np.geomspace(freqs[i - 1], freqs[i + 1], 41)
        zf = sweep(c, [net], fine)[net]
        k = int(np.argmax(np.abs(zf)))
        k = min(max(k, 1), len(fine) - 2)
        w = 2 * math.pi * fine
        B = (1 / zf).imag
        dB = (B[k + 1] - B[k - 1]) / (w[k + 1] - w[k - 1])
        if dB <= 0:
            continue                                  # not a parallel resonance (B must rise through zero)
        z0 = 2.0 / (w[k] * dB)
        q = float(abs(zf[k])) / z0
        if q >= Q_PEAK_MIN:
            out.append(dict(f=float(fine[k]), Z=float(abs(zf[k])), Z0=float(z0), Q=float(q)))
    return out


def plane_pairs(board, rails, grounds):
    """Facing rail and ground zones on two copper layers: [{rail, layers, area_mm2, d_mm, er, a_mm, b_mm, C_F}].
    Zone outlines, not fills (a placement has no fills); kae.physics.boardview gives the stack-up."""
    from shapely.ops import unary_union

    from kae.physics.boardview import BoardView
    bv = board if isinstance(board, BoardView) else BoardView.from_board(board)
    by = {}
    for net, ly, g in bv.zones:
        by.setdefault((net, ly), []).append(g)
    out = []
    for r in rails:
        best = None
        for (n, lr), gr in by.items():
            if n != r:
                continue
            for (gn, lg), gg in by.items():
                if gn not in grounds or lg == lr:
                    continue
                ov = unary_union(gr).intersection(unary_union(gg))
                d = abs(bv.zcu[lr] - bv.zcu[lg])
                if ov.is_empty or ov.area < 1.0 or d <= 0:
                    continue
                C = EPS0 * bv.er * ov.area * 1e-6 / (d * 1e-3)
                if best is None or C > best["C_F"]:
                    rect = ov.minimum_rotated_rectangle
                    xs = list(rect.exterior.coords) if hasattr(rect, "exterior") else [(0, 0)] * 3
                    s1 = math.dist(xs[0], xs[1])
                    s2 = math.dist(xs[1], xs[2])
                    best = dict(rail=r, layers=f"{lr}/{lg}", ground=gn, area_mm2=round(ov.area, 1), d_mm=round(d, 4),
                                er=bv.er, a_mm=round(max(s1, s2), 2), b_mm=round(min(s1, s2), 2), C_F=C)
        if best:
            out.append(best)
    return out


def cavity_modes(p):
    """(m, n, f Hz) of a plane pair's lowest modes 10, 01, 11 on its a x b extent."""
    v = C0 / math.sqrt(p["er"])
    a, b = p["a_mm"] * 1e-3, p["b_mm"] * 1e-3
    out = []
    for m, n in ((1, 0), (0, 1), (1, 1)):
        if (n and b <= 0) or (m and a <= 0):
            continue
        out.append((m, n, v / 2 * math.sqrt((m / a) ** 2 + ((n / b) ** 2 if b > 0 else 0))))
    return out


def clocks(brief):
    """{name: f Hz} of the clocks the brief states: crystals, oscillators and clock nets with a frequency."""
    out = {}
    for s in (brief or {}).get("structures") or []:
        f = s.get("f_Hz")
        if f and s.get("kind") in ("crystal", "oscillator", "clock"):
            out[s.get("id") or s.get("kind")] = float(f)
    for n, d in ((brief or {}).get("nets") or {}).items():
        if (d or {}).get("role") == "clock" and d.get("f_Hz"):
            out.setdefault(f"net:{n}", float(d["f_Hz"]))
    return out


def screen(board, brief=None, loops=None, bd=None, stage="placement", f_lo=F_LO, f_hi=F_HI, ppd=PTS_PER_DECADE):
    """The PDN screen of a board: dict(rails=[...], planes=[...], hazards=[...], assumptions=[...]).
    loops: {capacitor ref: loop nH} from a geometry (module docstring); stage names it in the findings."""
    from kae import hazards as H
    from kae.circuit import brief as B

    from . import models as M
    if brief is None:
        brief = B.build(board)
    if bd is None:
        bd = M.build(board, brief)
    loads = rail_loads(bd)
    try:
        planes = plane_pairs(board, list(bd.rails), bd.grounds)
    except Exception as e:  # noqa: BLE001 - a board without a usable stack-up still gets its rails screened
        planes = []
        bd.assumptions.append(f"plane pairs not read: {type(e).__name__}: {e}")
    c, caps, notes = screen_circuit(bd, loops, planes)
    n = max(2, int(round(math.log10(2 * f_hi / (0.5 * f_lo)) * ppd)) + 1)
    freqs = np.geomspace(0.5 * f_lo, 2 * f_hi, n)
    rails = [r for r in bd.rails if loads.get(r)]
    Zs = sweep(c, rails, freqs)
    band = (freqs >= f_lo) & (freqs <= f_hi)
    probe = [sweep(screen_circuit(bd, loops, planes, supply_scale=k)[0], rails, freqs[band]) for k in SUPPLY_PROBE]
    out_rails, hz = [], []
    for r in rails:
        if r not in Zs:
            continue
        V = bd.rails.get(r)
        I = sum(x[1] for x in loads[r])
        rec = dict(rail=r, V=V, loads=[x[0] for x in loads[r]], I_A=round(I, 4), I_basis="assumed: "
                   + "; ".join(f"{x[0]} {x[2]}" for x in loads[r][:6]),
                   caps=sorted(e.name for e in c.elems if e.kind == "C" and r in (e.a, e.b)))
        if not V or I <= 0:
            rec["note"] = "no rail voltage known: no target"
            out_rails.append(rec)
            continue
        zt = RIPPLE * abs(V) / I
        z = Zs[r]
        m = np.abs(z)
        ib = np.flatnonzero(band)
        k = ib[int(np.argmax(m[ib]))]
        pk = peaks(c, r, freqs, z, f_lo, f_hi)
        worst = dict(f=float(freqs[k]), Z=float(m[k]))
        at_peak = next((p for p in pk if p["Z"] >= worst["Z"] * 0.999), None)
        if at_peak:
            worst = dict(f=at_peak["f"], Z=at_peak["Z"])
        ratio = worst["Z"] / zt
        rng = [float(np.max(np.abs(p[r]))) / zt for p in probe if r in p] + [ratio]
        lo_ratio = min(rng)
        shape = "peak" if at_peak else ("inductive" if np.angle(z[k]) > 0 else "capacitive")
        kh = ib[-1]
        rec.update(Z_t=round(zt, 5), L_eff_nH=round(float(m[kh]) / (2 * math.pi * freqs[kh]) * 1e9, 3), worst=dict(f_Hz=round(worst["f"]), Z_ohm=round(worst["Z"], 5),
                                                ratio=round(ratio, 3), ratio_supply_probe=[round(x, 3) for x in rng[:-1]],
                                                shape=shape,
                                                Q=round(at_peak["Q"], 2) if at_peak else None),
                   peaks=[dict(f_Hz=round(p["f"]), Z_ohm=round(p["Z"], 5), Z0_ohm=round(p["Z0"], 5), Q=round(p["Q"], 2),
                               ratio=round(p["Z"] / zt, 3)) for p in pk])
        out_rails.append(rec)
        objs = [r] + rec["loads"][:4] + rec["caps"][:6]
        common = dict(V=V, I_A=round(I, 4), I_source="assumed (pin-count prior)", ripple=RIPPLE,
                      Z_t_ohm=round(zt, 5), stage=stage)
        if ratio > 1.0:
            # warn: over the tolerated peak whatever the supply stand-in, on a rail the board decouples, and
            # not the inductive top of the band, which the place terms' decap budget already prices
            # (priors.decap_budget: L_pin = n Z_t / (2 pi f_h); placement_physics_over_budget)
            sev = "warn" if lo_ratio > PEAK_TOLERATED and rec["caps"] and shape != "inductive" else "info"
            f, Zw = worst["f"], worst["Z"]
            if shape == "peak":
                fix = (f"damp the anti-resonance at {f / 1e6:.3g} MHz: a bulk capacitor whose ESR is about Z_t "
                       f"({zt * 1e3:.3g} mOhm), or same-value capacitors; do not add decade values")
            elif shape == "inductive":
                lneed = zt / (2 * math.pi * f) * 1e9
                fix = (f"lower the rail's effective inductance from {Zw / (2 * math.pi * f) * 1e9:.3g} nH to "
                       f"{lneed:.3g} nH: capacitors beside the loads' supply pins, vias at the pads, a plane pair, "
                       "or more capacitors in parallel")
            else:
                cneed = 1 / (2 * math.pi * f * zt) * 1e6
                fix = f"add bulk capacitance: about {cneed:.3g} uF after DC-bias derating"
            hz.append(H.make(
                "pdn_impedance_over_target", sev, "electrical",
                f"Rail {r}'s PDN impedance reaches {ratio:.2g}x its target ({Zw * 1e3:.3g} vs {zt * 1e3:.3g} mOhm) "
                f"at {f / 1e6:.3g} MHz ({'an anti-resonance, Q ' + format(at_peak['Q'], '.2g') if at_peak else shape}"
                f"); the target assumes a {I * 1e3:.0f} mA transient"
                + (f"; with the supply's stand-in impedance halved or doubled it is {lo_ratio:.2g}x"
                   if lo_ratio < ratio * 0.8 else "")
                + ("; no capacitor on the rail: a load that decouples itself, or a sense pin, needs none"
                   if not rec["caps"] else "") + f" ({stage})",
                objects=objs, evidence=dict(common, f_Hz=round(f), Z_ohm=round(Zw, 5), ratio=round(ratio, 3),
                                            shape=shape, robust=round(PEAK_ROBUST, 2), tolerated=PEAK_TOLERATED,
                                            ratio_min_supply_probe=round(lo_ratio, 3)),
                fix=fix + "; or state the load's real transient current"))
        sharp = [p for p in pk if p["Q"] > Q_ROGUE and p["Z"] > 0.5 * zt]
        if len(sharp) >= 2:
            hz.append(H.make(
                "pdn_rogue_wave_risk", "info", "electrical",
                f"Rail {r} has {len(sharp)} anti-resonances with Q > {Q_ROGUE:g} near its target; a load stepping "
                f"through them can stack their ringing ({stage})", objects=objs,
                evidence=dict(common, peaks=[dict(f_Hz=round(p["f"]), Q=round(p["Q"], 2), ratio=round(p["Z"] / zt, 2))
                                             for p in sharp[:4]]),
                fix="damp the peaks with a controlled-ESR bulk capacitor, or use fewer distinct capacitor values"))
    clk = clocks(brief)
    for p in planes:
        p["modes_Hz"] = {f"{m}{n}": round(f) for m, n, f in cavity_modes(p)}
        p["C_nF"] = round(p.pop("C_F") * 1e9, 3)
        for name, fc in clk.items():
            for mn, fm in p["modes_Hz"].items():
                hit = next((h for h in CAVITY_HARMONICS if abs(h * fc - fm) <= CAVITY_TOL * fm), None)
                if hit:
                    hz.append(H.make(
                        "pdn_cavity_mode_clock", "info", "electrical",
                        f"The {p['rail']} plane pair ({p['layers']}, {p['a_mm']:g} x {p['b_mm']:g} mm) resonates at "
                        f"{fm / 1e6:.4g} MHz (mode {mn}), within {CAVITY_TOL:.0%} of harmonic {hit} of {name} "
                        f"({fc / 1e6:.4g} MHz)", objects=[p["rail"], name],
                        evidence=dict(mode=mn, f_mode_Hz=fm, f_clock_Hz=fc, harmonic=hit, er=p["er"],
                                      a_mm=p["a_mm"], b_mm=p["b_mm"]),
                        fix="stitch and decouple at the plane's edges and corners (the mode's maxima), or change "
                            "the plane's extent"))
    return dict(stage=stage, band_Hz=[f_lo, f_hi], ripple=RIPPLE, rails=out_rails, planes=planes, hazards=hz,
                caps={k: dict(L_nH=round(v[0], 3), basis=v[1]) for k, v in caps.items()},
                assumptions=notes + [a for a in bd.assumptions if "DC bias" in a or "unread" in a][:20])


def loops_from_breakdown(rows):
    """{capacitor ref: nH}: the lowest decap loop each capacitor has in a place-terms breakdown
    (Terms.breakdown rows: kind 'decap', components labelled by capacitor ref, values in nH)."""
    out = {}
    for r in rows or []:
        if r.get("kind") != "decap":
            continue
        for comp in r.get("components") or []:
            ref, v = comp.get("label"), comp.get("value")
            if ref and v is not None and math.isfinite(float(v)) and float(v) > 0:
                out[ref] = min(out.get(ref, math.inf), float(v))
    return out


def compact(rep, rails=12):
    """A screen's report sized for an LLM-facing report: the rails' worst points and peaks, the plane pairs, how
    many capacitors had a geometry loop, and the hazards."""
    caps = rep.get("caps") or {}
    out = dict(rep, rails=[{k: v for k, v in r.items() if k != "caps"} for r in rep.get("rails", [])[:rails]],
               caps_with_loop=sum(1 for v in caps.values() if v.get("basis") == "loop"), caps_total=len(caps),
               assumptions=(rep.get("assumptions") or [])[:8])
    out.pop("caps", None)
    return out
