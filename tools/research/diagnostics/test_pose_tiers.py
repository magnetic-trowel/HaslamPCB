# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier membership (kae.place.pose_tiers), the joint stages' hook and pose_tiers (no KiCad, no placement)."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import pose_tiers as PT  # noqa: E402


def _fp(ref, n, kind="smd", lib_id="Resistor_SMD:R_0402", value="10k", numbers=None):
    nums = numbers if numbers is not None else [str(i + 1) for i in range(n)]
    return NS(ref=ref, uuid="u-" + ref, lib_id=lib_id, value=value, fields={}, locked=False, edge_cuts=False,
              pads=[NS(number=k, kind=kind, net=f"N{k}") for k in nums])


def _board():
    return NS(footprints=[
        _fp("R1", 2), _fp("C1", 2, lib_id="Capacitor_SMD:C_0402", value="100n"),
        _fp("L1", 0, numbers=["1", "1", "2", "2"], lib_id="Inductor_SMD:L_Split"),     # split pads: 2 terminals
        _fp("Q1", 3, lib_id="Package_TO_SOT_SMD:SOT-23", value="BSS138"),
        _fp("U1", 20, lib_id="Package_SO:TSSOP-20", value="STM32"),
        _fp("U2", 15, lib_id="Package_DFN_QFN:QFN-14_EP", value="X"),
        _fp("J1", 2, kind="thru_hole", lib_id="Connector_JST:JST_PH_B2B", value="Conn_01x02"),
        _fp("H1", 0, numbers=[""], kind="np_thru_hole", lib_id="MountingHole:MountingHole_3.2mm", value="MH"),
    ])


def test_terminals():
    b = {f.ref: f for f in _board().footprints}
    assert PT.terminals(b["L1"]) == 2 and PT.terminals(b["H1"]) == 0 and PT.terminals(b["U1"]) == 20


def test_tier_membership():
    b = _board()
    assert PT.tier_refs(b, "none") == []
    assert PT.tier_refs(b, "all") == sorted(f.ref for f in b.footprints)
    assert PT.tier_refs(b, "big") == ["J1", "U1"]
    assert PT.tier_refs(b, "big", big_pads=15) == ["J1", "U1", "U2"]
    assert PT.tier_refs(b, "small") == ["C1", "L1", "R1"]               # 2-terminal, connectors excluded
    assert PT.tier_refs(b, "mid") == ["J1", "Q1", "U1", "U2"]            # H1 (no terminal) only in all
    # nesting; M and P disjoint, together everything but the < 2-terminal parts
    u = {t: PT.tier_uuids(b, t) for t in PT.TIERS}
    assert u["none"] <= u["big"] <= u["mid"] <= u["all"]
    assert u["all"] - (u["mid"] | u["small"]) == {"u-H1"} and not (u["mid"] & u["small"])
    with pytest.raises(ValueError):
        PT.tier_uuids(b, "huge")


def test_stage_hook(monkeypatch, tmp_path):
    """kae.joint.stages passes pose_tier's parts to the placer as fixed (and locks them); without the
    setting it passes an empty set, which pipeline.place reads as no fixed parts (the control)."""
    from kae.joint import stages as S
    from kae.place import pipeline, pose_tiers
    assert "pose_tier" in S.STAGE_KEYS
    assert pose_tiers.held(_board(), {}) == set() and pose_tiers.held(_board(), None) == set()
    assert pose_tiers.held(_board(), {"pose_tier": "all"}) == {f.uuid for f in _board().footprints}
    seen = []

    class Stop(Exception):
        pass

    def fake_place(board, **kw):
        seen.append(set(kw["fixed"]))
        raise Stop
    monkeypatch.setattr(pipeline, "place", fake_place)
    for opts, want in (({}, set()), ({"pose_tier": "big"}, {"u-J1", "u-U1"})):
        st = S.KaeStages(tmp_path / "in.kicad_pcb", tmp_path / "wd", opts=opts)
        monkeypatch.setattr(st, "_load", lambda p: _board())
        with pytest.raises(Stop):
            st.place(0, 10.0)
        assert seen[-1] == want and want <= st.locked


def test_refs_on_fixture(capsys):
    fixture = Path(__file__).parents[3] / "kae" / "tests" / "data" / "board" / "fixture.kicad_pcb"
    if not fixture.exists():
        pytest.skip("kae fixture board not found")
    assert PT.main(["refs", str(fixture), "--tier", "none"]) == 0
    assert capsys.readouterr().out.strip() == ""
    PT.main(["refs", str(fixture), "--tier", "big"])
    big = capsys.readouterr().out.strip().split(",")
    assert "J1" in big
    PT.main(["refs", str(fixture), "--tier", "all"])
    from kae.board.kicad_file import load
    assert set(capsys.readouterr().out.strip().split(",")) == {f.ref for f in load(fixture).footprints}
    r = PT.pose_diff(fixture, fixture, "all")
    assert r["ok"] and r["held"] == r["parts"] and r["free_moved"] == 0
