# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.joint.halo: pressure schema, fallback producer, halo re-placement."""
import json
import shutil
from pathlib import Path

import pytest
from kae.board.kicad_file import load
from kae.joint import halo as H

DATA = Path(__file__).parent / "data" / "board"
FIXTURE = DATA / "fixture.kicad_pcb"


def _copy(tmp_path, name="start"):
    dst = tmp_path / f"{name}.kicad_pcb"
    shutil.copy2(FIXTURE, dst)
    for ext in (".kicad_pro", ".kicad_dru"):
        shutil.copy2(FIXTURE.with_suffix(ext), dst.with_suffix(ext))
    return dst


def _touching(tmp_path):
    """The fixture with U2 moved 0.1 mm right of U1's occupancy (U1 own right edge 11.9 mm,
    U2 at 90 degrees has its left edge 1.4 mm from its centre)."""
    from kae.place.writer import write
    src = _copy(tmp_path, "orig")
    b = load(src)
    u2 = next(fp for fp in b.footprints if fp.ref == "U2")
    dst = tmp_path / "start.kicad_pcb"
    write(str(src), str(dst), {u2.uuid: (13.4, 10.0, u2.rot, u2.side)}, log=None)
    for ext in (".kicad_pro", ".kicad_dru"):
        shutil.copy2(FIXTURE.with_suffix(ext), dst.with_suffix(ext))
    return dst


def _gap(path, a, b):
    """Gap (mm) between the exact occupancy rectangles of parts a and b on the board at path."""
    from kae.place.problem import Problem, shift
    P = Problem.build(load(path))
    rects = {}
    for p in P.parts:
        if p.ref in (a, b):
            r = min(p.rots, key=lambda r: min((r.rot - p.rot0) % 360, (p.rot0 - r.rot) % 360))
            rects[p.ref] = shift(r.own, p.x0, p.y0)
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = rects[a], rects[b]
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return (dx * dx + dy * dy) ** 0.5 if dx > 0 and dy > 0 else max(dx, dy)


def _poses(path):
    return {fp.ref: (round(fp.x, 4), round(fp.y, 4), round(fp.rot, 3), fp.side) for fp in load(path).footprints}


# ------------------------------------------------------------------ schema
def test_schema_accepts_and_normalises():
    p = H.validate_pressure({"schema": 1, "source": "t", "parts": {"U1": 1, "R1": 0.5},
                             "pairs": [["U1", "U2", 0.4]]})
    assert p["parts"] == {"U1": 1.0, "R1": 0.5} and p["pairs"] == [["U1", "U2", 0.4]]
    assert H.part_halos(p) == {"U1": 1.2, "R1": 0.5, "U2": 0.2}
    s = H.summary(p)
    assert s["parts_with_halo"] == 3 and s["total_mm"] == pytest.approx(1.9)


@pytest.mark.parametrize("bad", [
    {"parts": {}},                                       # no schema
    {"schema": 2, "parts": {}},
    {"schema": 1, "parts": {"U1": -1}},
    {"schema": 1, "parts": {"U1": "1"}},
    {"schema": 1, "parts": {"U1": float("nan")}},
    {"schema": 1, "parts": []},
    {"schema": 1, "pairs": [["U1", "U1", 1]]},
    {"schema": 1, "pairs": [["U1", 1]]},
    {"schema": 1, "pairs": {"U1": 1}},
    {"schema": 1, "source": 3},
    [],
])
def test_schema_rejects(bad):
    with pytest.raises(H.PressureError):
        H.validate_pressure(bad)


def test_load_pressure(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"schema": 1, "parts": {"U1": 0.3}}))
    assert H.load_pressure(f)["parts"] == {"U1": 0.3}
    f.write_text("{not json")
    with pytest.raises(H.PressureError):
        H.load_pressure(f)


# ------------------------------------------------------------------ fallback producer
def _item(desc, x, y):
    return {"description": desc, "pos": {"x": x, "y": y}, "uuid": "u"}


def test_fallback_one_pitch_per_open_capped():
    b = load(FIXTURE)
    pitch, why = H.routing_pitch(b)
    assert pitch == pytest.approx(0.25 + 0.2)              # Default class: track 0.25 + clearance 0.2
    assert "Default" in why
    one = {"items": [_item("Pad 1 [SIG1] of U1 on F.Cu", 10, 10), _item("Pad 1 [SIG1] of U4 on B.Cu", 10, 25)]}
    two = {"items": [_item("Pad 3 [VCC] of U1 on F.Cu", 11, 10), _item("Track [VCC] on F.Cu, length 2 mm", 12, 12)]}
    p = H.fallback_pressure(b, [one] + [two] * 6)
    H.validate_pressure(p)
    assert p["parts"]["U4"] == pytest.approx(pitch)
    assert p["parts"]["U1"] == pytest.approx(4 * pitch)     # 7 opens, capped at 4 pitches
    assert set(p["parts"]) == {"U1", "U4"} and p["pairs"] == []
    assert H.fallback_pressure(b, [])["parts"] == {}


