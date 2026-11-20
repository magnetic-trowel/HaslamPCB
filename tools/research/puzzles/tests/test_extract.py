# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Puzzle extractor tests on a synthetic board (no KiCad needed)."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extract as X  # noqa: E402

BOARD = """(kicad_pcb (version 20240108) (generator "test")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
  (net 1 "A")
  (net 2 "B")
  (net 3 "T")
  (net 4 "S")
  (footprint "R" (layer "F.Cu") (at 10 10 90)
    (property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -1 0) (size 0.8 0.8) (layers "F.Cu") (net 2 "B"))
    (pad "2" smd rect (at 1 0) (size 0.8 0.8) (layers "F.Cu") (net 1 "A")))
  (footprint "R" (layer "F.Cu") (at 14 10 0)
    (property "Reference" "R2" (at 0 0 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -1 0) (size 0.8 0.8) (layers "F.Cu") (net 2 "B"))
    (pad "2" smd rect (at 1 0) (size 0.8 0.8) (layers "F.Cu") (net 4 "S")))
  (footprint "R" (layer "F.Cu") (at 40 40 0)
    (property "Reference" "R3" (at 0 0 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -1 0) (size 0.8 0.8) (layers "F.Cu") (net 1 "A"))
    (pad "2" smd rect (at 1 0) (size 0.8 0.8) (layers "F.Cu") (net 0 "")))
  (gr_rect (start 0 0) (end 50 50) (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts") (uuid "e"))
  (segment (start 10 9) (end 10 5) (width 0.25) (layer "F.Cu") (net 1) (uuid "s1"))
  (segment (start 10 5) (end 39 5) (width 0.25) (layer "F.Cu") (net 1) (uuid "s2"))
  (segment (start 39 5) (end 39 40) (width 0.25) (layer "F.Cu") (net 1) (uuid "s3"))
  (segment (start 10 11) (end 13 11) (width 0.25) (layer "F.Cu") (net 2) (uuid "s4"))
  (segment (start 13 11) (end 13 10) (width 0.25) (layer "F.Cu") (net 2) (uuid "s5"))
  (via (at 12 11) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 2) (uuid "v1"))
  (segment (start 0 20) (end 50 20) (width 0.25) (layer "B.Cu") (net 3) (uuid "s6"))
  (segment (start 15 10) (end 15 30) (width 0.25) (layer "F.Cu") (net 4) (uuid "s7"))
  (segment (start 15 30) (end 15 10.5) (width 0.25) (layer "B.Cu") (net 4) (uuid "s8"))
)
"""
WIN = (6.0, 6.0, 20.0, 25.0)


@pytest.fixture
def board():
    return X.Board(BOARD)


def test_reads_pads_rotated(board):
    r1 = next(f for f in board.footprints if f["ref"] == "R1")
    p = {pd["num"]: pd["p"] for pd in r1["pads"]}
    assert p["1"] == pytest.approx((10, 11))   # (-1, 0) rotated 90 deg in KiCad's y-down frame
    assert p["2"] == pytest.approx((10, 9))


def test_clip_segment():
    assert X.clip_segment((0, 0), (10, 0), (2, -1, 5, 1)) == ((2, 0), (5, 0))
    assert X.clip_segment((0, 5), (10, 5), (2, -1, 5, 1)) is None


def test_arc_points_semicircle():
    pts = X.arc_points((1, 0), (0, 1), (-1, 0), 8)
    assert pts[0] == pytest.approx((1, 0)) and pts[-1] == pytest.approx((-1, 0))
    assert all(math.hypot(*p) == pytest.approx(1) for p in pts)
    assert any(p[1] > 0.9 for p in pts)


