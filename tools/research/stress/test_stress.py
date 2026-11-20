# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the stress-dial prototype's file handling and scoring logic (no KiCad needed)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import stress  # noqa: E402

PRO = {
    "board": {"design_settings": {"rules": {
        "min_clearance": 0.1, "min_track_width": 0.2, "min_hole_clearance": 0.25,
        "min_copper_edge_clearance": 0.5, "min_via_diameter": 0.5}}},
    "net_settings": {"classes": [
        {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3,
         "diff_pair_gap": 0.25, "diff_pair_width": 0.2},
        {"name": "Power", "clearance": 0.2, "track_width": 0.5, "via_diameter": 0.8, "via_drill": 0.4}]},
}

DRU = """(version 1)
(rule "hv"
  (condition "A.NetClass == 'HV'")
  (constraint clearance (min 0.5mm)))
(rule "wide" (constraint track_width (min 10mil) (opt 12mil) (max 1.0)))
(rule "holes" (constraint hole_clearance (min 0.3mm)))
(rule "expr" (constraint clearance (min "0.2mm + 0.1mm")))
"""


def test_ids():
    assert stress.derived_id("acme-board", 1.5) == "acme-board@c1.5"
    assert stress.derived_id("acme-board", 2.0) == "acme-board@c2"
    assert stress.split_id("acme-board@c1.5") == ("acme-board", 1.5)
    assert stress.split_id("acme-board@c2") == ("acme-board", 2.0)
    assert stress.split_id("acme-board") == ("acme-board", None)
    assert stress.split_id("odd@cable") == ("odd@cable", None)


def test_scale_project_scales_only_clearance_and_track_width():
    out, changes = stress.scale_project(PRO, 1.5)
    rules = out["board"]["design_settings"]["rules"]
    assert rules["min_clearance"] == pytest.approx(0.15) and rules["min_track_width"] == pytest.approx(0.3)
    d, p = out["net_settings"]["classes"]
    assert (d["clearance"], d["track_width"]) == pytest.approx((0.3, 0.375))
    assert (p["clearance"], p["track_width"]) == pytest.approx((0.3, 0.75))
    # everything else is left alone
    for key in ("min_hole_clearance", "min_copper_edge_clearance", "min_via_diameter"):
        assert rules[key] == PRO["board"]["design_settings"]["rules"][key]
    for key in ("via_diameter", "via_drill", "diff_pair_gap", "diff_pair_width"):
        assert d[key] == PRO["net_settings"]["classes"][0][key]
    assert len(changes) == 6
    assert PRO["net_settings"]["classes"][0]["clearance"] == 0.2  # the input is not modified


def test_scale_project_identity_and_missing_sections():
    out, changes = stress.scale_project(PRO, 1.0)
    assert out == PRO and len(changes) == 6
    assert stress.scale_project({}, 2.0) == ({}, [])
    assert stress.scale_project({"net_settings": {"classes": [{"name": "x"}]}}, 2.0)[1] == []


def test_scale_dru():
    text, n, left = stress.scale_dru(DRU, 2.0)
    assert "(constraint clearance (min 1mm))" in text
    assert "(constraint track_width (min 20mil) (opt 24mil) (max 2))" in text
    assert n == 4
    assert "(constraint hole_clearance (min 0.3mm))" in text            # another kind: left alone
    assert '(constraint clearance (min "0.2mm + 0.1mm"))' in text        # an expression: left alone
    assert sorted(left) == ["clearance", "hole_clearance"]
    assert '(condition "A.NetClass == \'HV\'")' in text
    assert stress.scale_dru(DRU, 1.0)[0].count("(rule") == 4


def _board(tmp_path, dru=False):
    src = tmp_path / "corpus" / "acme-board"
    src.mkdir(parents=True)
    (src / "board.kicad_pcb").write_text("(kicad_pcb (version 20260206))\n")
    (src / "board.kicad_pro").write_text(json.dumps(PRO))
    (src / "row.json").write_text(json.dumps({"id": "acme-board", "repo": "https://example.org/acme", "license": "MIT"}))
    if dru:
        (src / "board.kicad_dru").write_text(DRU)
    return src


