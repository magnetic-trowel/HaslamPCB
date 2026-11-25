# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.place.legalize: windowed CP-SAT repair and the exact polygon check."""
from pathlib import Path

import numpy as np
import shapely

from haslam.budget import Deadline
from haslam.board.kicad_file import load
from haslam.place.legalize import exact_check, kicad_violations, legalize, violation_parts
from haslam.place.problem import Problem
from haslam.place.state import State, grid_violations

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _pile():
    P = Problem.build(load(FIXTURE))
    st = State(P)
    for i in P.mov:                       # every movable part on one spot
        st.X[i], st.Y[i], st.K[i] = P.ncx // 2, P.ncy // 2, 0
    return P, st


def test_legalize_a_pile_then_exact_check_passes():
    P, st = _pile()
    assert grid_violations(st)
    rep = legalize(P, st, time_s=30.0, workers=2, seed=0)
    assert rep["end_violators"] == 0
    assert not grid_violations(st)
    assert exact_check(P, st) == []
    # locked parts and keepouts are respected on their sides
    for ob in P.obstacles:
        for i in P.mov:
            for side, r, _ in st.grid_rects(i):
                if side == ob.side:
                    assert r[1] <= ob.g[0] or ob.g[1] <= r[0] or r[3] <= ob.g[2] or ob.g[3] <= r[2]


def test_exact_check_reports_overlaps_and_outline():
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    parts = {p.ref: p.i for p in P.parts}
    a, b = parts["U1"], parts["U2"]
    st.X[b], st.Y[b], st.K[b] = st.X[a], st.Y[a], st.K[a]
    types = {v["type"] for v in exact_check(P, st)}
    assert "courtyards_overlap" in types
    st.X[b], st.Y[b] = -400, -400          # far outside the board
    types = {v["type"] for v in exact_check(P, st)}
    assert "pad_outside" in types
    assert ("outline", ) == tuple(r[0] for r in grid_violations(st)[b] if r[0] == "outline")


def test_kicad_violations_become_constraints():
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    parts = {p.ref: p.i for p in P.parts}
    a, b = parts["U1"], parts["U2"]
    (ax, ay), (bx, by) = st.pins_xy(a)[0], st.pins_xy(b)[0]
    drc = {"violations": [
        {"type": "courtyards_overlap", "severity": "error", "description": "Courtyards overlap",
         "items": [{"description": "Footprint U1", "pos": {"x": ax, "y": ay}},
                   {"description": "Footprint U2", "pos": {"x": bx, "y": by}}]},
        {"type": "silk_overlap", "severity": "warning", "items": []},
        {"type": "clearance", "severity": "error", "description": "Clearance violation",
         "items": [{"description": "Pad 1 [] of nowhere", "pos": {"x": ax, "y": ay}}]}]}
    vs = kicad_violations(drc)
    assert [v["type"] for v in vs] == ["courtyards_overlap", "clearance"]
    assert violation_parts(P, st, vs[0]) == {a, b}
    assert violation_parts(P, st, vs[1]) == {a}            # unknown reference: nearest pad


def test_closed_loop_repair_ends_exactly_legal():
    """The closed loop (haslam.place.exact.repair): exact findings -> culprits -> moved to spots
    the exact check passes, until none is left."""
    from haslam.place import exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    parts = {p.ref: p.i for p in P.parts}
    a, b = parts["U1"], parts["U2"]
    st.X[b], st.Y[b], st.K[b] = st.X[a], st.Y[a], st.K[a]        # an overlap
    st.X[parts["U3"]], st.Y[parts["U3"]] = 1, 1                 # pads off the board
    assert exact_check(P, st)
    rep = exact.repair(P, st, time_s=30.0)
    assert rep["start"] > 0 and rep["end"] == 0 and not rep["stuck"]
    assert exact_check(P, st) == []


def test_kicad_feedback_becomes_a_constraint_the_repair_honours():
    """KiCad sees what the model cannot (a solder-mask aperture drawn past a courtyard): its
    error between two parts becomes a separation the exact model enforces, so the repair
    moves the culprit and the check stays clean only once they are apart."""
    from haslam.place import exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    assert exact_check(P, st) == []
    i, j = P.parts[P.mov[0]], P.parts[P.mov[1]]
    report = {"violations": [{"type": "solder_mask_bridge", "severity": "error", "items": [
        {"description": f"Pad 1 [x] of {i.ref} on F.Cu", "pos": {"x": 0, "y": 0}},
        {"description": f"Pad 2 [y] of {j.ref} on F.Cu", "pos": {"x": 0, "y": 0}}]}]}
    fb = exact.kicad_feedback(P, st, report, step=0.5)
    assert fb["errors"] == 1 and fb["constraints"] == 2
    E = exact.ExactModel(P, st)
    d0 = E.hull(E.sh[i.i]).distance(E.hull(E.sh[j.i]))
    assert any(v["type"] == "kicad_feedback" for v in exact_check(P, st))
    rep = exact.repair(P, st, time_s=30.0)
    assert rep["end"] == 0
    E = exact.ExactModel(P, st)
    assert E.hull(E.sh[i.i]).distance(E.hull(E.sh[j.i])) >= d0 + 0.5 - 1e-6


def test_reseed_places_a_pile_and_overhang_keeps_only_pads_in():
    """Escalation steps of the closed loop: a constructive re-seed (biggest first, each at an
    exactly clean spot, looking ahead for the next big parts) places a pile exactly legal;
    allow_overhang lets a courtyard hang over the edge while its pads stay in."""
    from haslam.place import exact
    P, st = _pile()
    E = exact.ExactModel(P, st)
    failed = exact.reseed(P, st, E, set(P.mov), Deadline(60))
    assert not failed and exact_check(P, st) == []
    i = max(P.mov, key=lambda q: P.parts[q].area)
    before = P.parts[i].rots[0].g_board
    assert P.allow_overhang([i]) == [P.parts[i].ref]
    a, b = P.parts[i].rots[0].g_board, before
    assert (a[1] - a[0]) * (a[3] - a[2]) <= (b[1] - b[0]) * (b[3] - b[2])


def test_exact_check_reports_hole_clearance():
    """Regression (olimex-mipi-hdmi): KiCad's hole_clearance (a hole's edge to another net's
    copper) was not modelled, so placements the exact check passed had 13 KiCad errors."""
    from haslam.place.legalize import exact_check
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    parts = {p.ref: p.i for p in P.parts}
    j1, u = P.parts[parts["J1"]], parts["U1"]
    hole = next(k for k, pd in enumerate(j1.fp.pads) if pd.drill)
    hx, hy = st.pins_xy(j1.i)[hole]
    r = j1.fp.pads[hole].drill / 2
    pad = P.parts[u].fp.pads[0]                       # SIG1, not J1's net
    w = max(pad.size) / 2
    st.X[u], st.Y[u] = P.grid_of(hx + r + 0.6 + w - pad.lx, hy - pad.ly)
    st.K[u] = 0
    P.board.rules.hole_clearance = 0.0
    assert not [v for v in exact_check(P, st, parts=[u], max_items=500) if v["type"] == "hole_clearance"]
    P.board.rules.hole_clearance = 1.5
    hits = [v for v in exact_check(P, st, parts=[u], max_items=500) if v["type"] == "hole_clearance"]
    assert any(set(v["refs"]) == {"J1", "U1"} for v in hits)


def test_mask_openings_of_different_nets_bridge():
    """Regression (latentred-pdu, envopenpico): KiCad flags solder-mask openings (pad + mask
    expansion) of different nets closer than the board's minimum mask web; the exact model
    did not check them, so KiCad's DRC found bridges on 'legal' placements."""
    from haslam.place.legalize import exact_check
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    parts = {p.ref: p.i for p in P.parts}
    a, b = P.parts[parts["U1"]], P.parts[parts["U2"]]      # both on the front
    pa, pb = a.fp.pads[0], b.fp.pads[0]
    for pd in (pa, pb):
        pd.layers = ["F.Cu", "F.Mask"]
    ax, ay = st.pins_xy(a.i)[0]
    gap = 0.3                                             # copper clearance is met
    P.board.rules.clearance = 0.1
    st.X[b.i], st.Y[b.i] = P.grid_of(ax + max(pa.size) / 2 + gap + max(pb.size) / 2 - pb.lx, ay - pb.ly)
    st.K[b.i] = 0
    P.board.rules.mask_margin = 0.0
    P.board.rules.mask_min_width = 0.0

    def bridges():
        return [v for v in exact_check(P, st, parts=[b.i], max_items=500)
                if v["type"] == "solder_mask_bridge" and set(v["refs"]) == {"U1", "U2"}]
    assert not bridges()
    P.board.rules.mask_margin = 0.2                       # 0.4 of expansion > 0.3 gap
    assert bridges()
    P.board.rules.mask_margin = 0.0
    P.board.rules.mask_min_width = 0.5                    # web too thin
    assert bridges()
    # each expansion alone is below the gap, both together exceed it: the prefilter took the
    # max of one margin (`max(mmi + mmj)` joined the lists) and missed this pair
    from haslam.place.exact import ExactModel
    P.board.rules.mask_min_width = 0.0
    E = ExactModel(P, st)
    d = min(ga.distance(gb) for ga, ka, _ in E._shapes(a.i, st.pose(a.i))["pads"] if ka == 0
            for gb, kb, _ in E._shapes(b.i, st.pose(b.i))["pads"] if kb == 0)
    assert d > 0.05
    P.board.rules.mask_margin = 0.6 * d
    assert bridges()


