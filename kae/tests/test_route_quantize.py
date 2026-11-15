# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""quantize.fit: a value put on a grid never leaves the rule's interval (property tests over random
intervals and grids), plus the places that use it: class widths, session widths, repair, last mile."""
import math
import random
from types import SimpleNamespace

from kae.route import constraints as C
from kae.route import specctra as S
from kae.route import translate
from kae.route.constraints import RoutingClass
from kae.route.quantize import DSN, FR_WIDTH, NM, UM, fit, outside

GRIDS = [NM, 1e-5, DSN, FR_WIDTH, UM, 0.0254 / 10, 0.01]


def _on(v, q):
    return abs(v / q - round(v / q)) < 1e-6


def _nm(v):
    """v as KiCad stores it: whole nanometres."""
    return round(v * 1e6)


def _intervals(rng, n=4000):
    for _ in range(n):
        lo = round(rng.uniform(0.01, 2.0), rng.choice([3, 4, 5, 6]))
        kind = rng.random()
        if kind < 0.3:
            hi = lo                                            # min = max (controlled impedance)
        elif kind < 0.6:
            hi = round(lo + rng.uniform(0, 3e-4), 6)           # narrower than most grids
        elif kind < 0.8:
            hi = round(lo + rng.uniform(0, 0.5), 6)
        else:
            hi = None
        if rng.random() < 0.15:
            lo = None
        yield lo, hi, rng.choice(GRIDS), round(rng.uniform(0.0, 2.6), rng.choice([3, 4, 6, 9]))


def test_fit_stays_inside_the_interval_in_nm():
    rng = random.Random(20261115)
    for lo, hi, q, v in _intervals(rng):
        for side in ("near", "up", "down"):
            x = fit(v, lo, hi, q, side)
            assert x is not None, (v, lo, hi, q, side)
            n = _nm(x)
            assert lo is None or n >= _nm(lo), (v, lo, hi, q, side, x)
            assert hi is None or n <= _nm(hi), (v, lo, hi, q, side, x)
            assert not outside(x, lo, hi)


def test_fit_uses_the_grid_when_the_interval_holds_a_point_of_it():
    rng = random.Random(7)
    for lo, hi, q, v in _intervals(rng):
        has = (math.floor((hi if hi is not None else 1e9) / q + 1e-6) >=
               math.ceil((lo if lo is not None else -1e9) / q - 1e-6))
        x = fit(v, lo, hi, q)
        if has:
            assert _on(x, q)
        else:
            assert _on(x, NM)                          # the board's own grid, never past a bound


def test_fit_direction_and_nearest():
    rng = random.Random(11)
    for lo, hi, q, v in _intervals(rng):
        lo_, hi_ = (lo if lo is not None else -math.inf), (hi if hi is not None else math.inf)
        if not (lo_ + q <= v <= hi_ - q):
            continue                                   # clamping, not rounding, decides there
        up, down, near = fit(v, lo, hi, q, "up"), fit(v, lo, hi, q, "down"), fit(v, lo, hi, q)
        assert up >= v - 1e-9 and up - v < q + 1e-9
        assert down <= v + 1e-9 and v - down < q + 1e-9
        assert abs(near - v) <= q / 2 + 1e-9


def test_fit_on_a_grid_point_is_the_identity():
    for q in GRIDS:
        for k in (1, 7, 1521, 1907):
            v = k * q
            for side in ("near", "up", "down"):
                assert abs(fit(v, None, None, q, side) - v) < 1e-12


def test_fit_contradictory_rule_is_none():
    assert fit(0.2, 0.3, 0.2) is None
    assert fit(0.2, 0.2, 0.2) == 0.2


def test_known_cases():
    assert fit(0.19079, 0.19079, 0.19079, DSN, "up") == 0.19079       # thunderscope PCIe outer
    assert fit(0.19079, None, None, DSN, "up") == 0.1908               # a router-only value may round out
    assert fit(0.1521, None, None, FR_WIDTH, "up") == 0.1522           # Freerouting's half-width grid
    assert fit(0.3, 0.24892, None, DSN, "up") == 0.3
    assert fit(0.24892, 0.24892, None, DSN, "up") == 0.249             # a minimum drill, up never down
    assert fit(0.26, 0.2, 0.25549, UM, "up") == 0.255                  # past a max: the largest grid point inside


def test_width_choice_keeps_an_off_grid_rule():
    strict = SimpleNamespace(min=0.19079, opt=0.19079, max=0.19079)
    w, mn, mx = C._width_choice(None, strict, 0.127)
    assert (w, mn, mx) == (0.19079, 0.19079, 0.19079)
    strict = SimpleNamespace(min=0.1, opt=None, max=0.14789)
    assert C._width_choice(None, strict, 0.2)[0] == 0.14789            # net class above the max


SES = """(session x (routes (resolution um 10) (parser)
 (network_out (net "N1" (wire (path "Int2 (Sign)" 1908 0 0 1000 0)) (wire (path F.Cu 1522 0 0 1000 0))
   (wire (path F.Cu 1270 0 0 5 5)) (wire (path B.Cu 1912 0 0 9 9)) (wire (path B.Cu 3000 0 0 9 9))))))"""


def test_fit_widths_brings_session_wires_inside_their_limits():
    """A wire Freerouting's grid put past its class's max by at most one 0.2 um step comes back
    to the nearest width inside; wires inside their limits, or far outside, are left alone."""
    rc = RoutingClass("kae_PCIe", ["N1"], "PCIe", {"In2.Cu": 0.19079, "F.Cu": 0.1521, "B.Cu": 0.19},
                      (0.6, 0.3), limits={"In2.Cu": (0.19079, 0.19079), "F.Cu": (0.127, 0.1521),
                                          "B.Cu": (0.15, 0.191)})
    plan = SimpleNamespace(classes={"kae_PCIe": rc}, net_class={"N1": "kae_PCIe"},
                           dsn_layer_names={"In2.Cu": "Int2 (Sign)", "F.Cu": "F.Cu", "B.Cu": "B.Cu"})
    t = S.parse(SES)
    assert translate.fit_widths(translate.find(translate.find(t, "routes"), "network_out"), plan, 10000.0) == 3
    text = S.dumps(t)
    for want in ('(path "Int2 (Sign)" 1907.9 ', "(path F.Cu 1521 ", "(path F.Cu 1270 ", "(path B.Cu 1910 ",
                 "(path B.Cu 3000 "):
        assert want in text, (want, text)


def test_dsn_class_width_on_freerouting_grid():
    nodes = translate._class_rule_nodes({"F.Cu": 0.19079, "B.Cu": 0.1521}, None, ["F.Cu", "B.Cu"])
    assert nodes[0] == ["rule", ["width", "190.8"]]
    assert nodes[1][2] == ["rule", ["width", "152.2"]]


def test_repair_widening_stays_inside_the_rule():
    from kae.route import repair
    rc = RoutingClass("kae_PCIe", ["N1"], "PCIe", {"F.Cu": 0.19079}, (0.6, 0.3),
                      limits={"F.Cu": (0.19079, 0.19079)})
    plan = SimpleNamespace(classes={"kae_PCIe": rc}, net_class={"N1": "kae_PCIe"})
    assert repair._widened(plan, dict(net="N1", layer="F.Cu"), 0.1908) == 0.19079
    assert repair._widened(None, dict(net="N1", layer="F.Cu"), 0.1908) == 0.1909
