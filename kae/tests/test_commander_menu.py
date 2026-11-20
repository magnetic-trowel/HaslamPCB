# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.commander.menu: the priced loop-back menu, on synthetic reports (no KiCad)."""
import json
from pathlib import Path

from kae.commander import menu as M


def _conn(net, pads, cause, **kw):
    return dict(net=net, pads=list(pads), kinds=["pad"], cause=cause, line="", **kw)


def _bind(constraint, source="board", **kw):
    b = dict(constraint=constraint, required=0.2, available=0.12, source=source, where=".kicad_pro board setup",
             override=None, against="pad U1.3 (A)", layer="F.Cu", at=[1.0, 2.0])
    b.update(kw)
    return b


def _route_report(conns, stopped="no improvement", packages=None, **kw):
    blk = dict(blocked=[c for c in conns if c["cause"] != "congestion"],
               congestion=[c for c in conns if c["cause"] == "congestion"], summary=[], undiagnosed=0, hazards=[])
    if packages:
        blk["packages"] = packages
    rep = dict(input="/x/board.kicad_pcb", opts=dict(planes="cost", neckdown=False, pad_shapes="kicad"),
               plan=dict(min_width=0.1), repair=dict(rounds=[dict(round=1, stopped=stopped)],
                                                     final=dict(unconnected=len(conns), errors=0)),
               blocked=blk)
    rep.update(kw)
    return rep


def _joint_report(conns, stop="time: budget spent"):
    r = _route_report(conns)
    blk = r.pop("blocked")
    return dict(stop=stop, final=dict(unconnected=len(conns), blocked=blk, blocked_note="x"))


CONNS = [
    _conn("A", ["U1.3", "J1.1"], "congestion"),
    _conn("B", ["U1.40", "R1.1"], "congestion"),
    _conn("C", ["U1.7", "R2.1"], "rule", binding=_bind("track_width", available=0.12)),
    _conn("D", ["U2.1", "C1.1"], "kae default",
          binding=_bind("clearance", source="kae", override="KAE_IGNORED_CLEARANCE_FLOOR / "
                                                            "--set ignored_clearance_floor=", available=0.08)),
    _conn("E", ["U3.2", "C2.1"], "rule", binding=_bind("pad_shape", source="kae",
                                                       where="pad U3.2 copper beyond its DSN shape (0.004 mm, "
                                                             "--set pad_shapes=outside)")),
    _conn("F", ["U4.1", "C3.1"], "fixed copper", fixed_nets=["GND"]),
    _conn("G", ["J5.1", "J6.1"], "geometry", walled_by=["board edge on F.Cu"]),
    _conn("T", ["C22.2", "U7.1"], "kae default", binding=_bind("thermal_corridor", source="kae",
                                                                where="kae thermal-spoke corridor of spokes C22.2")),
    _conn("H", ["R9.1", "R8.1"], "rule", binding=_bind("clearance", against="track of X", where=".kicad_dru rule 'x'",
                                                       track=0.05)),
]

PKG = dict(package="U9", cause="via in pad", demand=40, escapable=30.0, short=10, relaxations=[
    dict(rule="track width", value=0.08, escapable=40, all=True, fab_class="advanced", fab_cost="+20%",
         kicad=".kicad_dru: ..."),
    dict(rule="vias in the balls' pads (via-in-pad, filled and capped; kae: --set escape_via_in_pad=true)",
         escapable=40, all=True, fab_class="advanced", fab_cost="+30%", kicad="fab: via-in-pad"),
    dict(rule="signals on plane layers In1.Cu", escapable=40, all=True, kicad="..."),
    dict(rule="2 more signal layers", escapable=40, all=True, kicad="stackup"),
])


def _ids(doc, where="menu"):
    return [it["id"] for it in doc[where]]


