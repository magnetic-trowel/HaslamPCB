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
