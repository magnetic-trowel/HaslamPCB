# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A bad relation in the board's own intent file drops only the relations (obd-solar FRICTION #58): the facts and
terms still reach the brief and the placer's physics; the relation error is still reported."""
import json

import pytest

from circuit_fixtures import board, buck_board

from haslam.intent import facts as F
from haslam.intent.objective import IntentError, load

FACTS = {"nets": {"+12V": {"V_V": 14.0, "why": "bench supply"}}}
GOOD = {"id": "near-C1-U1", "kind": "near", "a": "C1", "b": "U1", "mag": "tight", "why": "hot loop"}


def _doc(relations):
    return {"schema": "haslam.intent/1", "facts": FACTS, "relations": relations}


def _with_sidecar(tmp_path, doc):
    b = board(buck_board())
    b.path = str(tmp_path / "b.kicad_pcb")
    (tmp_path / "b.haslam_intent.json").write_text(json.dumps(doc))
    return b


@pytest.mark.parametrize("rels", [[GOOD, dict(GOOD)],                               # a duplicate id
                                  [dict(GOOD, frobnicate=1)],                       # an unknown argument
                                  [dict(GOOD, kind="nearish")]])                    # an unknown kind
def test_lenient_load_drops_only_the_relations(rels):
    with pytest.raises(IntentError):
        load(_doc(rels))                                          # authoring tools stay strict
    it = load(_doc(rels), relations_strict=False)
    assert it["relations"] == [] and it["relations_error"] and it["facts"] == FACTS


def test_good_relations_load_the_same_either_way():
    assert load(_doc([GOOD]), relations_strict=False) == load(_doc([GOOD]))
    assert "relations_error" not in load(_doc([GOOD]), relations_strict=False)


def test_bad_relation_keeps_facts_and_physics_in_the_brief(tmp_path):
    from haslam.circuit.brief import build
    from haslam.place.relations import from_brief
    b = _with_sidecar(tmp_path, _doc([GOOD, dict(GOOD)]))
    doc, _ = F.for_board(b.path)
    assert doc["facts"] == FACTS and "relations_error" in doc
    br = build(b)                                                 # raised IntentError before the fix
    assert br["nets"]["+12V"]["volts"] == 14.0                    # the stated fact reached the brief
    assert any(s["kind"] == "commutation_cell" for s in br["structures"])
    assert "error" in br["relations"]                             # and the relation error is still carried
    bundle, err = from_brief(b, br, b.path)
    assert bundle is None and "near-C1-U1" in err


def test_placer_keeps_its_physics_terms_with_a_bad_relation(tmp_path):
    from haslam.place.stubs import make_brief, make_terms
    b = _with_sidecar(tmp_path, _doc([GOOD, dict(GOOD)]))
    br, src = make_brief(b)
    assert src == "haslam.circuit.brief"
    terms, _ = make_terms(b, br)
    assert terms is not None and any(s.kind == "commutation" for s in terms.structs)
