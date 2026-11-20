# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.place.cutflow: cut capacities, negotiated overflow and per-part pressure from the placement alone."""
import json
import random
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
from shapely.geometry import box

from kae.place import cutflow as CF

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _pad(x, y, net="", size=0.5, kind="smd", layers=("F.Cu",)):
    return NS(x=x, y=y, net=net, size=(size, size), kind=kind, layers=list(layers))


def _board(parts, copper=("F.Cu", "B.Cu"), outline=None, clr=0.2, w=0.2):
    """parts: {ref: [pads]}."""
    fps = [NS(ref=ref, pads=pads, on_board=True) for ref, pads in parts.items()]
    return NS(footprints=fps, zones=[], outline=outline, stackup=NS(copper=list(copper)),
              rules=NS(netclasses={"Default": NS(clearance=clr, track_width=w)}))


def _channel(gap, nets=3):
    """A wall of through-hole pads across a one-layer 20 x 20 mm board along y = 0, part L left of x = 0 and part R
    right of it, with one opening of `gap` mm copper-to-copper between them; `nets` two-pin nets cross it top to bottom.
    Wall pads are 2 mm at a 1.5 mm pitch (overlapping: no capacity between them). Tiny no-net filler pads on a 2 mm
    grid off the wall (part F) refine the triangulation so that a route's cuts follow its geometry."""
    a = (gap + 2.0) / 2           # centre offset of the opening's two pads (r = 1 each)
    th = dict(size=2.0, kind="thru_hole", layers=("F.Cu",))
    left = [_pad(-a - 1.5 * i, 0.0, **th) for i in range(int((10 - a) / 1.5) + 1)]
    right = [_pad(a + 1.5 * i, 0.0, **th) for i in range(int((10 - a) / 1.5) + 1)]
    left.append(_pad(-10.0, 0.0, **th))
    right.append(_pad(10.0, 0.0, **th))
    parts = {"L": left, "R": right}
    for k in range(nets):
        x = (k - (nets - 1) / 2) * 0.6
        parts[f"T{k}"] = [_pad(x, 6.0, f"N{k}")]
        parts[f"B{k}"] = [_pad(x, -6.0, f"N{k}")]
    parts["F"] = [_pad(2.0 * i, 2.0 * j, size=0.01) for i in range(-4, 5) for j in range(-4, 5) if j]
    return _board(parts, copper=("F.Cu",), outline=box(-10, -10, 10, 10))


def _cut(g, ref_a, ref_b):
    """Cuts whose ends belong to ref_a and ref_b."""
    return [e for e, (u, v) in enumerate(g.cut_ends)
            if u < g.npad and v < g.npad and {g.owner[u], g.owner[v]} == {ref_a, ref_b}]


def test_a_channel_that_fits_two_tracks_overflows_by_one_for_three_nets_and_names_its_parts():
    # (1.2 - 0.2) / (0.2 + 0.2) = 2.5: two tracks fit the opening
    g = CF.build(_channel(1.2))
    [e] = _cut(g, "L", "R")
    assert g.cap[e] == 2
    r = CF.route(g)
    assert r["ovfK"] == 1 and r["ncutK"] == 1
    assert r["parts"] == {"L": pytest.approx(0.4), "R": pytest.approx(0.4)}     # one track short: one pitch of gap
    assert r["pairs"] == {("L", "R"): pytest.approx(0.4)}


def test_widening_the_channel_by_one_pitch_removes_the_overflow():
    g = CF.build(_channel(1.2 + 0.4))
    [e] = _cut(g, "L", "R")
    assert g.cap[e] == 3
    r = CF.route(g)
    assert r["ovfK"] == 0
    assert r["parts"] == {} and r["pairs"] == {}