def test_kicad_zone_error_keeps_the_part_off_the_whole_zone():
    """Regression (latentred-pdu): KiCad reports a zone at one point; a disc there let the
    culprit slide to another spot of the same zone for 6 rounds. A zone item now keeps the
    part off the zone's outline."""
    from shapely.geometry import box as sbox
    from haslam.board.model import Zone
    from haslam.place import exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    i = P.parts[P.mov[0]]
    x, y = st.xy(i.i)
    P.board.zones.append(Zone(uuid="z", name="", net="Z", layers=["F.Cu"], outline=sbox(x - 6, y - 6, x + 6, y + 6)))
    report = {"violations": [{"type": "solder_mask_bridge", "severity": "error", "items": [
        {"description": f"Pad 1 [x] of {i.ref} on F.Cu", "pos": {"x": x, "y": y}},
        {"description": "Zone [Z] on F.Cu, priority 0", "pos": {"x": x + 5, "y": y}}]}]}
    fb = exact.kicad_feedback(P, st, report)
    assert fb["constraints"] == 1
    (g, why), = P.feedback["avoid"][i.i]
    assert g.contains(sbox(x - 5.9, y - 5.9, x + 5.9, y + 5.9))
    # a malformed courtyard reported with the zone it touches is the footprint's, not the zone's
    mal = {"violations": [{"type": "malformed_courtyard", "severity": "error",
                           "description": "Footprint has malformed courtyard (not a closed shape)", "items": [
        {"description": f"Footprint {i.ref}", "pos": {"x": x, "y": y}},
        {"description": "Zone [Z] on F.Cu, priority 0", "pos": {"x": x + 5, "y": y}}]}]}
    fb = exact.kicad_feedback(P, st, mal)
    assert fb["fixed_only"] == 1 and fb["constraints"] == 0 and fb["placer_by_type"] == {}


def test_exact_rules_follow_kicad_on_copperless_pads_roundrects_and_custom_rules():
    """Regressions from the human-placement gate (humangate.py: the human placement must show
    no finding KiCad's DRC does not): a paste-only or copperless NPTH pad is no copper; a
    roundrect has rounded corners; a custom .kicad_dru clearance rule for a library replaces
    the netclass clearance; a net-less fiducial whose mask expansion equals its fill gap does
    not bridge to the zone."""
    from haslam.board.model import Pad
    from haslam.place import exact
    from haslam.place.legalize import pad_shape
    paste = Pad(number="", net="", kind="smd", shape="rect", size=(1, 1), lx=0, ly=0, lrot=0, x=0, y=0,
                layers=["F.Paste"])
    npth = Pad(number="", net="", kind="np_thru_hole", shape="circle", size=(2, 2), lx=0, ly=0, lrot=0, x=0, y=0,
               layers=["*.Cu", "*.Mask"], drill=2.0)
    ring = Pad(number="", net="", kind="np_thru_hole", shape="circle", size=(3, 3), lx=0, ly=0, lrot=0, x=0, y=0,
               layers=["*.Cu", "*.Mask"], drill=2.0)
    assert exact._no_copper(paste) and exact._no_copper(npth) and not exact._no_copper(ring)
    rr = Pad(number="1", net="", kind="smd", shape="roundrect", size=(1.0, 0.5), lx=0, ly=0, lrot=0, x=0, y=0,
             layers=["F.Cu"], rratio=0.25)
    assert pad_shape(rr).area < 0.5 - 1e-3                  # corners cut
    P, st = _pile()
    P.board.rules.custom = [dict(name="small", condition="A.memberOfFootprint('haslam_test:ASYM3')",
                                 constraints=[dict(type="clearance", min=0.05)])]
    cc = exact._custom_clearances(P)
    assert cc and cc[0][1:] == ("lib", "haslam_test:ASYM3", 0.05)
    E = exact.ExactModel(P, st)
    i, j = P.mov[0], P.mov[1]
    assert E._rule_clr(i, E.sh[i], j, E.sh[j]) in (0.05, None)


def _held_chain():
    """The fixture legalized, with a J1 -> U7 -> U1 protection chain that holds: U1 at a clean
    spot far from J1, U7 at the clean spot nearest J1. Returns (P, st, E, guard, ref)."""
    from haslam.place import clusters, exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    ref = {p.ref: p for p in P.parts}
    u = {r: p.uuid for r, p in ref.items()}
    brief = {"structures": [
        {"kind": "connector_chain", "connector": u["J1"], "pin": "1", "net": "VCC", "protected": True,
         "protection": [u["U7"]], "chain": [[u["J1"], "1"], [u["U7"], "3"], [u["U1"], "3"]]}]}
    P.order_rules = clusters.protection_order(P, brief)
    E = exact.ExactModel(P, st)
    cx, cy = st.xy(ref["J1"].i)
    guard = exact.OrderGuard(P, st)

    def spots(i):
        return [(X, Y, k) for c, X, Y, k in exact._candidates(P, st, i, *exact._tables(P, st, {i}),
                                                              list(range(4)), 0.0, 4000)]
    i1, i7 = ref["U1"].i, ref["U7"].i
    far = sorted(spots(i1), key=lambda t: -abs(P.ox + t[0] * P.g - cx) - abs(P.oy + t[1] * P.g - cy))
    for X, Y, k in far[:200]:
        if not E.findings_at(i1, X, Y, k):
            E.set_pose(i1, X, Y, k)
            break
    near = sorted(spots(i7), key=lambda t: abs(P.ox + t[0] * P.g - cx) + abs(P.oy + t[1] * P.g - cy))
    for X, Y, k in near[:400]:
        if not E.findings_at(i7, X, Y, k) and guard.count_at(i7, X, Y, k) == 0:
            E.set_pose(i7, X, Y, k)
            break
    assert guard.total() == 0 and not exact_check(P, st)
    return P, st, E, guard, ref


def test_repair_keeps_protection_order():
    """Regression (stickhub at fe68468): the closed loop's repair cleared a mask bridge by
    moving a protection part to the far side of what it protects (3 of its 24 rules broken
    locally, annealed 0). A repair move or eviction may not break an order rule that holds."""
    from shapely.geometry import Point
    from haslam.place import exact
    P, st, E, guard, ref = _held_chain()
    # KiCad objects to U7 where it is: the repair must move it and keep the chain
    x7, y7 = st.xy(ref["U7"].i)
    P.feedback = {"sep": {}, "avoid": {ref["U7"].i: [(Point(x7, y7).buffer(1.0), "test")]}}
    rep = exact.repair(P, st, time_s=30.0)
    assert rep["end"] == 0 and "U7" in rep["moved"]
    assert rep["order_broken"] == [0, 0]


def test_move_clean_skips_a_spot_that_breaks_protection_order(monkeypatch):
    """The guard itself: of two exactly clean spots, the nearer one puts the protection part
    farther from the connector than the protected part; the repair takes the other."""
    from haslam.place import exact
    P, st, E, guard, ref = _held_chain()
    i7 = ref["U7"].i
    cands = [(X, Y, k) for c, X, Y, k in exact._candidates(P, st, i7, *exact._tables(P, st, {i7}), list(range(4)),
                                                           0.0, 4000) if not E.findings_at(i7, X, Y, k)]
    bad = next(t for t in cands if guard.count_at(i7, *t) > 0)
    good = next(t for t in cands if guard.count_at(i7, *t) == 0)
    E.set_pose(i7, *good)                                # where it stands, the rule holds
    monkeypatch.setattr(exact, "_candidates", lambda *a, **k: [(0.0, *bad), (1.0, *good)])
    E.findings_at = lambda i, X, Y, K, **kw: []          # both spots clean
    ok, _ = exact.move_clean(P, st, E, i7, Deadline(30))
    assert ok and (int(st.X[i7]), int(st.Y[i7]), int(st.K[i7])) == tuple(good)
    assert guard.total() == 0