def test_derive_writes_a_board_folder(tmp_path):
    src = _board(tmp_path, dru=True)
    dst, rec = stress.derive(src, tmp_path / "out", 1.5)
    assert dst.name == "acme-board@c1.5"
    assert (dst / "board.kicad_pcb").read_bytes() == (src / "board.kicad_pcb").read_bytes()
    pro = json.loads((dst / "board.kicad_pro").read_text())
    assert pro["net_settings"]["classes"][0]["clearance"] == pytest.approx(0.3)
    assert "(min 0.75mm)" in (dst / "board.kicad_dru").read_text()
    row = json.loads((dst / "row.json").read_text())
    assert row["id"] == "acme-board@c1.5" and row["stress"] == {"base": "acme-board", "factor": 1.5}
    assert row["license"] == "MIT"
    assert rec["dru"] == {"scaled": 4, "left_alone": ["clearance", "hole_clearance"]}
    assert json.loads((dst / "stress.json").read_text())["factor"] == 1.5
    # the source is untouched
    assert json.loads((src / "board.kicad_pro").read_text()) == PRO


def test_derive_refuses_a_board_without_project_rules(tmp_path):
    src = _board(tmp_path)
    (src / "board.kicad_pro").unlink()
    with pytest.raises(SystemExit, match="nothing to scale"):
        stress.derive(src, tmp_path / "out", 1.5)
    with pytest.raises(SystemExit):
        stress.derive(_board(tmp_path / "b"), tmp_path / "out", 0)
    empty = _board(tmp_path / "c")
    (empty / "board.kicad_pro").write_text("{}")          # seen in the corpus: every level would be the same board
    with pytest.raises(SystemExit, match="nothing to scale"):
        stress.derive(empty, tmp_path / "out", 1.5)
    assert not (tmp_path / "out").exists()
    partial = _board(tmp_path / "d")
    (partial / "board.kicad_pro").write_text(json.dumps({"net_settings": PRO["net_settings"]}))
    assert stress.derive(partial, tmp_path / "out", 1.5)[1]["unscaled_defaults"] == ["min_clearance", "min_track_width"]


def test_ceiling_of():
    scan = [(1.0, {}), (1.2, {}), (1.5, {}), (2.0, {"clearance": 3}), (3.0, {"clearance": 9})]
    assert stress.ceiling_of(scan) == (1.5, (2.0, {"clearance": 3}))
    assert stress.ceiling_of([(1.0, {}), (2.0, {})]) == (2.0, None)
    assert stress.ceiling_of([(1.0, {}), (1.1, {"clearance": 1})]) == (1.0, (1.1, {"clearance": 1}))


def test_gained_counts_only_errors_above_the_base():
    base = dict(errors_by_type={"starved_thermal": 2})
    assert stress.gained(dict(errors_by_type={"starved_thermal": 2}), base) == {}
    assert stress.gained(dict(errors_by_type={"starved_thermal": 3, "clearance": 4}), base) == {"clearance": 4, "starved_thermal": 1}


def test_clean_level_bisects_to_the_threshold():
    calls = []

    def clean(f):
        calls.append(f)
        return f <= 1.734

    assert stress.clean_level(clean, 1.0, 4.0) == 1.73
    assert len(calls) < 14
    assert stress.clean_level(lambda f: True, 1.0, 4.0) == 4.0
    assert stress.clean_level(lambda f: False, 1.0, 4.0) is None
    assert stress.clean_level(lambda f: f <= 1.0, 1.0, 4.0) == 1.0


