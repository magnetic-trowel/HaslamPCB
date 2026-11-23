# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hot-loop cells stage on inverting buck-boosts (KAE_CELLS_INVERTING=1), on the synthetic board's three
inverter wirings (hotloop_fixtures.inverting_parts): a buck IC as an inverter with its input capacitor to ground
or straight to -5V, and a dedicated inverter. Each is laid, priced, returns through its own return net (`ret`),
closes no pin's way to its net, and adds no DRC error; with the flag off the stage does exactly what it did."""
import re
from pathlib import Path

import pytest

import critical_fixtures as F
from hotloop_fixtures import write_inverting_board
from kae.board import pcbnew_io
from kae.board.kicad_file import load
from kae.route import critical_write as W
from kae.route import drc, hotloop

pytestmark = [pytest.mark.kicad,
              pytest.mark.skipif(not pcbnew_io.available(), reason="no Python with pcbnew")]

ALL = dict(hotloop_keepout=1, hotloop_cells=1, hotloop_vias=1, hotloop_pours=1)
CELL = "cell:inverting:U1"
RET = {"ground": "GND", "direct": "-5V", "dedicated": "GND"}


def _stage(d, variant):
    p = F.write_board(d / "in") if variant == "buck" else write_inverting_board(d / "in", variant, routed=False)
    return p, hotloop.stage(p, F.synth_info(load(p)), d / "w", ALL, log=lambda *a: None)


@pytest.mark.parametrize("variant", sorted(RET))
def test_the_cells_stage_lays_an_inverter_and_returns_through_its_ret(variant, tmp_path, monkeypatch):
    monkeypatch.setenv("KAE_CELLS_INVERTING", "1")
    src, rep = _stage(tmp_path, variant)
    (c,) = [c for c in rep["cells"] if c["id"] == CELL]
    assert c["status"] == "routed" and c["L_nH"] > 0 and c["R_mohm"] > 0 and c["W_loop"] > 0
    assert c["ret"] == RET[variant]
    # its reference plane: the return net's own copper (the ground pour), or, with no pour of -5V, the stand-in
    # plane a buck without a ground plane gets (another net's), said so
    assert c["plane_src"] == ("return" if RET[variant] == "GND" else "other")
    assert not [h for h in rep["hazards"] if h["code"] in ("hotloop_cell_blocks_pin", "hotloop_cell_unrouted")]
    # the copper adds no DRC error
    base = drc.errors(drc.run(src, tmp_path / "base.json"))
    out = tmp_path / "out.kicad_pcb"
    W.edit(rep["board"], out, drop_guards=True)
    (tmp_path / "out.kicad_pro").write_text((tmp_path / "in" / "board.kicad_pro").read_text())
    errs = drc.errors(drc.run(out, tmp_path / "out.json"))
    mine = {r["uuid"] for r in W.routing(out) if r["locked"]}
    named = [v for v in errs if {i.get("uuid") for i in v.get("items", [])} & mine
             or any("kae-hl" in (i.get("description") or "") for i in v.get("items", []))]
    assert not named, [(v["type"], v["description"]) for v in named]
    assert len(errs) <= len(base), [v["type"] for v in errs]


def test_an_inverter_returning_to_its_negative_rail_takes_that_rails_plane(tmp_path, monkeypatch):
    """The input capacitor straight to -5V (TI SLVA721) over a -5V pour: the loop's reference plane and its return
    vias are -5V's, not the ground pour's, and its -5V hop is its return hop (through the plane)."""
    monkeypatch.setenv("KAE_CELLS_INVERTING", "1")
    p = write_inverting_board(tmp_path / "in", "direct", routed=False, neg_pour=True)
    rep = hotloop.stage(p, F.synth_info(load(p)), tmp_path / "w", ALL, log=lambda *a: None)
    (c,) = [c for c in rep["cells"] if c["id"] == CELL]
    assert c["status"] == "routed" and (c["ret"], c["plane_net"], c["plane_src"]) == ("-5V", "-5V", "return")
    vias = load(Path(rep["board"])).vias
    assert vias and {v.net for v in vias} == {"-5V"}
    assert not [h for h in rep["hazards"] if h["code"] == "hotloop_cell_blocks_pin"]


def _canon(path):
    """The work board without its fresh uuids (each run draws new ones)."""
    return re.sub(r'\(uuid "[^"]*"\)', "", path.read_text()) if path else None


@pytest.mark.parametrize("variant", ["buck"] + sorted(RET))
def test_the_flag_off_stage_is_the_stage_as_it_was(variant, tmp_path, monkeypatch):
    """A/A: the buck board's stage is the same with the flag on or off; the inverters get no cell with it off."""
    monkeypatch.setenv("KAE_CELLS_INVERTING", "0")
    _, off = _stage(tmp_path / "off", variant)
    if variant != "buck":
        assert off["cells"] == [] and off["board"] is None
        return
    monkeypatch.setenv("KAE_CELLS_INVERTING", "1")
    _, on = _stage(tmp_path / "on", variant)
    assert off["cells"] == on["cells"] and _canon(Path(off["board"])) == _canon(Path(on["board"]))