def test_kicad_round_that_moves_parts_refreshes_order_and_physics(monkeypatch):
    """The report's protection order and physics scorecard describe the board as written: a
    KiCad DRC round whose repair moves parts recomputes them (place()'s values stay as
    *_pre_drc); a loop that moves nothing leaves them alone."""
    import time
    from types import SimpleNamespace
    from haslam import cli
    from haslam.place import exact
    from haslam.place.pipeline import Result, final_physics
    from haslam.route import drc as kdrc
    P, st, E, guard, ref = _held_chain()
    i7 = ref["U7"].i
    u7 = ref["U7"].uuid

    class Terms:              # a scorecard that follows U7's x
        def breakdown(self, poses):
            return [dict(id="s", kind="k", util=abs(poses[u7][0]) / 100.0, value=0.0, unit="")]
    res = Result(poses=st.poses(), report={}, state=st, problem=P, terms=Terms(), order=P.order_rules)
    final_physics(res)
    assert res.report["protection_order"]["violated"] == 0
    pre = dict(res.report)
    cands = [(X, Y, k) for c, X, Y, k in exact._candidates(P, st, i7, *exact._tables(P, st, {i7}), list(range(4)),
                                                           0.0, 4000) if not E.findings_at(i7, X, Y, k)]
    bad = next(t for t in cands if guard.count_at(i7, *t) > 0)
    errors = iter([1, 0, 0])
    monkeypatch.setattr(kdrc, "kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(kdrc, "stage_board", lambda out, inp, tmp: out)
    monkeypatch.setattr(kdrc, "run", lambda staged, path, timeout: {})
    monkeypatch.setattr(exact, "kicad_feedback", lambda P, st, rep: dict(errors=next(errors), by_type={}, fixed_only=0))

    def repair(P, st, time_s, log=None):
        st.X[i7], st.Y[i7], st.K[i7] = bad
        return dict(moved=["U7"], findings=[])
    monkeypatch.setattr(exact, "repair", repair)
    a = SimpleNamespace(drc="on", drc_rounds=2, time=600.0, output="out.kicad_pcb", input="in.kicad_pcb", writer="sexpr")
    clean, _ = cli._kicad_loop(a, res, time.monotonic(), lambda *x, **k: dict(writer="fake"))
    assert clean
    assert res.report["protection_order_pre_drc"] == pre["protection_order"]
    assert res.report["scorecard_pre_drc"] == pre["scorecard"]
    assert res.report["protection_order"]["violated"] == 1
    assert res.report["scorecard"]["total_linear"] != pre["scorecard"]["total_linear"]
    # a clean first round moves nothing: no *_pre_drc
    res2 = Result(poses=st.poses(), report={}, state=st, problem=P, terms=Terms(), order=P.order_rules)
    final_physics(res2)
    errors = iter([0])
    cli._kicad_loop(a, res2, time.monotonic(), lambda *x, **k: dict(writer="fake"))
    assert "protection_order_pre_drc" not in res2.report and "scorecard_pre_drc" not in res2.report


def test_kicad_error_with_board_text_keeps_the_named_part_off_the_text():
    """sparkfun-xrp-controller (seed 2): KiCad's clearance error between J3's pad and the
    copper text 'v20' stayed through 6 rounds. The text item names no part, so matching it by
    position blamed whichever part had a pad nearest the text's anchor; now the named part
    alone keeps off the text, by more each time KiCad still objects."""
    from haslam.place import exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    i, j = P.parts[P.mov[0]], P.parts[P.mov[1]]
    jx, jy = (float(c) for c in st.pins_xy(j.i)[0])       # the text's anchor on j's pad
    report = {"violations": [{"type": "clearance", "severity": "error", "items": [
        {"description": f"Pad 1 [x] of {i.ref} on F.Cu", "pos": {"x": 0, "y": 0}},
        {"description": "PCB text 'v20' on F.Cu", "pos": {"x": jx, "y": jy}, "uuid": "no-such-text"}]}]}
    fb = exact.kicad_feedback(P, st, report, step=0.5)
    assert fb["errors"] == 1 and fb["constraints"] == 1 and fb["placer_by_type"] == {"clearance": 1}
    assert set(P.feedback["avoid"]) == {i.i} and not P.feedback["sep"]
    exact.kicad_feedback(P, st, report, step=0.5)                 # KiCad still objects: wider
    (g1, _), (g2, _) = P.feedback["avoid"][i.i]
    assert g2.area > g1.area
    # only fixed parts named: nothing to move
    fixed = next((p for p in P.parts if not p.movable), None)
    if fixed is not None:
        rep2 = {"violations": [{"type": "clearance", "severity": "error", "items": [
            {"description": f"Footprint {fixed.ref}", "pos": {"x": 0, "y": 0}},
            {"description": "PCB text 'x' on F.Cu", "pos": {"x": jx, "y": jy}}]}]}
        fb2 = exact.kicad_feedback(P, st, rep2)
        assert fb2["fixed_only"] == 1 and fb2["placer_by_type"] == {}


def test_knockout_text_box_carries_kicads_margin(tmp_path):
    """Knockout copper text is copper around the glyphs, grown by max(thickness/2, height/9)."""
    from haslam.board import sexpr
    from haslam.board.kicad_file import _text_box
    from haslam.place.problem import board_texts
    node = ('(gr_text "v20" (at 10 10 0) (layer "B.Cu"{}) (uuid "u1") (effects (font (size 1.27 1.27) '
            '(thickness 0.254) (bold yes)) (justify mirror)))')
    plain = _text_box(sexpr.parse(node.format("")))
    ko = _text_box(sexpr.parse(node.format(" knockout")))
    m = max(0.254 / 2, 1.27 / 9)
    (a0, b0, c0, d0), (a1, b1, c1, d1) = plain.bounds, ko.bounds
    assert abs((a0 - a1) - m) < 1e-9 and abs((d1 - d0) - m) < 1e-9
    f = tmp_path / "t.kicad_pcb"
    f.write_text("(kicad_pcb (version 20240108) " + node.format(" knockout") + ")")
    from types import SimpleNamespace
    assert board_texts(SimpleNamespace(path=str(f)))["u1"].equals(ko)


def test_kicad_edge_error_grows_the_named_parts_edge_clearance():
    """paw3222 (seed 1): KiCad's copper_edge_clearance (0.175 < 0.2 mm, inside the model's
    tolerance for polygonized arcs) named 'Segment on Edge.Cuts' and J1's pad; the edge item
    was matched by position to U1, so the feedback asked J1 and U1 to keep apart and the repair
    never moved anything over 6 rounds. Now the edge item names no part and J1's own edge
    clearance grows until the repair moves it."""
    from haslam.place import exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    E = exact.ExactModel(P, st)
    boundary = P.outline.boundary
    dist = {i: min(g.distance(boundary) for g, k, pd in E.sh[i]["pads"]) for i in P.mov if E.sh[i]["pads"]}
    i = min(dist, key=dist.get)                                 # the part nearest the edge
    j = min((q for q in dist if q != i), key=lambda q: float(np.min(np.hypot(*(st.pins_xy(q) - st.pins_xy(i)[0]).T))))
    jx, jy = (float(c) for c in st.pins_xy(j)[0])
    ref = P.parts[i].ref
    report = {"violations": [{"type": "copper_edge_clearance", "severity": "error", "items": [
        {"description": "Segment on Edge.Cuts", "pos": {"x": jx, "y": jy}},      # anchored by another part
        {"description": f"PTH pad 6 [SDIO] of {ref}", "pos": {"x": 0, "y": 0}}]}]}
    assert violation_parts(P, st, kicad_violations(report)[0]) == {i}
    fb = exact.kicad_feedback(P, st, report)
    assert fb["constraints"] == 1 and not P.feedback["sep"] and not P.feedback["avoid"]
    assert P.feedback["edge"] == {i: exact.EDGE_STEP}
    # KiCad keeps objecting until the model sees it too
    while not any(v["type"] == "copper_edge_clearance" and v["parts"] == [i] for v in exact_check(P, st)):
        exact.kicad_feedback(P, st, report)
    rep = exact.repair(P, st, time_s=30.0)
    assert rep["end"] == 0 and P.parts[i].ref in rep["moved"]
    E = exact.ExactModel(P, st)
    assert min(g.distance(boundary) for g, k, pd in E.sh[i]["pads"]) > dist[i]


def test_fix_order_moves_the_protection_part_back_within_the_physics_bound():
    """stickhub at 150 s: an annealer cut short leaves a protection-order rule broken, which the
    guarded repair keeps but does not fix. The final pass moves the protection part to the
    nearest clean spot that keeps the rule, unless the physics total would rise past its bound."""
    from haslam.place import exact
    P, st, E, guard, ref = _held_chain()
    i7 = ref["U7"].i
    cands = [(X, Y, k) for c, X, Y, k in exact._candidates(P, st, i7, *exact._tables(P, st, {i7}), list(range(4)),
                                                           0.0, 4000) if not E.findings_at(i7, X, Y, k)]
    bad = next(t for t in reversed(cands) if guard.count_at(i7, *t) > 0)
    E.set_pose(i7, *bad)
    assert guard.total() == 1 and not exact_check(P, st)
    # every move costs more physics than the bound allows: nothing moves
    calls = []

    def phys():
        calls.append(1)
        return 1.0 if len(calls) == 1 else 2.0
    rep = exact.fix_order(P, st, time_s=30.0, phys=phys)
    assert rep["end"] == 1 and not rep["moved"] and rep["refused_physics"] >= 1
    assert (int(st.X[i7]), int(st.Y[i7]), int(st.K[i7])) == tuple(bad)
    # within the bound: U7 moves and the rule holds, exactly clean
    rep = exact.fix_order(P, st, time_s=30.0, phys=lambda: 1.0)
    assert rep["start"] == 1 and rep["end"] == 0 and rep["moved"] == ["U7"]
    assert not exact_check(P, st) and not grid_violations(st)


def test_kicad_loop_writes_the_best_judged_placement_back(monkeypatch):
    """The KiCad loop keeps the placement KiCad judged best: a later round that ends with more
    errors, or a repair KiCad never judged (its DRC failed), puts that one back on disk."""
    import time
    from types import SimpleNamespace
    from haslam import cli
    from haslam.place import exact
    from haslam.place.pipeline import Result
    from haslam.route import drc as kdrc
    P, st, E, guard, ref = _held_chain()
    i7 = ref["U7"].i
    spots = [(X, Y, k) for c, X, Y, k in exact._candidates(P, st, i7, *exact._tables(P, st, {i7}), list(range(4)),
                                                           0.0, 400)[1:4]]
    monkeypatch.setattr(kdrc, "kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(kdrc, "stage_board", lambda out, inp, tmp: out)
    written = []

    def write(inp, out, poses, **k):
        written.append(dict(poses))
        return dict(writer="fake")

    def run_loop(verdicts, rounds):
        it = iter(verdicts)

        def run(staged, path, timeout):
            v = next(it)
            if v is None:
                raise kdrc.DrcError("kicad-cli failed")
            return {"n": v}
        monkeypatch.setattr(kdrc, "run", run)
        monkeypatch.setattr(exact, "kicad_feedback", lambda P, st, rep: dict(errors=rep["n"], by_type={}, fixed_only=0))
        moves = iter(spots)

        def repair(P, st, time_s, log=None):
            st.X[i7], st.Y[i7], st.K[i7] = next(moves)
            return dict(moved=["U7"], findings=[])
        monkeypatch.setattr(exact, "repair", repair)
        res = Result(poses=st.poses(), report={}, state=st, problem=P)
        a = SimpleNamespace(drc="on", drc_rounds=rounds, time=600.0, output="o", input="i", writer="sexpr")
        return res, cli._kicad_loop(a, res, time.monotonic(), write)

    start = (int(st.X[i7]), int(st.Y[i7]), int(st.K[i7]))
    res, (clean, _) = run_loop([2, 5, 3], 2)          # worse after the first repair: round 0 back
    assert clean is False and res.report["kicad_written_round"] == 0
    assert res.report["kicad_verdict"]["errors"] == 2        # the verdict of the board as written
    assert (int(st.X[i7]), int(st.Y[i7]), int(st.K[i7])) == start and written[-1] == res.poses
    assert res.poses[ref["U7"].uuid] == st.pose(i7)
    st.X[i7], st.Y[i7], st.K[i7] = start
    res, (clean, _) = run_loop([4, 1, None], 3)       # round 1 best; round 2's verdict never came
    assert res.report["kicad_written_round"] == 1
    assert (int(st.X[i7]), int(st.Y[i7]), int(st.K[i7])) == spots[0]
    st.X[i7], st.Y[i7], st.K[i7] = start
    res, (clean, _) = run_loop([3, 0], 2)             # clean: written as it is
    assert clean and res.report["kicad_written_round"] == 1
    st.X[i7], st.Y[i7], st.K[i7] = start
    calls = []
    monkeypatch.setattr(exact, "repair", lambda P, st, time_s, log=None: calls.append(1) or dict(start=2, moved=[], findings=[]))
    monkeypatch.setattr(kdrc, "run", lambda staged, path, timeout: calls.append("drc") or {"n": 3})
    res = Result(poses=st.poses(), report={}, state=st, problem=P)
    a = SimpleNamespace(drc="on", drc_rounds=6, time=600.0, output="o", input="i", writer="sexpr")
    n_written = len(written)
    clean, _ = cli._kicad_loop(a, res, time.monotonic(), write)   # a repair that moves nothing: one verdict, stop
    assert calls == ["drc", 1] and res.report["kicad_drc"][0]["repair"]["unchanged"]
    assert res.report["kicad_written_round"] == 0 and len(written) == n_written
    calls.clear()                                     # no findings for the exact model: the rounds go on
    monkeypatch.setattr(exact, "repair", lambda P, st, time_s, log=None: calls.append(1) or dict(start=0, moved=[], findings=[]))
    cli._kicad_loop(a, Result(poses=st.poses(), report={}, state=st, problem=P), time.monotonic(), write)
    assert calls.count("drc") == 7
    res, (clean, _) = run_loop([1, 1, 1], 2)          # no repair helped: the least-moved round 0 back
    assert clean is False and res.report["kicad_written_round"] == 0
    assert (int(st.X[i7]), int(st.Y[i7]), int(st.K[i7])) == start and written[-1] == res.poses


def test_mask_only_aperture_across_two_zone_fills_is_a_bridge(monkeypatch):
    """KiCad 10 (drc_test_provider_solder_mask.cpp, checkMaskAperture): a simple mask aperture
    (a mask graphic with no copper, e.g. a mask-only logo) bridges when it exposes two distinct
    positive nets; zone fills count (stickhub: LOGO4 on B.Mask across the GND and +5V fills).
    Inside one fill it exposes one net; a pad's own opening drawn as a graphic is the pad's."""
    from shapely.geometry import box
    from haslam.board.model import Zone
    from haslam.place import exact
    # counted work and one worker: on wall-clock time under a loaded full-suite run, legalization
    # stopped elsewhere, R1 landed elsewhere and the aperture missed the fill edge (flaky)
    monkeypatch.setenv("HASLAM_BUDGET", "work")
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=1, seed=0)
    from haslam.place.problem import geom_to_lib
    logo = next(p for p in P.parts if p.ref == "R1")
    # the aperture 3.6 mm from R1 towards the board's middle (clear of its pads, on the board
    # wherever the legalizer put R1: CP-SAT's layout varies with the host's load)
    cx, cy = st.xy(logo.i)
    dy = 3.6 if cy < P.outline.centroid.y else -3.6
    ap_board = box(cx - 0.6, cy + dy - 0.6, cx + 0.6, cy + dy + 0.6)
    logo.fp.graphics = dict(logo.fp.graphics or {}, **{"F.Mask": [geom_to_lib(ap_board, *st.pose(logo.i))]})
    others = [z for z in P.board.zones if z.net != "GND"]

    def zones(vcc_outline):
        P.board.zones = others + [
            Zone(uuid="zg", name="", net="GND", layers=["F.Cu", "B.Cu"], outline=P.outline, priority=0, clearance=0.2),
            Zone(uuid="zv", name="", net="VCC", layers=["F.Cu", "B.Cu"], outline=vcc_outline, priority=1,
                 clearance=0.2)]

    def bridges():
        E = exact.ExactModel(P, st)
        return [v for v in E.part_findings(logo.i) if v["type"] == "solder_mask_bridge"
                and "aperture exposes" in v["detail"]]
    zones(box(0, 0, 1, 1))
    E = exact.ExactModel(P, st)
    A = E.sh[logo.i]
    ap = A["gfx"]["mask"][A["side"]][0]
    assert not any(ap.intersects(g) for g, _, _ in A["pads"])
    ymid = (ap.bounds[1] + ap.bounds[3]) / 2
    zones(box(0, 0, 60, ymid))                         # the VCC fill's edge across the aperture
    found = bridges()
    assert found and "GND" in found[0]["detail"] and "VCC" in found[0]["detail"]
    zones(box(0, 0, 60, 40))                           # all VCC under it: one net
    assert not bridges()
    zones(box(0, 0, 60, ymid))
    g0 = A["pads"][0][0]                               # over its own pad: the pad's opening
    x, y, rot, side = st.pose(logo.i)
    logo.fp.graphics["F.Mask"] = [geom_to_lib(g0, x, y, rot, side).buffer(0.6)]
    E = exact.ExactModel(P, st)
    A = E.sh[logo.i]
    ap = A["gfx"]["mask"][A["side"]][0]
    assert ap.intersects(g0)
    zones(box(0, 0, 60, (ap.bounds[1] + ap.bounds[3]) / 2))
    assert not bridges()


def test_silk_conflicts_are_soft_and_the_silk_pass_clears_them():
    """Silkscreen where the project makes it an error (KiCad's default is a warning): silk over
    another part's silk is silk_overlap, over its pad mask openings silk_over_copper. Not
    legality: the final pass moves the smaller part to the nearest clean spot without one."""
    from shapely.geometry import box
    from haslam.place import exact
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    assert not exact.silk_on(P)
    E = exact.ExactModel(P, st)
    assert E.silk_check() == []
    P.severity = dict(P.severity or {}, silk_overlap="error", silk_over_copper="error")
    for p in P.parts:          # only the silk this test draws (the fixture's own texts would
        p.fp.silk, p.fp.silk_text = {}, {}    # meet wherever CP-SAT happened to put them)
    a = next(p for p in P.parts if p.ref == "U1")
    b = min((p for p in P.parts if p.movable and p.s == a.s and p.i != a.i), key=lambda p: p.area)
    # a wide silk bar under R1 reaching U1's position, and U1's own silk where it stands
    ax, ay = st.xy(a.i)
    bx, by = st.xy(b.i)
    from haslam.place.problem import geom_to_lib
    bar = box(min(ax, bx) - 0.5, min(ay, by) - 0.5, max(ax, bx) + 0.5, max(ay, by) + 0.5)
    b.fp.silk = {"F.SilkS" if b.s > 0 else "B.SilkS": [geom_to_lib(bar, *st.pose(b.i))]}
    a.fp.silk = {"F.SilkS" if a.s > 0 else "B.SilkS": [geom_to_lib(box(ax - 0.3, ay - 0.3, ax + 0.3, ay + 0.3), *st.pose(a.i))]}
    E = exact.ExactModel(P, st)
    found = E.silk_check()
    assert a.s == b.s and any(v["type"] == "silk_overlap" and set(v["parts"]) == {a.i, b.i} for v in found)
    assert not exact_check(P, st)                 # soft: legality is untouched
    rep = exact.fix_silk(P, st, time_s=30.0, max_wl_rise=10.0)
    assert rep["start"]["silk_overlap"] >= 1 and rep["end"]["silk_overlap"] < rep["start"]["silk_overlap"]
    assert rep["moved"] and rep["moved"][0] == min((a, b), key=lambda p: p.area).ref
    assert not exact_check(P, st) and not grid_violations(st)


def test_silk_texts_take_kicads_glyphs_inside_their_boxes():
    """refine_silk_text: pcbnew's glyph outlines replace the estimated text boxes, in each
    footprint's library frame (placed back where they were, they sit inside the box)."""
    import pytest
    from haslam.board import pcbnew_io
    from haslam.place import exact
    if not pcbnew_io.available():
        pytest.skip("no Python with pcbnew")
    P = Problem.build(load(FIXTURE))
    boxes = {p.i: [g for v in p.fp.silk_text.values() for g in v] for p in P.parts}
    rep = exact.refine_silk_text(P)
    assert rep["ok"] and rep["texts"] >= 1
    n = 0
    for p in P.parts:
        glyphs = [g for v in p.fp.silk_text.values() for g in v]
        if not glyphs or not boxes[p.i]:
            continue
        n += 1
        box_u = shapely.union_all(boxes[p.i]).buffer(0.3)
        assert sum(g.area for g in glyphs) < sum(b.area for b in boxes[p.i])
        assert all(box_u.contains(g) for g in glyphs), p.ref
    assert n >= 1
    # turned parts: KiCad keeps texts readable, so the glyphs of a part turned by 180 degrees
    # are not its unturned glyphs turned; the model picks the quarter turn's own glyphs
    turned = [p for p in P.parts if (p.fp.silk_text_turns or {}).get(180)]
    assert turned
    p = turned[0]
    assert exact.silk_text_at(p, p.rot0 + 180) is p.fp.silk_text_turns[180]
    assert exact.silk_text_at(p, p.rot0 + 178) is p.fp.silk_text_turns[180]
    assert exact.silk_text_at(p, p.rot0) is p.fp.silk_text
    assert exact.silk_text_at(p, p.rot0 - 90) is p.fp.silk_text_turns[270]


def test_silk_text_at_picks_the_nearest_quarter_turn():
    from types import SimpleNamespace
    from haslam.place import exact
    fp = SimpleNamespace(silk_text={"F.SilkS": ["a"]}, silk_text_turns={90: {"F.SilkS": ["b"]}, 180: {"F.SilkS": ["c"]}})
    p = SimpleNamespace(fp=fp, rot0=90.0)
    assert exact.silk_text_at(p, 90.0) is fp.silk_text
    assert exact.silk_text_at(p, 180.0) is fp.silk_text_turns[90]
    assert exact.silk_text_at(p, 275.0) is fp.silk_text_turns[180]
    assert exact.silk_text_at(p, 0.0) is fp.silk_text         # no 270 turn known: the unturned glyphs
    assert exact.silk_text_at(SimpleNamespace(fp=SimpleNamespace(silk_text={}), rot0=0.0), 90.0) == {}


def test_silk_term_prices_alike_in_both_annealers_and_pulls_silk_apart():
    """The annealer's silkscreen term (silk_on projects): overlap area of a part's silk with
    the other parts' silk and pad mask openings (exact.silk_grid), priced the same by the
    compiled engine and anneal.Annealer; annealing lowers it."""
    from shapely.geometry import box
    from haslam.place import exact
    from haslam.place.anneal import Annealer, make_annealer
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    for p in P.parts:                              # a wide silk bar on every part
        p.fp.silk = {"F.SilkS": [box(-4.0, -0.3, 4.0, 0.3)]}
    sg = exact.silk_grid(P)
    assert sg and all(len(v[1]) == len(P.parts[i].rots) for i, v in sg.items())
    ref = Annealer(P, st.copy(), terms=None, w_cong=0.0, silk=sg, w_silk=1.0, seed=0)
    fast = make_annealer(P, st.copy(), terms=None, w_cong=0.0, silk=sg, w_silk=1.0, seed=0)
    assert abs(fast.cost(fast.lam1) - ref.cost(ref.lam1)) < 1e-6
    s0 = ref.silk_total()
    fast.run(cpu_s=20.0, max_moves=30000)
    assert fast.terms_report()["silk"] * fast.A0 < s0 or s0 == 0


def test_kicad_loop_runs_a_crashed_drc_again(monkeypatch):
    """kicad-cli killed by a signal (buspirate5: 'DRC failed (rc=-11)') runs again on a fresh
    staged copy; an ordinary failure does not, and leaves the board unverified."""
    import time
    from types import SimpleNamespace
    from haslam import cli
    from haslam.place import exact
    from haslam.place.pipeline import Result
    from haslam.route import drc as kdrc
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    monkeypatch.setattr(kdrc, "kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(kdrc, "stage_board", lambda out, inp, tmp: str(Path(tmp) / "board.kicad_pcb"))
    monkeypatch.setattr(exact, "kicad_feedback", lambda P, st, rep: dict(errors=0, by_type={}, fixed_only=0))
    a = SimpleNamespace(drc="on", drc_rounds=2, time=600.0, output="o", input="i", writer="sexpr")
    for verdicts, clean_expected, crashes in (([-11, "ok"], True, 1), (["boom"], None, 0)):
        it = iter(verdicts)

        def run(staged, path, timeout):
            v = next(it)
            if v == -11:
                raise kdrc.DrcError("DRC failed (rc=-11): Segmentation fault")
            if v == "boom":
                raise kdrc.DrcError("DRC failed (rc=2): bad board")
            return {}
        monkeypatch.setattr(kdrc, "run", run)
        res = Result(poses=st.poses(), report={}, state=st, problem=P)
        clean, _ = cli._kicad_loop(a, res, time.monotonic(), lambda *x, **k: dict(writer="fake"))
        assert clean is clean_expected
        assert res.report["kicad_verified"] is (clean_expected is not None)
        assert res.report["kicad_drc"][0].get("crashes", 0) == crashes


def test_repair_judges_exactly_where_the_grid_leaves_no_room():
    """paw3222: a locked sensor's rectangle covers all but a strip narrower than a header, so
    the grid offered the header no origin at all and the repair called it 'no room' forever.
    With no grid-free origin the repair takes origins free of the other movable parts only and
    lets the exact check judge them against the fixed ones."""
    from haslam.place import exact
    from haslam.place.problem import Obstacle
    P, st = _pile()
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    i = next(p.i for p in P.parts if p.ref == "U7")
    si = 0 if P.parts[i].s > 0 else 1
    # a fixed rectangle over the whole board on U7's side: no grid-free origin anywhere
    P.obstacles = list(P.obstacles) + [Obstacle(side=si, rect=(0, 0, 0, 0), g=(-10, P.ncx + 10, -10, P.ncy + 10),
                                                why="test cover")]
    S, pad = exact._tables(P, st, {i})
    assert not exact._candidates(P, st, i, S, pad, list(range(len(P.parts[i].rots))), 4.0, 600)
    E = exact.ExactModel(P, st)
    home = (int(st.X[i]), int(st.Y[i]), int(st.K[i]))
    P.feedback = {"sep": {}, "avoid": {i: [(E.hull(E.sh[i]), "test")]}}   # it must leave where it is
    E = exact.ExactModel(P, st)
    ok, _ = exact.move_clean(P, st, E, i, Deadline(30))
    assert ok and (int(st.X[i]), int(st.Y[i]), int(st.K[i])) != home and not E.part_findings(i)


def test_board_copper_text_is_fixed_copper_for_the_exact_check():
    """Board-level copper text (KiCad's glyphs, refine_silk_text -> P.fixed_text_cu): a pad
    on it, or within the clearance, is a clearance error (pic-programmer: a socket placed over
    '1=>>' and 'I2C PROM'); text clear of the pads is not."""
    from shapely.geometry import box
    P, st = _pile()
    legalize(P, st, time_s=30.0)
    assert exact_check(P, st) == []
    p = next(q for q in P.parts if q.movable and q.fp.pads)
    pose = st.pose(p.i)
    from haslam.board import transform
    from haslam.place.legalize import pad_shape
    pd = p.fp.pads[0]
    g = transform.place_geom(pad_shape(pd), *pose)
    side = 0 if p.s > 0 else 1
    P.fixed_text_cu = [(side, box(*g.centroid.buffer(0.2).bounds), "1=>>")]
    found = [v for v in exact_check(P, st) if "copper text" in v.get("detail", "")]
    assert found and found[0]["type"] == "clearance" and p.ref in found[0]["refs"]
    far = P.outline.bounds
    P.fixed_text_cu = [(side, box(far[0] - 50, far[1] - 50, far[0] - 49, far[1] - 49), "away")]
    assert not [v for v in exact_check(P, st) if "copper text" in v.get("detail", "")]


def test_intrinsic_footprint_violations_are_not_the_placers():
    """A footprint's own Edge.Cuts against its own pad (a reverse-mount LED in its cut-out), or
    two pads of one resistor array, is the footprint's design: KiCad reports it once the fixed
    profile promotes the check, and no move fixes it."""
    from haslam.place.exact import _intrinsic as _own_cutout
    own = dict(type="copper_edge_clearance", items=[dict(description="Arc of D68 on Edge.Cuts"),
                                                    dict(description="Pad 1 [LED_PWR] of D68 on B.Cu")])
    other = dict(type="copper_edge_clearance", items=[dict(description="Arc of D68 on Edge.Cuts"),
                                                      dict(description="Pad 1 [X] of C3 on B.Cu")])
    board = dict(type="copper_edge_clearance", items=[dict(description="Segment on Edge.Cuts"),
                                                      dict(description="Pad 1 [X] of C3 on F.Cu")])
    assert _own_cutout(own) and not _own_cutout(other) and not _own_cutout(board)
    rn = dict(type="clearance", items=[dict(description="Pad 2 [SCDAT6] of RN2 on F.Cu"),
                                      dict(description="Pad 1 [SCDAT7] of RN2 on F.Cu")])
    assert _own_cutout(rn) and not _own_cutout(dict(type="clearance", items=rn["items"][:1]))



def test_own_keepout_is_intrinsic():
    """KiCad names a footprint keepout's owner only in the description, with one item: a pad of
    the same footprint inside it is the footprint's design (freetronics-kitten REG1, a 78xx whose
    B.Cu keepout covers its own mounting hole); another part's pad, or a board keepout, is not."""
    from haslam.place.exact import _intrinsic
    def v(desc, item):
        return dict(type="items_not_allowed", description=desc, items=[dict(description=item)])
    assert _intrinsic(v("Items not allowed (keepout area of REG1)", "NPTH pad of REG1"))
    assert _intrinsic(v("Items not allowed (keepout area of FID2)", "Pad 1 [<no net>] of FID2 on F.Cu"))
    assert _intrinsic(v("Items not allowed (keepout area 'TOP' of J1)", "Pad 3 [GND] of J1 on F.Cu"))
    assert not _intrinsic(v("Items not allowed (keepout area of REG1)", "Pad 1 [VIN] of C2 on F.Cu"))
    assert not _intrinsic(v("Items not allowed (keepout area of J1)", "Via [GND] on F.Cu - B.Cu"))
    assert not _intrinsic(v("Items not allowed (keepout area)", "Pad [<no net>] of CH1 on F.Cu"))
    assert not _intrinsic(v("Items not allowed (keepout area 'Left')", "Pad 1 [GND] of SW3 on F.Cu"))
    # through the DRC report reader, as the KiCad loop sees it (it once dropped the description)
    from haslam.place.legalize import kicad_violations
    rep = dict(violations=[dict(type="items_not_allowed", severity="error",
                                description="Items not allowed (keepout area of REG1)",
                                items=[dict(description="NPTH pad of REG1", pos=dict(x=59.5, y=-35.96))])])
    assert [_intrinsic(x) for x in kicad_violations(rep)] == [True]
    # a courtyard that does not close is the footprint's (bkw777 wp2-feather U1)
    assert _intrinsic(dict(type="malformed_courtyard", description="Footprint has malformed courtyard (not a closed shape)",
                           items=[dict(description="Footprint U1")]))

def test_anchor_fixes_only_parts_with_no_spot(monkeypatch):
    """place.pipeline._anchor_tight_parts: a part the grid gives no spot free of the fixed
    geometry is fixed at an exactly clean spot (the check runs on the fixture's real geometry;
    the 'no spot' verdict is forced, since this fixture has room); others are left alone."""
    from haslam.place import exact as ex
    from haslam.place import pipeline as pl
    monkeypatch.setattr(pl, "ANCHOR_AREA_SHARE", 0.0)
    P = Problem.build(load(FIXTURE))
    tight = max(P.mov, key=lambda q: P.parts[q].area)
    real = ex._candidates
    calls = {}

    def fake(P_, st, i, S, pad, ks, w_rot, limit, edge=False):
        calls[i] = calls.get(i, 0) + 1
        return [] if i == tight and calls[i] == 1 else real(P_, st, i, S, pad, ks, w_rot, limit, edge=edge)

    monkeypatch.setattr(ex, "_candidates", fake)
    rep = {}
    poses, hung = pl._anchor_tight_parts(P, rep, lambda m: None)
    assert list(poses) == [P.parts[tight].uuid] and hung == []
    assert rep["anchored"]["parts"][0]["anchored"] is True


def test_anchor_at_an_exact_only_spot_needs_kicad(monkeypatch):
    """No grid-free spot: the exact check's spots are fixed only when KiCad's DRC agrees; otherwise the part keeps
    the overhang and stays with the normal stages."""
    from haslam.place import exact as ex
    from haslam.place import pipeline as pl
    monkeypatch.setattr(pl, "ANCHOR_AREA_SHARE", 0.0)
    real = ex._candidates
    for verdict, anchored in (((False, "hole_clearance 2"), False), ((True, "clean"), True)):
        P = Problem.build(load(FIXTURE))
        tight = max((q for q in P.mov if P.parts[q].has_courtyard), key=lambda q: P.parts[q].area)
        calls = {"n": 0}

        def fake(P_, st, i, S, pad, ks, w_rot, limit, edge=False):
            if i == tight:
                calls["n"] += 1
                if calls["n"] <= 2:            # no spot at all, and none grid-free with the overhang
                    return []
            return real(P_, st, i, S, pad, ks, w_rot, limit, edge=edge)

        monkeypatch.setattr(ex, "_candidates", fake)
        asked = []
        monkeypatch.setattr(pl, "_kicad_agrees", lambda *a: (asked.append(a[3]), verdict)[1])
        rep = {}
        poses, hung = pl._anchor_tight_parts(P, rep, lambda m: None, board_path="x.kicad_pcb")
        row = rep["anchored"]["parts"][0]
        assert row["grid_free"] is False and asked and row["anchored"] is anchored
        assert (P.parts[tight].uuid in poses) is anchored and (hung == []) is anchored
        assert len(asked) == (1 if anchored else pl.ANCHOR_KICAD_TRIES)


def test_a_board_whose_only_free_part_is_anchored_writes_its_pose(monkeypatch):
    """Regression (loop-legal-ab2): when the anchored part was the board's only free part, place() returned no poses
    and the part stayed at its staged pose, off the board."""
    import dataclasses

    from haslam.place import exact as ex
    from haslam.place import pipeline as pl
    monkeypatch.setattr(pl, "ANCHOR_AREA_SHARE", 0.0)
    b = load(FIXTURE)
    P0 = Problem.build(b)
    keep = P0.parts[max((q for q in P0.mov if P0.parts[q].has_courtyard), key=lambda q: P0.parts[q].area)].uuid
    b = dataclasses.replace(b, footprints=[f if f.uuid == keep else dataclasses.replace(f, locked=True) for f in b.footprints])
    real = ex._candidates
    first = {"done": False}

    def fake(P_, st, i, S, pad, ks, w_rot, limit, edge=False):
        if not first["done"]:
            first["done"] = True
            return []                      # tight: no spot free of the fixed geometry
        return real(P_, st, i, S, pad, ks, w_rot, limit, edge=edge)

    monkeypatch.setattr(ex, "_candidates", fake)
    res = pl.place(b, seed=0, time_s=20.0, physics=False, workers=1)
    assert res.report.get("anchored", {}).get("uuids") == [keep]
    assert keep in res.poses


def test_round_pads_and_holes_measure_within_the_arc_error():
    """Regression (melexinvn-bs-kombo): a 3 mm NPTH hole and a 1.7 mm round pad 0.2402 mm apart, under a 0.25 mm
    hole clearance. KiCad measures arcs exactly and flags it; with 8 segments per quarter circle both polygons sat
    inside their circles and read 0.2491 mm, which the exact check (tolerance 0.005) passed."""
    from haslam.board.model import Pad
    from haslam.place.legalize import ARC_ERR, hole_shape, pad_shape
    gap = 0.2402
    hole = Pad(number="", net="", kind="np_thru_hole", shape="circle", size=(3.0, 3.0), lx=0.0, ly=0.0, lrot=0.0,
               x=0.0, y=0.0, layers=["F.Cu", "B.Cu"], drill=3.0)
    d = 1.5 + gap + 0.85
    pad = Pad(number="15", net="+3V3", kind="thru_hole", shape="oval", size=(1.7, 1.7), lx=d * 0.6, ly=d * 0.8, lrot=0.0,
              x=0.0, y=0.0, layers=["F.Cu", "B.Cu"], drill=1.0)
    measured = hole_shape(hole).distance(pad_shape(pad))
    assert gap <= measured <= gap + 2 * ARC_ERR + 1e-9
    assert measured < 0.25 - 0.005           # the exact check's test: it now reports the violation


def test_greedy_charges_its_scans_and_the_charges_change_no_decision():
    """Under counted budgets the greedy legalizer charges its real work (fit tests of the ring walk,
    grid-sized array passes, summed-area-table updates, rectangles marked): its scans between two
    deadline polls once cost no budget (a rip-up scan of a full board: 98 s wall, nothing charged)."""
    from haslam import budget
    from haslam.place.legalize import greedy
    poses = {}
    try:
        for mode in ("time", "work"):
            for compiled in (True, False):
                P, st = _pile()
                budget.set_mode(mode)
                greedy(P, st, list(P.mov), compiled=compiled)
                u = budget.clock().units
                kinds = ("legal_fit", "legal_cells", "legal_sat_cells", "legal_rect") if compiled \
                    else ("legal_cells", "legal_rect")
                assert all(u[k] > 0 for k in kinds), dict(u)
                if mode == "work":
                    spent = sum(u[k] * budget.RATES[k] for k in kinds)
                    assert budget.clock().spent >= spent > 0
                poses[mode, compiled] = (st.X.copy(), st.Y.copy(), st.K.copy())
    finally:
        budget.set_mode("time")
    for compiled in (True, False):
        assert all((a == b).all() for a, b in zip(poses["time", compiled], poses["work", compiled]))


def test_ripup_scan_counts_every_fit_test_of_a_full_board():
    """A part with no spot (the board full of larger parts) walks every origin within reach in
    every rotation: the scan reports each fit test, so the charge follows the work."""
    from haslam.place import _fastlegal as FL
    from haslam.place.problem import sat
    P, st = _pile()
    i = P.mov[0]
    ks = FL.rotations_for_fit(P.parts[i], 0)
    own, own_n, opp, opp_n, brd, brd_n = FL.part_arrays(P.parts[i], ks)
    pad, D = 4, 30
    full = sat(np.ones((P.ncx + 2 * pad, P.ncy + 2 * pad), dtype=np.int32))
    empty = sat(np.zeros((P.ncx + 2 * pad, P.ncy + 2 * pad), dtype=np.int32))
    E, E0, EB = FL.evict_arrays([])
    c, _, _, _, n, _ = FL.ripup_spot(full, full, empty, empty, P.sat_out, P.ncx, P.ncy, pad, 0, P.ncx // 2,
                                     P.ncy // 2, 0, 1.0, own, own_n, opp, opp_n, brd, brd_n, E, E0, EB, D)
    assert c < 0 and n == len(ks) * (2 * D * (D + 1) + 1)
    c, _, _, _, n = FL.nearest_spot(full, full, P.sat_out, P.ncx, P.ncy, pad, 0, P.ncx // 2, P.ncy // 2, 0, 1.0,
                                    own, own_n, opp, opp_n, brd, brd_n, D)
    assert c < 0 and n == len(ks) * (2 * D * (D + 1) + 1)
    S = sat(np.zeros((5, 5), dtype=np.int32))
    assert FL.sat_add_rect(S, 1, 3, 2, 4, 1) == 4 * 3 and S[-1, -1] == 4    # the cells after the corner


def _alone(P, st, keep):
    """Only the parts in `keep` are movable; the rest leave the board model (not obstacles)."""
    P.mov = [i for i in P.mov if i in keep]
    for i in keep:
        st.X[i], st.Y[i], st.K[i] = P.ncx // 2, P.ncy // 2, 0


def test_window_reaches_the_nearest_pose_clear_of_fixed_geometry():
    """A part dropped in the middle of a keepout wider than itself must travel further than the
    window's margin around it (pi-w-controller: a 28 mm module on a locked 40-pin header, 30 mm
    from the nearest clear pose). The window used to stay around the part, fail every round
    and leave it to the greedy fallback; it now covers the escape pose and solves it."""
    from haslam.place.problem import Obstacle
    P, st = _pile()
    i = P.mov[0]
    _alone(P, st, {i})
    cx, cy = P.ncx // 2, P.ncy // 2
    g = (cx - 120, cx + 120, cy - 100, cy + 100)        # 24 x 20 mm, part ~4 x 3.4 mm
    for side in (0, 1):
        P.obstacles.append(Obstacle(side=side, rect=None, g=g, why="test keepout"))
    assert ("obstacle", "test keepout") in grid_violations(st)[i]
    rep = legalize(P, st, time_s=20.0, workers=1, seed=0)
    assert rep["end_violators"] == 0 and not grid_violations(st)
    assert rep["solved"] >= 1 and "greedy" not in rep, rep


def test_rigid_group_keeps_its_offsets_where_single_parts_split():
    """A decap whose courtyard meets a fixed obstacle: alone, the displacement minimum moves only
    the cap, off its IC; as a rigid group the IC and cap move together and keep their offsets."""
    from haslam.place.problem import Obstacle
    out = {}
    for rigid in (False, True):
        P, st = _pile()
        a, b = P.mov[0], P.mov[1]                     # "IC" and "cap", both front
        _alone(P, st, {a, b})
        ra = [r for _, r, _ in st.grid_rects(a)]
        rb = [r for _, r, _ in st.grid_rects(b)]
        st.X[b] += max(r[1] for r in ra) - min(r[0] for r in rb) + 2      # cap just right of the IC
        rb = [r for _, r, _ in st.grid_rects(b)]
        top = min(r[2] for r in rb)
        g = (min(r[0] for r in rb), max(r[1] for r in rb), top - 60, top + 5)   # 0.5 mm into the cap
        P.obstacles.append(Obstacle(side=0, rect=None, g=g, why="test wall"))
        v = grid_violations(st)
        assert b in v and a not in v
        off0 = (st.X[b] - st.X[a], st.Y[b] - st.Y[a], st.K[a], st.K[b])
        rep = legalize(P, st, time_s=20.0, workers=1, seed=0, rigid=[[a, b]] if rigid else ())
        assert rep["end_violators"] == 0 and not grid_violations(st)
        out[rigid] = (st.X[b] - st.X[a], st.Y[b] - st.Y[a], st.K[a], st.K[b]) == off0
        if rigid:
            assert rep.get("rigid_solved", 0) >= 1, rep
    assert out == {False: False, True: True}


def test_rigid_group_that_overlaps_itself_moves_as_single_parts():
    """A group whose own members overlap cannot be repaired as a block: its parts go single."""
    P, st = _pile()
    a, b = P.mov[0], P.mov[1]
    _alone(P, st, {a, b})
    rep = legalize(P, st, time_s=20.0, workers=1, seed=0, rigid=[[a, b]])
    assert rep["end_violators"] == 0 and not grid_violations(st)
    assert not rep.get("rigid_solved")


def test_physics_breaks_ties_between_equal_displacement_repairs():
    """A part centred on a wall it must leave can go left or right at the same displacement;
    the solver used to pick one arbitrarily (tinkerforge temperature: decap Σu 1.46 or 2.40 by
    seed). With `phys`, the window compares its optima and keeps the lowest; displacement stays
    the objective."""
    from haslam.place.problem import Obstacle
    side = {}
    for sign in (1, -1):
        P, st = _pile()
        i = P.mov[0]
        _alone(P, st, {i})
        (a, b, c, d) = [r for _, r, _ in st.grid_rects(i)][0]
        x0 = (a + b) // 2 - (1 - (a + b) % 2)      # a thin wall through the middle: x0 + x1 = a + b
        P.obstacles.append(Obstacle(side=0, rect=None, g=(x0, a + b - x0, 0, P.ncy), why="test wall"))
        X0 = int(st.X[i])
        rep = legalize(P, st, time_s=20.0, workers=1, seed=0, phys=lambda s, i=i, sign=sign: sign * float(s.X[i]))
        assert rep["end_violators"] == 0 and not grid_violations(st)
        assert abs(int(st.Y[i]) - P.ncy // 2) == 0 and int(st.K[i]) == 0
        side[sign] = int(np.sign(int(st.X[i]) - X0))
    assert side == {1: -1, -1: 1}


def _strip(g, mover_x):
    """A 45 x 9 mm board at grid pitch g: a row of 1 x 1 mm parts at y 4-5 mm, 4 mm apart up to
    x = 17 mm and 7 mm apart after, so an 8 x 8 mm part fits nowhere without covering one of
    them, and near x = 5-13 mm only by covering two. Returns (P, st, mover index)."""
    from types import SimpleNamespace as NS
    from haslam.place.problem import sat
    from haslam.place.state import State

    def c(v):
        return int(round(v / g))

    def part(i, ref, w, h):
        own = (0, c(w), 0, c(h))
        r = NS(g_own=own, g_own_rects=(own,), g_opp=(), g_board=own, g_boards=(own,))
        return NS(i=i, ref=ref, movable=True, area=w * h, s=1.0, rots=[r], n_ortho=1)
    xs = [1, 5, 9, 13, 17, 24, 31, 38]
    parts = [part(n, f"R{n}", 1.0, 1.0) for n in range(len(xs))] + [part(len(xs), "M", 8.0, 8.0)]
    P = NS(g=g, ncx=c(45), ncy=c(9), obstacles=[], parts=parts, mov=list(range(len(parts))))
    P.sat_out = sat(np.zeros((P.ncx, P.ncy), dtype=bool))
    st = NS(P=P, X=np.zeros(len(parts), np.int64), Y=np.zeros(len(parts), np.int64), K=np.zeros(len(parts), np.int64))
    st.grid_rects = lambda i: State.grid_rects(st, i)
    for n, x in enumerate(xs):
        st.X[n], st.Y[n] = c(x), c(4)
    m = len(xs)
    st.X[m], st.Y[m] = c(mover_x), c(0.5)
    return P, st, m


def test_ripup_prices_evictions_by_distance_the_same_at_any_grid_pitch():
    """The rip-up charges each evicted part the push that clears it, a length like the mover's
    own travel. It used to charge 4 per covered cell, an area: at 0.1 and 0.25 mm the 8 mm part
    travelled 9 mm to cover one 1 mm part instead of pushing two aside where it was, at 0.5 mm
    it stayed, so the grid pitch decided the placement."""
    from haslam.place.legalize import greedy
    for compiled in (True, False):
        got = {}
        for g in (0.1, 0.25, 0.5):
            P, st, m = _strip(g, 5.0)
            rep = greedy(P, st, [m], compiled=compiled)
            assert rep["ripups"] >= 1 and not rep["unplaced"], rep
            rs = [r for i in P.mov for _, r, _ in st.grid_rects(i)]
            assert not any(a[1] > b[0] and b[1] > a[0] and a[3] > b[2] and b[3] > a[2]
                           for n, a in enumerate(rs) for b in rs[n + 1:])
            assert all(0 <= r[0] and r[1] <= P.ncx and 0 <= r[2] and r[3] <= P.ncy for r in rs)
            got[g] = (st.X[m] * g, rep["moved_mm"])
        xs = [x for x, _ in got.values()]
        # the mover stays within a few mm (the near pair is cheaper than a 13 mm trip) ...
        assert all(abs(x - 5.0) < 4.0 for x in xs), (compiled, got)
        # ... at the same place, whatever the pitch (to within the coarsest cell)
        assert max(xs) - min(xs) <= 0.5 + 1e-9, (compiled, got)


def test_evict_push_is_the_shortest_straight_push():
    from types import SimpleNamespace as NS
    from haslam.place import _fastlegal as FL
    from haslam.place.legalize import _evict_push
    own = (0, 80, 0, 80)
    r = NS(g_own=own, g_own_rects=(own,), g_opp=((30, 50, 30, 50),))
    ks_own, own_n, opp, opp_n, _, _ = FL.part_arrays(NS(rots=[NS(g_own=own, g_own_rects=(own,),
                                                                 g_opp=((30, 50, 30, 50),), g_board=own, g_boards=(own,))]))
    cases = [([(0, (5, 15, 40, 50))], 15),         # 15 cells to the left edge
             ([(0, (70, 90, 0, 10))], 10),         # 10 up / 10 left: pushed out the shorter way
             ([(0, (100, 110, 0, 10))], 0),        # clear of it
             ([(1, (35, 45, 0, 100))], 15),        # the back rectangle meets a back part: 15 sideways
             ([(1, (5, 15, 40, 50))], 0)]          # a back part under the front piece only: no overlap
    for ev, want in cases:
        X, Y = np.array([0]), np.array([0])
        assert int(_evict_push(r, X, Y, 0, ev)[0]) == want, ev
        E, E0, _ = FL.evict_arrays([ev])
        assert FL.evict_push(0, 0, 0, 0, ks_own, own_n, opp, opp_n, E, E0, 0) == want, ev