# ------------------------------------------------------------------ consumer
def test_halo_opens_a_gap_when_space_exists(tmp_path):
    start = _touching(tmp_path)
    assert _gap(start, "U1", "U2") < 0.2
    p = {"schema": 1, "source": "t", "parts": {"U1": 1.0}, "pairs": []}
    out = tmp_path / "out.kicad_pcb"
    rep = H.replace_with_halos(start, p, out, seed=3, time_s=30.0, moves_per_part=400)
    assert rep["legal"] and rep["halos_applied"] == 1 and not rep["relaxed"]
    assert _gap(out, "U1", "U2") >= 1.0 - 1e-6
    d = rep["displacement"]
    assert 0 < d["max_mm"] and d["median_share_diag"] < 0.05    # a revision (U7 starts off the board)


def test_halo_is_a_wish_when_no_space(tmp_path):
    start = _touching(tmp_path)
    p = {"schema": 1, "parts": {"U1": 40.0}}               # bigger than the board: cannot be met
    out = tmp_path / "out.kicad_pcb"
    rep = H.replace_with_halos(start, p, out, seed=3, time_s=30.0, moves_per_part=400)
    if rep["poses"]:
        assert rep["legal"] and rep["relaxed"]             # the halo was dropped, legality kept
    else:
        assert _poses(out) == _poses(start)                # illegal: the start board unchanged
    assert _gap(out, "U1", "U2") >= 0.0


def test_no_pressure_leaves_poses_unchanged(tmp_path):
    start = _touching(tmp_path)
    out = tmp_path / "out.kicad_pcb"
    rep = H.replace_with_halos(start, {"schema": 1, "parts": {}, "pairs": []}, out, seed=3, time_s=30.0)
    assert rep["poses"] == 0 and _poses(out) == _poses(start)
    rep = H.replace_with_halos(start, {"schema": 1, "parts": {"NOPE": 1.0}}, out, seed=3, time_s=30.0)
    assert rep["unknown_refs"] == ["NOPE"] and _poses(out) == _poses(start)


def test_halo_replace_is_seeded(tmp_path):
    start = _touching(tmp_path)
    p = {"schema": 1, "parts": {"U1": 1.0}, "pairs": [["U4", "U5", 0.6]]}
    outs = []
    for k in range(2):
        out = tmp_path / f"out{k}.kicad_pcb"
        H.replace_with_halos(start, p, out, seed=11, time_s=30.0, moves_per_part=400)
        outs.append(_poses(out))
    assert outs[0] == outs[1]


def test_cli_parses_restart_placeholders(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(H, "run", lambda a: seen.update(vars(a)) or {"rounds": []})
    out = tmp_path / "o.kicad_pcb"
    out.write_text("")
    rc = H.main(["--start", "best.kicad_pcb", "--input", "in.kicad_pcb", "-o", str(out), "--time", "120",
                 "--seed", "4", "--rounds", "2"])
    assert rc == 0 and seen["start"] == "best.kicad_pcb" and seen["rounds"] == 2 and seen["time"] == 120.0


def test_rounds_keep_the_better_board_with_fake_stages(tmp_path, monkeypatch):
    """The command line's round logic (pressure, re-place, strip, route, judge, keep) with the
    KiCad stages replaced: the start has 2 opens on U1; the routed result has 1 and is kept."""
    import kae.joint.stages as stages
    from kae.joint.scorecard import Scorecard
    from kae.route import critical_write as W

    start = _touching(tmp_path)
    inp = _copy(tmp_path, "input")
    calls = []
    opens = iter([2, 1, 1])
    unc = [{"items": [_item("Pad 1 [SIG1] of U1 on F.Cu", 10, 10), _item("Pad 1 [SIG1] of U7 on F.Cu", 80, 10)]}]

    class Fake(stages.KaeStages):
        def layout_from(self, board_path):
            calls.append(("layout_from", Path(board_path).name))
            return super().layout_from(board_path)

        def modules(self, lay, it, **kw):
            calls.append(("modules", it))
            return lay

        def route(self, lay, it, seed, time_s, **kw):
            calls.append(("route", it, len(W.routing(lay.board))))
            return lay

        def evaluate(self, lay, it):
            n = next(opens)
            return Scorecard(unconnected=n), {"drc": {"unconnected_items": unc[:n]}}

        def finish(self, lay, output):
            shutil.copy2(lay.board, output)

        def _ensure_brief(self, board):
            return {"nets": {}, "structures": []}

    monkeypatch.setattr(stages, "KaeStages", Fake)
    out = tmp_path / "o" / "out.kicad_pcb"
    import argparse
    a = argparse.Namespace(start=str(start), input=str(inp), output=str(out), time=600.0, seed=1, pressure=None,
                           rounds=2, place_time=20.0, margin=0.0, w_disp=H.W_DISP, lock_refs="", no_modules=False,
                           no_physics=True, workdir=str(tmp_path / "wd"), report=None)
    rep = H.run(a, log=lambda m: None)
    r1 = rep["rounds"][0]
    assert r1["pressure"]["parts_with_halo"] == 2 and r1["legal"] and r1["opens_before"] == 2
    assert r1["opens_after"] == 1 and r1["kept"]
    assert {"pressure", "replace", "modules", "route", "evaluate"} <= set(r1["seconds"])
    assert ("route", 0, 0) in calls                           # routed from bare placement
    assert rep["final_card"]["unconnected"] == 1 and out.exists() and out.with_suffix(".kicad_pro").exists()
    assert len(rep["rounds"]) == 2 and not rep["rounds"][1]["kept"]   # 1 -> 1: not better
