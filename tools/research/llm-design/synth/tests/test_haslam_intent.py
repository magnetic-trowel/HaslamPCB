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
    by = {r["kind"]: r for r in rows}
    assert by["near"]["mag"] == "2 mm" and by["near"]["b"] == "U1.1" and "DS p.9" in by["near"]["why"]
    assert by["keep_away"]["mag"] == "close"
    assert sorted(r["edge"] for r in rows if r["kind"] == "on_edge") == ["edge:nearest", "edge:west"]
    assert by["side"]["members"] == ["U1"] and by["side"]["side"] == "bottom"
    assert by["region"]["members"] == ["U1"] and by["region"]["region"] == "region:ne"
    assert all(r["id"] for r in rows) and len({r["id"] for r in rows}) == len(rows)
    assert {r["kind"] for r, _ in skipped} == {"hot_loop"}
    doc, problems = d.haslam.document()
    assert doc["relations"] == rows and not [p for p in problems if "relation" in p]
    for k in ("producer", "knobs", "environment"):
        assert k not in doc                     # nothing haslam does not read


def test_an_overshoot_term_at_the_switch_rating_is_flagged():
    # overshoot.peak bounds the ring above the bus: at the rating itself it never binds
    d = _design()
    d.haslam.term("T-OS", "hard", "overshoot.peak", where={"part": "U1"}, max="36 V", why="abs max")
    d.haslam.term("T-RING", "hard", "overshoot.peak", where={"part": "U1"}, max="19.5 V", why="36 - 16 - 0.5 V")
    w = [x for x in d.haslam.warnings() if x[0] != "haslam_intent.supply_prior"]
    assert [x[0] for x in w] == ["haslam_intent.overshoot_at_rating"] and w[0][1].startswith("T-OS:")


def test_term_where_takes_lists_and_globs():
    """F38: haslam's matcher takes a ref, a glob (* ? [...]) or a list of them; only plain refs must exist."""
    d = _design()
    for i, part in enumerate((["U1"], "U*", "U1??", "U[12]", ["U1", "U?"])):
        d.haslam.term(f"T{i}", "report", "temp.junction", where={"part": part}, max="85 C", why="ok")
    d.haslam.term("T-BAD", "report", "temp.junction", where={"part": ["U1", "U9"]}, max="85 C", why="typo")
    doc, problems = d.haslam.document()
    assert [p for p in problems if "where.part" in p] == ["haslam.term T-BAD.where.part: no part 'U9' in the design"]
    assert doc["terms"][4]["where"]["part"] == ["U1", "U?"]


def test_ics_on_a_class_prior_are_named():
    """F36: an IC without a supply-draw fact gets haslam's 10 mA class prior; a cell's controller does not."""
    d = _design()
    assert [x[2] for x in d.haslam.warnings() if x[0] == "haslam_intent.supply_prior"] == [["U1"]]
    d.haslam.part("U1", I_A=[1e-7, 1e-5], why="DS")
    assert not [x for x in d.haslam.warnings() if x[0] == "haslam_intent.supply_prior"]
    d2 = _design()
    d2.haslam.cell("U1", "buck", I_A=(0.01, 0.1, 0.5), vin="VIN", vout="VOUT", why="load")
    assert not [x for x in d2.haslam.warnings() if x[0] == "haslam_intent.supply_prior"]


def test_part_card_facts_pass_through_unvalidated():
    """F36/F48: haslam's newer per-part keys (core_I_A, core_f_Hz, core_t_s, core: false) reach the file as
    written; haslamsynth keeps no key list of its own (haslam's loader is the judge)."""
    card = _design().all_parts()[0].defn.with_(haslam=dict(core=False, core_I_A=[1e-6, 2e-6], core_f_Hz=1e5,
                                                           I_sustained_A=2e-6, why="DS 5.5"))
    d = _design()
    d.all_parts()[0].defn = card
    f = d.haslam.document()[0]["facts"]["parts"]["U1"]
    assert f["core"] is False and f["core_I_A"] == [1e-6, 2e-6] and f["core_f_Hz"] == 1e5
