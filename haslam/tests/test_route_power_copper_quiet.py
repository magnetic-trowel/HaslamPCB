# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Power copper leaves alone the nets whose loss widening could not cut (widen_min_loss_uW) and grows nothing in the
rule areas the minimal_copper setting names (bme280-array F46: GND at ~60 uA widened to 0.6-3 mm among thermally
isolated sensors). Runs without KiCad (synthetic export info, no fills, the DC plan stubbed)."""
import json

import pytest
from shapely.geometry import box

import critical_fixtures as F
from haslam.route import power_copper as pc
from test_route_power_copper_keepout import KEEPOUT, SEG

AREA = (106.0, 109.0, 112.0, 113.0)     # over the VIN track's middle
OPERATING = {"parts": {"U1": {"I_A": [1e-6, 1e-3], "why": "test"}}}


def _board(tmp_path, area=None, text_vars=None):
    from haslam.board.kicad_file import load
    p = F.write_board(tmp_path)
    s = p.read_text()
    i = s.rindex("\t(embedded_fonts no)")
    add = SEG.format(104.0, 111.0, 114, 111.0, "VIN", "0000000a-0000-0000-0000-00000000aaaa")
    add += SEG.format(114, 111.0, 119.69, 110.95, "VIN", "0000000a-0000-0000-0000-00000000aaab")
    if area:
        x0, y0, x1, y1 = AREA
        add += KEEPOUT.format(x0, y0, x1, y0, x1, y1, x0, y1).replace('(name "no_pour")', f'(name "{area}")') \
            .replace("(copperpour not_allowed)", "(copperpour allowed)")
    p.write_text(s[:i] + add + s[i:])
    if text_vars:
        pro = json.loads(p.with_suffix(".kicad_pro").read_text())
        pro.setdefault("text_variables", {}).update(text_vars)
        p.with_suffix(".kicad_pro").write_text(json.dumps(pro))
    return p, load(p)


def _pc(tmp_path, monkeypatch, amps, area=None, text_vars=None, source="intent", **opts):
    """Power copper on the board with a DC plan driving `amps` along the VIN track (J1.1 in, U1.3 out); `source`: where
    the load's current comes from (intent, part_table or prior)."""
    from haslam.excite import dc

    def plan(*a, sources=None, **k):
        if sources is not None and amps:
            sources["U1.3"] = {source}
        return {"J1.1": amps, "U1.3": -amps} if amps else {}
    monkeypatch.setattr(dc, "planned_injections", plan)
    p, b = _board(tmp_path, area, text_vars)
    op = tmp_path / "op.json"
    op.write_text(json.dumps(OPERATING))
    obj = pc.PowerCopper(p, dict(opts, vias=False, stitch=False, operating=str(op), neck=False),
                         info=F.synth_info(b), fills={}, log=lambda *a: None)
    obj.widen()
    return obj


def _vin_widened(obj):
    nets = {t.uuid: t.net for t in obj.board.tracks}
    return [u for u in obj.edits if nets.get(u) == "VIN"]


def test_a_microamp_net_is_not_widened(tmp_path, monkeypatch):
    quiet = _pc(tmp_path / "q", monkeypatch, 60e-6)
    assert "VIN" in quiet.quiet_nets() and quiet.quiet_nets()["VIN"] < 1e-9     # nW: 60 uA through ~20 mm
    assert not _vin_widened(quiet)
    assert quiet.stats["quiet_nets"]["VIN"] < 1e-3                                # reported in uW
    loud = _pc(tmp_path / "l", monkeypatch, 1.0)                                  # 1 A: widening pays
    assert "VIN" not in loud.quiet_nets() and _vin_widened(loud)
    off = _pc(tmp_path / "o", monkeypatch, 60e-6, widen_min_loss_uW=0)            # the setting off
    assert _vin_widened(off)


def test_a_net_whose_load_current_is_a_prior_is_widened_as_before(tmp_path, monkeypatch):
    """A class prior can understate a real power net: only stated (or part-table) currents make a net quiet."""
    obj = _pc(tmp_path, monkeypatch, 60e-6, source="prior")
    assert "VIN" not in obj.quiet_nets() and _vin_widened(obj)
    tab = _pc(tmp_path / "t", monkeypatch, 60e-6, source="part_table")
    assert "VIN" in tab.quiet_nets()


def test_a_net_without_planned_current_is_widened_as_before(tmp_path, monkeypatch):
    obj = _pc(tmp_path, monkeypatch, 0.0)                                         # no plan: nothing is known
    assert obj.quiet_nets() == {} and _vin_widened(obj)


@pytest.mark.parametrize("how", ["text_var", "opts"])
def test_nothing_grows_in_a_minimal_copper_rule_area(tmp_path, monkeypatch, how):
    area = box(*AREA)
    free = _pc(tmp_path / "free", monkeypatch, 1.0, area="SENSE")
    grown = [(a, b, w) for u in _vin_widened(free) for a, b, w, *_ in free.edits[u] if w > 0.25 + 1e-9]
    assert any(area.intersects(box(*a, *a).union(box(*b, *b)).convex_hull.buffer(w / 2)) for a, b, w in grown), \
        "the control must grow VIN copper into the area, or the test proves nothing"
    kw = dict(text_vars={"HASLAM_MINIMAL_COPPER": "SEN*"}) if how == "text_var" else dict(minimal_copper="SENSE")
    held = _pc(tmp_path / "held", monkeypatch, 1.0, area="SENSE", **kw)
    assert held.stats["minimal_copper_areas"] == ["SENSE"]
    pieces = [(a, b, w) for u in _vin_widened(held) for a, b, w, *_ in held.edits[u]]
    assert any(w > 0.25 + 1e-9 for _, _, w in pieces), "VIN still grows outside the area"
    for a, b, w in pieces:
        if w > 0.25 + 1e-9:
            seg = box(*a, *a).union(box(*b, *b)).convex_hull.buffer(w / 2, cap_style=2)
            assert seg.intersection(area).area < 1e-3, (a, b, w)
