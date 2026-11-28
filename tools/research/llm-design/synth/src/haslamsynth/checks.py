# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic design checks over the IR.

Each check yields Findings with a stable check id. Errors block the build's "checks pass"
status; waivers (Design.waive) turn a finding into an accepted, recorded exception.
"""
import itertools
import math
import re
from dataclasses import dataclass, field

from .ir import GRADES, OFF_BOARD, THREATS, DesignError, PinRef
from .kicadlib import LEGACY_HINT
from .units import parse_value


@dataclass
class Finding:
    check: str
    severity: str          # error | warning | info
    message: str
    objects: list = field(default_factory=list)
    waived_by: str = None

    def as_dict(self):
        d = {"check": self.check, "severity": self.severity, "message": self.message,
             "objects": self.objects}
        if self.waived_by:
            d["waived_by"] = self.waived_by
        return d


SERIES_CATEGORIES = ("fuse", "ptc", "connector", "relay", "inductor", "switch", "mosfet", "diode",
                     "transformer", "led", "bjt")
# parts that carry one current end to end (check_current); their control pins carry none of it
PATH_CATEGORIES = ("fuse", "ptc", "inductor", "switch", "mosfet", "diode", "led", "bjt")
CONTROL_PINS = {"mosfet": ("G",), "bjt": ("B",)}


class Checker:
    def __init__(self, design, symlibs=None, fplibs=None):
        self.d = design
        self.sym = symlibs
        self.fp = fplibs
        self.findings = []
        self._expand_cache = {}

    def add(self, check, severity, message, objects=()):
        self.findings.append(Finding(check, severity, message, [str(o) for o in objects]))

    def run(self):
        d = self.d.finalize()
        self.check_domains()
        self.check_boards()
        self.check_connectivity()
        self.check_pin_types()
        self.check_voltage()
        self.check_isolation()
        self.check_current()
        self.check_power()
        self.check_library()
        self.check_bom()
        self.check_provenance()
        self.check_dc_bias()
        self.check_protection()
        self.check_calcs()
        self.check_standby()
        self.check_intent()
        self.apply_waivers()
        return self.findings

    # -- voltage model --------------------------------------------------------------------------
    # V(net) is a linear form over independent variables, one per net (its declared range `v`), from the root
    # domain's 0 V: V(net) = [its own variable] + frac x V(domain ref), recursively along the domain chain.
    # Undeclared, frac = 1 and the form is the plain interval sum along the chain (stacked batteries exact).
    # Declared correlation (ir.Net frac/tracks/abs_v, Domain abs_v) changes the form or bounds it; see the
    # synth README "Correlated voltages". Differences cancel shared variables, so correlated nets come out tight.
    def expand(self, net, _stack=()):
        """(terms, root domain): V(net) from the root's 0 V as {variable net: coefficient}."""
        key = id(net)
        if key in self._expand_cache:
            return self._expand_cache[key]
        dom = self.d.domain_of(net)
        if dom is None:
            self._expand_cache[key] = (None, None)
            return None, None
        if key in _stack:
            raise DesignError(f"domain reference cycle at {dom.name} (net {net.full_name})")
        stack = _stack + (key,)
        ref = self.d.net_by_name(dom.ref)
        rdom = self.d.domain_of(ref)
        if rdom is dom or rdom is None:
            base, root = {}, dom
        else:
            bt, root = self.expand(ref, stack)
            if bt is None:
                self._expand_cache[key] = (None, None)
                return None, None
            k = 1.0 if net.frac is None else net.frac
            base = {n: c * k for n, c in bt.items()}
        own = {net: 1.0}
        t = self._tracked(net)
        if t is not None:
            # tracks: the net's own variable is the mismatch; add V(t) - V(t's domain ref)
            tt, troot = self.expand(t, stack)
            trt, _ = self.expand(self.d.net_by_name(self.d.domain_of(t).ref), stack)
            if troot is root and tt is not None and trt is not None:
                for n, c in tt.items():
                    own[n] = own.get(n, 0.0) + c
                for n, c in trt.items():
                    own[n] = own.get(n, 0.0) - c
        terms = dict(base)
        for n, c in own.items():
            terms[n] = terms.get(n, 0.0) + c
        self._expand_cache[key] = (terms, root)
        return terms, root

    def _tracked(self, net):
        if not net.tracks:
            return None
        try:
            t = self.d.net_by_name(net.tracks)
        except DesignError:
            return None
        return t if t is not net and self.d.domain_of(t) is not None else None

    def has_correlation(self):
        if not hasattr(self, "_has_corr"):
            self._has_corr = any(n.frac is not None or n.tracks or n.abs_v is not None for n in self.d.all_nets()) \
                or any(x.abs_v is not None for x in self.d.domains.values())
        return self._has_corr

    def chain(self, dom):
        """(terms, root) for a domain's 0 V relative to its root: {net: coefficient}."""
        terms, d, seen = {}, dom, set()
        while True:
            if d.name in seen:
                raise DesignError(f"domain reference cycle at {d.name}")
            seen.add(d.name)
            ref = self.d.net_by_name(d.ref)
            rd = self.d.domain_of(ref)
            if rd is d or rd is None:
                return terms, d
            terms[ref] = terms.get(ref, 0) + 1
            d = rd

    def domain_pair_vmax(self, da, db):
        """Worst |V| between any net of domain da and any net of domain db (None if separate roots)."""
        if self.has_correlation():
            # declared correlation: per-net ranges are no longer relative offsets, so take the exact worst pair
            na = [n for n in self.d.all_nets() if self.d.domain_of(n) is da and n.pins]
            nb = [n for n in self.d.all_nets() if self.d.domain_of(n) is db and n.pins]
            worst = None
            for a in na:
                for b in nb:
                    r = self.vdiff(a, b)
                    if r is not None:
                        worst = max(worst or 0.0, abs(r[0]), abs(r[1]))
            return worst
        ta, ra = self.chain(da)
        tb, rb = self.chain(db)
        if ra is not rb:
            return None
        rng_a = [self.vrange(n) for n in self.d.all_nets() if self.d.domain_of(n) is da and n.pins]
        rng_b = [self.vrange(n) for n in self.d.all_nets() if self.d.domain_of(n) is db and n.pins]
        rng_a, rng_b = [r for r in rng_a if r], [r for r in rng_b if r]
        if not rng_a or not rng_b:
            return None
        terms = dict(ta)
        for n, c in tb.items():
            terms[n] = terms.get(n, 0) - c
        lo = min(r[0] for r in rng_a) - max(r[1] for r in rng_b)
        hi = max(r[1] for r in rng_a) - min(r[0] for r in rng_b)
        for n, c in terms.items():
            v = self.vrange(n)
            if c == 0 or v is None:
                continue
            lo += min(c * v[0], c * v[1])
            hi += max(c * v[0], c * v[1])
        return max(abs(lo), abs(hi))

    def root(self, net):
        return self.expand(net)[1]

    def vrange(self, net):
        """The range of the net's own variable: v, else its domain's v_range ((0, 0) for a tracking net)."""
        if net.v is not None:
            return net.v
        if net.tracks:
            return (0.0, 0.0)
        dom = self.d.domain_of(net)
        return getattr(dom, "v_range", None)

    def _linear(self, terms):
        lo = hi = 0.0
        for n, c in terms.items():
            if abs(c) < 1e-12:
                continue
            v = self.vrange(n)
            if v is None:
                return None
            x0, x1 = c * v[0], c * v[1]
            lo += min(x0, x1)
            hi += max(x0, x1)
        return (lo, hi)

    def envelope(self, net):
        """Declared absolute envelope of a net (from its root's 0 V): its own abs_v, else its domain's; None."""
        if net.abs_v is not None:
            return net.abs_v
        dom = self.d.domain_of(net)
        if dom is not None and dom.abs_v is not None and self.d.net_by_name(dom.ref) is not net:
            return dom.abs_v
        return None

    def vabs(self, net):
        """Interval of V(net) from its root's 0 V: the linear form, intersected with any declared envelope."""
        terms, root = self.expand(net)
        lin = self._linear(terms) if terms is not None else None
        env = self.envelope(net) if terms is not None else None
        if env is None:
            return lin
        if lin is None:
            return env
        lo, hi = max(lin[0], env[0]), min(lin[1], env[1])
        return (lo, hi) if lo <= hi + 1e-9 else lin       # inconsistent: check_domains reports it

    def vdiff(self, a, b):
        """Interval of V(a) - V(b), or None if unknown or galvanically separate."""
        if a is b:
            return (0.0, 0.0)
        ta, ra = self.expand(a)
        tb, rb = self.expand(b)
        if ra is None or rb is None or ra is not rb:
            return None
        terms = dict(ta)
        for n, c in tb.items():
            terms[n] = terms.get(n, 0) - c
        lin = self._linear(terms)
        if self.envelope(a) is None and self.envelope(b) is None:
            return lin
        # an absolute envelope bounds the difference by its ends: V(a) - V(b) in [A.lo - B.hi, A.hi - B.lo]
        A, B = self.vabs(a), self.vabs(b)
        if A is None or B is None:
            return lin
        env = (A[0] - B[1], A[1] - B[0])
        if lin is None:
            return env
        lo, hi = max(lin[0], env[0]), min(lin[1], env[1])
        return (lo, hi) if lo <= hi + 1e-9 else lin

    def vmax_between(self, nets_a, nets_b):
        worst, pair = 0.0, None
        for a in nets_a:
            for b in nets_b:
                r = self.vdiff(a, b)
                if r is None:
                    continue
                m = max(abs(r[0]), abs(r[1]))
                if m > worst:
                    worst, pair = m, (a, b)
        return worst, pair

    # -- checks ---------------------------------------------------------------------------------
    def check_domains(self):
        d = self.d
        if not d.domains:
            self.add("domain.none", "warning", "design declares no voltage domains; voltage and isolation checks are skipped")
            return
        for dom in d.domains.values():
            try:
                ref = d.net_by_name(dom.ref)
            except DesignError:
                self.add("domain.ref", "error", f"domain {dom.name}: reference net {dom.ref} does not exist", [dom.name])
                continue
            rdom = d.domain_of(ref)
            if rdom is None:
                self.add("domain.ref", "error", f"domain {dom.name}: reference net {dom.ref} has no domain", [dom.name])
            elif rdom is dom and ref.v not in (None, (0.0, 0.0)):
                self.add("domain.ref", "error", f"root domain {dom.name}: its reference {dom.ref} must have v=0", [dom.name])
        for n in d.all_nets():
            if n.domain is None:
                self.add("net.no_domain", "error", f"net {n.full_name} has no domain", [n.full_name])
            elif d.domain_of(n) is None:
                self.add("net.no_domain", "error", f"net {n.full_name}: unknown domain {n.domain!r}", [n.full_name])
            elif self.vrange(n) is None and n.pins:
                self.add("net.no_voltage", "warning", f"net {n.full_name} has no voltage range; rating checks skip it",
                         [n.full_name])
        self.check_correlation()
        names = set(d.domains)
        for b in d.barriers:
            for x in (b.a, b.b):
                if x not in names:
                    self.add("barrier.domain", "error", f"barrier {b.a}-{b.b}: unknown domain {x}", [x])

    def check_correlation(self):
        """Declared correlation (frac, tracks, abs_v) must be usable and consistent with the nets' own ranges."""
        d = self.d
        for n in d.all_nets():
            dom = d.domain_of(n)
            if dom is None:
                continue
            try:
                ref = d.net_by_name(dom.ref)
            except DesignError:
                continue
            if n.frac is not None and (d.domain_of(ref) is dom or ref is n):
                self.add("net.correlation", "error",
                         f"net {n.full_name}: frac={n.frac:g} needs a domain floating on another net (V = frac x V(ref) + v); "
                         f"{dom.name} is a root domain whose ref is 0 V", [n.full_name])
            if n.tracks:
                t = self._tracked(n)
                if t is None:
                    self.add("net.correlation", "error",
                             f"net {n.full_name}: tracks={n.tracks!r} is not another net with a domain", [n.full_name])
                elif self.root(t) is not self.root(n):
                    self.add("net.correlation", "error",
                             f"net {n.full_name}: tracks {t.full_name}, which is in another root domain "
                             f"(galvanically separate: no common 0 V)", [n.full_name])
            env = self.envelope(n)
            if env is not None and n.pins:
                terms, _ = self.expand(n)
                lin = self._linear(terms) if terms is not None else None
                if lin is not None and (env[0] > lin[1] + 1e-9 or env[1] < lin[0] - 1e-9):
                    self.add("net.correlation", "error",
                             f"net {n.full_name}: absolute envelope abs_v={env} cannot hold: its own ranges put it at "
                             f"{lin[0]:.4g}..{lin[1]:.4g} V from the root's 0 V", [n.full_name])

    def check_boards(self):
        """Nets that leave a board must do so through a connector on that board."""
        d = self.d
        for b in d.blocks:
            if b.board is not None and b.board != OFF_BOARD and b.board not in d.boards:
                self.add("board.unknown", "error", f"block {b.name} is on undeclared board {b.board!r}", [b.name])
        if len(d.board_names()) + any(b.board_name == OFF_BOARD for b in d.blocks) < 2:
            return
        for n in d.all_nets():
            by_board = {}
            for r in n.pins:
                by_board.setdefault(r.part.block.board_name, []).append(r)
            if len(by_board) < 2:
                continue
            for board, refs in by_board.items():
                if board == OFF_BOARD:
                    continue
                if not any(r.part.defn.category == "connector" for r in refs):
                    self.add("board.crossing_without_connector", "error",
                             f"net {n.full_name} runs from board {board!r} to {sorted(set(by_board) - {board})} "
                             f"but has no connector pin on {board!r}", [n.full_name])

    def check_connectivity(self):
        for p in self.d.all_parts():
            for pin in p.pins:
                if pin.number in p.conn or pin.number in p.nc or pin.type == "no_connect":
                    continue
                self.add("conn.unconnected_pin", "error",
                         f"{p.ref} pin {pin.number} ({pin.name or '-'}) is neither connected nor marked NC",
                         [f"{p.ref}.{pin.number}"])
            for num in sorted(p.nc, key=_natkey):
                if num not in p.nc_reason and not p.defn.generic and p.defn.category not in ("connector", "relay"):
                    pin = next(x for x in p.pins if x.number == num)
                    self.add("conn.nc_without_reason", "warning",
                             f"{p.ref} pin {num} ({pin.name or '-'}) is left open without a reason "
                             f"(nc_pins(..., reason='datasheet says ...'))", [f"{p.ref}.{num}"])
        for n in self.d.all_nets():
            if not n.pins:
                if any(dom.ref == n.full_name or dom.ref == n.name for dom in self.d.domains.values()):
                    continue          # 0 V of a domain with no copper here (chassis, PE)
                self.add("conn.empty_net", "warning", f"net {n.full_name} has no pins", [n.full_name])
            elif len(n.pins) == 1:
                self.add("conn.single_pin_net", "error", f"net {n.full_name} connects only {n.pins[0].part.ref}.{n.pins[0].pin.number}",
                         [n.full_name])

    def check_pin_types(self):
        for n in self.d.all_nets():
            drivers = [r for r in n.pins if r.pin.type in ("output", "power_out")]
            if len(drivers) > 1:
                self.add("erc.output_conflict", "error",
                         f"net {n.full_name} has {len(drivers)} push-pull drivers: {[str(f'{r.part.ref}.{r.pin.number}') for r in drivers]}",
                         [n.full_name])
            if any(r.pin.type == "no_connect" for r in n.pins):
                self.add("erc.nc_pin_connected", "warning", f"net {n.full_name} connects a pin typed no_connect",
                         [n.full_name])

    def _pins_nets(self, part, keys):
        nets = []
        for k in keys:
            try:
                refs = part.pin(k)
            except DesignError as e:
                self.add("rating.bad_pin", "error", str(e), [part.ref])
                continue
            nets.extend(part.conn[r.pin.number] for r in refs if r.pin.number in part.conn)
        return nets

    def _derate(self, kind, cat):
        table = self.d.derating[kind]
        return table.get(cat, table.get("capacitor" if cat.startswith("capacitor") else cat, table["default"]))

    def _rate(self, check, part, stress, rating, what, extra=""):
        if rating is None or rating <= 0:
            return
        ratio = stress / rating
        lim = self._derate("voltage" if check == "rating.voltage" else
                           "current" if check == "rating.current" else "power", part.defn.category)
        msg = f"{part.ref} ({part.value}): {what} {stress:.3g} vs rating {rating:.3g} ({ratio:.0%}){extra}"
        if ratio > 1.0:
            self.add(check, "error", msg + " — exceeds rating", [part.ref])
        elif ratio > lim:
            self.add(check, "warning", msg + f" — above {lim:.0%} derating", [part.ref])

    def check_voltage(self):
        if not self.d.domains:
            return
        for p in self.d.all_parts():
            r = p.defn.ratings
            if getattr(p, "v_across", None) is not None and r.v_max:
                self._rate("rating.voltage", p, p.v_across, r.v_max, "declared voltage", " (declared v_across)")
            elif r.v_max:
                nets = list(dict.fromkeys(p.conn.values()))
                worst, pair = 0.0, None
                for a, b in itertools.combinations(nets, 2):
                    w, pr = self.vmax_between([a], [b])
                    if w > worst:
                        worst, pair = w, pr
                if pair:
                    self._rate("rating.voltage", p, worst, r.v_max, "voltage",
                               f" between {pair[0].full_name} and {pair[1].full_name}")
            if r.vz and p.p_diss is None and p.i_through is None:
                self._check_zener_conducts(p)
            for lim in r.limits:
                self._check_vlimit(p, lim)
            if r.polarity:
                pos, neg = self._pins_nets(p, [r.polarity[0]]), self._pins_nets(p, [r.polarity[1]])
                if pos and neg:
                    rng = self.vdiff(pos[0], neg[0])
                    if rng and rng[0] < -1.0:
                        self.add("rating.polarity", "error",
                                 f"{p.ref} ({p.value}): polarized part can see {rng[0]:.3g} V reverse "
                                 f"({pos[0].full_name} below {neg[0].full_name})", [p.ref])

    def _check_zener_conducts(self, p):
        """A zener whose nets can exceed its Vz conducts: its current must be limited and declared."""
        vz_max = p.defn.ratings.vz[2]
        pol = self._pins_nets(p, ["1"]), self._pins_nets(p, ["2"])
        if not (pol[0] and pol[1]):
            return
        rng = self.vdiff(pol[0][0], pol[1][0])
        if rng is not None and rng[1] > p.defn.ratings.vz[0]:
            self.add("rating.zener", "warning",
                     f"{p.ref} ({p.value}): its nets allow {rng[1]:.3g} V across it, above its Vz "
                     f"{p.defn.ratings.vz[0]:g}-{vz_max:g} V, so it conducts; declare the limited current "
                     f"(i_through=) or the dissipation (p_diss=) so its power can be checked", [p.ref])

    def _check_vlimit(self, p, lim):
        na, nb = self._pins_nets(p, lim.a), self._pins_nets(p, lim.b)
        what = f"V({'/'.join(map(str, lim.a))}-{'/'.join(map(str, lim.b))})"
        if lim.v_min is None:
            worst, pair = self.vmax_between(na, nb)
            if not pair:
                return
            where = f" ({pair[0].full_name} to {pair[1].full_name})"
        else:
            lo, hi, where = None, None, ""
            for a in na:
                for b in nb:
                    rng = self.vdiff(a, b)
                    if rng is None:
                        continue
                    lo = rng[0] if lo is None else min(lo, rng[0])
                    hi = rng[1] if hi is None else max(hi, rng[1])
            if lo is None:
                return
            if lo < lim.v_min:
                self.add("rating.voltage", "error",
                         f"{p.ref} ({p.value}): {what} can reach {lo:.3g} V, below its {lim.v_min:g} V limit", [p.ref])
            worst = max(hi, 0.0)
        if not lim.derate:
            if worst > lim.v_max:
                self._rate("rating.voltage", p, worst, lim.v_max, what, where)
            return
        if lim.v_rec is not None and worst <= lim.v_rec:
            if worst > lim.v_max:
                self._rate("rating.voltage", p, worst, lim.v_max, what, where)
            return
        if lim.v_rec is not None and worst <= lim.v_max:
            self.add("rating.voltage", "warning",
                     f"{p.ref} ({p.value}): {what} {worst:.3g} V is above the recommended {lim.v_rec:g} V "
                     f"(abs max {lim.v_max:g} V){where}", [p.ref])
            return
        self._rate("rating.voltage", p, worst, lim.v_max, what, where)

    def check_isolation(self):
        d = self.d
        if not d.domains:
            return
        for p in d.all_parts():
            roots = {}
            for num, net in p.conn.items():
                rt = self.root(net)
                if rt is not None:
                    roots.setdefault(rt.name, []).append(num)
            if len(roots) < 2:
                continue
            isos = p.defn.ratings.isolation
            pinsets = []
            for iso in isos:
                a = {r.pin.number for k in iso.a for r in p.pin(k)}
                b = {r.pin.number for k in iso.b for r in p.pin(k)}
                pinsets.append((iso, a, b))
            for (ra, pa), (rb, pb) in itertools.combinations(roots.items(), 2):
                covering = [iso for iso, a, b in pinsets
                            if (set(pa) <= a and set(pb) <= b) or (set(pa) <= b and set(pb) <= a)]
                if not covering:
                    self.add("domain.crossing", "error",
                             f"{p.ref} ({p.value}) bridges isolated domains {ra} (pins {sorted(pa)}) and {rb} "
                             f"(pins {sorted(pb)}) without a rated isolation between those pins",
                             [p.ref])
                    continue
                bar = self.barrier_between(ra, rb)
                if bar is None:
                    self.add("barrier.missing", "error",
                             f"{p.ref} crosses {ra}/{rb} but no Barrier is declared between them", [p.ref])
                    continue
                iso = max(covering, key=lambda i: GRADES[i.grade])
                if GRADES[iso.grade] < GRADES[bar.grade]:
                    self.add("barrier.grade", "error",
                             f"{p.ref} ({p.value}) isolation is {iso.grade}; barrier {bar.a}/{bar.b} needs {bar.grade}",
                             [p.ref])
                if bar.v_test_rms and iso.withstand_rms < bar.v_test_rms:
                    self.add("barrier.withstand", "error",
                             f"{p.ref} ({p.value}) withstand {iso.withstand_rms:.4g} Vrms < required {bar.v_test_rms:g} Vrms",
                             [p.ref])
                if bar.ac:
                    rated = iso.v_work_rms * math.sqrt(2) if iso.v_work_rms else None
                    unit = "V peak (from Vrms)"
                else:
                    # a DC barrier needs a DC working rating; an rms rating is not scaled by sqrt(2)
                    rated = iso.v_work_dc if iso.v_work_dc else iso.v_work_rms
                    unit = "V DC" if iso.v_work_dc else "V (rms rating applied to DC)"
                if rated is not None and rated < bar.v_work * 0.999:
                    self.add("barrier.working_voltage", "error",
                             f"{p.ref} ({p.value}) rated working voltage {rated:.4g} {unit} < barrier "
                             f"{bar.v_work:g} V {'peak' if bar.ac else 'DC'}", [p.ref])
                need = bar.creepage_mm
                if bar.creepage_by_group and iso.material_group in bar.creepage_by_group:
                    need = bar.creepage_by_group[iso.material_group]
                if iso.creepage_mm is not None and iso.creepage_mm < need:
                    self.add("barrier.package_creepage", "error",
                             f"{p.ref} ({p.value}) package creepage {iso.creepage_mm:g} mm < required {need:g} mm"
                             + (f" for material group {iso.material_group}" if iso.material_group else ""), [p.ref])

    def barrier_between(self, root_a, root_b):
        best = None
        for bar in self.d.barriers:
            da, db = self.d.domains.get(bar.a), self.d.domains.get(bar.b)
            if da is None or db is None:
                continue
            ra, rb = self._dom_root(da), self._dom_root(db)
            if {ra, rb} == {root_a, root_b}:
                if best is None or GRADES[bar.grade] > GRADES[best.grade]:
                    best = bar
        return best

    def _dom_root(self, dom):
        try:
            ref = self.d.net_by_name(dom.ref)
        except DesignError:
            return None
        rt = self.root(ref)
        return rt.name if rt else None

    def check_current(self):
        declared = set()
        for p in self.d.all_parts():
            if p.i_through is None or p.defn.category not in SERIES_CATEGORIES:
                continue
            declared.add(id(p))
            rat = p.defn.ratings
            if isinstance(p.i_through, dict):          # per pin/winding: {"1": 2.5, "SEC": 0.4}
                for key, amps in p.i_through.items():
                    for r in p.pin(key):
                        lim = rat.pin_i_max.get(r.pin.number, rat.pin_i_max.get(r.pin.name, rat.i_max))
                        self._rate("rating.current", p, amps, lim, f"declared current through pin {r.pin.number}")
                continue
            lim = rat.i_max if rat.i_max is not None else (min(rat.pin_i_max.values()) if rat.pin_i_max else None)
            self._rate("rating.current", p, p.i_through, lim, "declared current (i_through)")
        for p in self.d.all_parts():
            if p.defn.category not in SERIES_CATEGORIES or id(p) in declared:
                continue
            for r, amps, why in self._pin_currents(p):
                rat = p.defn.ratings
                lim = None
                for k in (r.pin.number, r.pin.name):
                    if k in rat.pin_i_max:
                        lim = rat.pin_i_max[k]
                if lim is None:
                    lim = rat.i_max
                self._rate("rating.current", p, amps, lim,
                           f"current on {r.net.full_name} through pin {r.pin.number} ({why}; set i_through= if the part "
                           f"carries less)")

    def _pin_currents(self, p):
        """(pin ref, amps, why) for a part with no declared i_through, from its nets' i_max.

        A net's i_max is the current of the whole net, not of every pin on it, so:
        - path parts (fuse, diode, LED, inductor, FET, BJT, switch) carry one current end to end: the smaller i_max
          of the nets on their current-carrying pins (a FET's gate and a BJT's base excluded), ground nets left out
          because a return net's total says nothing about one branch; every carrying pin, the ground one included,
          is rated at that current;
        - connectors split a net's current over their contacts on that net; their ground contacts carry the return
          of the other contacts (the sum of those nets' i_max, capped at the ground net's own i_max when it has
          one: in a battery-tap connector the taps' currents do not all return through tap 0), split the same way;
        - relays and transformers (windings or contact sets of different currents) keep the per-pin net current,
          ground nets left out.
        A net with no i_max contributes nothing (as before)."""
        refs = [PinRef(p, pd) for pd in p.pins if p.conn.get(pd.number) is not None]
        is_gnd = lambda r: r.net.kind == "ground"
        cat = p.defn.category
        if cat in PATH_CATEGORIES:
            carrying = [r for r in refs if r.pin.name not in CONTROL_PINS.get(cat, ())]
            amps = [r.net.i_max for r in carrying if not is_gnd(r) and r.net.i_max]
            if not amps:
                return []
            a = min(amps)
            return [(r, a, "the part's path current: smallest i_max of its nets") for r in carrying]
        if cat == "connector":
            out = []
            by_net = {}
            for r in refs:
                by_net.setdefault(id(r.net), []).append(r)
            ret = sum(rs[0].net.i_max for rs in by_net.values() if not is_gnd(rs[0]) and rs[0].net.i_max)
            for rs in by_net.values():
                n = rs[0].net
                # the return is at most the other contacts' sum, and never more than the ground net's own total
                total = (min(ret, n.i_max) if n.i_max else ret) if is_gnd(rs[0]) else (n.i_max or 0)
                if total:
                    out += [(r, total / len(rs), f"{total:g} A over {len(rs)} contact(s)"
                             + (" (return of the other contacts)" if is_gnd(rs[0]) else "")) for r in rs]
            return out
        return [(r, r.net.i_max, "net current") for r in refs if not is_gnd(r) and r.net.i_max]

    def check_power(self):
        for p in self.d.all_parts():
            rat = p.defn.ratings
            if p.p_diss is not None:
                if rat.p_max:
                    self._rate("rating.power", p, p.p_diss, rat.p_max, "dissipation (W)")
                elif p.p_diss > 0.25:
                    self.add("rating.power", "warning",
                             f"{p.ref} ({p.value}) dissipates {p.p_diss:g} W but has no power rating to check against",
                             [p.ref])
                continue
            if rat.vz and rat.p_max and isinstance(p.i_through, (int, float)):
                self._rate("rating.power", p, rat.vz[2] * p.i_through, rat.p_max,
                           f"zener dissipation Vz max {rat.vz[2]:g} V x i_through {p.i_through:g} A (W)")
                continue
            if p.defn.category == "resistor" and rat.p_max and len(p.conn) == 2:
                ohms = parse_value(p.value)
                a, b = list(p.conn.values())
                rng = self.vdiff(a, b)
                if ohms and rng:
                    v = max(abs(rng[0]), abs(rng[1]))
                    pw = v * v / ohms
                    if pw > rat.p_max * self._derate("power", "resistor"):
                        self.add("rating.power", "warning" if pw <= rat.p_max else "error",
                                 f"{p.ref} ({p.value}): worst case {v:.3g} V across it gives {pw:.3g} W vs "
                                 f"rating {rat.p_max:g} W — set p_diss from a calculation or fix the net ranges",
                                 [p.ref])

    def check_library(self):
        if self.sym is None:
            self.add("lib.unchecked", "info", "KiCad libraries not found; symbol/footprint checks skipped")
            return
        seen = set()
        for p in self.d.all_parts():
            defn = p.defn
            if id(defn) in seen:
                continue
            seen.add(id(defn))
            who = f"{p.ref} ({defn.mpn or defn.value})"
            if defn.symbol and not self.sym.has(defn.symbol):
                self.add("lib.symbol_missing", "error", f"{who}: symbol {defn.symbol} not in KiCad libraries", [p.ref])
                continue
            if defn.symbol:
                s = self.sym.get(defn.symbol)
                hidden = [x for x in s.pins if x.hidden and x.type in ("power_in", "power_out")]
                if hidden and not s.power:
                    self.add("lib.hidden_power_pins", "error",
                             f"{who}: symbol {defn.symbol} has hidden power pins {[x.number for x in hidden]} that "
                             f"connect implicitly by name; use a symbol without hidden pins", [p.ref])
            if not p.on_board:
                continue
            if not defn.footprint:
                self.add("lib.footprint_missing", "error", f"{who}: no footprint", [p.ref])
                continue
            if defn.footprint.startswith("custom:") and not self.fp.has(defn.footprint):
                self.add("lib.footprint_custom", "warning",
                         f"{who}: custom footprint {defn.footprint} is not drawn yet "
                         f"(designs/<slug>/footprints/custom.pretty/{defn.footprint.split(':', 1)[1]}.kicad_mod)",
                         [p.ref])
                continue
            if not self.fp.has(defn.footprint):
                self.add("lib.footprint_missing", "error", f"{who}: footprint {defn.footprint} not in KiCad libraries", [p.ref])
                continue
            pads = self.fp.pads(defn.footprint)
            pins = {x.number for x in p.pins}
            missing = sorted(pins - pads, key=_natkey)
            if getattr(self.fp, "legacy", lambda _: False)(defn.footprint):
                self.add("lib.footprint_legacy", "warning", f"{who}: {defn.footprint} is in {LEGACY_HINT}", [p.ref])
            if missing:
                found = (f"pads {sorted(pads, key=_natkey)}" if pads else
                         "no named pads read from the file; check it opens in KiCad")
                self.add("lib.pad_mismatch", "error",
                         f"{who}: symbol pins {missing} have no pad in {defn.footprint} ({found})",
                         [p.ref])
            extra = sorted(pads - pins, key=_natkey)
            if extra:
                self.add("lib.unused_pads", "warning",
                         f"{who}: footprint {defn.footprint} pads {extra} have no symbol pin (left unconnected)",
                         [p.ref])

    def check_bom(self):
        seen = set()
        for p in self.d.all_parts():
            defn = p.defn
            if id(defn) in seen or not defn.in_bom:
                continue
            seen.add(id(defn))
            if not defn.generic and not defn.mpn:
                self.add("bom.no_mpn", "warning", f"{p.ref} ({p.value}): no manufacturer part number", [p.ref])
            lc = (defn.lifecycle or "").lower()
            if lc in ("obsolete", "eol", "discontinued"):
                self.add("bom.lifecycle", "error", f"{p.ref} ({defn.mpn}) is {defn.lifecycle}", [p.ref])
            elif lc in ("nrnd", "last time buy", "ltb"):
                self.add("bom.lifecycle", "warning", f"{p.ref} ({defn.mpn}) is {defn.lifecycle}", [p.ref])

    def check_provenance(self):
        """Facts the LLM typed (pins, pin maps, ratings) must say where they came from."""
        seen = set()
        for p in self.d.all_parts():
            defn = p.defn
            if id(defn) in seen or defn.generic:
                continue
            seen.add(id(defn))
            who = f"{p.ref} ({defn.mpn or defn.value})"
            if not defn.datasheet and defn.category not in ("mechanical", "testpoint", "heatsink"):
                self.add("part.no_datasheet", "warning", f"{who}: no datasheet URL", [p.ref])
            need = []
            if defn.pins:
                need.append("pins")
            if defn.pinmap:
                need.append("pinmap")
            if defn.pin_names:
                need.append("pin_names")
            r = defn.ratings
            if r.limits or r.isolation or (r.v_max and defn.category not in ("resistor", "capacitor_ceramic")):
                need.append("ratings")
            missing = [k for k in need if not defn.source.get(k)]
            if missing:
                self.add("part.no_provenance", "warning",
                         f"{who}: no source for {', '.join(missing)} (PartDef(source={{'pins': 'DS rev, page, table'}}))",
                         [p.ref])

    def check_dc_bias(self):
        """Class II MLCCs lose much of their capacitance under DC bias: estimate it (mlcc_bias_factor) at the
        worst voltage across the part. fields={'Ceff': ...} (a vendor curve) overrides the estimate."""
        for p in self.d.all_parts():
            defn = p.defn
            if defn.category != "capacitor_ceramic" or len(p.conn) != 2 or "Ceff" in {**defn.fields, **p.fields}:
                continue
            diel = str(defn.fields.get("Dielectric", "X7R")).upper()
            if diel in ("C0G", "NP0", "COG", "NPO"):
                continue
            farads = parse_value(p.value)
            vr = defn.ratings.v_max
            if not farads or farads < 1e-6 or not vr:
                continue
            if p.v_across is not None:
                v = p.v_across
            else:
                a, b = list(p.conn.values())
                rng = self.vdiff(a, b)
                if rng is None:
                    continue
                v = max(abs(rng[0]), abs(rng[1]))
            pkg = mlcc_package(defn)
            k = mlcc_bias_factor(farads, v, pkg, diel) if pkg else None
            who = f"{p.ref} ({p.value} {diel} {vr:g} V{' ' + pkg if pkg else ''})"
            if k is None:
                if v / vr > 0.5:
                    self.add("rating.dc_bias", "warning",
                             f"{who} runs at {v:.3g} V ({v / vr:.0%} of rating) and its package is unknown, so its "
                             f"DC-bias loss cannot be estimated; record the vendor curve as fields={{'Ceff': '...'}}",
                             [p.ref])
                continue
            est = (f"{who} at up to {v:.3g} V ({v / vr:.0%} of rating): estimated Ceff ~{_si_f(k * farads)} "
                   f"({k:.0%} of nominal; typical, +/-15 % of nominal, from the field proxy V sqrt(C/volume) fitted "
                   f"to vendor curves, docs/research/physics/component-priors.md#mlcc-dc-bias-and-esr; a part rated "
                   f"far above the bias usually keeps more). Check the calculation that needs it; a vendor figure "
                   f"goes in fields={{'Ceff': '...'}}")
            # warn where both the rating (over half) and the estimate (under half left) say so; the model ignores the
            # rating, so below half of it the estimate is reported as info (conservative for high-rated parts)
            if v / vr > 0.5 and k < 0.5:
                self.add("rating.dc_bias", "warning", est, [p.ref])
            elif v / vr > 0.5 or k < 0.5:
                self.add("rating.dc_bias", "info", est, [p.ref])

    def check_protection(self):
        for n in self.d.all_nets():
            for t in n.threats:
                cats = THREATS[t]
                # overcurrent protection must be in series on the wire's own net; other
                # protectors may sit one series element in (e.g. a TVS behind a PTC or ferrite)
                reach = [n] if t == "overcurrent" else [n] + self._one_series_hop(n)
                if t == "reverse_polarity" and any(r.part.defn.category in ("fuse", "ptc") for r in n.pins) \
                        and any(r.part.defn.category == "tvs" for m in reach for r in m.pins):
                    continue          # crowbar: the TVS conducts on reversal and the fuse opens
                if not any(r.part.defn.category in cats for m in reach for r in m.pins):
                    self.add("protect.threat", "error",
                             f"external net {n.full_name} declares threat '{t}' but has no {'/'.join(cats)} on it",
                             [n.full_name])
                elif t == "overcurrent" and self._ahead_of_fuse(n):
                    self.add("protect.threat", "error",
                             f"external net {n.full_name} declares threat 'overcurrent' but "
                             f"{', '.join(self._ahead_of_fuse(n))} sit on the wire side of its fuse", [n.full_name])
        for n in self.d.all_nets():
            if not n.external or n.kind not in ("power", "hv", "mains", "high_current"):
                continue
            if not any(r.part.defn.category in ("fuse", "ptc") for r in n.pins):
                self.add("protect.entry_fuse", "warning",
                         f"external {n.kind} net {n.full_name} reaches the board without a fuse/PTC on it",
                         [n.full_name])
            elif self._ahead_of_fuse(n):
                self.add("protect.entry_fuse", "warning",
                         f"external {n.kind} net {n.full_name} has a fuse, but {', '.join(self._ahead_of_fuse(n))} "
                         f"connect on the wire side of it (the fuse protects only its own branch)", [n.full_name])

    # parts that may sit between the wire and its fuse without needing its protection
    ENTRY_SIDE_OK = ("connector", "fuse", "ptc", "tvs", "mov", "testpoint", "mechanical")

    def _ahead_of_fuse(self, net):
        """Parts on an external net, other than connectors, protectors and fuses, i.e. loads
        a fuse on that net does not protect."""
        return sorted({r.part.ref for r in net.pins if r.part.defn.category not in self.ENTRY_SIDE_OK},
                      key=_natkey)

    def _one_series_hop(self, net):
        out = []
        for r in net.pins:
            p = r.part
            if p.defn.category in ("fuse", "ptc", "inductor", "resistor") and len(p.conn) == 2:
                out.extend(m for m in p.conn.values() if m is not net)
        return out

    # parts that need no i_off on an always-on net: resistors are computed, the rest carry no off-state current
    STANDBY_EXEMPT = ("resistor", "capacitor", "capacitor_ceramic", "capacitor_film", "connector", "fuse", "ptc",
                      "inductor", "testpoint", "mechanical", "heatsink", "switch", "crystal", "transformer",
                      "thermistor")
    HIGH_Z = ("input", "bidirectional", "tri_state")    # IC pins that take no DC current from a divider node

    def check_standby(self):
        """Design.standby_budget: sum declared i_off, divider currents from the netlist and lumps against a limit."""
        d = self.d
        for bud in d.standby:
            nets = []
            for name in bud.nets:
                try:
                    nets.append(d.net_by_name(name))
                except DesignError:
                    self.add("standby.net", "error", f"standby_budget: no net {name!r}", [name])
            on = {id(n) for n in nets}
            rows, counted = [], set()
            for p in d.all_parts():
                if p.dnp or not p.on_board:
                    continue
                i = p.i_off
                if i is None and p.defn.i_off is not None and any(id(n) in on for n in p.conn.values()):
                    i = p.defn.i_off
                if i is None:
                    continue
                typ, mx = _typ_max(i)
                rows.append((p.ref, typ, mx, "declared i_off"))
                counted.add(p.ref)
            for n in nets:
                volts = bud.v.get(n.name, bud.v.get(n.full_name))
                if volts is None:
                    volts = _typical_volts(n, self.vabs(n))
                if volts is None:
                    self.add("standby.net", "warning", f"standby_budget: {n.full_name} has no voltage; its dividers "
                             f"are not computed (give v={{'{n.name}': volts}})", [n.full_name])
                    continue
                for refs, amps, path in self._dividers(n, volts, on, counted):
                    rows.append(("/".join(refs), amps, amps, f"divider {path} from {n.full_name} at {volts:g} V"))
                    counted |= set(refs)
            for label, i in bud.extra.items():
                typ, mx = _typ_max(i)
                rows.append((label, typ, mx, "lumped (extra=)"))
            covered = set(re.findall(r"[A-Za-z]+[0-9]+", " ".join(bud.extra)))
            for p in d.all_parts():
                if p.ref in counted or p.ref in covered or p.dnp or not p.on_board:
                    continue
                if p.defn.category in self.STANDBY_EXEMPT:
                    continue
                hit = sorted({n.full_name for n in p.conn.values() if id(n) in on})
                if hit:
                    self.add("standby.undeclared", "warning",
                             f"{p.ref} ({p.value}) sits on always-on {', '.join(hit)} but declares no i_off "
                             f"(off-state current: shutdown Iq or leakage from its datasheet's EC table; i_off=0 "
                             f"if it truly draws none)", [p.ref])
            typ = sum(r[1] for r in rows)
            mx = sum(r[2] for r in rows)
            lines = "; ".join(f"{lab} {t * 1e6:.3g}" + (f" (max {m * 1e6:.3g})" if m != t else "") + f" uA [{how}]"
                              for lab, t, m, how in sorted(rows, key=lambda r: -r[1]))
            what = f"standby from {', '.join(n.full_name for n in nets)}" + (f" ({bud.req})" if bud.req else "") + \
                (f", {bud.state}" if bud.state else "")
            self.add("standby.budget", "info",
                     f"{what}: {typ * 1e6:.3g} uA typical, {mx * 1e6:.3g} uA max, limit {bud.limit_uA:g} uA: {lines}",
                     [bud.req] if bud.req else [])
            if typ * 1e6 > bud.limit_uA:
                self.add("standby.budget", "error",
                         f"{what}: {typ * 1e6:.3g} uA typical exceeds the {bud.limit_uA:g} uA budget", [bud.req] if bud.req else [])
            elif mx * 1e6 > bud.limit_uA:
                self.add("standby.budget", "warning",
                         f"{what}: {mx * 1e6:.3g} uA with every contributor at its maximum exceeds the "
                         f"{bud.limit_uA:g} uA budget ({typ * 1e6:.3g} uA typical)", [bud.req] if bud.req else [])

    def _dividers(self, src, volts, on, skip):
        """[(resistor refs, amps, path)] for resistor networks from `src` to ground whose inner nodes take no other
        DC current (only resistors, capacitors and high-impedance IC inputs); a resistor into another always-on
        net or into a node that feeds a load carries that load's current, counted at the load, and is left out."""
        d = self.d
        root = self.root(src)

        def is_res(r):
            return r.part.defn.category == "resistor" and len(set(map(id, r.part.conn.values()))) == 2 \
                and len(r.part.conn) == 2 and r.part.ref not in skip \
                and not r.part.dnp and parse_value(r.part.value)

        def kind(n):
            if n is src:
                return "src"
            if n.kind == "ground" and self.root(n) is root:
                return "gnd"
            if id(n) in on:
                return "load"
            for r in n.pins:
                cat = r.part.defn.category
                if is_res(r) or cat.startswith("capacitor") or cat == "testpoint":
                    continue
                if cat in ("ic", "opto", "module") and r.pin.type in self.HIGH_Z:
                    continue
                if cat == "mosfet" and r.pin.name == "G":
                    continue
                return "load"
            return "inner"

        def other(r):
            return next(n for n in r.part.conn.values() if n is not r.net)

        out = []
        seen_res = set()
        for start in [r for r in src.pins if is_res(r)]:
            if start.part.ref in seen_res:
                continue
            # the cluster of inner nodes reachable from this resistor
            res, nodes, stack = {}, {}, [start]
            while stack:
                r = stack.pop()
                if r.part.ref in res:
                    continue
                a, b = r.net, other(r)
                ka, kb = kind(a), kind(b)
                if "load" in (ka, kb):
                    continue
                res[r.part.ref] = (a, b, parse_value(r.part.value))
                for n, k in ((a, ka), (b, kb)):
                    if k == "inner" and id(n) not in nodes:
                        nodes[id(n)] = n
                        stack.extend(x for x in n.pins if is_res(x))
            seen_res |= set(res)
            if not res:
                continue
            v = _solve_nodes(nodes, res, src, volts, kind)
            amps = sum((volts - v.get(id(b), 0.0 if kind(b) == "gnd" else volts)) / ohm
                       for a, b, ohm in res.values() if a is src) + \
                sum((volts - v.get(id(a), 0.0 if kind(a) == "gnd" else volts)) / ohm
                    for a, b, ohm in res.values() if b is src)
            if amps > 1e-12:
                refs = sorted(res, key=_natkey)
                out.append((refs, amps, "-".join(refs)))
        return out

    def check_calcs(self):
        ops = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b,
               ">": lambda a, b: a > b, "==": lambda a, b: math.isclose(a, b, rel_tol=1e-6)}
        for c in self.d.calcs:
            if c.limit is None:
                continue
            if not ops[c.op](c.value, c.limit):
                self.add("calc.limit", c.severity,
                         f"{c.name} = {c.value:.4g} {c.unit} violates {c.op} {c.limit:g} {c.unit}"
                         + (f" ({c.note})" if c.note else ""), [c.name])

    def check_intent(self):
        d = self.d
        for h in d.hazards:
            if not h.parts:
                self.add("hazard.procedural", "warning",
                         f"{h.id}: mitigated only procedurally ({h.mitigation})", [h.id])
            for x in h.parts:
                try:
                    d.find_part(x)
                except DesignError:
                    self.add("hazard.unknown_part", "error", f"{h.id}: mitigation part {x} does not exist", [h.id])
        for q in d.questions:
            if q.blocking and not q.answer:
                self.add("intent.blocking_question", "info",
                         f"{q.id} is BLOCKING and unanswered: {q.text}", [q.id])
        unknown = []
        d.place.resolve(unknown)
        for u in sorted(set(unknown)):
            self.add("place.unknown_object", "warning",
                     f"placement relation names {u!r}, which is not a part, domain, block or net", [u])
        for rel in d.place.relations:
            if rel["kind"] == "separate":
                a, b = rel["a"].removeprefix("domain:"), rel["b"].removeprefix("domain:")
                for x in (a, b):
                    if x not in d.domains:
                        self.add("place.unknown_object", "error", f"separate(): {x!r} is not a domain", [x])
                if not any({bar.a, bar.b} == {a, b} for bar in d.barriers):
                    self.add("place.separate_without_barrier", "error",
                             f"separate({a}, {b}) has no matching Barrier giving its spacing", [a, b])

    def apply_waivers(self, final=False):
        used = set()
        for f in self.findings:
            for i, w in enumerate(self.d.waivers):
                if w.check not in (f.check, "*"):
                    continue
                hay = " ".join([f.message] + f.objects)
                if re.search(w.match, hay):
                    f.waived_by = f"{w.by}: {w.reason}"
                    used.add(i)
                    break
        if final:
            self.findings = [f for f in self.findings if f.check != "waiver.unused"]
            for i, w in enumerate(self.d.waivers):
                if i not in used:
                    self.add("waiver.unused", "warning",
                             f"waiver {w.check} /{w.match}/ matches no finding; remove it ({w.reason[:60]})")


