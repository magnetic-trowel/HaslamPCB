# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth.layout: footprint geometry, pin escape, pad gaps and the fab minimums (no KiCad needed)."""
from haslamsynth import layout as LY

# a 4-pad row at 0.5 mm pitch, pads 0.3 x 1.0 (long along y: tracks leave along y), as in an MSOP side
MOD = """(footprint "T"
  (layer "F.Cu")
  (fp_rect (start -1.5 -1.5) (end 1.5 1.5) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
  (pad "1" smd roundrect (at -0.75 0) (size 0.3 1.0) (layers "F.Cu"))
  (pad "2" smd roundrect (at -0.25 0) (size 0.3 1.0) (layers "F.Cu"))
  (pad "3" smd roundrect (at 0.25 0) (size 0.3 1.0) (layers "F.Cu"))
  (pad "4" smd roundrect (at 0.75 0) (size 0.3 1.0) (layers "F.Cu"))
  (pad "" smd rect (at 0 1.2) (size 0.2 0.2) (layers "F.Paste"))
)"""


def _geo(tmp_path):
    p = tmp_path / "T.kicad_mod"
    p.write_text(MOD)
    return LY.footprint_geometry(str(p))


def test_geometry_pads_courtyard_pitch(tmp_path):
    pads, bbox = _geo(tmp_path)
    assert [q.number for q in pads] == ["1", "2", "3", "4"]       # unnamed paste pads left out
    assert bbox == (-1.5, -1.5, 1.5, 1.5)
    assert abs(LY.pitch_of(pads) - 0.5) < 1e-9
    assert pads[0].long_axis() == "y"


def test_escape_room_and_gap(tmp_path):
    pads, _ = _geo(tmp_path)
    a, b, d = pads[0], pads[1], pads[3]
    # a 0.127 mm track leaving pad 1 along y passes 0.5 - 0.0635 - 0.15 from pad 2
    assert abs(LY._escape_room(a, b, 0.127) - 0.2865) < 1e-9
    assert abs(LY._gap(a, b) - 0.2) < 1e-9
    assert LY._escape_room(a, d, 0.127) > 1.0                     # far pad: room is large


def test_rotated_pad_extents():
    p = LY.Pad("1", 0, 0, 0.3, 1.0, 90.0, True)
    assert p.extents() == (0.5, 0.15) and p.long_axis() == "x"
