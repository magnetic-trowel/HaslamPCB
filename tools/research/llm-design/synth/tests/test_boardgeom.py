# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board geometry from one source (F9, F10, F32), compass regions vs slots (F22), relations tied to requirements
(F23), thermal_isolate (F14), library footprint holes (F15)."""
import json

import pytest

from haslamsynth import Design, Hole, PartDef, PinDef, SlotBarrier, boardgeom
from haslamsynth.checks import Checker

BAR = SlotBarrier("y", 20.25, width_mm=1.5, bridges=[(20, 30)], edge_mm=2.5, sides=("POWER", "SENSE"))


def test_slot_barrier_makes_slots_strips_and_side_areas():
    """The numbers bme280-array's hand-written board.json had (slots, edge-strip keep-outs, POWER/SENSE)."""
    assert BAR.slots(50, 78) == [(2.5, 19.5, 20, 21.0), (30, 19.5, 47.5, 21.0)]
    ko = {k["name"]: k for k in BAR.keepouts(50, 78)}
    assert ko["BARRIER_STRIP_W"]["rect"] == [0.2, 18.5, 2.5, 22.0] and ko["BARRIER_STRIP_W"]["no"] == ["copper"]
    assert ko["BARRIER_STRIP_E"]["rect"] == [47.5, 18.5, 49.8, 22.0]
    assert ko["POWER"]["rect"] == [0.5, 0.5, 49.5, 19.0] and ko["POWER"]["no"] == []
    assert ko["SENSE"]["rect"] == [0.5, 21.5, 49.5, 77.5]
    v = SlotBarrier("x", 10, width_mm=1, bridges=[(5, 8)], edge_mm=2)
    assert v.slots(30, 20) == [(9.5, 2, 10.5, 5), (9.5, 8, 10.5, 18)]


def _design():
    d = Design("geo")
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.net("V", domain="LV", v=(0, 5), kind="power")
    d.require("REQ-4", "heat away from the sensors")
    ic = lambda n: PartDef(mpn=n, category="ic", footprint="Package_TO_SOT_SMD:SOT-23",
                           pins=[PinDef("1", "V"), PinDef("2", "G")])
    pw, sn = d.block("PWR"), d.block("SNS")
    for blk, name, ref in ((pw, "CONV", "U1"), (sn, "SENS", "U101"), (sn, "SENS", "U102"), (sn, "SENS", "U105")):
        u = blk.add(ic(name), ref=ref)
        d.nets["V"].connect(u["V"]); d.nets["GND"].connect(u["G"])
    d.board(width_mm=50, height_mm=78, holes=[Hole(3.5, 3.5, 3.2)], cuts=[BAR],
            zones=[{"net": "GND", "layer": "B.Cu", "name": "GND_N", "area": "POWER"}], seed_area=(3, 6, 47, 76))
    d.place.fixed("U101", 7.5, 35, source="array")
    d.place.fixed("U102", 19, 35, source="array")
    d.place.fixed("U105", 7.5, 46, source="array")
    return d.finalize()


def test_board_json_from_the_design():
    g, problems = boardgeom.board_json(_design())
    assert not problems
    assert g["outline"] == [50.0, 78.0] and g["holes"] == [[3.5, 3.5]] and len(g["slots"]) == 2
    assert g["fixed"]["U101"]["x"] == 7.5 and g["fixed"]["U105"]["y"] == 46
    assert g["zones"][0]["rect"] == [0.5, 0.5, 49.5, 19.0]                  # zone by area name
    assert g["seed_area"] == [3, 6, 47, 76]


def test_hand_board_json_must_agree(tmp_path):
    d = _design()
    (tmp_path / "board.json").write_text(json.dumps({"outline": [50, 80], "fixed": {"U101": {"x": 7.5, "y": 35},
                                                                                   "U1": {"x": 9, "y": 9}}}))
    out = []
    g = boardgeom.write(d, tmp_path, tmp_path / "out", lambda c, s, m, o=(): out.append((c, s, m)))
    errs = [m for c, s, m in out if s == "error"]
    assert len(errs) == 1 and "outline" in errs[0] and "[50, 80]" in errs[0]
    assert g["fixed"]["U1"] == {"x": 9, "y": 9}                             # merged, and said so
    assert any(s == "info" and "fixed.U1" in m for c, s, m in out)
    assert json.loads((tmp_path / "out" / "board.json").read_text())["fixed"]["U1"]["x"] == 9


def test_compass_region_across_a_slot_warns():
    """F22: 'north' is the board's northern third (26 mm on 78 mm), past the slot at 19.5-21 mm."""
    d = _design()
    d.place.region("block:PWR", "north")
    d.place.region("block:SNS", "area:SENSE")
    g, _ = boardgeom.board_json(d)
    out = []
    boardgeom.check_regions(d, g, lambda c, s, m, o=(): out.append((c, s, m)))
    assert len(out) == 1 and out[0][0] == "layout.region_crosses_slot" and "POWER, SENSE" in out[0][2]


