# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hot-loop cells stage on inverting buck-boosts (HASLAM_CELLS_INVERTING=1), on the synthetic board's three
inverter wirings (hotloop_fixtures.inverting_parts): a buck IC as an inverter with its input capacitor to ground
or straight to -5V, and a dedicated inverter. Each is laid, priced, returns through its own return net (`ret`),
closes no pin's way to its net, and adds no DRC error; with the flag off the stage does exactly what it did."""
import re
from pathlib import Path

import pytest

import critical_fixtures as F
from hotloop_fixtures import write_inverting_board
from haslam.board import pcbnew_io
from haslam.board.kicad_file import load
from haslam.route import critical_write as W
from haslam.route import drc, hotloop

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
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
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
             or any("haslam-hl" in (i.get("description") or "") for i in v.get("items", []))]
    assert not named, [(v["type"], v["description"]) for v in named]
    assert len(errs) <= len(base), [v["type"] for v in errs]


def test_an_inverter_returning_to_its_negative_rail_takes_that_rails_plane(tmp_path, monkeypatch):
    """The input capacitor straight to -5V (TI SLVA721) over a -5V pour: the loop's reference plane and its return
    vias are -5V's, not the ground pour's, and its -5V hop is its return hop (through the plane)."""
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
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
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "0")
    _, off = _stage(tmp_path / "off", variant)
    if variant != "buck":
        assert off["cells"] == [] and off["board"] is None
        return
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
    _, on = _stage(tmp_path / "on", variant)
    assert off["cells"] == on["cells"] and _canon(Path(off["board"])) == _canon(Path(on["board"]))


def test_the_four_layer_inverter_at_one_and_a_half_amps(tmp_path, monkeypatch):
    """The saved route-CLI input (tools/haslamres/experiments/inverters/make_boards.py): a buck IC as an inverter on
    four layers (a GND plane on In1.Cu), its input capacitor straight to -5V, 1.5 A out by its operating facts. Laid
    over the In1.Cu plane (no -5V copper: the stand-in plane, said so), its hops sized for the switch's current."""
    from haslam.route import critical_physics as P
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
    data = Path(__file__).parent / "data" / "inverters"
    p = tmp_path / "in" / "board.kicad_pcb"
    p.parent.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        (p.parent / f"board{ext}").write_text((data / "inv-direct-4l" / f"board{ext}").read_text())
    rep = hotloop.stage(p, F.synth_info(load(p)), tmp_path / "w",
                        dict(ALL, operating=str(data / "inv-direct-4l.operating.json")), log=lambda *a: None)
    (c,) = [c for c in rep["cells"] if c["id"] == CELL]
    assert c["status"] == "routed" and (c["ret"], c["plane_src"]) == ("-5V", "other")
    assert c["plane_net"] == "GND"
    b = load(Path(rep["board"]))
    # I_L = I_out / (1 - D) at 12 V -> -5 V: the hops are at least IPC-2221 wide for it (or flagged)
    widths = [t.width for t in b.tracks if t.net in ("+12V", "-5V")]
    assert widths and max(widths) >= P.ipc2221_width(1.5) - 1e-6


def test_the_cells_stage_lays_an_inverting_buck(tmp_path, monkeypatch):
    """A TPS6371x inverting buck (HASLAM_CELLS_INVBUCK=1 with inverting cells on): laid as a buck's loop through
    ground, priced, closing no pin's way, adding no DRC error."""
    from test_circuit_inverting import _inv_buck_parts
    monkeypatch.setattr(F, "PARTS", _inv_buck_parts())
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
    monkeypatch.setenv("HASLAM_CELLS_INVBUCK", "1")
    src = F.write_board(tmp_path / "in")
    rep = hotloop.stage(src, F.synth_info(load(src)), tmp_path / "w", ALL, log=lambda *a: None)
    (c,) = [c for c in rep["cells"] if c["id"] == CELL]
    assert c["status"] == "routed" and c["L_nH"] > 0 and c["R_mohm"] > 0 and c["ret"] == "GND"
    assert not [h for h in rep["hazards"] if h["code"] in ("hotloop_cell_blocks_pin", "hotloop_cell_unrouted")]
    base = drc.errors(drc.run(src, tmp_path / "base.json"))
    out = tmp_path / "out.kicad_pcb"
    W.edit(rep["board"], out, drop_guards=True)
    (tmp_path / "out.kicad_pro").write_text((tmp_path / "in" / "board.kicad_pro").read_text())
    assert len(drc.errors(drc.run(out, tmp_path / "out.json"))) <= len(base)


def test_the_cells_stage_lays_a_dual_rail_ics_negative_half(tmp_path, monkeypatch):
    """A TPS65133's inverting half (HASLAM_CELLS_DUALRAIL=1): its loop through the IC's input and VNEG pins and the
    output capacitor to ground, laid, priced, closing no pin's way, adding no DRC error."""
    from test_circuit_inverting import DUAL
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in F.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in DUAL:
                net, f2, pt = DUAL[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS65133" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(F, "PARTS", parts)
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
    monkeypatch.setenv("HASLAM_CELLS_DUALRAIL", "1")
    src = F.write_board(tmp_path / "in")
    rep = hotloop.stage(src, F.synth_info(load(src)), tmp_path / "w", ALL, log=lambda *a: None)
    (c,) = [c for c in rep["cells"] if c["id"] == CELL]
    assert c["status"] == "routed" and c["L_nH"] > 0 and c["R_mohm"] > 0 and c["ret"] == "GND"
    assert not [h for h in rep["hazards"] if h["code"] in ("hotloop_cell_blocks_pin", "hotloop_cell_unrouted")]
    base = drc.errors(drc.run(src, tmp_path / "base.json"))
    out = tmp_path / "out.kicad_pcb"
    W.edit(rep["board"], out, drop_guards=True)
    (tmp_path / "out.kicad_pro").write_text((tmp_path / "in" / "board.kicad_pro").read_text())
    assert len(drc.errors(drc.run(out, tmp_path / "out.json"))) <= len(base)
