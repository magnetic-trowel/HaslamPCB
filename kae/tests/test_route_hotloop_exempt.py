# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Net-exempt hot-loop keep-outs (hotloop_keepout_exempt): the zone-name marker, the fork's
kae_exempt_keepouts scope and kae's own router's exemption (no KiCad needed)."""
from shapely.geometry import box

from kae.route import critical_space as CS
from kae.route import freerouting as FR
from kae.route import hotloop as HL
from kae.route import specctra as S
from kae.route import translate as T

DSN = '''(pcb "/tmp/x.dsn"
  (resolution um 10)
  (unit um)
  (structure (layer F.Cu (type signal)) (layer In1.Cu (type signal)))
  (network (net GND (pins U1-1)) (net "+5V" (pins U1-2)) (net SW (pins U1-3)) (net SIG (pins U2-1)))
)
'''


def test_zone_name_carries_the_exempt_nets():
    name = HL.exempt_name("kae-crit:hotloop:U4:GND", {"+5V", "SW", "GND", "/a b|c"})
    assert name.startswith("kae-crit:hotloop:U4:GND#x=") and " " not in name
    assert HL.exempt_nets(name) == {"+5V", "SW", "GND", "/a b|c"}
    assert HL.hard_zone(name)                                       # still a keep-out (dropped from the output)
    assert HL.exempt_nets("kae-crit:hotloop:U4:GND") is None        # a plain keep-out
    assert HL.exempt_name("kae-crit:x", set()) == "kae-crit:x"
    assert T._zone_name_in(f"zone {name} GND") == name
    assert T._zone_name_in("zone kae-crit:hotloop:U4:GND GND") == ""


def test_scope_round_trip(monkeypatch):
    monkeypatch.setenv("KAE_HOTLOOP_KEEPOUT_EXEMPT", "hard")
    tree = S.parse(DSN)
    nets = {"GND", "+5V", "SW", "SIG"}
    n = T.write_exempt_keepouts(tree, [("In1.Cu", box(10, -12, 14, -8), "kae_crit1", ["+5V", "GND", "NOPE", "SW"])],
                                lambda l: l, nets)
    assert n == 1
    back = S.parse(S.dumps(tree))
    node = S.find(back, T.EXEMPT_SCOPE)
    assert S.find(node, "mode") is None
    area = S.find(node, "area")
    assert area[1] == "In1.Cu"
    assert S.find(area, "clearance_class")[1] == "kae_crit1"
    assert [str(x) for x in S.find(area, "exempt")[1:]] == ["+5V", "GND", "SW"]   # nets the DSN has
    poly = S.find(area, "polygon")
    xy = [float(v) for v in poly[3:]]
    assert min(xy[0::2]) == 10000 and max(xy[0::2]) == 14000 and min(xy[1::2]) == 8000   # um, y up
    monkeypatch.setenv("KAE_HOTLOOP_KEEPOUT_EXEMPT", "soft")
    monkeypatch.setenv("KAE_HOTLOOP_KEEPOUT_SOFT_COST", "6")
    T.write_exempt_keepouts(tree, [("F.Cu", box(0, -2, 2, 0), "c", ["GND"])], lambda l: l)
    node = S.find(tree, T.EXEMPT_SCOPE)
    assert len(S.findall(tree, T.EXEMPT_SCOPE)) == 1
    assert S.find(node, "mode") == ["mode", "soft"] and float(S.find(node, "cost")[1]) == 6.0


def test_fork_setting_follows_the_scope(tmp_path):
    p = tmp_path / "b.dsn"
    tree = S.parse(DSN)
    T.write_exempt_keepouts(tree, [("F.Cu", box(0, -2, 2, 0), "c", ["GND"])], lambda l: l)
    p.write_text(S.dumps(tree))
    assert FR.fork_settings(p, None) == {"kae_exempt_keepouts": "true"}


def test_kae_router_lets_the_exempt_nets_through():
    """critical_space: the keep-out's item stops other nets, not the cell's own."""
    name = HL.exempt_name("kae-crit:hotloop:U4:GND", {"GND", "+5V", "SW"})
    it = CS.Item("shape", "GND", ["In1.Cu"], box(0, 0, 1, 1), 0.0, None, owner=f"zone {name} GND")
    it.exempt = frozenset(CS._keepout_exempt(it.owner) | {"GND"})
    sp = CS.Space.__new__(CS.Space)
    assert sp.need(it, "+5V", "via", "In1.Cu") is None
    assert sp.need(it, "SW", "track", "In1.Cu") is None
    plain = CS.Item("shape", "GND", ["In1.Cu"], box(0, 0, 1, 1), 0.0, None, owner="zone kae-crit:x GND")
    assert plain.exempt is None and CS._keepout_exempt(plain.owner) is None
