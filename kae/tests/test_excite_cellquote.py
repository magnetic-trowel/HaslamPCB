# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.excite.cellquote: the cell window alone ranks two layouts of one cell as the evaluator does."""
import math

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


def test_a_non_physical_quote_gives_no_score():
    ok = dict(source="a", state="ok", L_nH=1.0, R_mohm=5.0)
    assert CQ.score([ok]) == round(math.log(5.0), 4)
    assert CQ.score([ok, dict(source="b", state="invalid")]) is None
    assert CQ.score([ok, dict(source="b", state="open")]) > CQ.score([ok, dict(ok, source="b")])


def test_the_quote_takes_the_evaluators_l_and_r_through_a_cap_resonance(tmp_path, monkeypatch):
    """The multi-cap fixture of test_excite_hotloop (a 150 nF cap at U1's pins beside C1): the quote's L_loop is
    the evaluator's (stored energy with the caps at ESR + ESL), so it is positive and agrees with the evaluator's
    raw window at the same pitch; R likewise (the copper's dissipation). With the layout's share Im z / w the
    quote read a negative L there and the cells stage would have ranked layouts by a value the evaluator never
    scores."""
    from kae.excite import models as M
    from kae.excite.evaluate import evaluate
    build = M.build

    def with_cap(b, brief):
        bd = build(b, brief)
        bd.circuit.z("Cx", "GND", "VIN", M._rlc(0.005, 0.3e-9, 150e-9), pa="U1.4", pb="U1.3", kind="C")
        return bd
    monkeypatch.setattr(M, "build", with_cap)
    q = _q(tmp_path, "closed", monkeypatch)
    p = write_hotloop_board(tmp_path / "ev", "closed")
    ev = evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125,
                  scope="losses")
    (c,) = [r for r in ev["cells"] if r["source"] == CELL]
    assert q["state"] == "ok" and c["state"] == "ok"
    assert q["L_nH"] > 0
    assert math.isclose(q["L_nH"], c["window"]["L_raw_nH"], rel_tol=0.02, abs_tol=0.005)
    assert math.isclose(q["R_mohm"], c["window"]["R_raw_mohm"], rel_tol=0.02, abs_tol=0.01)