# MLCC DC bias (class II): C(V)/C = 1 / (1 + (z / DCB_Z0)^DCB_P), z = V sqrt(C[F] / body volume [mm3]), volume
# L x W x min(W, 2.5 mm). The loss follows the DC field in the layers; a footprint gives the body, and at fixed
# permittivity C/volume ~ 1/t^2, so V/t ~ V sqrt(C/volume) for a part that fills its body. Same model and constants
# as haslam.excite.models.mlcc_bias_factor (fitted to Murata/TDK/Samsung typical curves and EPCI 2019, +/-0.15:
# docs/research/physics/component-priors.md#mlcc-dc-bias-and-esr), copied because haslam's module needs numpy.
# The rated voltage is not in the curve (no source gave a usable law; a higher-rated part of the same C and body
# has thicker layers and loses less, so ignoring it is conservative). Y5V/Z5U lose about twice as fast.
DCB_Z0 = 0.011
DCB_P = 1.3
MLCC_LW = {"0201": (0.6, 0.3), "0402": (1.0, 0.5), "0603": (1.6, 0.8), "0805": (2.0, 1.25), "1206": (3.2, 1.6),
           "1210": (3.2, 2.5), "1812": (4.5, 3.2), "2220": (5.7, 5.0)}


def mlcc_bias_factor(farads, volts, pkg, diel="X7R"):
    """C(V)/C of a class II MLCC of nominal `farads` at DC `volts`, imperial package `pkg`; None if unknown."""
    if str(diel).upper() in ("C0G", "NP0", "COG", "NPO"):
        return 1.0
    lw = MLCC_LW.get(pkg)
    if lw is None or not farads:
        return None
    if not volts or volts <= 0:
        return 1.0
    z = volts * math.sqrt(farads / (lw[0] * lw[1] * min(lw[1], 2.5)))
    z0 = DCB_Z0 / (2.0 if str(diel).upper() in ("Y5V", "Z5U") else 1.0)
    return 1.0 / (1.0 + (z / z0) ** DCB_P)


