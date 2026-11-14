# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route.drc.canonical_unconnected: unconnected pairs named the same whichever of the copper at an
anchor KiCad's DRC happened to name (it varies from run to run on one file)."""
import copy

from kae.route import drc

# two GND tracks meeting at (2, 0); a connector's front and back GND pads at one position (5, 5); a GND pad
# elsewhere (9, 9) that is not joined to either
ITEMS = [
    dict(uuid="t1", kind="track", net="GND", description="Track [GND] on F.Cu, length 1.0000 mm",
         pos=[1_000_000, 0], anchors=[[1_000_000, 0], [2_000_000, 0]]),
    dict(uuid="t2", kind="track", net="GND", description="Track [GND] on F.Cu, length 3.0000 mm",
         pos=[2_000_000, 0], anchors=[[2_000_000, 0], [5_000_000, 0]]),
    dict(uuid="p2", kind="pad", net="GND", description="Pad 2 [GND] of P1 on F.Cu", pos=[5_000_000, 5_000_000],
         anchors=[[5_000_000, 5_000_000]]),
    dict(uuid="p4", kind="pad", net="GND", description="Pad 4 [GND] of P1 on B.Cu", pos=[5_000_000, 5_000_000],
         anchors=[[5_000_000, 5_000_000]]),
    dict(uuid="q1", kind="pad", net="GND", description="Pad 1 [GND] of C1 on F.Cu", pos=[2_100_000, 1_000_000],
         anchors=[[2_100_000, 1_000_000]]),
    dict(uuid="v1", kind="via", net="SIG", description="Via [SIG] on F.Cu - B.Cu", pos=[2_000_000, 0],
         anchors=[[2_000_000, 0]]),
]
BY = {it["uuid"]: it for it in ITEMS}


def _it(u, pos=None):
    it = BY[u]
    p = pos or it["pos"]
    return dict(description=it["description"], pos=dict(x=p[0] / 1e6, y=p[1] / 1e6), uuid=u)


def _rep(*pairs):
    return dict(violations=[], unconnected_items=[dict(type="unconnected_items", severity="error",
                                                         description="Missing connection between items",
                                                         items=[_it(a), _it(b)]) for a, b in pairs])


def test_the_same_pairs_whichever_item_kicad_named():
    # run 1 named t1 and p2, run 2 t2 and p4, in the other order: the same connections
    a = drc.canonical_unconnected(_rep(("t1", "q1"), ("p2", "q1")), ITEMS)
    b = drc.canonical_unconnected(_rep(("q1", "t2"), ("q1", "p4")), ITEMS)
    assert a == b
    named = [[i["uuid"] for i in u["items"]] for u in a["unconnected_items"]]
    assert sorted(map(sorted, named)) == [["p2", "q1"], ["q1", "t1"]]


def test_other_nets_at_the_anchor_are_not_candidates():
    rep = drc.canonical_unconnected(_rep(("t2", "q1")), ITEMS)
    assert {i["uuid"] for i in rep["unconnected_items"][0]["items"]} == {"t1", "q1"}   # never the SIG via


def test_items_it_does_not_know_as_kicad_names_them_are_left_alone():
    rep = _rep(("t2", "q1"))
    rep["unconnected_items"][0]["items"][0]["description"] = "Track [GND] on Top, length 3.0000 mm"
    rep["unconnected_items"].append(dict(type="unconnected_items", items=[
        dict(description="Zone [GND] on F.Cu", pos=dict(x=0.0, y=0.0), uuid="z1"), _it("q1")]))
    want = copy.deepcopy(rep)
    want["unconnected_items"].sort(key=drc._content_key)
    assert drc.canonical_unconnected(rep, ITEMS) == want
    assert drc.canonical_unconnected(copy.deepcopy(want), None) == want