def _two_pads(kind, layers):
    """P1, P2 (1 mm square, 2 mm apart) plus four far pads on two nets."""
    parts = {"P1": [_pad(0.0, 0.0, size=1.0, kind=kind, layers=layers)],
             "P2": [_pad(2.0, 0.0, size=1.0, kind=kind, layers=layers)]}
    for i, (x, y) in enumerate([(-6, 6), (8, 6), (-6, -6), (8, -6)]):
        parts[f"Q{i}"] = [_pad(x, y, f"M{i % 2}")]
    return _board(parts, outline=box(-8, -8, 10, 8))


def test_an_smd_pad_narrows_only_its_own_layer_a_through_hole_pad_every_layer():
    g = CF.build(_two_pads("smd", ("F.Cu", "F.Paste", "F.Mask")))
    [e] = _cut(g, "P1", "P2")
    # F.Cu: gap 2 - 0.5 - 0.5 = 1.0 -> floor(0.8 / 0.4) = 2; B.Cu: gap 2.0 -> floor(1.8 / 0.4) = 4
    assert g.cap[e] == 6
    g = CF.build(_two_pads("thru_hole", ("F.Cu", "B.Cu")))
    [e] = _cut(g, "P1", "P2")
    assert g.cap[e] == 4


def test_inner_layers_covered_by_zones_are_planes_and_zone_nets_are_not_routed():
    bd = _two_pads("thru_hole", ("F.Cu", "In1.Cu", "B.Cu"))
    bd.stackup.copper = ["F.Cu", "In1.Cu", "B.Cu"]
    bd.zones = [NS(net="M0", layers=["In1.Cu"], outline=box(-8, -8, 10, 8))]
    g = CF.build(bd)
    assert g.signal_layers == ["F.Cu", "B.Cu"]
    assert "M0" in g.zone_nets and len(g.conns) == 1


def _random_board(n=80, seed=3):
    rng = random.Random(seed)
    parts = {}
    for i in range(n // 4):
        x, y = rng.uniform(1, 29), rng.uniform(1, 19)
        kind = "thru_hole" if i % 5 == 0 else "smd"
        layers = ("F.Cu", "B.Cu") if kind == "thru_hole" else ("F.Cu",)
        parts[f"U{i}"] = [_pad(x + dx, y + dy, f"S{rng.randrange(n // 6)}", 0.6, kind, layers)
                          for dx, dy in ((0, 0), (0.8, 0), (0, 0.8), (0.8, 0.8))]
    return _board(parts, outline=box(0, 0, 30, 20))


def test_same_seed_same_result():
    a = CF.route(CF.build(_random_board()), seed=4)
    b = CF.route(CF.build(_random_board()), seed=4)
    assert a["ovf0"] == b["ovf0"] and a["ovfK"] == b["ovfK"]
    assert np.array_equal(a["demand"], b["demand"])
    assert a["parts"] == b["parts"] and a["pairs"] == b["pairs"]


def test_values_match_the_stage0_prototype():
    # Pinned from cutrank.py measures() (2026-11 gap audit, design 2) on the same boards and rules.
    m = CF.measure(_random_board(), 0.2, 0.2)
    assert (m["ovf0"], m["ovfK"], m["ncut0"], m["ncutK"], m["nconn"]) == PINNED_RANDOM
    m = CF.measure(FIXTURE)
    assert (m["ovf0"], m["ovfK"], m["npad"], m["nconn"]) == PINNED_FIXTURE


def test_pressure_file_schema(tmp_path):
    out = tmp_path / "p.json"
    assert CF.main([str(FIXTURE), "--pressure", str(out), "--json"]) == 0
    doc = json.loads(out.read_text())
    assert doc["schema"] == 1 and doc["source"] == "cutflow"
    assert set(doc) == {"schema", "source", "parts", "pairs"}
    assert all(isinstance(k, str) and isinstance(v, float) for k, v in doc["parts"].items())
    for a, b, mm in doc["pairs"]:
        assert isinstance(a, str) and isinstance(b, str) and a < b and mm > 0
        assert doc["parts"][a] >= mm and doc["parts"][b] >= mm
    assert CF.pressure_doc({"U1": 0.4}, {("R1", "U1"): 0.4}) == {
        "schema": 1, "source": "cutflow", "parts": {"U1": 0.4}, "pairs": [["R1", "U1", 0.4]]}


PINNED_RANDOM = (113.0, 1.0, 56, 1, 67)    # ovf0, ovfK, ncut0, ncutK, connections
PINNED_FIXTURE = (0.0, 0.0, 25, 11)        # ovf0, ovfK, pads, connections (Default class 0.2 / 0.25 mm)


def test_same_result_whatever_the_hash_seed(tmp_path):
    # two-pin nets first seen at a merged pad beside another new net: the routing order must not follow Python's
    # string hashing (unsorted, seed 3 gave ovfK 5 and the others 6)
    script = tmp_path / "run.py"
    script.write_text(
        "import sys; sys.path[:0] = [%r]\n"
        "import test_place_cutflow as T\nfrom kae.place import cutflow as CF\n"
        "bd = T._random_board()\n"
        "for k, fp in enumerate(bd.footprints[::3]):\n"
        "    fp.pads.append(T._pad(fp.pads[0].x, fp.pads[0].y, 'X%%d' %% (k // 2)))\n"
        "r = CF.route(CF.build(bd), seed=1)\nprint(r['ovf0'], r['ovfK'], list(r['demand']))\n" % str(Path(__file__).parent))
    import os
    import subprocess
    import sys
    outs = {subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True,
                           env=dict(os.environ, PYTHONHASHSEED=str(h))).stdout for h in (1, 2, 3, 4)}
    assert len(outs) == 1


