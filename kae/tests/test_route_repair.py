# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route repair geometry and DSN ordering (no KiCad needed)."""
import copy
from types import SimpleNamespace

from shapely.geometry import Point, box

from kae.route import repair, specctra as S, translate

DSN = '''(pcb x
  (placement
    (component R0603 (place R1 0 0 front 0) (place R2 1000 0 front 0) (place R3 2000 0 front 0))
    (component C0402 (place C1 0 1000 front 0) (place C2 1000 1000 front 0))
    (component SOT23 (place Q1 0 2000 front 0))
  )
  (network
    (net A (pins R1-1 C1-1))
    (net B (pins R1-2 R2-1))
    (net C (pins R2-2 R3-1))
    (net D (pins R3-2 Q1-1))
    (class kae_Default A B C D)
  )
)
'''


def _order(tree):
    pl = S.find(tree, "placement")
    comps = [(c[1], [p[1] for p in S.findall(c, "place")]) for c in S.findall(pl, "component")]
    nets = [n[1] for n in S.findall(S.find(tree, "network"), "net")]
    return comps, nets


def test_permute_is_reproducible_and_keeps_everything():
    t0 = S.parse(DSN)
    t = copy.deepcopy(t0)
    assert not translate.permute(t, 0) and t == t0          # seed 0: KiCad's order
    a, b = copy.deepcopy(t0), copy.deepcopy(t0)
    assert translate.permute(a, 3) and translate.permute(b, 3)
    assert a == b                                            # same seed, same order
    (ca, na), (c0, n0) = _order(a), _order(t0)
    assert sorted(na) == sorted(n0) and sorted(x for _, p in ca for x in p) == sorted(x for _, p in c0 for x in p)
    assert S.find(S.find(a, "network"), "class") == S.find(S.find(t0, "network"), "class")
    orders = set()
    for seed in range(1, 8):
        t = copy.deepcopy(t0)
        translate.permute(t, seed)
        orders.add(repr(_order(t)))
    assert len(orders) > 1
    assert repair.round_seed(0, 1) != 0 and repair.round_seed(5, 1) != repair.round_seed(5, 2)


def test_permute_pins_shuffles_only_the_image_pins_and_only_when_asked():
    """permute_pins: a seed also shuffles the pins inside each library image (the fork creates components by
    reference name, so that is the one first-pass order the DSN still decides). Off, the DSN is as before; on,
    the components and nets have the order the seed gave them without it, and no pin is lost."""
    lib = ('(pcb x (library (image R (outline (path F.Cu 0 0 0 1 0)) (pin P 1 0 0) (pin P 2 1 0) (pin P 3 2 0)'
           ' (pin P 4 3 0) (pin P 5 4 0) (pin P 6 5 0)) (image C (pin P 1 0 0) (pin P 2 1 0)))'
           ' (placement (component R (place R1 0 0 front 0) (place R2 1 0 front 0)) (component C (place C1 2 0 front 0)))'
           ' (network (net A (pins R1-1 C1-1)) (net B (pins R1-2 R2-1)) (net D (pins R2-2 C1-2))))')
    t0 = S.parse(lib)

    def pins(t):
        return [[p[2] for p in S.findall(im, "pin")] for im in S.findall(S.find(t, "library"), "image")]
    changed = 0
    for seed in range(1, 9):
        off, on = copy.deepcopy(t0), copy.deepcopy(t0)
        translate.permute(off, seed)
        translate.permute(on, seed, pins=True)
        assert pins(off) == pins(t0)
        assert _order(on) == _order(off)
        assert [sorted(x) for x in pins(on)] == [sorted(x) for x in pins(t0)]
        assert S.find(S.findall(S.find(on, "library"), "image")[0], "outline") is not None
        changed += pins(on) != pins(t0)
    assert changed >= 6
    t = copy.deepcopy(t0)
    assert not translate.permute(t, 0, pins=True) and t == t0


def _sq(x, y, h):
    return [[[x - h, y - h], [x + h, y - h], [x + h, y + h], [x - h, y + h], [x - h, y - h]]]


def _pad(uuid, net, x, y, h=0.5, layers=("F.Cu",)):
    return dict(uuid=uuid, net=net, pos=[x, y], layers=list(layers), comp="U1", pin=uuid, ref="U1",
                number=uuid, poly_by_layer={l: [_sq(x, y, h)] for l in layers}, thermal_gap=0.5, spoke_angle=0.0)


def _ring(polygon):
    return [[list(c) for c in polygon.exterior.coords]] + [[list(c) for c in h.coords] for h in polygon.interiors]


