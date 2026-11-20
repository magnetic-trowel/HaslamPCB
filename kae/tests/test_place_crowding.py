# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pad crowding (tools/research/place/crowding.py): other parts' pads within 2 mm of each pad."""
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from place_terms_fixtures import board, cap0402

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "research" / "place" / "crowding.py"
FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="tools/research/place not present")


def _mod():
    spec = importlib.util.spec_from_file_location("crowding", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_counts_other_parts_pads_on_the_same_side_within_the_radius():
    C = _mod()
    # 0402 pads sit 0.5 mm either side of the part's centre
    a = cap0402("C1", "A", "GND", 10.0, 10.0)                  # pads at x 9.5 and 10.5
    b = cap0402("C2", "A", "GND", 12.0, 10.0)                  # pads at x 11.5 and 12.5
    far = cap0402("C3", "A", "GND", 40.0, 30.0)
    back = cap0402("C4", "A", "GND", 10.0, 10.0, side="B")     # under C1, on the other side
    pts = C.pad_points(board([a, b, far, back]))
    assert sorted(p[0] for p in pts if p[3] == 0) == [9.5, 10.5]
    # C1: 9.5 sees no pad of C2 nearer than 2 mm (11.5 is exactly 2.0 away); 10.5 sees 11.5 only.
    # C2: 11.5 sees 10.5 only (9.5 is exactly 2.0 away); 12.5 sees neither. A part's own pads never count.
    assert C.neighbour_counts(pts) == [0, 1, 1, 0, 0, 0, 0, 0]
    assert C.neighbour_counts(pts, radius=2.01) == [1, 2, 2, 1, 0, 0, 0, 0]
    r = C.crowding(board([a, b, far, back]))
    assert r == dict(pads=8, radius_mm=2.0, mean=0.25, p50=0, p90=1, share_any=0.25)
    # a rotated part's pads are counted where they are on the board
    turned = cap0402("C2", "A", "GND", 10.0, 11.0, rot=90.0)   # pads at (10, 10.5) and (10, 11.5)
    assert C.neighbour_counts(C.pad_points(board([a, turned]))) == [2, 2, 2, 2]
    assert C.crowding(board([]))["pads"] == 0 and C.crowding(board([]))["mean"] is None


def test_cli_reads_plain_and_gzipped_boards(tmp_path, capsys):
    C = _mod()
    gz = tmp_path / "output.kicad_pcb.gz"
    gz.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    out = tmp_path / "rows.json"
    assert C.main([f"plain={FIXTURE}", f"packed={gz}", "--out", str(out)]) == 0
    rows = json.loads(out.read_text())
    assert rows["plain"] == rows["packed"] and rows["plain"]["pads"] == 28 and rows["plain"]["mean"] == 0.0
    assert "plain: pads" in capsys.readouterr().out
    assert C.main([str(tmp_path / "missing.kicad_pcb")]) == 1
