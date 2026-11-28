# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth.haslam_intent: facts the design already states become haslam facts; explicit declarations win."""
from haslamsynth import Design, PartDef, PinDef


def _design():
    d = Design("ki")
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.net("VIN", domain="LV", v=(0, 30), kind="power", v_typ=(9, 12, 16))
    d.net("VOUT", domain="LV", v=(0, 6), kind="power", v_typ=5.0)
    b = d.block("b")
    card = PartDef(mpn="BUCK1", category="ic", footprint="Package_TO_SOT_SMD:SOT-23-5",
                   pins=[PinDef("1", "VIN"), PinDef("2", "GND"), PinDef("3", "SW")],
                   haslam=dict(f_sw_Hz=2e6, v_sw_max_V=36, why="BUCK1 DS p.1"))
    u = b.add(card, ref="U1")
    d.nets["VIN"].connect(u["VIN"]); d.nets["GND"].connect(u["GND"]); d.nets["VOUT"].connect(u["SW"])
    d.finalize()
    return d


def test_defaults_from_nets_and_part_cards():
    d = _design()
    doc, problems = d.haslam.document()
    f = doc["facts"]
    assert f["nets"]["VIN"]["V_V"] == 12 and f["nets"]["VIN"]["range_V"] == [9.0, 16.0]   # (lo, typ, hi)
    assert f["nets"]["VOUT"]["V_V"] == 5.0 and f["nets"]["VOUT"]["range_V"] == [0.0, 6.0]  # range from v=
    assert f["parts"]["U1"]["f_sw_Hz"] == 2e6 and "BUCK1" in f["parts"]["U1"]["why"]


def test_explicit_declarations_win():
    d = _design()
    d.haslam.part("U1", f_sw_Hz=1e6, why="this design's RT")
    d.haslam.net("VOUT", 3.3, why="trimmed")
    f = d.haslam.document()[0]["facts"]
    assert f["parts"]["U1"]["f_sw_Hz"] == 1e6 and f["parts"]["U1"]["v_sw_max_V"] == 36
    assert f["nets"]["VOUT"]["V_V"] == 3.3


def test_relations_written_for_haslam_and_the_rest_reported():
    d = _design()
    b = d.blocks[0]
    c = b.add(PartDef(mpn="C", category="capacitor", footprint="Capacitor_SMD:C_0402_1005Metric",
                      pins=[PinDef("1", "1"), PinDef("2", "2")]), ref="C1")
    d.nets["VIN"].connect(c["1"]); d.nets["GND"].connect(c["2"])
    d.place.near("C1", "U1.1", within_mm=2.0, note="DS p.9: input cap at VIN")
    d.place.far("C1", "U1", "close")
    d.place.edge("U1", "west")
    d.place.edge("U1", "any")
    d.place.hot_loop(["U1.1", "C1.1", "C1.2", "U1.2"])
    d.place.side("U1", "bottom")
    d.place.region("U1", "corner-ne")
    d.finalize()
    rows, skipped = d.haslam.relations()
    by = {r["kind"]: r for r in rows if not r.get("requested")}
    assert by["near"]["mag"] == "2 mm" and by["near"]["b"] == "U1.1" and "DS p.9" in by["near"]["why"]
    # the hot loop becomes a requested tight near of its other part to its first (IC) pin
    hot = [r for r in rows if r.get("requested")]
    assert [(r["kind"], r["a"], r["b"], r["mag"]) for r in hot] == [("near", "C1", "U1.1", "tight")]
    assert by["keep_away"]["mag"] == "close"
    assert sorted(r["edge"] for r in rows if r["kind"] == "on_edge") == ["edge:nearest", "edge:west"]
    assert by["side"]["members"] == ["U1"] and by["side"]["side"] == "bottom"
    assert by["region"]["members"] == ["U1"] and by["region"]["region"] == "region:ne"
    assert all(r["id"] for r in rows) and len({r["id"] for r in rows}) == len(rows)
    assert not skipped
    doc, problems = d.haslam.document()
    assert doc["relations"] == rows and not [p for p in problems if "relation" in p]
    for k in ("producer", "knobs", "environment"):
        assert k not in doc                     # nothing haslam does not read


def test_an_overshoot_term_at_the_switch_rating_is_flagged():
    # overshoot.peak bounds the ring above the bus: at the rating itself it never binds
    d = _design()
    d.haslam.term("T-OS", "hard", "overshoot.peak", where={"part": "U1"}, max="36 V", why="abs max")
    d.haslam.term("T-RING", "hard", "overshoot.peak", where={"part": "U1"}, max="19.5 V", why="36 - 16 - 0.5 V")
    w = d.haslam.warnings()
    assert [x[0] for x in w] == ["haslam_intent.overshoot_at_rating"] and w[0][1].startswith("T-OS:")


def _current_design(rise=None):
    d = Design("kc")
    if rise is not None:
        d.board(width_mm=40, height_mm=30, trace_rise_c=rise)
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.net("VIN", domain="LV", v=(0, 30), kind="power", v_typ=(9, 12, 16), i_max=2.0)
    d.net("VOUT", domain="LV", v=(0, 6), kind="power", v_typ=5.0, i_max=3.0)
    b = d.block("b")
    card = PartDef(mpn="BUCK1", category="ic", footprint="Package_TO_SOT_SMD:SOT-23-5",
                   pins=[PinDef("1", "VIN"), PinDef("2", "GND"), PinDef("3", "SW")])
    u = b.add(card, ref="U1")
    d.nets["VIN"].connect(u["VIN"]); d.nets["GND"].connect(u["GND"]); d.nets["VOUT"].connect(u["SW"])
    d.finalize()
    return d


def test_current_carrying_nets_get_a_heat_limit_at_the_boards_conductor_rise():
    doc, problems = _current_design(rise=20).haslam.document()
    heat = [t for t in doc["terms"] if t["obs"] == "heat.track"]
    assert [(t["id"], t["tier"], t["max"], t["rate"]) for t in heat] == [("D-HEAT", "limit", "20 K", "5 mW_eq/K")]
    assert "trace_rise_c" in heat[0]["source"] and not problems
    assert not [t for t in doc["terms"] if t["obs"] == "drop.rail"]           # no drop bound unless asked for
    assert [t for t in _design().haslam.document()[0]["terms"] if t["obs"] == "heat.track"] == []   # no i_max: none


def test_the_designs_own_dc_terms_replace_the_defaults_and_drops_are_opt_in():
    d = _current_design()
    d.haslam.term("T-HEAT", "limit", "heat.track", max="30 K", rate="1 mW_eq/K", why="w", source="s")
    d.haslam.term("T-DROP", "limit", "drop.rail", where={"rail": "VOUT"}, max="50 mV", rate="1 mW_eq/mV", why="w", source="s")
    d.haslam.dc_terms(drop_share=0.03)
    doc, _ = d.haslam.document()
    ids = sorted(t["id"] for t in doc["terms"] if t["obs"] in ("heat.track", "drop.rail"))
    assert ids == ["D-DROP-VIN", "T-DROP", "T-HEAT"]                              # 10 K default: replaced
    vin = next(t for t in doc["terms"] if t["id"] == "D-DROP-VIN")
    assert vin["max"] == "360 mV" and vin["where"] == {"rail": "VIN"}            # 3 % of 12 V
    d2 = _current_design()
    d2.haslam.dc_terms(heat=False)
    assert not [t for t in d2.haslam.document()[0]["terms"] if t["obs"] == "heat.track"]