def test_net_clusters_follow_overlapping_copper_and_join_layers():
    cu = ["F.Cu", "B.Cu"]
    pads = [_pad("p1", "N", 0, 0), _pad("p2", "N", 10, 0), _pad("p3", "N", 20, 0),
            _pad("p4", "N", 30, 0, layers=("B.Cu",)), _pad("m1", "M", 5, 5)]
    info = dict(pads=pads)
    piece_a = box(-1, -2, 11, 2)                 # touches p1 and p2
    piece_b = box(28, 3, 32, 6)                  # holds the via below, not p4
    fills = [dict(uuid="z", net="N", layers={"F.Cu": [_ring(piece_a), _ring(piece_b)]})]
    copper = {"v1": dict(kind="via", net="N", pos=[30, 4], size=0.6),
              "t1": dict(kind="track", net="N", layer="B.Cu", a=[30, 0], b=[30, 4], width=0.2)}
    parts = repair.net_clusters("N", info, copper, fills, cu)
    assert sorted(sorted(c["pads"]) for c in parts) == [["p1", "p2"], ["p3"], ["p4"]]
    main = parts[0]
    assert main["pads"] == {"p1", "p2"} and len(main["pieces"]) == 1
    p4 = next(c for c in parts if "p4" in c["pads"])
    assert p4["routed"] == {"v1", "t1"} and len(p4["pieces"]) == 1   # track -> via -> F.Cu piece


def test_spoke_tracks_land_in_fill_and_keep_clear_of_other_nets():
    pad = _pad("p1", "N", 0, 0)
    foreign = _pad("m1", "M", 2.0, 0)            # blocks the 0 degree direction
    info = dict(pads=[pad, foreign], graphics=[])
    fill = box(-6, -6, 6, 6).difference(box(-1.2, -1.2, 1.2, 1.2)).difference(Point(2.0, 0).buffer(0.9))
    zone = dict(uuid="z", net="N", layers={"F.Cu": [_ring(fill)]})
    plan = SimpleNamespace(net_class={"N": "kae_A", "M": "kae_A"},
                           classes={"kae_A": SimpleNamespace(widths={"F.Cu": 0.2})},
                           matrix={("kae_A", "kae_A", "F.Cu"): (0.2, 0.2, 0.2)},
                           pin_class={}, obstacle_classes={}, obstacles=[])
    space = repair._Space({}, info, plan)
    got = repair.spoke_tracks(pad, zone, "F.Cu", 2, plan, space)
    assert len(got) == 2
    core = fill.buffer(-(0.1 + 0.01))
    m = box(1.5, -0.5, 2.5, 0.5)
    from shapely.geometry import LineString
    for s in got:
        assert s["net"] == "N" and s["layer"] == "F.Cu" and s["width"] == 0.2
        assert tuple(s["a"]) == (0.0, 0.0)                           # from the pad's centre
        assert core.buffer(1e-6).contains(Point(s["b"]))           # KiCad: the end lies in the fill
        assert LineString([s["a"], s["b"]]).buffer(0.1).distance(m) >= 0.2 - 1e-6


def test_spoke_tracks_lie_in_the_rotated_pads_frame_y_down():
    """Spokes at the pad's orientation, y down like thermal_corridors: a pad at 33.75 degrees
    whose only fill is a narrow wedge at 33.75 degrees (up and right on screen) gets a spoke
    into it; `+ sin` mirrored the candidates 7.5 degrees off either side of it."""
    import math
    from shapely.geometry import Polygon
    pad = dict(_pad("p1", "N", 0, 0), orient=33.75)
    info = dict(pads=[pad], graphics=[])
    a, h = math.radians(33.75), math.radians(4.0)
    wedge = Polygon([(0, 0), (10 * math.cos(a - h), -10 * math.sin(a - h)),
                     (10 * math.cos(a + h), -10 * math.sin(a + h))]).difference(Point(0, 0).buffer(1.0))
    zone = dict(uuid="z", net="N", layers={"F.Cu": [_ring(wedge)]})
    plan = SimpleNamespace(net_class={"N": "kae_A"}, classes={"kae_A": SimpleNamespace(widths={"F.Cu": 0.2})},
                           matrix={}, pin_class={}, obstacle_classes={}, obstacles=[])
    got = repair.spoke_tracks(pad, zone, "F.Cu", 1, plan, repair._Space({}, info, plan))
    assert len(got) == 1
    bx, by = got[0]["b"]
    assert bx > 0 and by < 0 and abs(math.degrees(math.atan2(-by, bx)) - 33.75) < 1e-3


