# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.em.mesh and kae.em.topology: the raster connects what the board's copper connects, and nothing else.

A fine-pitch pad no wider than a cell whose edges fall on the cell centres used to rasterize to nothing (no centre
inside it, so no coverage was sampled): its track then read open. Different nets never share a raster piece; a
split the raster still makes is found against the board's own connectivity and bridged."""
import numpy as np
import pytest
from shapely.geometry import box

from kae.board.model import Board, Footprint, Pad, Stackup, Track, Via
from kae.em import solve as ES
from kae.em import topology as T
from kae.em.kicad import BoardMesh
from kae.em.mesh import Layer, Mesh

P = 0.25
OFFSETS = [0.0, 0.0625, 0.125, 0.1875]


def _pad(num, net, x, y, w, h, layers=("F.Cu",), drill=0.0):
    return Pad(number=str(num), net=net, kind="thru_hole" if drill else "smd", shape="rect", size=(w, h), lx=x, ly=y,
               lrot=0.0, x=x, y=y, layers=list(layers), drill=drill)


def _board(pads, tracks=(), vias=()):
    fp = Footprint(ref="U1", value="", lib_id="", uuid="", x=0.0, y=0.0, rot=0.0, side="F", locked=False,
                   pads=list(pads))
    st = Stackup(copper=["F.Cu", "B.Cu"], cu_thickness=[0.035, 0.035], gaps=[1.5], er=[4.5])
    return Board(path="synthetic.kicad_pcb", version=1, footprints=[fp], tracks=list(tracks), vias=list(vias),
                 stackup=st)


def _track(net, a, b, w=0.127, layer="F.Cu"):
    return Track(uuid=f"{net}{a}{b}", net=net, layer=layer, width=w, start=a, end=b)


def _comps(bm, *toks):
    """The copper piece of each pad (one network over all of them)."""
    ts = [bm.pad(t) for t in toks]
    net = ES.Network(bm.m)
    return [int(net.comp[net.term_node[t]]) for t in ts]


def _pad_row(off):
    """Eight 0.25 x 0.8 mm pads at 0.5 mm pitch, nets alternating, each with a 0.127 mm track leaving its end (off
    its centre line, inside the pad) to a test pad 2.5 mm away. At off = 0 the pads' long edges fall on cell centres."""
    pads, tracks = [], []
    for k in range(8):
        net = f"N{k}"
        x = 0.5 * k + off
        s = 1 if k % 2 == 0 else -1
        pads.append(_pad(k + 1, net, x, 0.0, 0.25, 0.8))
        tracks.append(_track(net, (x + 0.06, s * 0.36), (x + 0.06, s * 2.5)))
        pads.append(_pad(f"t{k}", net, x + 0.06, s * 2.8, 0.6, 0.6))
    return _board(pads, tracks)


@pytest.mark.parametrize("off", OFFSETS)
def test_fine_pitch_pads_keep_their_tracks_and_their_nets_apart(off):
    bm = BoardMesh(None, (-1, -4, 5, 4), P, b=_pad_row(off), fills={})
    assert bm.topology["splits"] == [] and bm.topology["joins"] == [] and bm.topology["unresolved"] == []
    assert bm.topology["bridged"] == []                 # connected by the raster itself, not by a repair
    cs = _comps(bm, *[f"U1.{k + 1}" for k in range(8)], *[f"U1.t{k}" for k in range(8)])
    for k in range(8):
        assert cs[k] == cs[8 + k], f"pad {k + 1} reads open from its track at offset {off}"
    assert len(set(cs[:8])) == 8                         # no two nets in one piece


def test_a_pad_between_two_rows_of_centres_covers_half_of_each():
    m = Mesh.over(0, 0, 2, 2, P, [Layer("T", 0.0, 0.035, 1)])
    cov = m.coverage(box(0.5, 0.875, 1.5, 1.125))       # 0.25 tall, edges on the centres of rows 3 and 4
    assert cov[3, 2:6] == pytest.approx(0.5) and cov[4, 2:6] == pytest.approx(0.5)
    assert cov.sum() == pytest.approx(1.0 * 0.25 / P ** 2)


def test_bars_join_only_one_nets_cells_and_a_terminal_never_spans_two_nets():
    bm = BoardMesh(None, (-1, -4, 5, 4), P, b=_pad_row(0.0), fills={})
    m = bm.m
    net = ES.Network(m)
    for o, (dj, di) in (("x", (0, 1)), ("y", (1, 0))):
        f = net.fil[o]
        lay = net.layer_of_sub[f["s"]]
        assert (m.lab[lay, f["j"], f["i"]] == m.lab[lay, f["j"] + dj, f["i"] + di]).all()
    both = np.zeros((m.ny, m.nx), bool)
    both[m.lab[0] == m.net_id("N0")] = True
    both[m.lab[0] == m.net_id("N1")] = True
    with pytest.raises(ValueError, match="nets"):
        m.terminal("bad", 0, mask=both)


