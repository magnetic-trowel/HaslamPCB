# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""cut_rank.py statistics on hand-made rows: duplicates merged, Spearman, concordance, report."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import cut_rank as CR    # noqa: E402


def _row(board, run, opens, ovfK, hpwl, npad=100, layers=2):
    return dict(board=board, run=run, opens=opens, ovfK=ovfK, ovf0=ovfK * 2, hpwl=hpwl, rudy=1.0 + 0.1 * run,
                crowd=1.0, npad=npad, layers=layers)


def test_identical_placements_merge_and_give_the_noise_floor():
    rows = [_row("b", 0, 4, 1, 10), dict(_row("b", 0, 6, 1, 10), run=1), _row("b", 2, 9, 3, 12)]
    pl, sds = CR.dedupe(rows)
    assert len(pl) == 2 and sorted(p["opens"] for p in pl) == [5, 9]
    assert sds == [2 ** 0.5]


def test_concordance_counts_measure_ties_as_half():
    pl = [dict(opens=1, m=1), dict(opens=2, m=2), dict(opens=3, m=2)]
    assert CR.concordance(pl, "m") == (2, 0, 1)


def test_report_on_a_perfectly_ranking_measure(tmp_path):
    rows = []
    for b in range(5):
        for k in range(5):
            rows.append(_row(f"b{b}", k, opens=k, ovfK=k, hpwl=10 - k, npad=100 + 200 * b))
    p = tmp_path / "x.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    res = CR.analyse(str(p))
    assert res["boards"] == 5
    assert res["all"]["ovfK"]["median"] == pytest.approx(1.0)
    assert res["all"]["hpwl"]["median"] == pytest.approx(-1.0)
    assert res["all"]["ovfK"]["concordance"] == 1.0
    assert set(res["band"]) == {"<=150", "150-400", "400-1500"}
    assert "ovfK: median 1.00" in CR.report_md(res, "x")
