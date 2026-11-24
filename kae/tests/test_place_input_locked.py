# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors of locked parts only: left out of legality by the score (score 14), and named to the caller by kae
(kae.place.pipeline.locked_input_errors / input_locked_hazard): kind, parts, place, and that the method cannot
fix them."""
from kae.place import pipeline

from test_place_zones import _problem


def _lock_on_edge(P):
    """The fixture's fixed part moved onto the board edge, as if the input had it there."""
    f = next(q for q in P.parts if not q.movable)
    x0, y0, x1, y1 = P.outline.bounds
    f.x0, f.y0 = x0, (y0 + y1) / 2        # its origin on the left edge: pads within the edge clearance
    return f


def test_errors_of_locked_parts_only_are_listed():
    P, st = _problem()
    clean = pipeline.locked_input_errors(P, st)
    f = _lock_on_edge(P)
    got = pipeline.locked_input_errors(P, st)
    assert got["count"] >= 1 and got["count"] > clean["count"]
    it = next(i for i in got["items"] if f.ref in i["parts"])
    assert set(it["parts"]) == {f.ref} and len(it["at"]) == 2 and it["type"]
    # a part kae pinned itself is not the input's
    assert pipeline.locked_input_errors(P, st, exclude={f.uuid})["count"] == clean["count"]


def test_movable_parts_never_count():
    P, st = _problem()
    got = pipeline.locked_input_errors(P, st)
    movable = {q.ref for q in P.parts if q.movable}
    assert not any(set(i["parts"]) & movable for i in got["items"])


def test_hazard_names_count_kinds_parts_and_place():
    info = dict(count=2, items=[dict(type="copper_edge_clearance", parts=["J4"], at=[5.45, -34.4], detail=""),
                                dict(type="courtyards_overlap", parts=["J4", "J5"], at=[5.45, -34.4], detail="")])
    h = pipeline.input_locked_hazard(info)
    assert h["code"] == "input_locked_errors" and h["severity"] == "info"
    assert "2 error(s) left out of legality" in h["message"] and "only locked parts" in h["message"]
    assert "copper_edge_clearance J4 at (5.45, -34.4)" in h["message"] and "J4/J5" in h["message"]
    assert "input errors no placement can fix" in h["message"]
    assert h["objects"] == ["J4", "J5"] and h["evidence"]["count"] == 2
    many = dict(count=20, items=[dict(type="clearance", parts=[f"J{k}"], at=[0, 0], detail="") for k in range(20)])
    assert "and 8 more" in pipeline.input_locked_hazard(many)["message"]
