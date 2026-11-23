# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/research/physics/board_summary.py, the board description the operating facts are written from: it lists
every inductor (an inverter's output filter L2 was folded into the passives' count, so no fact could name it) and
reads the board as the evaluator does (its inverting cells)."""
import importlib.util

import pytest
from pathlib import Path

from hotloop_fixtures import write_inverting_board

ROOT = Path(__file__).resolve().parents[2]


def _summary():
    spec = importlib.util.spec_from_file_location("board_summary", ROOT / "tools/research/physics/board_summary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.summarize


def test_every_inductor_is_listed_and_the_inverter_is_a_section(tmp_path, monkeypatch):
    monkeypatch.delenv("HASLAM_CELLS_INVERTING", raising=False)
    out = _summary()(str(write_inverting_board(tmp_path, "ground")))
    refs = {p["ref"]: p for p in out["parts"]}
    assert "L1" in refs and "inductor" not in out["passives_without_structure"]
    assert any("cell:inverting:U1" in s["id"] for s in out["sections"])


def test_an_inductor_outside_every_structure_is_listed(tmp_path):
    import critical_fixtures as CF
    l9 = ("L9", "1uH", "Inductor_SMD:L_0805_2012Metric", 135.0, 120.0, 0.0,
          [("1", "+3V3", -0.95, 0.0, 1.0, 1.45, "smd", 0.0, "", "passive"),
           ("2", "+3V3_F", 0.95, 0.0, 1.0, 1.45, "smd", 0.0, "", "passive")], (1.7, 1.0))
    out = _summary()(str(CF.write_board(tmp_path, extra=[l9])))
    assert "L9" in {p["ref"] for p in out["parts"]}


def test_a_sections_parts_are_all_listed(tmp_path, monkeypatch):
    """An inverter cell with eleven parts (mecsem's hvdc board) lost its controller U21: the list was cut at ten
    and U21 sorts after C1xx."""
    from types import SimpleNamespace

    import critical_fixtures as CF
    from haslam.intent import sections as SE
    parts = {f"C{100 + k}" for k in range(10)} | {"U21"}
    monkeypatch.setattr(SE, "from_brief", lambda br: {"s": SimpleNamespace(id="cell:inverting:U21",
                                                                            kind="commutation_cell", parts=parts, nets=set())})
    out = _summary()(str(CF.write_board(tmp_path)))
    assert set(out["sections"][0]["parts"]) == parts


def test_the_summary_and_the_brief_find_the_same_cells_on_a_board_without_pin_names(tmp_path, monkeypatch):
    """A board whose footprints carry no pin functions (meshsat's a-power board: its bucks have only their nodes'
    names): the summary's sections are the brief's cells (an older summary showed none where the brief had five)."""
    import critical_fixtures as CF
    from haslam.board.kicad_file import load
    from haslam.circuit.brief import build
    from test_circuit_cells_channels import BOOT
    parts = [(ref, val, lib, x, y, rot,
              [(n, net, lx, ly, w, h, kind, drill, "" if ref == "U1" else fn, "" if ref == "U1" else pt)
               for n, net, lx, ly, w, h, kind, drill, fn, pt in pads], cy)
             for ref, val, lib, x, y, rot, pads, cy in CF.PARTS]
    monkeypatch.setattr(CF, "PARTS", parts + [BOOT])
    monkeypatch.delenv("HASLAM_CELLS_INVERTING", raising=False)
    p = str(CF.write_board(tmp_path))
    cells = sorted(s["id"] for s in build(load(p), inverting=True)["structures"] if s["kind"] == "commutation_cell")
    out = _summary()(p)
    assert cells == ["cell:buck:U1"]
    assert sorted(s["id"] for s in out["sections"] if s["kind"] == "commutation_cell") == cells


def _stripped(extra=(), rename=None, drop=()):
    import critical_fixtures as CF
    rename = rename or {}
    return [(ref, val, lib, x, y, rot,
             [(n, rename.get(net, net), lx, ly, w, h, kind, drill, "" if ref == "U1" else fn, "" if ref == "U1" else pt)
              for n, net, lx, ly, w, h, kind, drill, fn, pt in pads], cy)
            for ref, val, lib, x, y, rot, pads, cy in CF.PARTS if ref not in drop] + list(extra)


def test_pin_names_that_are_their_nets_labels_count_as_none(tmp_path, monkeypatch):
    """Pin facts read off a schematic's net labels name every pin after its own net ('SW', 'VIN', 'GND', all typed
    passive): read as pin functions they hid the switcher from the rule for unannotated pins (meshsat's AP64500s
    and e1-dock's AP63205 lost their cells with the facts' pintypes applied)."""
    import critical_fixtures as CF
    from haslam.board.kicad_file import load
    from haslam.circuit.brief import build
    from test_circuit_cells_channels import BOOT
    parts = _stripped([BOOT])
    labelled = []
    for ref, val, lib, x, y, rot, pads, cy in parts:
        if ref == "U1":
            pads = [(n, net, lx, ly, w, h, kind, drill, net.lstrip("/") if net else "", "passive")
                    for n, net, lx, ly, w, h, kind, drill, fn, pt in pads]
        labelled.append((ref, val, lib, x, y, rot, pads, cy))
    monkeypatch.setattr(CF, "PARTS", labelled)
    br = build(load(str(CF.write_board(tmp_path))))
    assert [s["id"] for s in br["structures"] if s["kind"] == "commutation_cell"] == ["cell:buck:U1"]


def test_pin_facts_for_another_part_are_not_applied(tmp_path):
    """Pin facts whose reference names another part (a schematic of another revision: 29 pins for a 6-pad part)
    are skipped, so that part's pin names are not read as this one's."""
    import critical_fixtures as CF
    from haslam.board import pinfacts as PF
    from haslam.board.kicad_file import load
    b = load(str(CF.write_board(tmp_path)))
    pins = {"U1": {str(k): ["passive", f"P{k}"] for k in range(1, 30)}, "C1": {"1": ["passive", "A"]}}
    for fp in b.footprints:
        for pad in fp.pads:
            pad.pinfunction, pad.pintype = "", ""
    assert PF.apply(b, pins) == 1
    u1 = next(f for f in b.footprints if f.ref == "U1")
    assert all(not p.pinfunction for p in u1.pads)


def test_an_unnamed_switchers_input_is_the_net_of_most_of_its_pins(tmp_path, monkeypatch):
    """A switcher with no pin names whose input has no capacitor of its own (e1-dock's AP63205 on CELL_F, its EN
    tied to VIN): its input is the net of most of its pins off the switch node, the far end, ground and its
    bootstrap capacitor; before, it had no input and no cell."""
    import critical_fixtures as CF
    from haslam.board.kicad_file import load
    from haslam.circuit.brief import build
    from test_circuit_cells_channels import BOOT
    monkeypatch.setattr(CF, "PARTS", _stripped([BOOT], rename={"VIN": "CELL_F"}, drop=("C1", "D1")))
    br = build(load(str(CF.write_board(tmp_path))))
    cells = [(s["id"], s["rail"]) for s in br["structures"] if s["kind"] == "commutation_cell"]
    assert cells == [("cell:buck:U1", "CELL_F")]


CORPUS = {"meshsat-meshsat-fieldkit-pcb-a-power": ["cell:buck:U12", "cell:buck:U4", "cell:buck:U5", "cell:buck:U6",
                                                   "cell:buck:U7"],
          "meshsat-meshsat-fieldkit-pcb-e1-dock": ["cell:buck:U12", "cell:buck:U5", "cell:half_bridge:Q6+Q5"]}


@pytest.mark.parametrize("board", sorted(CORPUS))
@pytest.mark.parametrize("with_pintypes", [False, True])
def test_the_corpus_boards_cells_with_and_without_their_pintypes(board, with_pintypes, monkeypatch):
    """The two real boards (third-party: read from HASLAM_BOARDS / HASLAM_BASELINES when set, never committed), with and
    without their schematic pintypes: the same cells either way (HASLAM_CELLS_EXTBB off)."""
    import json
    import os
    root, base = os.environ.get("HASLAM_BOARDS"), os.environ.get("HASLAM_BASELINES")
    pcb = Path(root or "/nonexistent") / "boards" / board / "board.kicad_pcb"
    pt = Path(base or "/nonexistent") / "boards" / board / "pintypes.json"
    if not pcb.exists() or (with_pintypes and not pt.exists()):
        pytest.skip("corpus board or its pintypes not available (HASLAM_BOARDS, HASLAM_BASELINES)")
    monkeypatch.delenv("HASLAM_CELLS_EXTBB", raising=False)
    out = _summary()(str(pcb), pintypes=json.loads(pt.read_text()) if with_pintypes else None)
    assert sorted(s["id"] for s in out["sections"] if s["kind"] == "commutation_cell") == CORPUS[board]
