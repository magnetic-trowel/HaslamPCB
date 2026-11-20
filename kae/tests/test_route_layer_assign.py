# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `net_layers` setting (kae.route.layer_assign): a per-net layer assignment reaches the routing plan as
class layer sets, and leaves the plan alone when unset. tools/research/routing/net_layers.py writes the tables."""
import importlib.util
import json
from pathlib import Path

import pytest

from kae.board.kicad_file import load
from kae.route import constraints as CN
from kae.route import layer_assign as LA

import critical_fixtures as F

TOOL = Path(__file__).resolve().parents[2] / "tools" / "research" / "routing" / "net_layers.py"


def _tool():
    if not TOOL.exists():
        pytest.skip("tools/research/routing not present")
    spec = importlib.util.spec_from_file_location("net_layers", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _board(tmp_path):
    p = F.write_board(tmp_path)
    return p, F.synth_info(load(p))


def _classes(plan):
    return {n: (tuple(rc.nets), tuple(rc.layers) if rc.layers else None) for n, rc in plan.classes.items()}


def _smd_only_nets(info):
    """Nets whose pads are all surface-mount on one layer: {net: that layer}."""
    by = {}
    for pad in info["pads"]:
        if pad.get("net"):
            by.setdefault(pad["net"], []).append(pad)
    out = {}
    for net, pads in by.items():
        lays = {l for pd in pads for l in pd.get("layers") or [] if l in info["copper"]}
        if not any(pd.get("drilled") for pd in pads) and len(lays) == 1:
            out[net] = next(iter(lays))
    return out


def test_unset_leaves_the_plan_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("KAE_NET_LAYERS", raising=False)
    p, info = _board(tmp_path)
    assert LA.assign(info, p, {}, list(info["copper"])) == ({}, None)
    plan = CN.plan(info, p, {})
    assert "layer_assign" not in plan.notes
    assert all(rc.layers is None for rc in plan.classes.values())
    # a table that restricts nothing gives the same classes as no table
    t = tmp_path / "t.json"
    t.write_text(json.dumps(dict(version=1, nets={})))
    assert _classes(CN.plan(info, p, {"net_layers": str(t)})) == _classes(plan)


def test_a_table_splits_classes_and_keeps_pad_layers(tmp_path, monkeypatch):
    monkeypatch.delenv("KAE_NET_LAYERS", raising=False)
    p, info = _board(tmp_path)
    cu = list(info["copper"])
    smd = _smd_only_nets(info)
    assert len(smd) >= 2 and len(cu) >= 2
    (a, la), (b, lb) = sorted(smd.items())[:2]
    other = next(l for l in cu if l != lb)
    t = tmp_path / "t.json"
    # a: its pad layer only -> every other layer is off. b: a layer without its pads -> the pad layer is added;
    # on a two-layer board that allows every layer, so b keeps its class
    t.write_text(json.dumps(dict(version=1, source="test", nets={a: [la], b: [other], "no such net": ["F.Cu"]})))
    off, note = LA.assign(info, p, {"net_layers": str(t)}, cu)
    assert off[a] == tuple(l for l in cu if l != la)
    if len(cu) == 2:
        assert b not in off and note["unrestricted"]["everywhere"] == 1
    else:
        assert set(off[b]) == set(cu) - {other, lb}
    assert note["found"] and note["restricted"] == len(off) and note["source"] == "test"
    plan = CN.plan(info, p, {"net_layers": str(t)})
    rc = plan.classes[plan.net_class[a]]
    assert rc.layers == [la] and plan.notes["layer_assign"]["restricted"] == len(off)
    base = CN.plan(info, p, {})
    assert len(plan.classes) == len(base.classes) + 1 or len(base.classes[base.net_class[a]].nets) == 1
    # the environment variable works where neither the project nor opts set it
    monkeypatch.setenv("KAE_NET_LAYERS", str(t))
    assert _classes(CN.plan(info, p, {})) == _classes(plan)


def test_cap_drops_the_rarest_layer_sets(tmp_path, monkeypatch):
    monkeypatch.delenv("KAE_NET_LAYERS", raising=False)
    p, info = _board(tmp_path)
    cu = list(info["copper"])
    smd = _smd_only_nets(info)
    t = tmp_path / "t.json"
    t.write_text(json.dumps(dict(version=1, nets={n: [l] for n, l in smd.items()})))
    off, note = LA.assign(info, p, {"net_layers": str(t), "net_layers_max_sets": 0}, cu)
    assert off == {} and note["unrestricted"]["rare_set"] == len(smd)
    off, note = LA.assign(info, p, {"net_layers": str(t)}, cu)
    assert len(off) == len(smd) and note["layer_sets"] == len(set(smd.values()))


def test_directory_lookup_by_stem_and_fingerprint(tmp_path, monkeypatch):
    monkeypatch.delenv("KAE_NET_LAYERS", raising=False)
    p, info = _board(tmp_path / "b")
    cu = list(info["copper"])
    net, layer = sorted(_smd_only_nets(info).items())[0]
    d = tmp_path / "tables"
    d.mkdir()
    off, note = LA.assign(info, p, {"net_layers": str(d)}, cu)
    assert off == {} and note["found"] is False
    (d / f"{LA.fingerprint(info['nets'])}.json").write_text(json.dumps(dict(version=1, nets={net: [layer]})))
    off, note = LA.assign(info, p, {"net_layers": str(d)}, cu)
    assert net in off and note["found"]
    (d / "board.json").write_text(json.dumps(dict(version=1, nets={})))   # the stem wins
    assert LA.assign(info, p, {"net_layers": str(d)}, cu)[0] == {}


BOARD = '''(kicad_pcb (version 20250101)
\t(segment
\t\t(start 0 0)
\t\t(end 3 4)
\t\t(width 0.2)
\t\t(layer "F.Cu")
\t\t(net "A")
\t)
\t(segment (start 0 0) (end 0 10) (width 0.2) (layer "In1.Cu") (net "A"))
\t(arc (start 0 0) (mid 1 1) (end 6 8) (width 0.2) (layer "B.Cu") (net "B \\"q\\""))
\t(via (at 0 0) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "A"))
)'''


def test_tool_extracts_tables_and_measures_reach(tmp_path):
    T = _tool()
    t = T.tracks(BOARD)
    assert dict(t["A"]) == {"F.Cu": 5.0, "In1.Cu": 10.0} and dict(t['B "q"']) == {"B.Cu": 10.0}
    assert T.table(BOARD)["nets"] == {"A": ["F.Cu", "In1.Cu"], 'B "q"': ["B.Cu"]}
    assert T.table(BOARD, roles=True)["nets"]["A"] == ["B.Cu", "F.Cu", "In1.Cu"]
    assert T.fingerprint(T.net_names(BOARD)) == LA.fingerprint(["A", 'B "q"'])
    ref = BOARD.replace('(layer "In1.Cu")', '(layer "F.Cu")')
    r = T.reach(BOARD, ref)
    assert r["nets_compared"] == 2 and r["off_net_share"] == 0.5 and r["off_length_share"] == 0.4
    src = tmp_path / "x.kicad_pcb"
    src.write_text(BOARD)
    assert T.main(["extract", str(src), "-o", str(tmp_path / "out")]) == 0
    names = sorted(f.name for f in (tmp_path / "out").iterdir())
    assert names == sorted(["x.json", f"{T.fingerprint(T.net_names(BOARD))}.json"])
    old = '(kicad_pcb (net 0 "")\n (net 1 "N1")\n (segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net 1)))'
    assert dict(T.tracks(old)["N1"]) == {"F.Cu": 1.0}