def test_edge_model_measures_copper_to_copper():
    tall = dict(size=(0.5, 2.0), kind="smd", layers=["F.Cu"])
    parts = {"P1": [NS(x=0.0, y=0.0, net="", **tall)], "P2": [NS(x=2.0, y=0.0, net="", **tall)]}
    for i, (x, y) in enumerate([(-6, 6), (8, 6), (-6, -6), (8, -6)]):
        parts[f"Q{i}"] = [_pad(x, y, f"M{i % 2}")]
    bd = _board(parts, outline=box(-8, -8, 10, 8))
    [e] = _cut(CF.build(bd), "P1", "P2")
    # centre model: r = (0.5 + 2) / 4 each -> F.Cu gap 0.75 -> 1; B.Cu 2.0 -> 4
    assert CF.build(bd).cap[e] == 5
    g = CF.build(bd, model="edge")
    [e] = _cut(g, "P1", "P2")
    # edge model: copper 1.5 apart on F.Cu -> floor(1.3 / 0.4) = 3; B.Cu 2.0 -> 4
    assert g.cap[e] == 7
    assert CF.measure(FIXTURE, model="edge")["npad"] == PINNED_FIXTURE[2]


def test_measured_counts_routed_tracks_through_a_one_track_gap():
    bd = _channel(0.8)                       # (0.8 - 0.2) / 0.4 = 1.5: one track fits
    bd.tracks = [NS(net=f"N{k}", layer="F.Cu", width=0.2, start=(x, 3.0), end=(x, -3.0), mid=None)
                 for k, x in ((0, -0.1), (1, 0.1))]
    bd.tracks.append(NS(net="N2", layer="B.Cu", width=0.2, start=(0.0, 3.0), end=(0.0, -3.0), mid=None))  # not a signal layer here
    r = CF.measured(bd)
    [e] = _cut(r["graph"], "L", "R")
    assert r["capacity"][e] == 1 and r["demand"][e] == 2
    assert r["ovf"] == 1
    assert r["parts"] == {"L": pytest.approx(0.4), "R": pytest.approx(0.4)}
    assert r["pairs"] == {("L", "R"): pytest.approx(0.4)}
    assert CF.pressure_doc(r["parts"], r["pairs"], "measured")["source"] == "measured"