def test_pad_cut_off_from_its_zone_gets_a_spoke_into_the_rest_of_the_net():
    """A pad in its own island of fill is joined to the net's other piece, not to its island
    (a spoke into its own island joins nothing)."""
    pad, other = _pad("p1", "N", 0, 0), _pad("q1", "N", 5, 0)
    info = dict(pads=[pad, other], graphics=[], copper=["F.Cu", "B.Cu"])
    island = box(-2, -2, 2, 2).difference(box(-0.9, -0.9, 0.9, 0.9)).union(box(0.4, -0.1, 0.95, 0.1))
    main = box(3, -3, 8, 3)
    zone = dict(uuid="z", net="N", layers={"F.Cu": [_ring(island), _ring(main)]})
    plan = SimpleNamespace(net_class={"N": "kae_A"}, classes={"kae_A": SimpleNamespace(widths={"F.Cu": 0.2})},
                           matrix={}, pin_class={}, obstacle_classes={}, obstacles=[], copper=["F.Cu", "B.Cu"])
    report = dict(violations=[], unconnected_items=[dict(items=[
        dict(description="Pad 1 [N] of U1 on F.Cu", uuid="p1", pos=dict(x=0, y=0)),
        dict(description="Zone [N] on F.Cu, priority 0", uuid="z", pos=dict(x=3, y=-3))])])
    a = repair.analyse(report, {}, info, plan, fills=[zone], layer_map={}, copper={})
    assert len(a["spokes"]) == 1 and not a["thermal"]
    end = Point(a["spokes"][0]["b"])
    assert main.contains(end) and not island.buffer(0.05).contains(end)


def test_split_planes_keep_the_windows_that_matter():
    """The main part's fill becomes a plane: the hole around a cut-off pad of the net stays a
    window (else the router counts the pad as connected), a large hole stays, a small hole
    around foreign copper goes (it only slows the router)."""
    p1, p2 = _pad("p1", "N", 2, 2, h=0.3), _pad("p2", "N", 4.4, 4.4, h=0.1)
    info = dict(pads=[p1, p2], graphics=[])
    piece = (box(0, 0, 20, 20).difference(box(12, 12, 16, 16)).difference(box(4, 4, 4.8, 4.8))
             .difference(box(8, 8, 8.7, 8.7)))
    fills = [dict(uuid="z", net="N", layers={"F.Cu": [_ring(piece)]})]
    tree = S.parse('(pcb x (structure (layer F.Cu (type signal)) (plane N (polygon F.Cu 0 0 0 1 0 1 -1 0 -1))))')
    out = repair._fill_planes(tree, fills, {"N"}, lambda l: l, info, {}, ["F.Cu"])
    assert out["removed"] == 1 and out["added"] == 1 and out["parts"] == 2
    plane = S.findall(S.find(tree, "structure"), "plane")[0]
    windows = []
    for w in S.findall(plane, "window"):
        xs = [float(v) / 1000 for v in w[1][3::2]]
        windows.append((min(xs), max(xs)))
    assert len(windows) == 2
    assert any(lo < 4.1 and hi > 4.7 for lo, hi in windows)     # the cut-off pad's hole
    assert any(lo < 12.1 and hi > 15.9 for lo, hi in windows)   # the large hole


def test_router_budget_scales_only_past_the_old_split():
    """router_share "auto" gives the first routing 0.6 of the time up to 1,500 s (as the
    fixed 0.6 did) and all but repair_reserve_s beyond; repair rounds "auto" are bounded only
    by the no-improvement rule and the time."""
    from kae.route import bridge, repair
    fixed = dict(bridge.DEFAULT_OPTS)
    auto = dict(fixed, router_share="auto")
    for left in (100.0, 600.0, 880.0, 1500.0):
        assert abs(bridge.router_budget(left, auto) - bridge.router_budget(left, fixed)) < 1e-9
    assert abs(bridge.router_budget(3580.0, auto) - 2980.0) < 1e-9
    assert bridge.router_budget(3580.0, fixed) == 3580.0 * 0.6
    assert bridge.router_budget(1000.0, dict(fixed, repair=False)) == 900.0
    assert repair.max_rounds(fixed) == 5 and repair.max_rounds(dict(fixed, rounds="auto")) == repair.AUTO_ROUNDS


def test_critical_cli_passes_bridge_options():
    from kae.route.critical_cli import _bridge_opts
    assert _bridge_opts(["rounds=auto", "router-share=0.8", "repair_reserve_s=900"]) == dict(
        rounds="auto", router_share=0.8, repair_reserve_s=900)


def test_slot_wait_comes_out_of_freeroutings_deadline(tmp_path, monkeypatch, capsys):
    """A wait for a host-wide Freerouting slot is spent from the caller's budget: the job
    timeout Freerouting gets is the budget less its start-up margin and the wait, and a wait
    over SLOT_WARN of the budget is logged."""
    import fcntl
    import threading
    import time as _t
    from kae.route import freerouting as FR
    fake = tmp_path / "fake-freerouting"
    fake.write_text("#!/usr/bin/env python3\nimport sys\nopen(sys.argv[sys.argv.index('-do') + 1], 'w')"
                    ".write(' '.join(sys.argv))\n")
    fake.chmod(0o755)
    monkeypatch.setenv("KAE_BRIDGE_FREEROUTING", str(fake))
    monkeypatch.setenv("KAE_FR_SLOTS", "1")
    monkeypatch.setenv("KAE_FR_LOCKDIR", str(tmp_path / "slots"))
    (tmp_path / "slots").mkdir()
    held = open(tmp_path / "slots" / "slot0", "a")
    fcntl.flock(held, fcntl.LOCK_EX)
    threading.Timer(4.0, lambda: (fcntl.flock(held, fcntl.LOCK_UN), held.close())).start()
    t0 = _t.monotonic()
    run = FR.route(tmp_path / "board.dsn", tmp_path / "board.ses", tmp_path, budget_s=30.0)
    assert _t.monotonic() - t0 >= 3.5
    w = run.report["slot_wait_s"]
    assert w >= 3.0
    assert abs(run.report["job_timeout_s"] - (30.0 - 3.0 - w)) < 0.2          # margin min(15, 10 %) = 3 s
    assert "--router.job_timeout=00:00:2" in run.ses.read_text()               # 23-24 s, not 27
    assert "warning: waited" in capsys.readouterr().out