def test_a_via_joins_two_layers_and_a_lost_landing_is_bridged():
    pads = [_pad("a", "S", 0.0, 0.0, 0.6, 0.6), _pad("b", "S", 4.0, 0.0, 0.6, 0.6, layers=("B.Cu",))]
    tracks = [_track("S", (0.0, 0.0), (2.0, 0.0)), _track("S", (2.0, 0.0), (4.0, 0.0), layer="B.Cu")]
    via = Via(uuid="v", net="S", x=2.0, y=0.0, size=0.6, drill=0.3, layers=["F.Cu", "B.Cu"])
    b = _board(pads, tracks, [via])
    bm = BoardMesh(None, (-1, -1, 5, 1), P, b=b, fills={})
    assert bm.topology["splits"] == []
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca == cb
    # without the via the board's copper is two pieces: the raster agrees (no split, no join)
    bm = BoardMesh(None, (-1, -1, 5, 1), P, b=_board(pads, tracks), fills={})
    assert bm.topology["splits"] == [] and bm.topology["joins"] == []
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca != cb
    # the via's landing on B.Cu lost (a cell taken by other copper): found and bridged
    bm = BoardMesh(None, (-1, -1, 5, 1), P, b=b, fills={}, topology=None)
    for _, cs in bm.m.via_landing(bm.m.vias[0]):
        for c in cs:
            if c[0] == 1:
                bm.m.lab[c] = -1
    rep = T.check(bm)
    assert len(rep["splits"]) == 1 and len(rep["bridged"]) == 1 and rep["splits"][0]["net"] == "S"
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca == cb


def test_two_pours_of_one_net_join_only_through_a_via():
    fills = {"G": {"F.Cu": [box(0, 0, 3, 3)], "B.Cu": [box(4, 0, 7, 3)]}}
    pads = [_pad("a", "G", 1.5, 1.5, 0.6, 0.6), _pad("b", "G", 5.5, 1.5, 0.6, 0.6, layers=("B.Cu",))]
    win = (-1, -1, 8, 4)
    bm = BoardMesh(None, win, P, b=_board(pads), fills=fills)
    rep = bm.topology
    assert rep["clusters"] == 2 and rep["splits"] == [] and rep["joins"] == []
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca != cb
    # a via in the overlap of the two pours' layers: a track on F.Cu from the pour to it, the via on the B.Cu pour
    fills = {"G": {"F.Cu": [box(0, 0, 3, 3)], "B.Cu": [box(3.5, 0, 7, 3)]}}
    via = Via(uuid="v", net="G", x=4.0, y=1.5, size=0.6, drill=0.3, layers=["F.Cu", "B.Cu"])
    b = _board(pads, [_track("G", (2.5, 1.5), (4.0, 1.5))], [via])
    bm = BoardMesh(None, win, P, b=b, fills=fills)
    assert bm.topology["clusters"] == 1 and bm.topology["splits"] == [] and bm.topology["joins"] == []
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca == cb


def test_a_track_crossing_a_fill_joins_it_only_where_it_ends_in_it():
    fills = {"G": {"F.Cu": [box(2, -1, 4, 1)]}}
    pads = [_pad("a", "G", 0.0, 0.0, 0.6, 0.6), _pad("b", "G", 6.0, 0.0, 0.6, 0.6), _pad("c", "G", 3.0, 0.6, 0.3, 0.3)]
    # a track from a to b straight across the fill, ending in neither: KiCad does not join it to the fill (c's piece)
    b = _board(pads, [_track("G", (0.0, 0.0), (6.0, 0.0))])
    bm = BoardMesh(None, (-1, -2, 7, 2), P, b=b, fills=fills)
    rep = bm.topology
    assert rep["splits"] == [] and len(rep["joins"]) == 1      # the raster fuses the copper; reported, not changed
    groups = rep["joins"][0]["items"]
    assert sorted(groups) == [["U1.a", "U1.b"], ["U1.c"]]
    # the same track ending in the fill (two segments meeting inside it): one piece, nothing to report
    b = _board(pads, [_track("G", (0.0, 0.0), (3.0, 0.0)), _track("G", (3.0, 0.0), (6.0, 0.0))])
    bm = BoardMesh(None, (-1, -2, 7, 2), P, b=b, fills=fills)
    assert bm.topology["clusters"] == 1 and bm.topology["joins"] == [] and bm.topology["splits"] == []