def test_extract_terminals_and_kinds(board, tmp_path):
    pz, sol, meta = X.extract(board, WIN, "synthetic", tier="test", label="rect")
    assert sorted(meta["footprints"]) == ["R1", "R2"]
    nets = meta["nets"]
    # A leaves the window at y=6 (one terminal on F.Cu); its pad on R3 is not in the puzzle
    assert nets["A"]["kind"] == "crossing" and len(nets["A"]["terminals"]) == 1
    t = nets["A"]["terminals"][0]
    assert t["p"] == pytest.approx([10, 6]) and t["layer"] == "F.Cu"
    assert nets["B"]["kind"] == "inside" and nets["B"]["human_vias"] == 1
    assert nets["B"]["human_len"] == pytest.approx(4.0)
    assert nets["T"]["kind"] == "through" and len(nets["T"]["terminals"]) == 2
    # S leaves on F.Cu and comes back on B.Cu, ending next to the F.Cu-only pad: the human
    # copper inside is two pieces joined outside the window
    assert len(nets["S"]["terminals"]) == 2 and nets["S"]["plant_components"] == 2
    assert meta["totals"]["outside_links"] == 1
    assert "segment" not in pz.split("(gr_rect")[0]
    assert pz.count("(locked yes)") == meta["totals"]["terminals"]
    assert "R3" not in pz and "(net 1 \"A\")" in pz
    assert pz.count('(layer "Edge.Cuts")') == 1 and "(start 0 0)" not in pz
    X.write_puzzle(tmp_path, pz, sol, meta)
    v = X.verify(tmp_path)
    assert v["structural_ok"], v["problems"]
    assert json.loads((tmp_path / "puzzle.json").read_text())["tier"] == "test"


def test_through_drop(board):
    _, _, meta = X.extract(board, WIN, through="drop")
    assert "T" not in meta["nets"]


def test_score_solution_and_puzzle(board, tmp_path):
    pz, sol, meta = X.extract(board, WIN)
    X.write_puzzle(tmp_path, pz, sol, meta)
    s = X.score(tmp_path / "solution.kicad_pcb", tmp_path, use_kicad=False)
    assert s["solved"] and s["length_ratio"] == pytest.approx(1.0) and s["via_ratio"] == pytest.approx(1.0)
    p = X.score(tmp_path / "puzzle.kicad_pcb", tmp_path, use_kicad=False)
    assert not p["solved"] and "B" in p["open_nets"]


def test_verify_catches_broken_plant(board, tmp_path):
    pz, sol, meta = X.extract(board, WIN)
    sol = sol.replace("(via (at 12", "(via (at 30")  # move B's via away: B stays joined by tracks
    sol = "\n".join(l for l in sol.splitlines() if "(start 13" not in l)  # cut B
    X.write_puzzle(tmp_path, pz, sol, meta)
    v = X.verify(tmp_path)
    assert not v["structural_ok"] and any(p.startswith("B:") for p in v["problems"])


def test_window_grows_to_whole_footprints(board):
    _, _, meta = X.extract(board, (9.8, 8, 13.2, 12))  # cuts R2 in half
    r = meta["rect"]
    assert r[0] <= 9.6 and r[2] >= 15.4


def test_auto_and_around(board):
    w = X.window_around(board, "R2", 1.0)
    assert w[0] == pytest.approx(11.6) and w[2] == pytest.approx(16.4)
    assert X.auto_windows(board, "ic") == []


@pytest.mark.skipif(not __import__("os").environ.get("KAE_KICAD_WRAP"), reason="needs KiCad ($KAE_KICAD_WRAP)")
def test_kicad_reads_puzzle_and_solution(board, tmp_path):
    pz, sol, meta = X.extract(board, WIN)
    X.write_puzzle(tmp_path, pz, sol, meta)
    v = X.verify(tmp_path, drc=True)
    assert v["drc"] and "error" not in v["drc"], v
    # S's two pieces meet at one point on two layers; kicad-cli calls them joined there, the
    # union-find does not (see README, known limits), so only the other nets are checked here.
    assert v["drc"]["unconnected"] <= meta["totals"]["outside_links"], v["drc"]
    s = X.score(tmp_path / "puzzle.kicad_pcb", tmp_path)
    assert s["drc"]["unconnected"] > meta["totals"]["outside_links"] and not s["solved"]