def test_slot_wait_ends_with_the_budget(tmp_path, monkeypatch):
    """With every slot held for good, route() runs without one once the budget is spent
    waiting, instead of hanging its caller."""
    import fcntl
    from kae.route import freerouting as FR
    fake = tmp_path / "fake-freerouting"
    fake.write_text("#!/usr/bin/env python3\nimport sys\nopen(sys.argv[sys.argv.index('-do') + 1], 'w')"
                    ".write(' '.join(sys.argv))\n")
    fake.chmod(0o755)
    monkeypatch.setenv("KAE_BRIDGE_FREEROUTING", str(fake))
    monkeypatch.setenv("KAE_FR_SLOTS", "1")
    monkeypatch.setenv("KAE_FR_LOCKDIR", str(tmp_path / "slots"))
    (tmp_path / "slots").mkdir()
    held = open(tmp_path / "slots" / "slot0", "a")
    fcntl.flock(held, fcntl.LOCK_EX)
    run = FR.route(tmp_path / "board.dsn", tmp_path / "board.ses", tmp_path, budget_s=10.0)
    assert run.report.get("slot_gave_up") and run.ses is not None
    assert run.report["slot_wait_s"] < 10.0
    held.close()


def test_excess_counts_only_errors_beyond_the_input():
    from kae.route import drc
    s = dict(errors=7, unconnected=2, by_type={"copper_edge_clearance": 4, "solder_mask_bridge": 2, "clearance": 1})
    base = {"copper_edge_clearance": 4, "solder_mask_bridge": 3}
    assert drc.excess(s, base) == 1          # the clearance error is the router's
    assert drc.excess(s, {}) == 7            # no baseline: every error counts, as before
    assert drc.excess(dict(by_type={}), base) == 0


