# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.drc_items: one reading of a DRC report for kae, the restart judge and (by equality) kaebench."""
import importlib.util
import json
from pathlib import Path

import pytest

from kae import drc_items as DI

ROOT = Path(__file__).resolve().parents[2]


def test_constants_equal_the_benchmarks():
    """kaebench keeps its own copies (the scorer stays independent of kae): they must not drift."""
    tools = pytest.importorskip("kaebench.tools")
    score = pytest.importorskip("kaebench.score")
    assert DI.ENV_DEPENDENT == tools.ENV_DEPENDENT_CHECKS
    assert DI.DRC_UNCONNECTED_CAP == score.DRC_UNCONNECTED_CAP
    assert DI.PLACEMENT_TYPES == score.PLACEMENT_ERROR_TYPES
    assert set(DI.PLACER_TYPES) - set(DI.PLACEMENT_TYPES) == {"solder_mask_bridge"}


def test_the_restart_judge_loads_the_same_rules():
    spec = importlib.util.spec_from_file_location("restart_drc_items", ROOT / "tools" / "kaeres" / "restart.py")
    restart = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restart)
    assert restart.DRC_UNCONNECTED_CAP == DI.DRC_UNCONNECTED_CAP and restart.UNCONNECTED_PY == DI.UNCONNECTED_PY
    from kae.route import drc
    assert drc.ENV_DEPENDENT is DI.ENV_DEPENDENT and drc.UNCONNECTED_PY is DI.UNCONNECTED_PY


def test_errors_by_type_drops_other_severities_and_library_checks():
    rep = dict(violations=[dict(type="clearance", severity="error"), dict(type="clearance", severity="error"),
                           dict(type="silk_overlap", severity="warning"),
                           dict(type="lib_footprint_mismatch", severity="error")],
               unconnected_items=[dict(type="unconnected_items", severity="error")])
    assert DI.errors_by_type(rep) == {"clearance": 2}
    assert len(DI.errors(rep, ignore=())) == 3
    assert DI.errors(rep, types=("silk_overlap",)) == []
    assert DI.errors_by_type({}) == {}


def test_unconnected_ignored(tmp_path):
    b = tmp_path / "board.kicad_pcb"
    assert not DI.unconnected_ignored(b)
    for sev, want in (("ignore", True), ("warning", False)):
        b.with_suffix(".kicad_pro").write_text(json.dumps(
            {"board": {"design_settings": {"rule_severities": {"unconnected_items": sev}}}}))
        assert DI.unconnected_ignored(b) is want
    kb = pytest.importorskip("kaebench.boardfiles")
    assert kb.unconnected_ignored(b) is False


# item descriptions as KiCad 10 writes them (shapes from the corpus' DRC reports)
ITEMS = [
    ("Pad 2 [GND] of C3 on F.Cu", "pad", ["GND"], "C3"),
    ("PTH pad 6 [GND] of J11", "pad", ["GND"], "J11"),
    ("NPTH pad of H1", "pad", [], "H1"),
    ("Pad 1 [<no net>] of S4 on L1", "pad", [], "S4"),
    ("Pad 1 [GND] of D2 on Top Layer", "pad", ["GND"], "D2"),          # a layer name with a space
    ("Pad 1 [D[0]] of R47 on TOP", "pad", ["D[0]"], "R47"),            # a net name with brackets
    ("Via [sdram_dq[3]] on F.Cu - B.Cu", "via", ["sdram_dq[3]"], None),
    ("Footprint U1", "footprint", [], "U1"),
    ("Footprint ADS4 (0x4B)", "footprint", [], "ADS4"),
    ("Footprint text of U$3 (${REV})", "footprint", [], "U$3"),
    ("Reference field of D1", "other", [], "D1"),
    ("Value field of Q1 (CMUT3904)", "other", [], "Q1"),
    ("Pad [<no net>] of On - Off on F.Cu", "pad", [], "On - Off"),       # a reference with spaces
    ("PCB text '[OSHW] UID:' on F.Silkscreen", "other", [], None),
    ("Polygon [<no net>] of G*** on B.Cu", "other", [], "G***"),
    ("Track [A/B] on F.Cu, length 1.2 mm", "track", ["A/B"], None),
    ("Zone [GND] on L1 [Top], priority 0", "zone", ["GND"], None),     # a layer name with brackets
    ("Segment on Edge.Cuts", "other", [], None),
    ("Pad 1 [<no net>] of  on F.Cu", "pad", [], None),                 # a part without a reference
    ("Footprint  ", "footprint", [], None),
    ("PCB text 'out of 3' on F.Silkscreen", "other", [], None),
]


def test_items_kind_nets_and_owner():
    for desc, kind, nets, ref in ITEMS:
        assert (DI.item_kind(desc), DI.item_nets(desc), DI.item_ref(desc)) == (kind, nets, ref), desc


def test_open_nets_and_board_names():
    rep = dict(unconnected_items=[dict(items=[dict(description="Pad 1 [A/B] of U1 on F.Cu"),
                                              dict(description="Track [A/B] on F.Cu, length 1 mm")]),
                                  dict(items=[dict(description="Pad 2 [D[0]] of U2 on F.Cu")])])
    assert DI.open_nets(rep) == ["A/B", "D[0]"]
    assert DI.board_nets(DI.open_nets(rep), ["A{slash}B", "D[0]", "C"]) == ["A{slash}B", "D[0]"]
    assert DI.board_nets(["X"], ["A{slash}B"]) == ["X"]