def test_req_makes_relations_requested_and_is_checked():
    d = _design()
    d.place.region("block:PWR", "area:POWER", req="REQ-4")
    d.place.far("U1", "U101", req="REQ-9")
    rows = {r["kind"]: r for r in d.haslam.relations()[0]}
    assert rows["region"]["requested"] is True and "REQ-4" in rows["region"]["why"]
    assert rows["keep_away"]["requested"] is True
    errs = [f for f in Checker(d).run() if f.check == "place.unknown_requirement"]
    assert len(errs) == 1 and "REQ-9" in errs[0].message


def test_thermal_isolate_writes_regions_and_nearest_keep_aways():
    d = _design()
    d.place.thermal_isolate(["block:PWR"], ["U101", "U102", "U105"], area="POWER", req="REQ-4")
    g, _ = boardgeom.board_json(d)
    rows = d.haslam.relations(g)[0]
    reg = [r for r in rows if r["kind"] == "region"]
    far = [(r["a"], r["b"]) for r in rows if r["kind"] == "keep_away"]
    assert reg and reg[0]["members"] == ["U1"] and reg[0]["region"] == "area:POWER" and reg[0]["strength"] == "required"
    assert sorted(far) == [("U1", "U101"), ("U1", "U102")]                   # the row next to POWER, not U105
    assert all(r["requested"] and r["category"] == "thermal" for r in rows if r["kind"] in ("region", "keep_away"))
    assert not [r for r, why in d.haslam.relations(g)[1] if r["kind"] in ("thermal_isolate", "fixed")]


@pytest.mark.kicad
def test_footprint_holes_below_the_fab_minimum(tmp_path):
    """F15: KiCad's _ThermalVias variants carry 0.2 mm holes; JLC's standard minimum is 0.3 mm."""
    from haslamsynth import layout
    from haslamsynth.kicadlib import FootprintLibs, footprint_dir
    d = Design("fab")
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    b = d.block("b")
    u = b.add(PartDef(mpn="X", category="ic", footprint="Package_SON:WSON-10-1EP_2.5x2.5mm_P0.5mm_EP1.2x2mm_ThermalVias",
                      pins=[PinDef(str(i), f"P{i}") for i in range(1, 12)]), ref="U1")
    d.nets["GND"].connect(u["P11"])
    d.board(width_mm=20, height_mm=20)
    d.finalize()
    out = []
    layout.check_footprint_holes(d, FootprintLibs(footprint_dir()), lambda c, s, m, o=(): out.append((c, s, m)))
    # no fab named: a warning against JLC's 2-layer standard, not a fault
    assert len(out) == 1 and out[0][1] == "warning" and "0.2 mm" in out[0][2]
    assert "use Package_SON:WSON-10-1EP_2.5x2.5mm_P0.5mm_EP1.2x2mm" in out[0][2]
    d.board_spec.min_drill_mm = 0.3                   # the design names its fab's minimum: an error
    out.clear()
    layout.check_footprint_holes(d, FootprintLibs(footprint_dir()), lambda c, s, m, o=(): out.append((c, s, m)))
    assert len(out) == 1 and out[0][1] == "error"
    d.board_spec.min_drill_mm = 0.2
    out.clear()
    layout.check_footprint_holes(d, FootprintLibs(footprint_dir()), lambda c, s, m, o=(): out.append((c, s, m)))
    assert not out
    # liion-balancer, prius-solar-mppt: 4-layer boards, where 0.2 mm vias are the standard process
    d.board_spec.min_drill_mm, d.board_spec.layers = None, 4
    layout.check_footprint_holes(d, FootprintLibs(footprint_dir()), lambda c, s, m, o=(): out.append((c, s, m)))
    assert not out


def test_no_board_json_for_a_design_without_layout_geometry(tmp_path):
    """Older designs (leadacid-balancer, liion-balancer, rpi-mains-relay, prius-solar-mppt) give d.board an outline,
    holes and descriptive keep-outs in a lower-left, y-up frame: the build must not write a board.json that
    sch_to_board would read mirrored, nor fail them on holes it cannot drill. Their d.place.fixed stay unused."""
    d = Design("old")
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    u = d.block("b").add(PartDef(mpn="X", category="ic", footprint="Package_TO_SOT_SMD:SOT-23",
                                 pins=[PinDef("1", "G")]), ref="U1")
    d.nets["GND"].connect(u["G"])
    d.board(width_mm=100, height_mm=80, holes=[Hole(5, 5, 4.3)],
            keepouts=[{"relative": "3 mm ring around each hole", "what": "copper", "layers": "all"}])
    d.place.fixed("U1", 50, 40, source="enclosure")
    d.finalize()
    out = []
    assert boardgeom.write(d, tmp_path, tmp_path / "out", lambda c, s, m, o=(): out.append((c, s, m))) == {}
    assert not out and not (tmp_path / "out" / "board.json").exists()
    assert [r["kind"] for r, _ in d.haslam.relations({})[1]] == ["fixed"]
    # opted in: written, the M4 hole and the descriptive keep-out are warnings, not errors, and left out
    d.board_spec.board_json = True
    g = boardgeom.write(d, tmp_path, tmp_path / "out", lambda c, s, m, o=(): out.append((c, s, m)))
    assert g["holes"] == [[5, 5]] and "keepouts" not in g and g["fixed"]["U1"]["x"] == 50
    assert sorted(s for c, s, m in out) == ["warning", "warning"] and all(c == "board.geometry" for c, s, m in out)