def test_each_cause_has_its_item():
    doc = M.build_menu([_route_report(CONNS, packages=[PKG])])
    ids = _ids(doc) + _ids(doc, "ask")
    for want in ("kae_default", "thermal_corridor", "neckdown", "pad_shape", "planes_allow", "via_in_pad", "rule_relax",
                 "release_fixed_copper", "add_layers", "grow_outline", "pin_swap", "more_effort"):
        assert want in ids, want
    kd = next(it for it in doc["menu"] if it["id"] == "kae_default")
    assert kd["knob"]["route"] == ["--set", "ignored_clearance_floor=0.08"]
    assert kd["knob"]["joint"] == ["--set", "bridge.ignored_clearance_floor=0.08"]
    nd = next(it for it in doc["menu"] if it["id"] == "neckdown")
    assert nd["knob"]["joint"] == ["--set", "bridge.neckdown=true"]
    assert "C: U1.7-R2.1" in nd["evidence"]["connections"]
    vip = next(it for it in doc["menu"] if it["id"] == "via_in_pad")
    assert vip["knob"]["effect"] == "plan_only" and vip["price"]["fab_class"] == "advanced"
    rr = [it for it in doc["ask"] if it["id"] == "rule_relax"]
    assert rr and all(it["price"]["scorer"] == "forbidden" and it["score"] == 0 for it in rr)
    # every menu item has a knob the scorer allows; ranks are 1..n by score
    assert all(it["knob"]["kind"] != "none" and it["price"]["scorer"] == "allowed" for it in doc["menu"])
    assert [it["rank"] for it in doc["menu"]] == list(range(1, len(doc["menu"]) + 1))
    sc = [it["score"] for it in doc["menu"]]
    assert sc == sorted(sc, reverse=True)


def test_every_open_accounted_for():
    doc = M.build_menu([_route_report(CONNS + [_conn("Z", ["R5.1", "R6.1"], "geometry", walled_by=["pad"])])])
    addressed = {c for it in doc["menu"] + doc["ask"] if it["id"] != "more_effort"
                 for c in it["evidence"]["connections"]}
    un = set(doc["unactionable"]["connections"])
    allc = {f"{c['net']}: {'-'.join(c['pads'])}" for c in doc["persistence"]["connections"]}
    assert allc == addressed | un
    assert "Z: R5.1-R6.1" in un and doc["unactionable"]["why"] == {"geometry": 1}


def test_persistence_over_three_reports():
    a, b, c = CONNS[0], CONNS[1], _conn("Q", ["U1.9", "R7.1"], "congestion")
    reps = [_route_report([a, b]), _route_report([a, c]), _route_report([a])]
    doc = M.build_menu(reps)
    p = {x["net"]: x["persistence"] for x in doc["persistence"]["connections"]}
    assert p == {"A": 1.0, "B": round(1 / 3, 4), "Q": round(1 / 3, 4)}
    parts = {x["ref"]: x for x in doc["persistence"]["parts"]}
    assert parts["U1"]["persistence"] == 1.0 and parts["U1"]["mean_opens"] == round(5 / 3, 4)
    assert parts["R1"]["persistence"] == round(1 / 3, 4)
    assert doc["n_reports"] == 3
    nd = next(it for it in doc["menu"] if it["id"] == "neckdown")
    assert nd["gain"] == round(1 + 2 / 3, 4)
    # U1 recurs in every report: the part is a target even with few opens
    assert any(it["id"] == "move_part" and it["target"]["parts"] == ["U1"] for it in doc["menu"])


def test_deterministic_bytes():
    reps = [_route_report(CONNS, packages=[PKG]), _joint_report(CONNS[:3])]
    s1 = M.dumps(M.build_menu(json.loads(json.dumps(reps))))
    s2 = M.dumps(M.build_menu(json.loads(json.dumps(reps))))
    assert s1 == s2


def test_route_and_joint_reports_accepted():
    j = M.build_menu([_joint_report(CONNS[:2])])
    assert j["kinds"] == ["joint"] and j["opens"]["connections"] == 2
    me = next(it for it in j["menu"] if it["id"] == "more_effort")
    assert me["gain"] == round(2 * M.EFFORT_PRIOR_TIME, 4)          # the joint loop stopped on time
    r = M.build_menu([_route_report(CONNS[:2], stopped="time")])
    assert r["kinds"] == ["route"]
    assert next(it for it in r["menu"] if it["id"] == "more_effort")["gain"] == round(2 * M.EFFORT_PRIOR_TIME, 4)
    # a standalone diagnosis
    blk = _route_report(CONNS[:2])["blocked"]
    s = M.build_menu([blk])
    assert s["kinds"] == ["blocked"] and s["opens"]["connections"] == 2


