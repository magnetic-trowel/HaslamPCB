# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.em.mesh: copper that holds no cell centre (a 0.25 mm pad whose long edges run through a row of centres at
0.25 mm pitch) is still painted, so a track that ends on the pad away from its centre cell connects to it, as in
KiCad."""
from shapely.geometry import box

from haslam.em import solve as ES
from haslam.em.mesh import Layer, Mesh


def _mesh():
    return Mesh.over(0, 0, 4, 2, 0.25, [Layer("T", 0.0, 0.035, 1)])


def test_a_pad_between_rows_of_centres_is_painted():
    m = _mesh()
    pad = box(1.55, 0.875, 2.45, 1.125)          # 0.9 x 0.25 mm; its long edges on the centres of rows 3 and 4
    cov = m.coverage(pad)
    assert abs(cov.sum() * m.pitch ** 2 - pad.area) < 0.05 * pad.area
    assert m.paint(0, "A", pad) >= 6


def test_a_track_ending_on_the_pad_edge_connects():
    m = _mesh()
    pad = box(1.55, 0.875, 2.45, 1.125)
    m.paint_connected(0, "A", pad)
    m.paint_line(0, "A", [(1.686, 1.0), (1.686, 0.1)], 0.25)       # enters the pad at its end, not its centre
    m.terminal("pad", 0, geom=pad, net="A")
    m.terminal("far", 0, xy=(1.686, 0.1), net="A")
    net = ES.Network(m)
    assert net.comp[net.term_node["pad"]] == net.comp[net.term_node["far"]]


def test_neighbouring_pads_of_other_nets_stay_apart():
    m = _mesh()
    a, b = box(1.55, 0.875, 2.45, 1.125), box(1.55, 1.375, 2.45, 1.625)    # 0.5 mm pitch, 0.25 mm apart
    m.paint_connected(0, "A", a)
    m.paint_connected(0, "B", b)
    m.terminal("a", 0, geom=a, net="A")
    m.terminal("b", 0, geom=b, net="B")
    net = ES.Network(m)
    assert net.comp[net.term_node["a"]] != net.comp[net.term_node["b"]]