def test_pick_levels_stays_inside_the_ceiling():
    assert stress.pick_levels(1.1, 1.0) is None                    # no room for two tighter levels
    assert stress.pick_levels(2.0, 1.0) == [1.0, 1.4, 2.0]         # human at the rule: geometric middle
    assert stress.pick_levels(2.0, 1.52) == [1.0, 1.5, 2.0]        # human level well inside: it is the middle
    assert stress.pick_levels(4.0, 3.9) == [1.0, 1.75, 3.0]        # capped; human above 0.9 x top
    assert stress.pick_levels(1.2, 1.0) == [1.0, 1.1, 1.2]
    for c in (1.2, 1.3, 1.5, 1.9, 2.5, 4.0):
        for h in (None, 1.0, 1.2, 1.6, 4.0):
            lv = stress.pick_levels(c, h)
            assert lv[0] == 1.0 < lv[1] < lv[2] <= min(c, stress.TOP_CAP)


def test_hardest_clean():
    assert stress.hardest_clean({1.0: True, 1.5: True, 2.0: False}) == (1.5, True)
    assert stress.hardest_clean({1.0: True, 1.5: False, 2.0: True}) == (1.0, False)   # clean came back: not monotone
    assert stress.hardest_clean({1.0: False, 1.5: False}) == (None, True)
    assert stress.hardest_clean({1.0: True, 1.5: True, 2.0: True}) == (2.0, True)


def test_narrowest_track(tmp_path):
    b = tmp_path / "board.kicad_pcb"
    b.write_text('(kicad_pcb\n\t(segment\n\t\t(start 1 2)\n\t\t(end 3 4)\n\t\t(width 0.25)\n\t\t(layer "F.Cu")\n\t)\n'
                 '\t(arc\n\t\t(start 1 2)\n\t\t(mid 2 2)\n\t\t(end 3 4)\n\t\t(width 0.2)\n\t)\n'
                 '\t(gr_line (start 0 0) (end 1 1) (stroke (width 0.05)))\n)\n')
    assert stress.narrowest_track(b) == 0.2
    b.write_text("(kicad_pcb)\n")
    assert stress.narrowest_track(b) is None
    assert stress.narrowest_track(tmp_path / "missing.kicad_pcb") is None


def test_collect_and_summarize(tmp_path):
    def attempt(method, factor, clean, completion, unconnected):
        d = tmp_path / method / method / "route" / f"acme-board@{stress.tag(factor)}" / "attempt-0"
        d.mkdir(parents=True)
        (d / "attempt.json").write_text(json.dumps(dict(
            adapter=method, id=d.parent.name, status="ok", runtime_s=3.0, method_usage=dict(cpu_s=12.5),
            score=dict(clean=clean, valid=True, unconnected=unconnected, completion=completion, errors=0, errors_by_type={}))))
        if method == "bridge":
            (d / "adapter.log").write_text('[restart] ...\nKAE_WORK {"attempts": 4, "cpu_s": 12.0}\n')

    attempt("fr", 1.0, True, 1.0, 0), attempt("fr", 1.5, False, 0.8, 2), attempt("fr", 2.0, False, 0.9, 1)
    attempt("bridge", 1.0, True, 1.0, 0), attempt("bridge", 1.5, True, 1.0, 0), attempt("bridge", 2.0, False, 0.9, 1)
    rows = stress.collect([tmp_path / "fr", tmp_path / "bridge"])
    assert {r["restarts"] for r in rows if r["method"] == "bridge"} == {4}
    assert {r["restarts"] for r in rows if r["method"] == "fr"} == {None}
    assert len(rows) == 6 and {r["board"] for r in rows} == {"acme-board"}
    table = {t["method"]: t for t in stress.summarize(rows, [dict(id="acme-board@c1", ceiling=2.0, human_level=1.3)])}
    assert table["fr"]["hardest_clean"] == 1.0 and table["bridge"]["hardest_clean"] == 1.5
    assert table["fr"]["completion_monotone"] is False and table["bridge"]["completion_monotone"] is True
    assert table["bridge"]["ceiling"] == 2.0 and table["bridge"]["human_level"] == 1.3
    assert table["bridge"]["cpu_s"] == [12.5, 12.5, 12.5]