def test_planes_on_renamed_layers_are_dropped():
    """analyse() names the open layers canonically (In1.Cu); KiCad writes the DSN plane on the
    layer's user name (GND_PLANE), and the plane was never dropped."""
    dsn = ('(pcb x (structure (layer F.Cu (type signal)) (layer GND_PLANE (type power)) '
           '(layer In2.Cu (type signal)) (layer B.Cu (type signal))'
           ' (plane GND (polygon GND_PLANE 0 0 0 100 0 100 100 0 100))'
           ' (plane VCC (polygon In2.Cu 0 0 0 100 0 100 100 0 100))))')
    lmap, _ = repair.layer_names(S.parse(dsn), ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"])
    t = S.parse(dsn)
    assert repair._drop_planes(t, {"GND": {"In1.Cu"}, "VCC": {"B.Cu"}}, lmap) == 1
    assert [str(p[1]) for p in S.findall(S.find(t, "structure"), "plane")] == ["VCC"]


def test_thermal_all_keeps_every_pads_corridors_after_a_starved_thermal(monkeypatch):
    """A repair round that finds a starved pad re-plans with the starved pads' corridors; under
    --thermal-all that dropped every other pad's corridors."""
    calls = []

    def fake_plan(info, path, opts):
        calls.append(opts["thermal_pads"])
        return SimpleNamespace()
    monkeypatch.setattr(repair.constraints, "plan", fake_plan)
    base = SimpleNamespace(plane_policy="keep")
    assert repair._thermal_plan(base, {}, "b.kicad_pcb", {"thermal_pads": "all"}, {}, {"p1"}) is base
    got = repair._thermal_plan(base, {}, "b.kicad_pcb", {"thermal_pads": ["p0"]}, {}, {"p0", "p1"})
    assert calls == [["p0", "p1"]] and got.plane_policy == "keep"


def test_no_time_for_a_routed_round_still_draws_the_spokes(tmp_path, monkeypatch):
    """With too little time left for a routed repair round (counted budgets: the router spends its
    whole share) and no last mile, the starved thermals of round 0 still get their spoke tracks,
    without the router, and the board with them is kept when KiCad's DRC finds it better."""
    starved = dict(violations=[dict(type="starved_thermal", severity="error", items=[]) for _ in range(3)],
                   unconnected_items=[])
    clean = dict(violations=[], unconnected_items=[])
    reports = [starved, clean]
    monkeypatch.setattr(repair.drc, "run", lambda board, out, timeout=900, cache=True: reports.pop(0))
    edits = []

    def edit_routing(path, dst, **kw):
        edits.append(kw)
        if path != dst:
            dst.write_text(path.read_text())
        else:
            dst.write_text(path.read_text() + "+spokes")
        return {"routing": []}
    monkeypatch.setattr(repair.pcbnew_io, "edit_routing", edit_routing)
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", lambda p: {"zones": []})
    spoke = dict(net="GND", layer="F.Cu", a=[0, 0], b=[1, 0], width=0.3)
    monkeypatch.setattr(repair, "analyse", lambda *a, **k: dict(
        widen={}, items=set(), nets=set(), spokes=[spoke], connect=set(), open={}, thermal=set(), unattributed=[]))
    monkeypatch.setattr(repair.freerouting, "route", lambda *a, **k: (_ for _ in ()).throw(AssertionError("router")))
    monkeypatch.setattr(repair, "clock_now", lambda: 1000.0)
    inp, out = tmp_path / "in.kicad_pcb", tmp_path / "out.kicad_pcb"
    inp.write_text("board")
    out.write_text("routed")
    rep = repair.loop(inp, out, tmp_path / "wd", SimpleNamespace(), {}, {}, deadline=1030.0, log=lambda m: None)
    assert rep["final"]["errors"] == 0
    assert rep["rounds"][1]["stopped"] == "time" and rep["rounds"][1]["spokes_only"]["kept"]
    assert out.read_text() == "routed+spokes"
    assert edits[-1] == dict(add=[spoke])
    # below SPOKES_MIN_S nothing is tried
    reports[:] = [starved]
    out.write_text("routed")
    rep = repair.loop(inp, out, tmp_path / "wd2", SimpleNamespace(), {}, {}, deadline=1010.0, log=lambda m: None)
    assert rep["final"]["errors"] == 3 and "spokes_only" not in rep["rounds"][1] and out.read_text() == "routed"


import pytest


@pytest.mark.parametrize("joined", [1, 0])
def test_spokes_with_no_routed_round_go_into_the_last_miles_first_round(tmp_path, monkeypatch, joined):
    """With the last mile on, the spoke tracks no routed round had time for are added to the last
    mile's first board before its joins and judged by that round's DRC (also when it joins
    nothing); there is no spokes-only round taking the last mile's time."""
    from kae.route import lastmile
    starved = dict(violations=[dict(type="starved_thermal", severity="error", items=[]) for _ in range(3)],
                   unconnected_items=[{"items": []}, {"items": []}])
    after = dict(violations=[], unconnected_items=[{"items": []}] * (2 - joined))
    reports = [starved]
    monkeypatch.setattr(repair.drc, "run",
                        lambda board, out, timeout=900, cache=True: reports.pop(0) if reports else after)
    edits = []

    def edit_routing(path, dst, **kw):
        edits.append(kw)
        dst.write_text(path.read_text() + ("+spokes" if kw.get("add") else ""))
        return {"routing": []}
    monkeypatch.setattr(repair.pcbnew_io, "edit_routing", edit_routing)
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", lambda p: {"zones": []})
    spoke = dict(net="GND", layer="F.Cu", a=[0, 0], b=[1, 0], width=0.3)
    monkeypatch.setattr(repair, "analyse", lambda *a, **k: dict(
        widen={}, items=set(), nets=set(), spokes=[spoke], connect=set(), open={}, thermal=set(), unattributed=[]))
    monkeypatch.setattr(repair, "input_errors", lambda *a: {})
    seen = []

    def close(board, info, plan, fills, out, **kw):
        seen.append(board.read_text())
        if joined:
            out.write_text(board.read_text() + "+join")
        return dict(joined=joined, failed=0, ripped=[], added=["j"] * joined, nets={})
    monkeypatch.setattr(lastmile, "close", close)
    monkeypatch.setattr(lastmile, "open_nets", lambda rep: [])   # a list, as open_nets returns: round_robin sorts it
    monkeypatch.setattr(repair, "clock_now", lambda: 1000.0)
    inp, out = tmp_path / "in.kicad_pcb", tmp_path / "out.kicad_pcb"
    inp.write_text("board")
    out.write_text("routed")
    rep = repair.loop(inp, out, tmp_path / "wd", SimpleNamespace(), {}, {"last_mile": True}, deadline=1100.0,
                      log=lambda m: None)
    assert seen[0] == "routed+spokes"                 # the spokes were on the board the last mile joined on
    assert sum(1 for e in edits if e.get("add")) == 1   # once: later rounds build on that board
    assert rep["rounds"][1]["stopped"] == "time" and rep["rounds"][1]["spokes_pending"] == 1
    assert not any("spokes_only" in r for r in rep["rounds"])
    lm = next(r for r in rep["rounds"] if r["round"] == "lm1")
    assert lm["spokes"] == 1 and lm["kept"]
    assert rep["final"]["errors"] == 0 and rep["final"]["unconnected"] == 2 - joined
    assert out.read_text() == "routed+spokes" + ("+join" if joined else "")


# ---- how one attempt spends the time after its first routing: the last mile's reserve, repair cycles
def _opens(n, errors=0):
    return dict(violations=[dict(type="clearance", severity="error", items=[]) for _ in range(errors)],
                unconnected_items=[{"items": []}] * n)


def _post_route(tmp_path, monkeypatch, reports, joins=(), close_s=0.0):
    """repair.loop with KiCad, the router and the last mile's joins replaced: DRC runs return `reports` in turn
    (the last one again when they run out), every repair round is a widening (no router), the last mile's
    close() joins `joins` in turn (0 when they run out) and takes `close_s` of the fake clock. Returns
    (run, seen): run(opts, left) -> report; seen counts the DRC runs, close() calls and clock reads."""
    from kae.route import lastmile
    seen = dict(drc=0, close=0, clock=0, now=1000.0)
    reports, joins = list(reports), list(joins)

    def run_drc(board, out, timeout=900, cache=True):
        seen["drc"] += 1
        return reports.pop(0) if len(reports) > 1 else reports[0]

    def edit_routing(path, dst, **kw):
        if path != dst:
            dst.write_text(path.read_text())
        return {"routing": []}

    def close(board, info, plan, fills, out, **kw):
        seen["close"] += 1
        seen["now"] += close_s
        n = joins.pop(0) if joins else 0
        if n:
            out.write_text(board.read_text() + "+join")
        return dict(joined=n, failed=0, ripped=[], added=["j"] * n, nets={})

    def clock():
        seen["clock"] += 1
        return seen["now"]
    monkeypatch.setattr(repair.drc, "run", run_drc)
    monkeypatch.setattr(repair.pcbnew_io, "edit_routing", edit_routing)
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", lambda p: {"zones": []})
    monkeypatch.setattr(repair, "_with_via_tracks", lambda board, rip, routed: set(rip))
    monkeypatch.setattr(repair, "analyse", lambda *a, **k: dict(
        widen={"u1": 0.3}, items=set(), nets=set(), spokes=[], connect=set(), open={}, thermal=set(),
        unattributed=[]))
    monkeypatch.setattr(repair.freerouting, "route", lambda *a, **k: (_ for _ in ()).throw(AssertionError("router")))
    monkeypatch.setattr(repair, "input_errors", lambda *a: {})
    monkeypatch.setattr(lastmile, "close", close)
    monkeypatch.setattr(lastmile, "open_nets", lambda rep: [])
    monkeypatch.setattr(repair, "clock_now", clock)
    inp, out = tmp_path / "in.kicad_pcb", tmp_path / "out.kicad_pcb"
    inp.write_text("board")

    def run(opts, left):
        out.write_text("routed")
        return repair.loop(inp, out, tmp_path / "wd", SimpleNamespace(), {}, dict(opts), deadline=seen["now"] + left,
                           log=lambda m: None)
    return run, seen


def _labels(rep):
    return [(r["round"], r.get("level") or r.get("stopped")) for r in rep["rounds"]]


def test_last_mile_reserve_scales_with_the_attempt_budget_only_when_asked():
    """The setting off: last_mile_reserve_s whatever the budget (the old rule). With a share: that share of
    the attempt's budget, never under one last-mile round nor over last_mile_reserve_s."""
    R = repair.last_mile_reserve
    assert R({}) == 0.0 and R({"last_mile": False, "last_mile_reserve_share": 0.15, "attempt_s": 900}) == 0.0
    for budget in (60, 600, 3000):
        assert R({"last_mile": True, "attempt_s": budget}) == 90.0
        assert R({"last_mile": True, "attempt_s": budget, "last_mile_reserve_share": 0.0}) == 90.0
    on = {"last_mile": True, "last_mile_reserve_share": 0.15}
    assert R(dict(on, attempt_s=60)) == repair.LAST_MILE_MIN_S          # 9 s would leave no last-mile round
    assert R(dict(on, attempt_s=400)) == 60.0
    assert R(dict(on, attempt_s=600)) == 90.0 and R(dict(on, attempt_s=3000)) == 90.0
    assert R(dict(on, attempt_s=400, last_mile_reserve_s=45.0)) == 45.0
    assert R(on, span_s=400) == 60.0                                    # no attempt budget known: the loop's own time
    assert R(on) == 90.0
    assert repair.max_cycles({}) == 1 and repair.max_cycles({"repair_cycles": 1.0}) == 1
    assert repair.max_cycles({"repair_cycles": 3}) == 3
    assert repair.max_cycles({"repair_cycles": 0.0}) == repair.max_cycles({"repair_cycles": "auto"}) == repair.AUTO_ROUNDS


def test_the_relative_reserve_runs_the_round_the_absolute_one_skips(tmp_path, monkeypatch):
    """100 s left of a 120 s attempt: under the absolute 90 s reserve no repair round runs (100 - 90 < 45); with
    the reserve at 0.15 of the budget (30 s: one last-mile round) the round runs and the last mile follows."""
    run, seen = _post_route(tmp_path, monkeypatch, [_opens(1, errors=1), _opens(1)])
    rep = run({"last_mile": True, "attempt_s": 120.0}, left=100.0)
    assert _labels(rep)[1] == (1, "time") and rep["final"]["errors"] == 1
    seen.update(drc=0, close=0)
    run, seen = _post_route(tmp_path, monkeypatch, [_opens(1, errors=1), _opens(1)])
    rep = run({"last_mile": True, "attempt_s": 120.0, "last_mile_reserve_share": 0.15}, left=100.0)
    assert _labels(rep)[:3] == [(0, None), (1, "items"), (2, "open connections: last mile")]
    assert rep["rounds"][1]["kept"] and rep["final"] == dict(errors=0, unconnected=1, by_type={})
    assert seen["close"] == 2 and "cycles" not in rep       # the last mile had its rounds; one cycle, as before


def test_repair_cycles_go_on_until_a_cycle_closes_nothing(tmp_path, monkeypatch):
    """repair_cycles 0: after the last mile, with time left and the board still open, the repair rounds run
    again (numbered on, from the DRC report the cycle ended with), then the last mile when they changed the
    board; a cycle that made the board no better is the last. repair_cycles 1 (the default) is one cycle."""
    reports = [_opens(3), _opens(3), _opens(2), _opens(1), _opens(1)]
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    rep = run({"last_mile": True}, left=500.0)
    assert rep["final"]["unconnected"] == 2 and "cycles" not in rep
    assert [l for l in _labels(rep) if l[0] in (1, 2, "lm1", "lm2")] == [
        (1, "items"), (2, "open connections: last mile"), ("lm1", "last_mile free"), ("lm2", "last_mile")]
    one_cycle = dict(seen)

    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    rep = run({"last_mile": True, "repair_cycles": 0.0}, left=500.0)
    assert rep["cycles"] == 3 and rep["final"]["unconnected"] == 1
    assert _labels(rep) == [
        (0, None), (1, "items"), (2, "open connections: last mile"), ("lm1", "last_mile free"), ("lm2", "last_mile"),
        ("c2", "cycle"), (3, "items"), (4, "open connections: last mile"), ("lm1", "last_mile free"),
        ("lm2", "last_mile"),
        ("c3", "cycle"), (5, "items"), (6, "open connections: last mile")]
    assert [r.get("kept") for r in rep["rounds"] if r["round"] in (1, 3, 5)] == [False, True, False]
    # one DRC per round that made a board (rounds 1, 3, 5 and the first lm1): none to start a later cycle
    assert seen["drc"] == 5 and one_cycle["drc"] == 3
    assert seen["close"] == 4        # cycle 3's rounds changed nothing: no third last mile
    assert (tmp_path / "wd" / "cycle2" / "repair3").is_dir() and (tmp_path / "wd" / "cycle3" / "repair5").is_dir()

    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    assert run({"last_mile": True, "repair_cycles": 2}, left=500.0)["cycles"] == 2      # a bound of its own
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    assert "cycles" not in run({"repair_cycles": 0.0}, left=500.0)                      # no last mile: no cycles


def test_repair_cycles_end_with_the_time_and_on_a_clean_board(tmp_path, monkeypatch):
    """A further cycle needs a routed round's time (ROUND_MIN_S) before the deadline; a clean board gets none."""
    reports = [_opens(3), _opens(3), _opens(2), _opens(1), _opens(1)]
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1], close_s=230.0)
    rep = run({"last_mile": True, "repair_cycles": 0.0}, left=500.0)     # two close() calls: 40 s left
    assert rep["cycles"] == 1 and rep["final"]["unconnected"] == 2
    run, seen = _post_route(tmp_path, monkeypatch, [_opens(1), _opens(1), _opens(0)], joins=[1])
    rep = run({"last_mile": True, "repair_cycles": 0.0}, left=500.0)
    assert rep["cycles"] == 1 and rep["final"]["unconnected"] == 0 and seen["close"] == 1


