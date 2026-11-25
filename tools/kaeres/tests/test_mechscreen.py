# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""mechscreen: board lists, the netrules screen on a synthetic board (no KiCad), the summary."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "kae" / "src"))
import mechscreen as M  # noqa: E402


def pad(ref, num, net, x, y, w=0.3, layers=("F.Cu",)):
    r = [[x - w / 2, y - w / 2], [x + w / 2, y - w / 2], [x + w / 2, y + w / 2], [x - w / 2, y + w / 2]]
    return dict(ref=ref, number=num, net=net, pos=[x, y], layers=list(layers), poly=[[r]], uuid=f"{ref}.{num}", lib="x:y")


class FakeCtx:
    def __init__(self, info, dru):
        self.info, self.dru, self.source, self.bid = info, dru, "test", "fake"


def test_read_ids(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# c\nb1\nb2 extra\n\nb1\n")
    assert M.read_ids([f"@{f}", "b3,b2"]) == ["b1", "b2", "b3"]


def test_netrules_counts_stricter_pairs_near_enough():
    try:
        import kae.board.dru_cond  # noqa: F401
    except ImportError:
        try:
            M.variant_module(M.NETRULES_COMMIT, "kae/board/dru_cond.py", "kae.board.dru_cond")
        except Exception:
            pytest.skip("dru_cond not available (commit not in this clone)")
    info = dict(netclasses={"Default": dict(clearance=0.2)},
                nets={n: dict(netclass="Default") for n in ("HV", "LV", "GND")},
                pads=[pad("U1", "1", "HV", 0.0, 0.0), pad("U1", "2", "LV", 0.8, 0.0),   # gap 0.5 < 1.0
                      pad("U1", "3", "GND", 0.0, 3.0),                                    # gap 2.7: too far
                      pad("U2", "1", "LV", 0.0, -1.6)],                                   # gap 1.3 < 1.5: near
                settings={})
    dru = [dict(name="hv", condition="A.NetName == 'HV' && B.NetName != 'GND'", layer="",
                constraints=[dict(type="clearance", min=1.0)])]
    r = M.screen_netrules(FakeCtx(info, dru))
    assert r["count"] == 2 and r["tight"] == 1 and r["rules"] == 1 and r["net_pairs"] == 1
    # a rule looser than the net class is not counted
    dru[0]["constraints"][0]["min"] = 0.1
    assert M.screen_netrules(FakeCtx(info, dru))["count"] == 0


def test_top_summary(tmp_path, capsys):
    f = tmp_path / "s.jsonl"
    rows = [dict(board=f"b{i}", screen="x", count=c, examples=[]) for i, c in enumerate([0, 0, 5, 1])]
    rows.append(dict(board="bad", screen="x", error="boom"))
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    M.top([f])
    out = capsys.readouterr().out
    assert "5 boards, 1 errors, 2 with count > 0, total 6" in out and "b2" in out
