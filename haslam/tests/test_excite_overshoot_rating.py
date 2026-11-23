# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A cell's overshoot observer is referenced to its switch's rating stated in the operating facts, for every cell
class (the new inverting, dual-rail, inverting-buck and external-FET cells too). A part-table rating (duanestorey's
LMR51430, 38 V, SLUSEF4A) reaches the per-corner bounds but leaves the observer's reference as it was
(haslam.excite.observe.rate_overshoot: the corpus boards' outputs stay unchanged)."""
import pytest

import critical_fixtures as CF
from hotloop_fixtures import write_extbb_board, write_inverting_board
from haslam.board.kicad_file import load
from haslam.circuit.brief import build
from haslam.excite import models as M
from haslam.excite import observe as O
from haslam.excite import sources as S
from haslam.excite.evaluate import ledger_for
from haslam.physics import criteria as CR


def _rated(path, intent, env, monkeypatch):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    b = load(str(path))
    br = build(b, inverting=True)
    bd = M.build(b, br)
    srcs = S.add_all(bd, br)
    obs = O.observers(bd, br, srcs)
    P, _ = ledger_for(bd, br, srcs, intent)
    O.rate_overshoot(obs, P)
    return {o.meta["source"]: o for o in obs if o.kind == "overshoot"}, P


def test_a_part_tables_rating_reaches_an_inverting_cells_ledger_not_its_reference(tmp_path, monkeypatch):
    obs, P = _rated(write_inverting_board(tmp_path, "ground"), None, {}, monkeypatch)
    o = obs["cell:cell:inverting:U1"]
    vm = P["cell:cell:inverting:U1"]["V_max"]
    assert vm.typ == pytest.approx(38.0) and vm.source == "part_table"
    assert o.src_class == "prior"


def _parts(base, mapping, value, extra=()):
    out = []
    for ref, val, lib, x, y, rot, pads, cy in base:
        pads = [(n, *(mapping[(ref, n)][:1]), lx, ly, w, h, kind, drill, mapping[(ref, n)][1] or fn, mapping[(ref, n)][2])
                if (ref, n) in mapping else (n, net, lx, ly, w, h, kind, drill, fn, pt)
                for n, net, lx, ly, w, h, kind, drill, fn, pt in pads]
        out.append((ref, value if ref == "U1" else val, lib, x, y, rot, pads, cy))
    return out + list(extra)


@pytest.mark.parametrize("cls", ["dualrail", "invbuck", "extbb"])
def test_the_operating_facts_rating_references_every_new_cell_class(cls, tmp_path, monkeypatch):
    from test_circuit_inverting import DUAL, FLY, INV_BUCK
    env = {"extbb": {"HASLAM_CELLS_EXTBB": "1"}}.get(cls, {})
    if cls == "extbb":
        p = write_extbb_board(tmp_path)
        cid = "cell:boost:U1"
    else:
        mapping, value, extra = (DUAL, "XYZ65133", ()) if cls == "dualrail" else (INV_BUCK, "XYZ63710", (FLY,))
        monkeypatch.setattr(CF, "PARTS", _parts(CF.PARTS, mapping, value, extra))
        p = CF.write_board(tmp_path)
        cid = "cell:inverting:U1"
    intent = {"cells": {cid: {"v_sw_max_V": 40.0}}}
    obs, P = _rated(p, intent, env, monkeypatch)
    o = obs[f"cell:{cid}"]
    assert o.src_class == "intent" and o.bound == pytest.approx(CR.overshoot_limits(P[f"cell:{cid}"]["V"].typ, 40.0)[0])
