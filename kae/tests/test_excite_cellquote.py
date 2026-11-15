# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.excite.cellquote: the cell window alone ranks two layouts of one cell as the evaluator does."""
from hotloop_fixtures import plane_fills, write_hotloop_board
from kae.excite import cellquote as CQ

CELL = "cell:cell:buck:U1"


def _q(tmp_path, variant, monkeypatch):
    import kae.route.critical_recheck as CRR
    monkeypatch.setattr(CRR, "fills_of", lambda p: plane_fills())
    p = write_hotloop_board(tmp_path / variant, variant)
    (r,) = [r for r in CQ.quote_cells(str(p), pitch=0.125, log=lambda *a: None) if r["source"] == CELL]
    return r


def test_the_quote_ranks_a_longer_loop_worse_and_an_open_one_open(tmp_path, monkeypatch):
    a, b, c = (_q(tmp_path, v, monkeypatch) for v in ("closed", "long", "open"))
    assert a["state"] == b["state"] == "ok" and c["state"] == "open"
    assert b["L_nH"] > a["L_nH"] > 0 and b["R_mohm"] > a["R_mohm"] > 0
    verdict, total = CQ.compare([a], [b])
    assert verdict[CELL] == -1 and total < 0          # a (closed) is the better layout
    assert CQ.compare([b], [c])[0][CELL] == -1        # an open cell loses to any closed one