def test_a_split_in_a_track_is_bridged_with_its_resistance():
    b = _board([_pad("a", "S", 0.0, 0.0, 0.6, 0.6), _pad("b", "S", 4.0, 0.0, 0.6, 0.6)],
               [_track("S", (0.0, 0.0), (4.0, 0.0))])
    bm = BoardMesh(None, (-1, -1, 5, 1), P, b=b, fills={}, topology=None)
    j, i = bm.m.cell(2.0, 0.0)
    bm.m.lab[0, j, i] = -1                               # a cell of the track lost
    rep = T.check(bm)
    assert len(rep["bridged"]) == 1 and rep["bridged"][0]["gap_mm"] == pytest.approx(2 * P)
    assert any("bridged" in line for line in T.notes(rep))
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca == cb
    q = [x for x in bm.m.lumped if x.name == "bridge:S"]
    assert len(q) == 1 and q[0].R == pytest.approx(Mesh.RHO_CU_OHM_MM * 2 * P / (P * 0.035))


def test_a_track_whose_end_lies_in_another_nets_cells_is_joined_at_that_end():
    """Two 0.1 mm tracks meeting at a point where a pour of another net owns the cells (the pour's edge cells cover
    more): neither chain reaches the point, and the chains are bridged there."""
    fills = {"G": {"F.Cu": [box(1.0, 0.12, 4.0, 2.0), box(1.0, -2.0, 4.0, -0.12)]}}
    pads = [_pad("a", "S", 0.0, 0.0, 0.6, 0.6), _pad("b", "S", 2.5, 2.5, 0.6, 0.6)]
    tracks = [_track("S", (0.0, 0.0), (2.5, 0.0), w=0.1), _track("S", (2.5, 0.0), (2.5, 2.5), w=0.1)]
    b = _board(pads, tracks)
    bm = BoardMesh(None, (-1, -3, 5, 3.5), P, b=b, fills=fills)
    assert bm.topology["splits"] == [] and bm.topology["bridged"] == []      # joined by the raster's own bridges
    ca, cb = _comps(bm, "U1.a", "U1.b")
    assert ca == cb


def test_a_through_hole_pad_sharing_its_number_with_smd_pads_keeps_its_barrel():
    """A hotswap footprint: pad 1 is an SMD pad on B.Cu and a plated hole; the track to the hole is on F.Cu."""
    pads = [_pad("1", "S", 3.0, 0.0, 1.0, 1.0, layers=("B.Cu",)),
            _pad("1", "S", 0.0, 0.0, 1.6, 1.6, layers=("F.Cu", "B.Cu"), drill=1.0),
            _pad("t", "S", 0.0, 3.0, 0.6, 0.6)]
    tracks = [_track("S", (0.0, 0.0), (0.0, 3.0), w=0.3), _track("S", (0.0, 0.0), (3.0, 0.0), w=0.3, layer="B.Cu")]
    bm = BoardMesh(None, (-2, -2, 5, 4), P, b=_board(pads, tracks), fills={})
    assert len(bm.m.vias) == 1 and bm.topology["splits"] == []
    net = ES.Network(bm.m)
    assert net.ncomp == 1 or len({int(net.comp[n]) for n in net.node[net.node >= 0]}) == 1


def test_pads_sharing_a_number_are_separate_items_and_a_track_over_a_pad_centre_joins_it():
    nc = "unconnected-(U1-MP)"
    pads = [_pad("MP", nc, 0.0, 0.0, 1.0, 1.0), _pad("MP", nc, 6.0, 0.0, 1.0, 1.0),
            _pad("x", "S", 0.0, 2.0, 0.6, 0.6), _pad("y", "S", 3.0, 2.0, 0.6, 0.6), _pad("z", "S", 6.0, 2.0, 0.6, 0.6)]
    # one track from x to z passing over y's centre, ending in neither y nor its middle
    b = _board(pads, [_track("S", (0.0, 2.0), (6.0, 2.0))])
    ref = T.reference(BoardMesh(None, (-1, -1, 7, 3), P, b=b, fills={}, topology=None))
    assert ref[("pad", "U1.MP#0")] != ref[("pad", "U1.MP#1")]
    assert ref[("pad", "U1.x")] == ref[("pad", "U1.y")] == ref[("pad", "U1.z")]
    bm = BoardMesh(None, (-1, -1, 7, 3), P, b=b, fills={})
    assert bm.topology["splits"] == [] and bm.topology["joins"] == [] and bm.topology["clusters"] == 3
