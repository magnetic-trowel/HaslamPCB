# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""perturb.py on the kae fixture board: routing stripped, a seeded share of small parts moved, nothing overlapping."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).parent), str(ROOT / "kae" / "src")]

import perturb as PT                     # noqa: E402
from kae.board.kicad_file import load    # noqa: E402

FIXTURE = ROOT / "kae" / "tests" / "data" / "board" / "fixture.kicad_pcb"


def _run(tmp_path, capsys, *args):
    out = tmp_path / "out.kicad_pcb"
    assert PT.main([str(FIXTURE), str(out), *args]) == 0
    return out, json.loads(capsys.readouterr().out)


def test_moves_a_seeded_share_by_the_distance_and_strips_routing(tmp_path, capsys):
    out, rep = _run(tmp_path, capsys, "--distance", "0.5", "--share", "0.5", "--seed", "3")
    text = out.read_text()
    assert "(segment" not in text and "(via " not in text and "filled_polygon" not in text
    before = {fp.ref: fp for fp in load(str(FIXTURE), rules=False).footprints}
    after = {fp.ref: fp for fp in load(str(out), rules=False).footprints}
    assert rep["moved"]
    for ref, dx, dy in rep["moved"]:
        assert len(before[ref].pads) <= 4 and not before[ref].locked
        assert abs((dx * dx + dy * dy) ** 0.5 - 0.5) < 1e-6
        assert abs(after[ref].x - before[ref].x - dx) < 1e-4 and abs(after[ref].y - before[ref].y - dy) < 1e-4
    still = set(before) - {r for r, _, _ in rep["moved"]}
    assert all(abs(after[r].x - before[r].x) < 1e-9 and abs(after[r].y - before[r].y) < 1e-9 for r in still)
    _, again = _run(tmp_path, capsys, "--distance", "0.5", "--share", "0.5", "--seed", "3")
    assert again == rep


def test_moved_parts_do_not_overlap_others(tmp_path, capsys):
    out, rep = _run(tmp_path, capsys, "--distance", "1.0", "--share", "1.0", "--seed", "1")
    shapes = {fp.ref: PT.footprint_shape(fp) for fp in load(str(out), rules=False).footprints}
    base = {fp.ref: PT.footprint_shape(fp) for fp in load(str(FIXTURE), rules=False).footprints}
    assert len(rep["moved"]) >= 5
    for ref, _, _ in rep["moved"]:
        for other, s in shapes.items():
            if other != ref and not PT._hits(base[ref], base[other]):
                assert not PT._hits(shapes[ref], s)


def test_all_moves_every_unlocked_part_by_one_vector(tmp_path, capsys):
    _, rep = _run(tmp_path, capsys, "--distance", "0.2", "--all", "--seed", "2")
    vecs = {(dx, dy) for _, dx, dy in rep["moved"]}
    assert rep["all"] and len(vecs) == 1 and not rep["kept"]
    assert len(rep["moved"]) == sum(1 for fp in load(str(FIXTURE), rules=False).footprints
                                    if not fp.locked and fp.on_board)