def test_more_effort_always_present_and_last_on_ties():
    doc = M.build_menu([_route_report([])])
    assert _ids(doc) == ["more_effort"]


def test_task_route_forbids_placement():
    reps = [_route_report([_conn(n, [f"U1.{i}", "R1.1"], "congestion") for i, n in enumerate("ABCD", 30)])]
    assert any(it["id"] == "move_part" for it in M.build_menu(reps)["menu"])
    doc = M.build_menu(reps, opts=dict(task="route"))
    assert not any(it["id"] == "move_part" for it in doc["menu"])
    assert any(it["id"] == "move_part" and it["score"] == 0 for it in doc["ask"])


def test_board_rotation_and_flip():
    pads = [("N1", 1.0, 0.0), ("N2", -1.0, 0.0)] + [("", 0.0, 0.0)] * 20
    board = dict(name="b", copper_layers=2,
                 parts=dict(U1=dict(pads=22, side="F", smd=True, x=0.0, y=0.0, pad_xy=pads),
                            R1=dict(pads=2, side="F", smd=True, x=0, y=10, pad_xy=[("N1", 0.0, 10.0)]),
                            R2=dict(pads=2, side="F", smd=True, x=0, y=-10, pad_xy=[("N2", 0.0, -10.0)])),
                 nets=dict(N1=[("U1", 1.0, 0.0), ("R1", 0.0, 10.0)], N2=[("U1", -1.0, 0.0), ("R2", 0.0, -10.0)]))
    conns = [_conn("N1", ["U1.1", "R1.1"], "congestion"), _conn("N2", ["U1.2", "R2.1"], "congestion"),
             _conn("N3", ["U1.3", "R3.1"], "congestion")]
    doc = M.build_menu([_route_report(conns)], board=board)
    rot = next(it for it in doc["menu"] if it["id"] == "rotate_part")
    rh = rot["evidence"]["rotation_hpwl"]
    assert rh["0"] == 22.0 and rh["270"] == 18.0 and rot["evidence"]["best_rotation"] == 270
    flip = next(it for it in doc["ask"] if it["id"] == "flip_part")
    assert flip["price"]["assembly_usd"] == M.FIRST_BOTTOM_USD


def test_drc_unconnected_used_without_diagnosis():
    rep = dict(input="b", opts={}, repair=dict(rounds=[], final=dict(unconnected=1)))
    drc = {"unconnected_items": [{"items": [{"description": "Pad 3 [SIG] of U1 on F.Cu"},
                                            {"description": "Pad 1 [SIG] of J1 on F.Cu"}]}]}
    doc = M.build_menu([rep], drc=drc)
    assert doc["persistence"]["connections"][0]["pads"] == ["J1.1", "U1.3"]


def test_knob_keys_exist_in_registries():
    from kae.route import bridge
    from kae.route import constraints as CN
    for k in M.BRIDGE_KEYS:
        assert k in bridge.DEFAULT_OPTS, k
    for k in M.CONSTRAINT_KEYS:
        assert k in CN.DEFAULTS, k
    esc = (Path(bridge.__file__).parent / "escape.py").read_text()
    for k in M.BRIDGE_OPT_KEYS:
        assert f'get("{k}")' in esc, k
    # every knob the catalogue emits names one of those keys
    known = set(M.BRIDGE_KEYS + M.BRIDGE_OPT_KEYS + M.CONSTRAINT_KEYS)
    doc = M.build_menu([_route_report(CONNS, packages=[PKG])])
    for it in doc["menu"]:
        args = (it["knob"].get("route") or []) + (it["knob"].get("joint") or [])
        for i, a in enumerate(args):
            if a == "--set":
                k = args[i + 1].split("=")[0].removeprefix("bridge.")
                assert k in known, k


def test_cli(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_route_report(CONNS)))
    out = tmp_path / "m.json"
    assert M.main([str(p), "--out", str(out), "--top", "2"]) == 0
    doc = json.loads(out.read_text())
    assert doc["schema"] == M.SCHEMA and len(doc["menu"]) == 2