def test_rounds_skipped_for_time_run_in_a_second_cycle_with_what_the_last_mile_left(tmp_path, monkeypatch):
    """100 s left under the absolute reserve: the rounds are skipped, the last mile joins nothing and uses
    none of the time. With cycles the rounds then run with no reserve (the last mile has had its turn);
    without, the time is returned unused."""
    reports = [_opens(2, errors=1), _opens(2)]
    run, seen = _post_route(tmp_path, monkeypatch, reports)
    rep = run({"last_mile": True}, left=100.0)
    assert _labels(rep)[1] == (1, "time") and rep["final"]["errors"] == 1
    run, seen = _post_route(tmp_path, monkeypatch, reports)
    rep = run({"last_mile": True, "repair_cycles": 0.0}, left=100.0)
    assert rep["final"] == dict(errors=0, unconnected=2, by_type={})
    assert ("c2", "cycle") in _labels(rep) and (2, "items") in _labels(rep)
    assert rep["cycles"] == 3 and not any(r.get("kept") for r in rep["rounds"][_labels(rep).index(("c3", "cycle")):])
    # a first cycle that routed and closed nothing is not repeated
    run, seen = _post_route(tmp_path, monkeypatch, [_opens(2)])
    rep = run({"last_mile": True, "repair_cycles": 0.0}, left=500.0)
    assert rep["cycles"] == 1 and seen["drc"] == 2


