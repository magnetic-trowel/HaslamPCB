# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A KiCad rule area that forbids tracks holds in every routing stage (bme280-array F32: copper keepouts on the
edge strips beside a slot keep tracks on the thermal bridge). One plan obstacle feeds them all: Freerouting's DSN
(translate.apply writes plan.obstacles as keepouts), the Space of the last mile, taut, the critical router and power
copper (critical_space builds plan.obstacles into its items), and the repair rounds' widening and spoke checks
(repair._Space). The KiCad test checks the export reads the area and the DSN carries it."""
import json
import shutil
from pathlib import Path

import pytest
from shapely.geometry import LineString, box

import critical_fixtures as F
from haslam.route import constraints as CN

AREA = (106.0, 109.0, 112.0, 113.0)       # across the fixture's J1 -> U1 input path on F.Cu


def _info(tmp_path, tracks=True, vias=True):
    from haslam.board.kicad_file import load
    p = F.write_board(tmp_path)
    b = load(p)
    info = F.synth_info(b)
    x0, y0, x1, y1 = AREA
    info["zones"].append(dict(owner="", name="STRIP_W", layers=["F.Cu"], rule_area=True, net="",
                              rings=[[[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]],
                              no_tracks=tracks, no_vias=vias, no_pads=False, no_pour=False, no_footprints=False))
    return p, b, info


def _rule_area_obstacles(plan):
    return [ob for ob in plan.obstacles if ob.why.startswith("rule area STRIP_W")]


@pytest.mark.parametrize("vias,kind", [(True, "keepout"), (False, "wire_keepout")])
def test_the_plan_holds_the_rule_area(tmp_path, vias, kind):
    p, _b, info = _info(tmp_path, vias=vias)
    obs = _rule_area_obstacles(CN.plan(info, p, dict(severities={})))
    assert [(ob.kind, ob.layer) for ob in obs] == [(kind, "F.Cu")]
    assert obs[0].geom.equals(box(*AREA))


def test_every_stage_sees_it(tmp_path):
    from haslam.route import translate
    from haslam.route.critical_space import Space
    from haslam.route.repair import _Space
    p, b, info = _info(tmp_path)
    plan = CN.plan(info, p, dict(severities={}))
    across, beside = ((104.5, 111.0), (113.5, 111.0)), ((104.5, 114.5), (113.5, 114.5))
    # the last mile, taut, the critical router and power copper: Space (built from the plan, or given it)
    for sp in (Space(b, info, plan=plan), Space(b, info)):
        assert sp.track_violations("VIN", "F.Cu", 0.25, *across, first=True)
        assert any(getattr(v[0], "kind", None) == "keepout" for v in sp.track_violations("VIN", "F.Cu", 0.25, *across))
        assert not [v for v in sp.track_violations("VIN", "F.Cu", 0.25, *beside)
                    if getattr(v[0], "kind", None) == "keepout"]
        assert not [v for v in sp.track_violations("VIN", "B.Cu", 0.25, *across)       # F.Cu only
                    if getattr(v[0], "kind", None) == "keepout"]
    # the repair rounds: a widened track or a spoke must not enter it
    rs = _Space({}, info, plan)
    assert not rs.fits_geom("VIN", "F.Cu", LineString(across).buffer(0.125))
    assert rs.fits_geom("VIN", "B.Cu", LineString(across).buffer(0.125))
    # Freerouting: the obstacle's DSN shape is the area on its layer
    (main, windows), = translate._shape_nodes(_rule_area_obstacles(plan)[0], lambda l: l, plan.copper)
    assert main[:2] == ["polygon", "F.Cu"] and not windows


def test_power_copper_grows_around_it(tmp_path):
    from haslam.route import power_copper as pc
    from test_route_power_copper_keepout import SEG
    p = F.write_board(tmp_path)
    s = p.read_text()
    i = s.rindex("\t(embedded_fonts no)")
    s = s[:i] + SEG.format(104.0, 111.0, 114, 111, "VIN", "0000000a-0000-0000-0000-00000000aaaa") + s[i:]
    p.write_text(s)
    from haslam.board.kicad_file import load
    b = load(p)
    info = F.synth_info(b)
    x0, y1 = AREA[0], AREA[3]
    # a strip just above the track: the track itself may stay (KiCad flags only new copper here), growth may not
    strip = (x0, 111.3, AREA[2], y1)
    info["zones"].append(dict(owner="", name="STRIP_W", layers=["F.Cu"], rule_area=True, net="",
                              rings=[[[[strip[0], strip[1]], [strip[2], strip[1]], [strip[2], strip[3]],
                                       [strip[0], strip[3]], [strip[0], strip[1]]]]],
                              no_tracks=True, no_vias=True))
    obj = pc.PowerCopper(p, dict(vias=False, stitch=False, neck=False), info=info, fills={}, log=lambda *a: None)
    obj.widen()
    pieces = [x for v in obj.edits.values() for x in v]
    assert any(w > 0.25 + 1e-9 for _a, _b, w, *_ in pieces), "VIN must still grow outside the area"
    for a, b_, w, *_ in pieces:
        assert LineString([a, b_]).buffer(w / 2, cap_style=2).intersection(box(*strip)).area < 1e-6, (a, b_, w)


# ----------------------------------------------------------------------------- live KiCad
KEEPOUT = '''\t(zone
\t\t(layer "F.Cu")
\t\t(uuid "0000000b-0000-0000-0000-00000000cccc")
\t\t(name "STRIP_W")
\t\t(hatch edge 0.5)
\t\t(connect_pads (clearance 0))
\t\t(min_thickness 0.25)
\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour allowed) (footprints allowed))
\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))
\t\t(polygon (pts (xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1})))
\t)
'''


def _kicad_ok():
    from haslam.board import pcbnew_io
    return pcbnew_io.available()


@pytest.mark.kicad
@pytest.mark.skipif(not _kicad_ok(), reason="no Python with pcbnew")
def test_kicad_rule_area_reaches_the_dsn(tmp_path):
    from haslam.board import pcbnew_io
    from haslam.route import specctra, translate
    src = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"
    p = tmp_path / "board.kicad_pcb"
    text = src.read_text()
    for ext in (".kicad_pro", ".kicad_dru"):
        if src.with_suffix(ext).exists():
            shutil.copy(src.with_suffix(ext), p.with_suffix(ext))
    from haslam.board.kicad_file import load
    b0 = load(src)
    ox0, oy0, ox1, oy1 = b0.outline[0].bounds
    cx, cy = (ox0 + ox1) / 2, (oy0 + oy1) / 2
    area = dict(x0=round(cx - 2, 3), y0=round(cy - 1, 3), x1=round(cx + 2, 3), y1=round(cy + 1, 3))
    i = text.rindex("\t(embedded_fonts")
    p.write_text(text[:i] + KEEPOUT.format(**area) + text[i:])
    info = pcbnew_io.export_dsn(p, tmp_path / "kicad.dsn")
    zs = [z for z in info["zones"] if z.get("name") == "STRIP_W"]
    assert len(zs) == 1 and zs[0]["rule_area"] and zs[0]["no_tracks"] and zs[0]["no_vias"]
    plan = CN.plan(info, p)
    assert [(ob.kind, ob.layer) for ob in _rule_area_obstacles(plan)] == [("keepout", "F.Cu")]
    tree = specctra.read(tmp_path / "kicad.dsn")
    n_with = translate.apply(tree, plan, info)["obstacles"]
    out = tmp_path / "board.dsn"
    specctra.write(tree, out)
    dsn = " ".join(out.read_text().split())
    # a keepout polygon on F.Cu spanning the area (DSN um, y up)
    want = (area["x0"], area["y0"], area["x1"], area["y1"])
    assert any(_bbox(k) is not None and all(abs(a - b) < 0.01 for a, b in zip(_bbox(k), want))
               for k in _sexpr_lines(dsn) if "(polygon F.Cu" in k), "rule area missing from the DSN"
    # and it is one keepout more than the same board without the area
    info2 = dict(info, zones=[z for z in info["zones"] if z.get("name") != "STRIP_W"])
    n_without = translate.apply(specctra.read(tmp_path / "kicad.dsn"), CN.plan(info2, p), info2)["obstacles"]
    assert n_with == n_without + 1


def _bbox(node):
    """(x0, y0, x1, y1) board mm of the first polygon in a DSN node, or None."""
    i = node.find("(polygon")
    if i < 0:
        return None
    nums = [float(t) for t in node[i:node.find(")", i)].split()[3:]]
    xs, ys = [x / 1000 for x in nums[0::2]], [-y / 1000 for y in nums[1::2]]
    return min(xs), min(ys), max(xs), max(ys)


def _sexpr_lines(text):
    """Top-level-ish (keepout ...) nodes of a DSN, one string each."""
    out, i = [], 0
    while True:
        i = text.find("(keepout", i)
        if i < 0:
            return out
        depth, j = 0, i
        while j < len(text):
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
            if depth == 0:
                break
        out.append(text[i:j].replace("\n", " "))
        i = j
