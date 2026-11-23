# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/research/physics/board_summary.py, the board description the operating facts are written from: it lists
every inductor (an inverter's output filter L2 was folded into the passives' count, so no fact could name it) and
reads the board as the evaluator does (its inverting cells)."""
import importlib.util
from pathlib import Path

from hotloop_fixtures import write_inverting_board

ROOT = Path(__file__).resolve().parents[2]


def _summary():
    spec = importlib.util.spec_from_file_location("board_summary", ROOT / "tools/research/physics/board_summary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.summarize


def test_every_inductor_is_listed_and_the_inverter_is_a_section(tmp_path, monkeypatch):
    monkeypatch.delenv("KAE_CELLS_INVERTING", raising=False)
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
    from kae.intent import sections as SE
    parts = {f"C{100 + k}" for k in range(10)} | {"U21"}
    monkeypatch.setattr(SE, "from_brief", lambda br: {"s": SimpleNamespace(id="cell:inverting:U21",
                                                                            kind="commutation_cell", parts=parts, nets=set())})
    out = _summary()(str(CF.write_board(tmp_path)))
    assert set(out["sections"][0]["parts"]) == parts