def test_one_cycle_reads_the_clock_as_before(tmp_path, monkeypatch):
    """Counted-work budgets charge every clock read: with repair_cycles 1 and no reserve share, loop() adds
    no read to its one cycle (the same reads as _cycle alone), so a counted run does the same work."""
    reports = [_opens(3), _opens(3), _opens(2), _opens(1), _opens(1)]
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    run({"last_mile": True}, left=500.0)
    reads = seen["clock"]
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    run({"last_mile": True, "repair_cycles": 1.0, "last_mile_reserve_share": 0.0, "attempt_s": 900.0}, left=500.0)
    assert seen["clock"] == reads
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    out = tmp_path / "out.kicad_pcb"
    out.write_text("routed")
    rep = repair._cycle(tmp_path / "in.kicad_pcb", out, tmp_path / "wd1", SimpleNamespace(), {}, {"last_mile": True},
                        deadline=seen["now"] + 500.0, log=lambda m: None)
    assert seen["clock"] == reads and "_carry" in rep


def test_cycles_end_with_the_counted_budget(tmp_path, monkeypatch):
    """Work mode: the deadline is counted work. Every DRC charges 30 nominal seconds and every cycle makes
    the board better, so only the counted budget ends the cycles: no cycle starts with under ROUND_MIN_S of
    it left, whatever the wall clock does."""
    from kae import budget
    reports = [_opens(n) for n in (9, 9, 8, 7, 6, 5, 4, 3, 2, 1)]
    run, seen = _post_route(tmp_path, monkeypatch, reports, joins=[1])
    clock = budget.set_mode("work")
    try:
        monkeypatch.setattr(repair, "clock_now", budget.now)
        real = repair.drc.run

        def charged(board, out, timeout=900, cache=True):
            budget.charge("seconds", 30.0)
            return real(board, out, timeout=timeout, cache=cache)
        monkeypatch.setattr(repair.drc, "run", charged)
        inp, out = tmp_path / "in.kicad_pcb", tmp_path / "out.kicad_pcb"
        out.write_text("routed")
        t0 = budget.now()
        rep = repair.loop(inp, out, tmp_path / "wdw", SimpleNamespace(), {}, {"last_mile": True, "repair_cycles": 0.0},
                          deadline=t0 + 200.0, log=lambda m: None)
        spent = clock.spent - t0
        assert rep["cycles"] == 4 and rep["final"]["unconnected"] == 5      # 6 DRCs: 180 s, 20 s left
        assert 200.0 - repair.ROUND_MIN_S < spent <= 200.0
        assert not clock.ceiling_hit and clock.units["seconds"] == 30.0 * seen["drc"]
    finally:
        budget.set_mode("time")


