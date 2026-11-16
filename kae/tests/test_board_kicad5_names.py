# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Names kae's reader must give an old (KiCad 5) board the way KiCad 10's reader does:
overbar net names, renamed copper layers, NPTH and aperture pad numbers.

The expected values are what pcbnew 10.0.7 reports for KICAD5 (PCB_IO_MGR.Load); see
kae.board.kicad_file.legacy_names for the rules in KiCad's source.
"""
import pytest

from kae.board import kicad_file
from kae.board.kicad_file import new_overbar

# A 4-layer KiCad 5 board: copper layers renamed (Top, GND, PWR, Bottom), overbar nets,
# numbered NPTH pads (one with an annular ring) and a numbered paste-only pad, all with a net, a back-side part, a zone whose
# legacy net_name is in the old overbar notation.
KICAD5 = """(kicad_pcb (version 20171130) (host pcbnew 5.1.9)
  (general (thickness 1.6))
  (page A4)
  (layers
    (0 Top signal)
    (1 GND power)
    (2 PWR power)
    (31 Bottom signal)
    (36 B.SilkS user)
    (37 F.SilkS user)
    (38 B.Mask user)
    (39 F.Mask user)
    (44 Edge.Cuts user)
    (46 B.CrtYd user)
    (47 F.CrtYd user)
  )
  (setup (trace_min 0.2))
  (net 0 "")
  (net 1 ~RTS)
  (net 2 R~W)
  (net 3 "~CS~ X")
  (net 4 +5V)
  (net_class Default "default"
    (clearance 0.2) (trace_width 0.25) (via_dia 0.8) (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1)
    (add_net +5V) (add_net R~W) (add_net ~RTS) (add_net "~CS~ X")
  )
  (module Test:Part (layer Top) (tedit 0) (tstamp 5A000001)
    (at 10 10)
    (fp_text reference U1 (at 0 -2) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value Part (at 0 2) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
    (pad 1 smd rect (at -1 0) (size 1 1) (layers Top F.Mask) (net 1 ~RTS))
    (pad 2 thru_hole circle (at 1 0) (size 1.5 1.5) (drill 0.8) (layers *.Cu *.Mask) (net 2 R~W))
    (pad 3 np_thru_hole circle (at 0 1.5) (size 1 1) (drill 1) (layers *.Cu *.Mask) (net 4 +5V))
    (pad 4 smd rect (at 0 -1) (size 0.5 0.5) (layers F.Paste) (net 4 +5V))
    (pad 5 np_thru_hole circle (at 0 3) (size 2 2) (drill 1) (layers *.Cu *.Mask) (net 4 +5V))
  )
  (module Test:Part (layer Bottom) (tedit 0) (tstamp 5A000002)
    (at 20 10 180)
    (fp_text reference U2 (at 0 -2) (layer B.SilkS) (effects (font (size 1 1) (thickness 0.15)) (justify mirror)))
    (fp_text value Part (at 0 2) (layer B.SilkS) (effects (font (size 1 1) (thickness 0.15)) (justify mirror)))
    (pad 1 smd rect (at -1 0 180) (size 1 1) (layers Bottom B.Mask) (net 3 "~CS~ X"))
  )
  (gr_line (start 0 0) (end 30 0) (layer Edge.Cuts) (width 0.1))
  (gr_line (start 30 0) (end 30 20) (layer Edge.Cuts) (width 0.1))
  (gr_line (start 30 20) (end 0 20) (layer Edge.Cuts) (width 0.1))
  (gr_line (start 0 20) (end 0 0) (layer Edge.Cuts) (width 0.1))
  (segment (start 9 10) (end 5 10) (width 0.25) (layer Top) (net 1))
  (segment (start 11 10) (end 15 10) (width 0.25) (layer GND) (net 2))
  (via (at 15 10) (size 0.8) (drill 0.4) (layers Top Bottom) (net 2))
  (zone (net 1) (net_name ~RTS) (layer PWR) (tstamp 0) (hatch edge 0.5)
    (connect_pads (clearance 0.5))
    (min_thickness 0.25)
    (fill (arc_segments 32) (thermal_gap 0.5) (thermal_bridge_width 0.5))
    (polygon (pts (xy 1 1) (xy 29 1) (xy 29 19) (xy 1 19)))
  )
  (zone (net 4) (net_name +5V) (layer GND) (tstamp 0) (hatch edge 0.5)
    (connect_pads (clearance 0.5))
    (min_thickness 0.25)
    (fill (arc_segments 32) (thermal_gap 0.5) (thermal_bridge_width 0.5))
    (polygon (pts (xy 1 1) (xy 29 1) (xy 29 19) (xy 1 19)))
  )
)
"""


@pytest.fixture(scope="module")
def k5(tmp_path_factory):
    p = tmp_path_factory.mktemp("k5") / "board.kicad_pcb"
    p.write_text(KICAD5)
    return kicad_file.load(p)


@pytest.mark.parametrize("old,new", [
    ("~RTS", "~{RTS}"), ("R~W", "R~{W}"), ("~CS~ X", "~{CS} X"), ("~A B", "~{A} B"),
    ("A~~B", "A~B"), ("~", "~"), ("~{RTS}", "~{RTS}"), ("x~~{y", "x~~{y"), ("GND", "GND"),
    ("(~RD)", "(~{RD})"),
])
def test_overbar_is_kicads_conversion(old, new):
    assert new_overbar(old) == new


def test_overbar_net_names(k5):
    assert set(k5.nets) == {"~{RTS}", "R~{W}", "~{CS} X", "+5V", "~RTS"}
    u1 = next(f for f in k5.footprints if f.ref == "U1")
    assert {p.number: p.net for p in u1.pads}["1"] == "~{RTS}"
    assert sorted(t.net for t in k5.tracks) == ["R~{W}", "~{RTS}"]
    assert k5.vias[0].net == "R~{W}"
    # add_net is converted too: the net keeps its class
    assert k5.nets["R~{W}"].netclass == "Default"


def test_zone_keeps_its_legacy_net_name(k5):
    # KiCad does not convert a zone's (net_name): it differs from net 1's converted
    # name, so pcbnew puts the zone on a new net "~RTS"
    assert sorted(z.net for z in k5.zones) == ["+5V", "~RTS"]


def test_renamed_copper_layers(k5):
    assert k5.stackup.copper == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert set(k5.layers) >= {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"} and "GND" not in k5.layers
    assert sorted(t.layer for t in k5.tracks) == ["F.Cu", "In1.Cu"]
    assert k5.vias[0].layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"] and k5.vias[0].type == "through"
    assert {z.net: z.layers for z in k5.zones} == {"~RTS": ["In2.Cu"], "+5V": ["In1.Cu"]}
    u1, u2 = sorted(k5.footprints, key=lambda f: f.ref)
    assert u1.side == "F" and u2.side == "B"
    assert u1.pads[0].layers == ["F.Cu", "F.Mask"]
    assert u2.pads[0].layers == ["B.Cu", "B.Mask"]


def test_npth_and_aperture_pads_have_no_number(k5):
    u1 = next(f for f in k5.footprints if f.ref == "U1")
    # numbers: none for NPTH or copperless pads (PAD::CanHaveNumber); nets: none for pads
    # without copper, which includes an NPTH pad no larger than its hole (PAD::IsOnCopperLayer)
    assert [(p.kind, p.number, p.net) for p in u1.pads] == [
        ("smd", "1", "~{RTS}"), ("thru_hole", "2", "R~{W}"), ("np_thru_hole", "", ""), ("smd", "", ""),
        ("np_thru_hole", "", "+5V")]


def test_new_boards_are_untouched(tmp_path):
    """A stamp past the overbar change keeps `~` names as written (KiCad does too), and
    canonical layer names give no aliases."""
    t = KICAD5.replace("(version 20171130)", "(version 20211014)")
    for old, new in (("Top", "F.Cu"), ("GND", "In1.Cu"), ("PWR", "In2.Cu"), ("Bottom", "B.Cu")):
        t = t.replace(f" {old} signal)", f" {new} signal)").replace(f" {old} power)", f" {new} power)")
        t = t.replace(f"(layer {old})", f"(layer {new})").replace(f"(layers {old} ", f"(layers {new} ")
    t = t.replace("(layers F.Cu Bottom)", "(layers F.Cu B.Cu)")
    p = tmp_path / "board.kicad_pcb"
    p.write_text(t)
    tree = kicad_file.parse_board(t)
    assert kicad_file.layer_aliases(tree) == {}
    b = kicad_file.load(p)
    assert set(b.nets) == {"~RTS", "R~W", "~CS~ X", "+5V"}
    assert b.stackup.copper == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
