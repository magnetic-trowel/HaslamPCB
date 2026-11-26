# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.place.springs: served-pin springs for 2-pad passives (opt-in, place_passive_springs)."""
from pathlib import Path

from haslam.board import kicad_file
from haslam.circuit.brief import build
from haslam.place import springs
from haslam.place.pipeline import place
from haslam.place.problem import Problem

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _problem():
    b = kicad_file.load(FIXTURE)
    br = build(b)
    P = Problem.build(b)
    for p in P.parts:
        p.kind = (br["parts"].get(p.uuid) or {}).get("kind", "")
    return b, br, P


def test_springs_tie_passive_to_served_pin():
    _, br, P = _problem()
    s = springs.served_springs(P, br, base=1.0, cells={})
    assert s, "the fixture's pull-down gets a spring"
    for (i, k, j, q, w, role) in s:
        a, c = P.parts[i], P.parts[j]
        assert a.kind in springs.PASSIVE and c.kind not in springs.PASSIVE
        assert a.fp.pads[k].net == c.fp.pads[q].net          # the spring joins two pads of one net
        assert w == 1.0 and role in springs.ROLES
    n0 = len(P.nets)
    idx = springs.add_springs(P, s)
    assert idx == list(range(n0, n0 + len(s)))
    assert all(P.nets[j].kind == "spring" and len(P.nets[j].pins) == 2 for j in idx)


def test_exclude_and_roles():
    _, br, P = _problem()
    s = springs.served_springs(P, br, base=1.0, cells={})
    assert springs.served_springs(P, br, base=1.0, cells={}, exclude={x[0] for x in s}) == []
    assert springs.served_springs(P, br, base=1.0, cells={}, roles=("decoupling",)) == [
        x for x in s if x[5] == "decoupling"]


def test_weight_from_prior_cell():
    cells = {"pull_up|0402|2": {"d": {"p50": 1.5}}, "pull_up": {"d": {"p50": 6.0}}, "led_resistor": {"d": {"p50": 60.0}}}
    assert springs.weight(cells, "pull_up", "0402", 2, 1.0) == 2.0        # 3 / 1.5
    assert springs.weight(cells, "pull_up", "0603", 4, 1.0) == 0.5        # backs off to the role
    assert springs.weight(cells, "led_resistor", "0603", 2, 2.0) == 0.5   # clamped at 0.25 x base
    assert springs.weight(cells, "divider", "0603", 2, 1.5) == 1.5        # no cell: the base


def test_shipped_priors_load():
    cells = springs.priors()
    assert cells, "place/data/passive_priors.json ships with the package"
    assert all("d" in c and "p50" in c["d"] for c in cells.values())


def test_place_with_springs_is_legal(tmp_path):
    b = kicad_file.load(FIXTURE)
    res = place(b, seed=0, time_s=20, opts={"place_passive_springs": 1.0})
    rep = res.report
    assert rep["passive_springs"]["springs"] >= 1 and rep["passive_springs"]["base"] == 1.0
    assert rep["legal_grid"] and not rep.get("exact")
    res0 = place(kicad_file.load(FIXTURE), seed=0, time_s=20)
    assert "passive_springs" not in res0.report       # off by default
