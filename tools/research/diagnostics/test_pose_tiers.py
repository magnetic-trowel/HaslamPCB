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
              x=100.0, y=-10.0, rot=0.0, side="F", on_board=True,
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


# ------------------------------------------------------------------ the pose oracle (held at human poses)
def _oracle(tmp_path, board, tier="big", legal=True, reason=None, poses=None, **extra):
    from kae.place import pose_tiers
    held = poses or {u: [10.0, -5.0, 90.0, "F"] for u in pose_tiers.tier_uuids(board, tier)}
    o = dict(schema=pose_tiers.ORACLE_SCHEMA, board="b", key=pose_tiers.board_key(board), big_pads=16,
             tiers={tier: dict(held=held, legal=legal, reason=reason)}, **extra)
    (tmp_path / f"{o['key']}.json").write_text(__import__("json").dumps(o))
    return held


def test_held_poses_from_oracle(tmp_path):
    from kae.place import pose_tiers
    b = _board()
    want = _oracle(tmp_path, b)
    got = pose_tiers.held_poses(b, {"pose_tier": "big", "pose_source": str(tmp_path)})
    assert got == {u: tuple(p) for u, p in want.items()} and set(got) == {"u-J1", "u-U1"}
    assert pose_tiers.held_poses(b, {"pose_source": str(tmp_path)}) == {}          # no tier: nothing held


def test_held_poses_refusals(tmp_path):
    """No silent fallback: a board the oracle lacks, a tier it lacks or found illegal, stop the run."""
    from kae.place import pose_tiers
    b = _board()
    opts = {"pose_tier": "big", "pose_source": str(tmp_path)}
    with pytest.raises(pose_tiers.PoseOracleError, match="no human poses"):
        pose_tiers.held_poses(b, opts)
    _oracle(tmp_path, b, legal=False, reason="clearance 2")
    with pytest.raises(pose_tiers.PoseOracleError, match="excluded: clearance 2"):
        pose_tiers.held_poses(b, opts)
    with pytest.raises(pose_tiers.PoseOracleError, match="no tier mid"):
        pose_tiers.held_poses(b, dict(opts, pose_tier="mid"))
    _oracle(tmp_path, b, poses={"u-ZZ": [0, 0, 0, "F"]})
    with pytest.raises(pose_tiers.PoseOracleError, match="not on this board"):
        pose_tiers.held_poses(b, opts)


def test_held_poses_without_oracle_refuse_staged_parts():
    """The first build held parts where a place task's input stages them, off the board: refused now."""
    from kae.place import pose_tiers
    b = _board()
    assert pose_tiers.held_poses(b, {"pose_tier": "big"}) == {"u-J1": (100.0, -10.0, 0.0, "F"),
                                                              "u-U1": (100.0, -10.0, 0.0, "F")}
    next(f for f in b.footprints if f.ref == "U1").on_board = False
    with pytest.raises(pose_tiers.PoseOracleError, match="off the board.*U1"):
        pose_tiers.held_poses(b, {"pose_tier": "big"})


def test_stage_moves_held_parts_to_oracle_poses(monkeypatch, tmp_path):
    """The stage writes the held parts' oracle poses into its input before placing, places from that
    board (so the output keeps them) and passes them as fixed."""
    from kae.joint import stages as S
    from kae.place import pipeline
    (tmp_path / "o").mkdir()
    want = _oracle(tmp_path / "o", _board())
    written, seen = [], []

    class Stop(Exception):
        pass

    def fake_place(board, **kw):
        seen.append((set(kw["fixed"]), kw["board_path"]))
        raise Stop
    monkeypatch.setattr(pipeline, "place", fake_place)
    st = S.KaeStages(tmp_path / "in.kicad_pcb", tmp_path / "wd",
                     opts={"pose_tier": "big", "pose_source": str(tmp_path / "o")})
    monkeypatch.setattr(st, "_load", lambda p: _board())
    monkeypatch.setattr(st, "_write_poses", lambda src, dst, poses: written.append((src, dst, poses)))
    with pytest.raises(Stop):
        st.place(0, 10.0)
    assert written and written[0][2] == {u: tuple(p) for u, p in want.items()}
    assert st.input == written[0][1] and seen[0] == ({"u-J1", "u-U1"}, str(written[0][1]))
    assert {"u-J1", "u-U1"} <= st.locked


def test_oracle_verdict():
    sys.path.insert(0, str(Path(__file__).parent))
    import pose_oracle as PO
    types = ("clearance", "courtyards_overlap", "copper_edge_clearance")
    assert PO.excess_errors({"clearance": 3, "courtyards_overlap": 1, "starved_thermal": 9},
                            {"clearance": 3}, types) == {"courtyards_overlap": 1}
    assert PO.excess_errors({"copper_edge_clearance": 22}, {"copper_edge_clearance": 22}, types) == {}
    assert PO.tier_verdict({}, 0, ["U1"]) == (True, None)
    legal, why = PO.tier_verdict({"courtyards_overlap": 1}, 1, ["U1"])
    assert not legal and "courtyards_overlap 1" in why and "1 held parts" in why
    assert PO.tier_verdict({}, 0, [])[0] is False
