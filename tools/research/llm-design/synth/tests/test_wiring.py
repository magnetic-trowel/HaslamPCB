# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""blk.wire / Wiring: the add-with-a-pin-map helper every design used to re-implement (obd-solar FRICTION.md #4)."""
import pytest

from haslamsynth import Design, DesignError, PinDef, Wiring
from haslamsynth.lib import IC
from haslamsynth.wiring import ohms_value

U = IC("TEST1", pins=[PinDef("1", "VIN", "power_in"), PinDef("2", "GND", "power_in"), PinDef("3", "OUT", "output"),
                      PinDef("4", "NC", "no_connect")], footprint="Package_TO_SOT_SMD:SOT-23-5")


def design():
    d = Design("wire")
    d.net("GND", domain="LV", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.net("VIN", domain="LV", v=(0, 12), kind="power")
    return d


def test_block_wire_connects_global_and_local_nets():
    d = design()
    b = d.block("A", domain="LV")
    out = b.net("OUT", v=(0, 5))
    u = b.wire(U, "U1", {"VIN": "VIN", "GND": d.nets["GND"], "OUT": "OUT"}, nc=["NC"], nc_reason="NC, DS p.1")
    assert u.ref == "U1"
    assert u.conn["1"] is d.nets["VIN"] and u.conn["2"] is d.nets["GND"] and u.conn["3"] is out
    assert u.nc == {"4"} and u.nc_reason["4"] == "NC, DS p.1"


def test_an_undeclared_net_is_an_error_not_a_new_net():
    d = design()
    b = d.block("A", domain="LV")
    with pytest.raises(DesignError, match="VINN is not declared"):
        b.wire(U, "U1", {"VIN": "VINN"})
    assert "VINN" not in b.nets and "VINN" not in d.nets


def test_wiring_nets_parts_and_passives():
    d = design()
    w = Wiring(d, "CHG", "Charger", "test block", domain="LV",
               nets=[("SW", (-0.7, 12), "switching", {"i_max": 2}), ("FB", (0, 3), "analog")])
    assert w.b.title == "Charger" and w.n("SW").i_max == 2 and w.n("GND") is d.nets["GND"]
    w.add(U, "U201", {"VIN": "VIN", "GND": "GND", "OUT": "SW"}, nc=["NC"], nc_reason="NC")
    r = w.R("R201", 4700, "SW", "FB", note="divider top", p_diss=0.01, v_max=50)
    assert r.value == "4.7k" and r.notes == "divider top" and r.p_diss == 0.01 and r.defn.ratings.v_max == 50
    c = w.C("C201", "10u", 25, "VIN", "GND", pkg="1206", diel="X5R")
    assert c.defn.fields.get("Dielectric") == "X5R" and c.ref == "C201"
    assert [p.ref for p in w.b.parts] == ["U201", "R201", "C201"]


def test_ohms_value():
    assert [ohms_value(x) for x in (0.18, 100, 4700, 100e3, 2.2e6, "10k")] == ["0.18", "100", "4.7k", "100k", "2.2M",
                                                                              "10k"]
