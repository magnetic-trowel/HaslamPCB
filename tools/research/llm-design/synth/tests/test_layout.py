# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kaesynth.layout: footprint geometry, pin escape, pad gaps and the fab minimums (no KiCad needed)."""
from kaesynth import layout as LY

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


# ----------------------------------------------------------------------------------------- relations
IC = """(footprint "IC" (layer "F.Cu")
  (fp_rect (start -2 -2) (end 2 2) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
  (pad "1" smd rect (at -1.5 0) (size 0.5 0.5) (layers "F.Cu"))
  (pad "2" smd rect (at 1.5 0) (size 0.5 0.5) (layers "F.Cu")))"""
CAP = """(footprint "CAP" (layer "F.Cu")
  (fp_rect (start -1 -0.5) (end 1 0.5) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
  (pad "1" smd rect (at -0.5 0) (size 0.4 0.4) (layers "F.Cu"))
  (pad "2" smd rect (at 0.5 0) (size 0.4 0.4) (layers "F.Cu")))"""


def _rel_design(tmp_path):
    from kaesynth import Design, PartDef, PinDef
    from kaesynth.kicadlib import FootprintLibs
    lib = tmp_path / "t.pretty"
    lib.mkdir()
    (lib / "IC.kicad_mod").write_text(IC)
    (lib / "CAP.kicad_mod").write_text(CAP)
    d = Design("rel")
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.net("VIN", domain="LV", v=(0, 5), kind="power")
    b = d.block("b")
    u = b.add(PartDef(mpn="IC1", category="ic", footprint="t:IC", pins=[PinDef("1", "VIN"), PinDef("2", "GND")]),
              ref="U1")
    caps = [b.add(PartDef(mpn="C", category="capacitor", footprint="t:CAP", pins=[PinDef("1", "1"), PinDef("2", "2")]),
                  ref=r) for r in ("C1", "C2")]
    for p in (u, *caps):
        d.nets["VIN"].connect(p["1" if p is not u else "VIN"])
        d.nets["GND"].connect(p["2" if p is not u else "GND"])
    d.finalize()
    return d, FootprintLibs(tmp_path / "none", local=[tmp_path])


def _run(d, fl, rows, fixed=None):
    out = []
    kept = LY.check_relations(d, fl, rows, lambda *a: out.append(a), fixed=fixed, outline=(100, 50))
    return kept, {(c, s): [m for cc, ss, m, _ in out if (cc, ss) == (c, s)] for c, s, _, _ in out}


def test_relation_courtyards_bound_a_near(tmp_path):
    # U1.1 sits 0.5 mm inside its courtyard, a CAP pad 0.5 mm inside its own: 1.0 mm is the least reachable
    d, fl = _rel_design(tmp_path)
    rows = [{"id": "far", "kind": "near", "a": "C1", "b": "U1.1", "within_mm": 0.8},
            {"id": "edge", "kind": "near", "a": "C1", "b": "U1.1", "within_mm": 1.05},
            {"id": "ok", "kind": "near", "a": "C1", "b": "U1.1", "mag": "tight"}]
    kept, f = _run(d, fl, rows)
    assert [r["id"] for r in kept] == ["far", "edge", "ok"]          # free parts: kept, the placer still acts
    err = f[("kae_intent.relation_infeasible", "error")]
    assert len(err) == 1 and err[0].startswith("far:") and "1.00 mm" in err[0] and "loosen it to 1.5 mm" in err[0]
    warn = f[("kae_intent.relation_infeasible", "warning")]
    assert len(warn) == 1 and warn[0].startswith("edge:")


def test_relation_free_edge_reach(tmp_path):
    # U1's pads (0.25 mm half size) need 0.5 mm copper-to-edge clearance: a pad centre 0.75 mm from the edge
    d, fl = _rel_design(tmp_path)
    kept, f = _run(d, fl, [{"id": "e", "kind": "edge", "part": "U1", "edge": "west", "within_mm": 0.5},
                           {"id": "e2", "kind": "edge", "part": "U1", "edge": "west"}])
    assert len(kept) == 2
    (err,) = f[("kae_intent.relation_infeasible", "error")]
    assert err.startswith("e:") and "0.75 mm" in err


def test_relation_fixed_sides_dropped_and_checked(tmp_path):
    d, fl = _rel_design(tmp_path)
    fixed = {"U1": {"x": 10, "y": 10, "rot": 0}, "C2": {"x": 30, "y": 10, "rot": 0}}
    rows = [{"id": "n", "kind": "near", "a": "C2", "b": "U1", "mag": "tight"},
            {"id": "k", "kind": "keep_away", "a": "C2", "b": "U1", "mag": "close"},
            {"id": "e", "kind": "edge", "part": "U1", "edge": "west"},
            {"id": "e-ok", "kind": "edge", "part": "U1", "edge": "west", "within_mm": 9.0},
            {"id": "free", "kind": "near", "a": "C1", "b": "U1", "mag": "close"},
            {"id": "g", "kind": "group", "members": ["U1", "C1", "C2"], "mag": "loose"}]
    kept, f = _run(d, fl, rows, fixed)
    by = {r["id"]: r for r in kept}
    assert set(by) == {"free", "g"}                                  # every all-fixed row dropped
    assert by["g"]["members"] == ["U1", "C1"]                        # C2 only related to the fixed anchor
    errs = f[("kae_intent.relation_infeasible", "error")]
    assert sorted(e.split(":")[0] for e in errs) == ["e", "n"]       # keep_away and e-ok are met where fixed
    assert any("8.50 mm from the west edge" in e for e in errs)
    assert any("U1 or C2" in e or "C2 or U1" in e for e in errs)
    info = f[("layout.relation", "info")]
    assert sum("already decided" in m for m in info) == 4 and "2 written for kae" in info[-1]
