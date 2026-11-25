# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.em.mesh: a track of zero width is no copper. It must not crash the bar builder (its width
divided the pitch) and must not join anything."""
from haslam.em import solve as ES
from haslam.em.mesh import Layer, Mesh


def test_a_zero_width_track_is_no_copper():
    m = Mesh.over(0, -2, 6, 2, 0.25, [Layer("T", 0.0, 0.035, 1)])
    m.paint_line(0, "A", [(0.2, 0.05), (5.8, 0.05)], 0.0)
    m.paint_line(0, "B", [(0.2, 1.05), (5.8, 1.05)], 0.15)       # a real track beside it still conducts
    m.terminal("b0", 0, xy=(0.2, 1.05), net="B")
    m.terminal("b1", 0, xy=(5.8, 1.05), net="B")
    net = ES.Network(m)
    assert int(net.comp[net.term_node["b0"]]) == int(net.comp[net.term_node["b1"]])
    assert not any(w <= 0 for w, _ in m.thin.values())
    assert not (m.lab[0][:, :] == m.net_id("A")).any()
