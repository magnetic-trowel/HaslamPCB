# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.em.topology's reference connectivity against live KiCad's (skipped without pcbnew).

The raster check judges the mesh by the board's own connectivity; that reference must group a net's pads and vias
exactly as pcbnew does, or the check bridges splits KiCad does not see and misses joins it does."""
import pytest

from connectivity_fixtures import connectivity_board
from haslam.board import pcbnew_io

pytestmark = [pytest.mark.kicad,
              pytest.mark.skipif(not pcbnew_io.available(), reason="no Python with pcbnew")]


@pytest.mark.parametrize("pitch", [0.25, 0.1])
def test_mesh_topology_reference_is_kicads(tmp_path, pitch):
    from haslam.em import topology as T
    from haslam.em.kicad import BoardMesh
    p = tmp_path / "conn.kicad_pcb"
    nets = connectivity_board(p)
    got = pcbnew_io.copper_items(p, clusters=True)
    assert got["unconnected"] == 1                                   # C9 only
    kc = {i["uuid"]: i["cluster"] for i in got["items"]}
    bm = BoardMesh(p, (-2, -2, 32, 180), pitch)
    item_of = {}                                                     # KiCad uuid -> the check's item
    for f in bm.b.footprints:
        for q in f.pads:
            item_of[q.uuid] = ("pad", f"{f.ref}.{q.number}")
    for k, v in enumerate(bm.b.vias):
        item_of[v.uuid] = ("via", k)
    ref = T.reference(bm)
    for net in nets:
        mine = {i["uuid"] for i in got["items"] if i["net"] == net and i["uuid"] in item_of}
        kicad, ours = {}, {}
        for u in mine:
            kicad.setdefault(kc[u], set()).add(item_of[u])
            ours.setdefault(ref[item_of[u]], set()).add(item_of[u])
        assert sorted(map(sorted, kicad.values())) == sorted(map(sorted, ours.values())), net
        assert len(kicad) == (2 if net == "C9" else 1), net
    rep = bm.topology
    assert rep["splits"] == [] and rep["unresolved"] == [] and rep["not_bridged"] == []
    # only C9's 0.1 mm gap is narrower than a cell: the raster may fuse it (reported, not changed)
    assert {j["net"] for j in rep["joins"]} <= {"C9"}