def test_post_route_settings_default_to_the_old_behaviour(tmp_path, monkeypatch):
    """The three settings of this file's last section are off by default and read like every kae limit:
    KiCad text variable KAE_<NAME>, then opts (--set), then env, then the default."""
    from kae.route import constraints as C
    for name in ("KAE_LAST_MILE_RESERVE_SHARE", "KAE_REPAIR_CYCLES", "KAE_PERMUTE_PINS"):
        monkeypatch.delenv(name, raising=False)
    off = {n: C.setting_env(n) for n in ("last_mile_reserve_share", "repair_cycles", "permute_pins")}
    assert off == dict(last_mile_reserve_share=0.0, repair_cycles=1, permute_pins=0)
    assert repair.last_mile_reserve(dict(off, last_mile=True, attempt_s=120.0)) == 90.0 and repair.max_cycles(off) == 1
    monkeypatch.setenv("KAE_REPAIR_CYCLES", "0")
    assert repair.max_cycles({"repair_cycles": C.setting_env("repair_cycles")}) == repair.AUTO_ROUNDS
    assert C.setting_env("repair_cycles", None, {"repair_cycles": 3}) == 3.0          # --set wins over env
    board = tmp_path / "b.kicad_pcb"
    board.with_suffix(".kicad_pro").write_text('{"text_variables": {"KAE_LAST_MILE_RESERVE_SHARE": "0.2"}}')
    assert C.setting_env("last_mile_reserve_share", board, {"last_mile_reserve_share": 0.15}) == 0.2