def mlcc_package(defn):
    """Imperial package code of a ceramic capacitor card: fields Package, else the KiCad footprint name."""
    pkg = str(defn.fields.get("Package", "") or "")
    if pkg in MLCC_LW:
        return pkg
    m = re.search(r"[_:]C_(\d{4})_\d{4}Metric", defn.footprint or "")
    return m.group(1) if m and m.group(1) in MLCC_LW else None


def _si_f(farads):
    for scale, unit in ((1e-6, "uF"), (1e-9, "nF"), (1e-12, "pF")):
        if farads >= scale:
            return f"{farads / scale:.3g} {unit}"
    return f"{farads:.3g} F"


def _typ_max(i):
    """(typ, max) amps of an i_off: a number, or (typ, max)."""
    if isinstance(i, (tuple, list)):
        return float(i[0]), float(i[-1])
    return float(i), float(i)


def _typical_volts(net, vabs):
    """A net's standby voltage: its v_typ (the typical of (lo, typ, hi)), else the top of its range."""
    if net.v_typ is not None:
        return float(net.v_typ[1] if isinstance(net.v_typ, (tuple, list)) else net.v_typ)
    return float(vabs[1]) if vabs else None


def _solve_nodes(nodes, res, src, volts, kind):
    """Node voltages {id(net): V} of a resistor network: src at `volts`, ground at 0, inner nodes by KCL
    (Gaussian elimination; the networks are a few nodes). A node with no path to src or ground floats at 0 A."""
    idx = {k: i for i, k in enumerate(nodes)}
    n = len(idx)
    if not n:
        return {}
    A = [[0.0] * (n + 1) for _ in range(n)]
    for a, b, ohm in res.values():
        g = 1.0 / ohm
        for x, y in ((a, b), (b, a)):
            if id(x) not in idx:
                continue
            i = idx[id(x)]
            A[i][i] += g
            if id(y) in idx:
                A[i][idx[id(y)]] -= g
            elif kind(y) == "src":
                A[i][n] += g * volts
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(A[r][c]))
        if abs(A[piv][c]) < 1e-30:
            continue
        A[c], A[piv] = A[piv], A[c]
        for r in range(n):
            if r != c and A[r][c]:
                f = A[r][c] / A[c][c]
                A[r] = [x - f * y for x, y in zip(A[r], A[c])]
    return {k: (A[i][n] / A[i][i] if abs(A[i][i]) > 1e-30 else volts) for k, i in idx.items()}


def _natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]


def summarize(findings):
    out = {"error": 0, "warning": 0, "info": 0, "waived": 0}
    for f in findings:
        if f.waived_by:
            out["waived"] += 1
        else:
            out[f.severity] += 1
    return out
