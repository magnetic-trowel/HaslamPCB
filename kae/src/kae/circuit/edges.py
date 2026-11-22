# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Is this net fast? Edge rate against route delay (docs/topics/llm/net-role-classification.md).

A net is electrically long when its route delay exceeds a fraction of its driver's rise time:
over t_r/6 it wants signal-integrity review, over t_r/2 it rings unless the edge is slowed or
the line terminated (Johnson; ADI MT-097; the threshold is CONTESTED, see
docs/topics/rules/si-fundamentals.md). Names do not decide it: an HDMI_HPD line is slow, a
74LVC output crossing a board is fast.

    driver_edge(nl, roles, net) -> Edge | None   the fastest driver on the net and its t_r
    t_pd_ps_mm(er, outer)                         propagation delay per mm
    critical_mm(t_r_ns, t_pd)                     (review, terminate) lengths: t_r/6 and t_r/2
    long_net_hazards(brief, board)                kae.hazards entries for routed or placed nets

Rise times come from the driver's family, never from an LLM guess; every value names its
source and is marked `assumed` (a family default, not this part's datasheet or IBIS model).
The value taken is the fastest plausible edge of the family (the strongest slew setting a
firmware may choose), so a flag errs towards review. Nets of interfaces whose standards
define the termination and edge (USB, PCIe, HDMI, LVDS, MIPI, Ethernet MDI, DDR, CAN, RS-485)
are judged by their interface rules, not here. Parts without a family row have no t_r:
their nets are not judged, and the brief says so ('edge': {'t_r_ns': None, ...}).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

C_MM_NS = 299.792458          # speed of light, mm/ns
ER_DEFAULT = 4.5              # FR-4 when the board states no stackup (kae.board.kicad_file's default)
REVIEW, TERMINATE = 6.0, 2.0  # route delay > t_r/6: review; > t_r/2: terminate or slow the edge

# interfaces whose standards fix edge and termination: their rule packs judge them (net-role-classification.md:
# "protocol data-rate and impedance tables stay deterministic in the interface rule packs")
JUDGED_BY_INTERFACE = ('usb2', 'usb3', 'pcie', 'sata', 'hdmi', 'displayport', 'mipi', 'lvds', 'serdes', 'ethernet_mdi',
                       'ddr', 'can', 'rs485')
DRIVER_TYPES = ('output', 'bidirectional', 'tri_state', 'open_collector', 'open_emitter')
NOT_DRIVER_FN = re.compile(r'^(P?GND\w*|VSS\w*|VDD\w*|VCC\w*|AVDD\w*|DVDD\w*|IOVDD\w*|VBAT\w*|VIN\w*|3V3|5V|NC|DNC|EP|PAD)$')

# (family, part-text regex, t_r ns (10-90 %, fastest plausible setting), source). First match wins; the regexes
# run on Part.text() (value, lib id, part-number fields). [S]: read from a snippet or secondary source.
_TI_HC = 'TI SN74HC04 (SCLS078H) 6.7: t_t typ 6 ns at 6 V, 8 ns at 4.5 V, CL 50 pF'
_TI_HCT = 'TI SN74HCT04 (SCLS042F): t_t typ 8 ns at 5.5 V, CL 50 pF'
_PCB_TABLE = 'Complete PCB Design (Elsevier), appendix "Rise and fall times for various logic families" [S]'
_E2E = 'TI E2E logic forum (879178 and an LVC thread): LVC about 1.5-2 ns at 3.3 V into 30 pF; AHC about 0.7 ns/V [S]'
_SIT = 'SiTime SiT8008B: t_r typ 1 ns (20-80 %) at 15 pF, 3.3 V; x1.33 to 10-90 % for a linear edge'
_STM32 = ('ST DS8626 (STM32F405/407) "I/O AC characteristics": OSPEEDR=11 t_r/t_f 2.5 ns at 10 pF, 4 ns at 30 pF '
          '(reset default OSPEEDR=00: 100 ns) [S]')
_AVR = 'Microchip ATmega328P datasheet Table 28-6: SPI master rise/fall 3.6 ns typ (no GPIO figure is given)'
_MCU = ('assumed like STM32 at its fastest setting (2.5 ns): the RP2040, ESP32 and nRF datasheets give no GPIO rise '
        'time and no public IBIS model was found; RP2040 resets to slow slew')
_FPGA = ('assumed: FPGA datasheets give no LVCMOS edge ("see the IBIS models"); taken as fast as a CMOS oscillator '
         'output at light load (SiT8008B 0.46 ns 20-80 % at 5 pF)')
# (family, part-text regex, t_r ns 10-90 %, source): logic first (a '74LVC' must not read as '74HC')
FAMILY_TR = [
    ('74LVC', re.compile(r'(?<![A-Z0-9])(SN)?74(A?LVCH?|ALVCH?|AVC|LVT|AUC)\d|\bNC7S[ZV]\d', re.I), 1.5, _E2E),
    ('74AC', re.compile(r'(?<![A-Z0-9])(SN|MC|CD|M)?74(ACT?|VHCT?|FCT?)\d|(?<![A-Z0-9])(SN|MC)?74F\d', re.I), 1.5, _PCB_TABLE),
    ('74AHC', re.compile(r'(?<![A-Z0-9])(SN)?74AHCT?\d', re.I), 2.3, _E2E),
    ('74HCT', re.compile(r'(?<![A-Z0-9])(SN|MC|CD|M|NL|TC)?74HCT\d', re.I), 8.0, _TI_HCT),
    ('74HC', re.compile(r'(?<![A-Z0-9])(SN|MC|CD|M|NL|TC)?74HC\d', re.I), 6.0, _TI_HC),
    ('74LS', re.compile(r'(?<![A-Z0-9])(SN|DM)?74A?LS\d', re.I), 10.0, _PCB_TABLE),
    ('STM32', re.compile(r'\bSTM32', re.I), 2.5, _STM32),
    ('AVR', re.compile(r'\bAT(MEGA|TINY|XMEGA)|\bAT90', re.I), 3.6, _AVR),
]
MCU_MODULE = re.compile(r'ESP32|ESP8266|ESP-\d|WROOM|WROVER|RP2040|RP2350|\bPico\b|XIAO|nRF5\d|Arduino|STM32|ATmega', re.I)
SUBTYPE_TR = {'mcu': (2.5, _MCU), 'fpga': (0.5, _FPGA), 'oscillator': (1.3, _SIT)}


@dataclass
class Edge:
    t_r_ns: float
    family: str
    source: str
    driver: str            # 'U3.12 (PA5)'
    ref: str               # driver part key
    pin: str               # driver pad number
    refdes: str = ''       # driver reference as on the board
    assumed: bool = True

    def to_json(self) -> dict:
        return {'t_r_ns': self.t_r_ns, 'family': self.family, 'source': self.source, 'driver': self.driver,
                'driver_ref': self.refdes, 'driver_pin': self.pin, 'assumed': self.assumed}


def t_pd_ps_mm(er: float, outer: bool) -> float:
    """Propagation delay (ps/mm): stripline sqrt(er)/c; microstrip sqrt(0.475 er + 0.67)/c, the IPC-2141 /
    Motorola MECL handbook fit for FR-4 class microstrip."""
    e = (0.475 * er + 0.67) if outer else er
    return 1000.0 * math.sqrt(e) / C_MM_NS


def critical_mm(t_r_ns: float, t_pd: float) -> tuple[float, float]:
    """(review, terminate) route lengths in mm: delays of t_r/6 and t_r/2."""
    return (1000.0 * t_r_ns / REVIEW / t_pd, 1000.0 * t_r_ns / TERMINATE / t_pd)


def part_edge(part, pr) -> tuple[float, str, str] | None:
    """(t_r ns, family, source) for a part that can drive a net, from its family, or None."""
    if pr.kind not in ('ic', 'module', 'oscillator'):
        return None
    text = part.text()
    for fam, rx_, tr, src in FAMILY_TR:
        if rx_.search(text):
            return tr, fam, src
    key = 'oscillator' if pr.kind == 'oscillator' else pr.subtype
    if pr.kind == 'module' and MCU_MODULE.search(text):
        key = 'mcu'
    if key in SUBTYPE_TR:
        tr, src = SUBTYPE_TR[key]
        return tr, key, src
    return None


def _drives(pin, pr) -> bool:
    if pin.nc or NOT_DRIVER_FN.match(pin.fn or ''):
        return False
    if pin.ptype in DRIVER_TYPES:
        return True
    # untyped pins (KiCad 5 and imported boards): an oscillator's output, or any IC or module signal pin
    return pin.ptype in ('', 'unspecified')


def driver_edge(nl, roles, net: str) -> Edge | None:
    """The fastest-edged driver on `net`, or None when no pin on it belongs to a family with a known t_r."""
    nv = nl.nets.get(net)
    if nv is None:
        return None
    best = None
    for p in nv.pins:
        pr = roles.parts.get(p.ref)
        if pr is None or not _drives(p, pr):
            continue
        e = part_edge(nl.parts[p.ref], pr)
        if e and (best is None or e[0] < best.t_r_ns):
            best = Edge(e[0], e[1], e[2], p.label.replace(p.ref, nl.parts[p.ref].refdes, 1), p.ref, p.number,
                        refdes=nl.parts[p.ref].refdes)
    return best


def board_t_pd(nl) -> tuple[float, str, bool]:
    """(t_pd ps/mm, basis, assumed) for routes on this board: the slowest layer kind it has (stripline on a
    board with inner layers, microstrip on a two-layer one), at the stackup's highest stated er."""
    st = getattr(nl, 'stackup', None)
    ers = [e for e in (getattr(st, 'er', None) or []) if e]
    er = max(ers) if ers else ER_DEFAULT
    outer = st is None or len(getattr(st, 'copper', None) or []) <= 2
    assumed = st is None or getattr(st, 'source', 'default') != 'file' or not ers
    kind = 'microstrip (two copper layers)' if outer else 'stripline (inner layers)'
    return t_pd_ps_mm(er, outer), f"{kind}, er {er:g}{' (assumed FR-4)' if assumed else ' (board stackup)'}", assumed


def net_edge(nl, roles, net: str, t_pd=None) -> dict:
    """The brief's 'edge' entry of a net: its driver's t_r (or None), the review and terminate lengths on this
    board, and whether an unterminated route on it can reach the terminate length (`can_ring`)."""
    nr = roles.nets.get(net)
    iface = (nr.attrs.get('interface') if nr is not None else None) or None
    if iface in JUDGED_BY_INTERFACE:
        return {'t_r_ns': None, 'judged_by': f"interface rules ({iface})"}
    e = driver_edge(nl, roles, net)
    if e is None:
        return {'t_r_ns': None, 'judged_by': 'no driver with a known edge family'}
    t_pd, basis, assumed = t_pd or board_t_pd(nl)
    rev, term = critical_mm(e.t_r_ns, t_pd)
    d = e.to_json()
    d.update(t_pd_ps_mm=round(t_pd, 2), t_pd_basis=basis, review_mm=round(rev, 1), terminate_mm=round(term, 1))
    if nl.extent_mm:
        span = nl.extent_mm[0] + nl.extent_mm[1]
        d['board_span_mm'] = round(span, 1)
        d['can_ring'] = term < span
    return d


# ------------------------------------------------------------------------------- lengths on a placed or routed board
def _route_graph(board, net):
    """Adjacency {node: [(node, mm, layer)]} of `net`'s tracks and vias; nodes are (x, y, layer) rounded to 1 um."""
    adj = {}

    def key(x, y, ly):
        return (round(x, 3), round(y, 3), ly)

    def link(a, b, mm, ly):
        adj.setdefault(a, []).append((b, mm, ly))
        adj.setdefault(b, []).append((a, mm, ly))
    for t in getattr(board, 'tracks', None) or []:
        if t.net != net:
            continue
        pts = [t.start] + ([t.mid] if getattr(t, 'mid', None) else []) + [t.end]
        mm = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        link(key(*t.start, t.layer), key(*t.end, t.layer), mm, t.layer)
    for v in getattr(board, 'vias', None) or []:
        if v.net != net:
            continue
        lys = list(v.layers or [])
        for i in range(len(lys) - 1):
            link(key(v.x, v.y, lys[i]), key(v.x, v.y, lys[i + 1]), 0.0, None)
    return adj


def _pad_nodes(adj, pad):
    """Graph nodes inside a pad's copper (a circle of its half-diagonal, on its layers)."""
    r = 0.5 * math.hypot(*pad.size) + 1e-3
    lys = set(pad.layers or [])
    return [n for n in adj if (n[2] in lys or '*.Cu' in lys) and math.hypot(n[0] - pad.x, n[1] - pad.y) <= r]


def net_paths(board, net, driver_ref, driver_pin, t_pd_of):
    """[(load 'R5.1', mm, ps, routed)] from the driver pad to every other pad of `net`: along the routed copper
    (Dijkstra on delay) where it reaches the pad, else the Manhattan distance between the pads (an estimate:
    an unrouted or placed-only net)."""
    import heapq
    pads = [(f.ref, p) for f in board.footprints for p in f.pads if p.net == net and getattr(f, 'on_board', True)]
    src = next((p for r, p in pads if r == driver_ref and str(p.number) == str(driver_pin)), None)
    if src is None:
        return []
    adj = _route_graph(board, net)
    dist = {}
    if adj:
        h = [(0.0, 0.0, n) for n in _pad_nodes(adj, src)]
        for d, mm, n in h:
            dist[n] = (d, mm)
        heapq.heapify(h)
        while h:
            d, mm, n = heapq.heappop(h)
            if dist.get(n, (math.inf,))[0] < d:
                continue
            for m, L, ly in adj.get(n, ()):
                nd = d + L * t_pd_of(ly or n[2])
                if nd < dist.get(m, (math.inf,))[0]:
                    dist[m] = (nd, mm + L)
                    heapq.heappush(h, (nd, mm + L, m))
    out = []
    for r, p in pads:
        if p is src or (r == driver_ref and str(p.number) == str(driver_pin)):
            continue
        hit = [dist[n] for n in _pad_nodes(adj, p) if n in dist] if adj else []
        if hit:
            d, mm = min(hit)
            out.append((f"{r}.{p.number}", mm, d, True))
        else:
            mm = abs(p.x - src.x) + abs(p.y - src.y)
            out.append((f"{r}.{p.number}", mm, mm * t_pd_of(None), False))
    return out


def layer_t_pd(board):
    """t_pd_of(layer) in ps/mm for `board`: microstrip on the outer copper, stripline inside; the slowest kind
    (stripline when the board has inner layers) for an unrouted estimate (layer None)."""
    st = getattr(board, 'stackup', None)
    ers = [e for e in (getattr(st, 'er', None) or []) if e]
    er = max(ers) if ers else ER_DEFAULT
    cu = list(getattr(st, 'copper', None) or ['F.Cu', 'B.Cu'])
    outer = {cu[0], cu[-1]}
    ms, sl = t_pd_ps_mm(er, True), t_pd_ps_mm(er, False)
    worst = sl if len(cu) > 2 else ms
    return lambda ly: worst if ly is None else (ms if ly in outer else sl)


def long_net_hazards(brief, board, max_nets=400):
    """kae.hazards entries for nets whose driver-to-load delay on `board` exceeds t_r/2 (warn: it rings unless
    terminated or slowed) or t_r/6 (info: review). Routed copper where it exists, else Manhattan estimates."""
    from kae import hazards as H
    out = []
    if not brief or board is None:
        return out
    t_pd_of = layer_t_pd(board)
    todo = [(n, d['edge']) for n, d in (brief.get('nets') or {}).items()
            if isinstance(d, dict) and (d.get('edge') or {}).get('t_r_ns')]
    for net, e in sorted(todo)[:max_nets]:
        paths = net_paths(board, net, e.get('driver_ref'), e.get('driver_pin'), t_pd_of)
        if not paths:
            continue
        load, mm, ps, routed = max(paths, key=lambda x: x[2])
        t_r_ps = 1000.0 * e['t_r_ns']
        if ps <= t_r_ps / REVIEW:
            continue
        ring = ps > t_r_ps / TERMINATE
        how = 'routed' if routed else 'estimated (Manhattan, not yet routed)'
        src = f"{e['family']}, {'assumed family default' if e.get('assumed') else 'part data'}: {e['source']}"
        ev = dict(length_mm=round(mm, 1), delay_ps=round(ps), t_r_ns=e['t_r_ns'], ratio=round(ps / t_r_ps, 2),
                  review_ps=round(t_r_ps / REVIEW), terminate_ps=round(t_r_ps / TERMINATE), length=how, t_r_source=src,
                  driver=e.get('driver'), load=load)
        objs = [net, e.get('driver_ref'), load.split('.')[0]]
        if ring:
            out.append(H.make('edge_ringing_risk', 'warn', 'electrical',
                              f"Net {net}: {mm:.0f} mm from driver {e.get('driver')} to {load} ({how}) is {ps:.0f} ps, over half "
                              f"the driver's {e['t_r_ns']:g} ns edge: unterminated, it will ring and may double-clock edge-"
                              f"sensitive inputs.", objects=objs, evidence=ev,
                              fix=f"Shorten it below {t_r_ps / TERMINATE / (ps / mm):.0f} mm, add a series resistor "
                                  f"(about 22-33 ohm) at {e.get('driver_ref')} pin {e.get('driver_pin')}, or lower the "
                                  f"driver's slew rate; a slower edge from the part's datasheet or IBIS [Ramp] lowers the risk."))
        else:
            out.append(H.make('edge_si_review', 'info', 'electrical',
                              f"Net {net}: {mm:.0f} mm from {e.get('driver')} to {load} ({how}) is {ps:.0f} ps, over a sixth of "
                              f"the driver's {e['t_r_ns']:g} ns edge: electrically long; review for ringing.",
                              objects=objs, evidence=ev,
                              fix=f"Keep it under {t_r_ps / REVIEW / (ps / mm):.0f} mm, or plan a series resistor at the driver."))
    return out
