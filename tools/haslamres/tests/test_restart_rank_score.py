# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""restart.py --rank-score: attempts of equal KiCad rank ranked by a physics score (obd-solar FRICTION #55: restarts
ranked by KiCad alone; worst_rail_mohm computed and unused)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import restart  # noqa: E402


def _a(**kw):
    d = dict(alt_env="", tiebreak="", tiebreak_margin=0.1, rank_score="score", rank_score_margin=0.05,
             rank_score_s=60.0, rank_wait=False)
    d.update(kw)
    return argparse.Namespace(**d)


def _info(k, rank):
    return dict(k=k, rank=list(rank), out=f"/tmp/a{k}/out.kicad_pcb")


def test_score_decides():
    assert restart.score_decides([100.0, 3.0], [80.0, 9.0], 0.05) == (True, True)      # the rail decides first
    assert restart.score_decides([100.0, 3.0], [102.0, 2.0], 0.05) == (True, True)     # within margin: the cells
    assert restart.score_decides([100.0, 3.0], [102.0, 3.05], 0.05) == (False, False)
    assert restart.score_decides([None, 3.0], [50.0, 4.0], 0.05) == (True, False)      # a null element is skipped
    assert restart.score_decides(None, [1.0], 0.05) == (False, False)


def test_equal_rank_goes_to_the_score(monkeypatch):
    scores = {0: [120.0, 5.0], 1: [60.0, 5.0], 2: None}
    monkeypatch.setattr(restart, "rank_score", lambda a, info, cache: scores[info["k"]])
    best, ties = _info(0, (0, 0, 3, 2, 0)), []
    assert restart.better(_a(), _info(1, (0, 0, 3, 2, 0)), best, {}, ties)
    assert ties[-1]["by"] == "rank_score" and ties[-1]["switched"]
    assert not restart.better(_a(), _info(2, (0, 0, 3, 2, 0)), best, {}, ties)         # unmeasured: the incumbent
    # KiCad rank still comes first
    assert restart.better(_a(), _info(2, (0, 0, 2, 9, 0)), best, {}, ties)
    assert not restart.better(_a(), _info(1, (0, 0, 4, 0, 0)), best, {}, ties)
    # off without the option
    assert not restart.better(_a(rank_score=""), _info(1, (0, 0, 3, 2, 0)), best, {}, [])
