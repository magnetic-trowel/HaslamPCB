# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An inverting buck-boost (TI SLVA721) is a commutation cell: its switch IC sits between its input rail and the
negative rail it makes (its ground pins on that rail), its inductor runs from the switch node to ground.

The recogniser required the inductor's far end off ground (a buck's output, a boost's input) and skipped this
converter: a -12 V inverter (an LMR51430 with GND on -12V, VIN on 12V, L from SW to PGND) had no cell, so its hot
loop was never priced. It is recognised for the evaluator; the placer and the router keep their cells as they were
until their cell stages handle a loop whose reference is the negative rail (KAE_CELLS_INVERTING)."""
from functools import lru_cache

import pytest

from hotloop_fixtures import plane_fills, write_inverting_board
from kae.board.kicad_file import load
from kae.circuit.brief import build

CELL = "cell:inverting:U1"


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    return str(write_inverting_board(tmp_path_factory.mktemp("inverting")))


def _cells(brief):
    return {s["id"]: s for s in brief["structures"] if s["kind"] == "commutation_cell"}


def test_an_inverting_converter_is_a_cell_with_its_rails(board):
    s = _cells(build(load(board), inverting=True))[CELL]
    assert (s["class"], s["topology"]) == ("inverting", "inverting_buck_boost")
    assert (s["rail"], s["vin"], s["vout"], s["gnd"], s["sw"]) == ("+12V", "+12V", "-5V", "-5V", "Net-(U1-SW)")
    m = s["members_ref"]
    # the input cap, the IC's input and its reference (ground) pins on -5V, the output cap back to ground
    assert [(m[u], p) for u, p in s["loop"]] == [("C1", "1"), ("U1", ["3"]), ("U1", ["4"]), ("C2", "1"), ("C2", "2"),
                                                ("C1", "2")]
    assert s["excite"]["V"] == pytest.approx(17.0)               # the switch's swing V_in + |V_out|


# variant -> (gnd: the IC's reference, ret: where the input capacitor returns, the loop's parts and pads)
VARIANTS = {
    "ground": ("-5V", "GND", [("C1", "1"), ("U1", ["3"]), ("U1", ["4"]), ("C2", "1"), ("C2", "2"), ("C1", "2")]),
    "direct": ("-5V", "-5V", [("C1", "1"), ("U1", ["3"]), ("U1", ["4"]), ("C1", "2")]),
    "dedicated": ("GND", "GND", [("C1", "1"), ("U1", ["3"]), ("U1", ["5"]), ("D2", "1"), ("D2", "2"), ("C2", "1"),
                                 ("C2", "2"), ("C1", "2")]),
}


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_each_inverter_wiring_is_a_cell_with_its_reference_and_return(variant, tmp_path):
    """A buck IC as an inverter (its GND pin on -5V) with its input capacitor to ground or straight to -5V (TI
    SLVA721's placement), and a dedicated inverter on ground with its rectifier into -5V: each is one cell whose
    `gnd` is the IC's reference and whose `ret` is where its input capacitor returns, read from the capacitor."""
    gnd, ret, loop = VARIANTS[variant]
    s = _cells(build(load(str(write_inverting_board(tmp_path, variant))), inverting=True))[CELL]
    assert (s["class"], s["vin"], s["vout"], s["gnd"], s["ret"]) == ("inverting", "+12V", "-5V", gnd, ret)
    assert [(s["members_ref"][u], p) for u, p in s["loop"]] == loop


def test_a_cells_return_is_its_input_capacitors_other_terminal(tmp_path):
    import critical_fixtures as F
    s = _cells(build(load(str(F.write_board(tmp_path)))))["cell:buck:U1"]
    assert s["ret"] == s["gnd"] == "GND"


def test_the_placer_and_router_brief_is_unchanged_unless_asked(board, monkeypatch):
    monkeypatch.delenv("KAE_CELLS_INVERTING", raising=False)
    assert CELL not in _cells(build(load(board)))
    monkeypatch.setenv("KAE_CELLS_INVERTING", "1")
    assert CELL in _cells(build(load(board)))


@lru_cache(maxsize=None)
def _ev(board):
    from kae.excite.evaluate import evaluate
    return evaluate(board, pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125)


def test_the_evaluator_prices_an_inverting_cells_hot_loop(board, monkeypatch):
    from kae.physics import criteria as CR
    monkeypatch.delenv("KAE_CELLS_INVERTING", raising=False)
    ev = _ev(board)
    obs = {o["id"]: o for o in ev["observations"] if o["scope"].get("source") == f"cell:{CELL}"}
    assert ev["open_cells"] == [] and {"overshoot.peak", "loss.loop", "loss.loop_ac"} <= set(obs)
    assert min(obs["loss.loop"]["values"]) > 0 and min(obs["loss.loop_ac"]["values"]) > 0
    # the switch stands off V_in + |V_out| = 17 V: its overshoot bound is that bus's
    assert obs["overshoot.peak"]["reference"]["value"] == pytest.approx(CR.overshoot_limits(17.0)[0])


def test_an_inverting_cells_bus_and_duty():
    from types import SimpleNamespace

    from kae.excite import params as PA
    from kae.excite.beliefs import Ledger
    from kae.physics import converter as CV
    brief = {"structures": [{"id": "c1", "class": "inverting", "topology": "inverting_buck_boost", "rail": "IN",
                             "vin": "IN", "vout": "NEG"}],
             "nets": {"IN": {"volts": 12.0}, "NEG": {"volts": -5.0}}}
    s = SimpleNamespace(meta={"cell": "c1", "cls": "inverting", "bus": "IN"}, name="c1")
    P = PA.cell(Ledger(), s, brief, None, None, "")
    assert P["V"].typ == pytest.approx(17.0)
    assert P["D"].typ == pytest.approx(5.0 / (12.0 * CV.ETA[1] + 5.0))
    assert CV.topology_of("inverting", {})[0] == "inverting_buck_boost"


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_each_inverters_dc_feed_balances(variant, tmp_path):
    """The inverting cell feeds -5V in the DC band (kae.excite.dc's signed convention: from its pins, its return
    through the switch node and the inductor to ground), and the plan's injections balance exactly, for each wiring:
    the IC's reference on -5V (capacitor to ground or to -5V) or on ground with a rectifier into -5V."""
    from kae.excite import dc as DC
    p = write_inverting_board(tmp_path, variant, load=True)
    b = load(str(p))
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0}, "-5V": {"V_V": -5.0}},
              "parts": {"J2": {"I_A": [0.3, 0.3]}}}
    inj = DC.planned_injections(b, intent, brief=build(b, inverting=True))     # raises on any imbalance
    # -5V's load, signed: into the -5V copper at its supply pad, out of ground (the cell sets its current)
    assert inj["J2.1"] > 0 and inj["J2.2"] == pytest.approx(-inj["J2.1"])
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    # its input current comes from +12V at J1
    assert inj["J1.1"] > 0


DUAL = {("U1", "1"): ("-5V", "VNEG", "power_out"), ("U1", "5"): ("Net-(U1-SWN)", "SWN", "output"),
        ("L1", "1"): ("Net-(U1-SWN)", "", "passive"), ("L1", "2"): ("GND", "", "passive"),
        ("C2", "1"): ("-5V", "", "passive")}


def test_a_dual_rail_ics_negative_half_is_an_inverting_cell(tmp_path, monkeypatch):
    """A dual +/- rail IC (TPS65133: its SWN switch from the input, L from SWN to ground, the rectifier inside from
    SWN to its VNEG pin) on ground: its negative half was missed, since its ground is the system's. KAE_CELLS_DUALRAIL
    (default: as the inverting recognition): the cell's reference and return are ground, its loop the input capacitor, the IC's input
    and VNEG pins and the output capacitor."""
    import critical_fixtures as CF
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in DUAL:
                net, f2, pt = DUAL[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS65133" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(CF, "PARTS", parts)
    p = str(CF.write_board(tmp_path))
    monkeypatch.setenv("KAE_CELLS_DUALRAIL", "0")
    assert CELL not in _cells(build(load(p), inverting=True))
    monkeypatch.delenv("KAE_CELLS_DUALRAIL", raising=False)
    assert CELL not in _cells(build(load(p), inverting=False))       # it follows the inverting recognition
    s = _cells(build(load(p), inverting=True))[CELL]
    assert (s["vin"], s["vout"], s["gnd"], s["ret"]) == ("VIN", "-5V", "GND", "GND")
    assert [(s["members_ref"][u], q) for u, q in s["loop"]] == [("C1", "1"), ("U1", ["3"]), ("U1", ["1"]), ("C2", "1"),
                                                                ("C2", "2"), ("C1", "2")]


INV_BUCK = {("U1", "6"): ("Net-(U1-CP)", "CP", "passive"), ("L1", "2"): ("-5V", "", "passive"),
            ("C2", "1"): ("-5V", "", "passive"), ("U1", "1"): ("Net-(U1-FB)", "FB", "input")}
FLY = ("C7", "1uF", "Capacitor_SMD:C_0603_1608Metric", 124.0, 106.0, 0.0,
       [("1", "Net-(U1-CP)", -0.75, 0.0, 0.8, 0.95, "smd", 0.0, "", "passive"),
        ("2", "Net-(U1-SW)", 0.75, 0.0, 0.8, 0.95, "smd", 0.0, "", "passive")], (1.5, 0.8))


def test_an_inverting_buck_is_an_inverting_cell_with_a_bucks_loop(tmp_path, monkeypatch):
    """A TPS6371x inverting buck: a flying capacitor from its CP pin to the switch node shifts the node below ground,
    the inductor runs from it to -5V. It was typed a plain buck (to a negative rail). Behind KAE_CELLS_INVBUCK:
    class `inverting`, topology `inverting_buck` (D = |V_out| / V_in, I_L = I_out), its loop a buck's."""
    import critical_fixtures as CF
    from kae.physics import converter as CV
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in INV_BUCK:
                net, f2, pt = INV_BUCK[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS63710" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(CF, "PARTS", parts + [FLY])
    p = str(CF.write_board(tmp_path))
    monkeypatch.delenv("KAE_CELLS_INVBUCK", raising=False)
    assert [s["class"] for s in _cells(build(load(p))).values()] == ["buck"]        # the router's brief: off
    monkeypatch.setenv("KAE_CELLS_INVBUCK", "0")
    assert [s["class"] for s in _cells(build(load(p), inverting=True)).values()] == ["buck"]
    monkeypatch.delenv("KAE_CELLS_INVBUCK", raising=False)
    (s,) = _cells(build(load(p), inverting=True)).values()                          # the evaluator's: on
    assert (s["id"], s["class"], s["topology"], s["vout"], s["gnd"], s["ret"]) == \
        ("cell:inverting:U1", "inverting", "inverting_buck", "-5V", "GND", "GND")
    assert [s["members_ref"][u] for u, _ in s["loop"]] == ["C1", "U1", "U1", "C1"]
    op = CV.operating("inverting_buck", 12.0, -5.0, 1.0, 0.9)
    assert op.D == pytest.approx(5 / 12) and op.I_L == op.I_sw == 1.0 and op.V_bus == 12.0


def test_the_recheck_measures_an_inverter_over_its_return_plane(tmp_path):
    """critical_recheck measured a cell's loop against the nearest ground layer: an inverter whose input capacitor
    returns to -5V (4 layers: GND on In1.Cu, a -5V pour on B.Cu under the cell) was rechecked over the GND plane.
    Its reference plane is its return net's: B.Cu; a buck's stays the ground's."""
    from kae.route.critical_recheck import RoutedBoard, cell_value
    p = write_inverting_board(tmp_path, "direct", routed=True, neg_pour=True, layers=4)
    b = load(str(p))
    br = build(b, inverting=True)
    s = _cells(br)[CELL]
    v, extra = cell_value(RoutedBoard(b, fills=None, brief=br), s)
    assert v is not None and v > 0 and extra["gnd_layer"] == "B.Cu"


def test_a_vss_named_net_an_inverter_drives_below_ground_is_its_output(tmp_path, monkeypatch):
    """A buck IC wired as an inverter with its ground on a VSS-named net and a rectifier from its switch node into
    that net (mecsem's beam deflector: TPS5430 on VSSA, D2 into VSSA, L2 to ground): VSSA was a ground by its name,
    so the inverter was never seen. With inverting cells on it leaves the grounds and is the cell's output."""
    import critical_fixtures as CF
    from hotloop_fixtures import D2, inverting_parts

    def vssa(parts):
        return [(r, v, lib, x, y, rot, [(n, "VSSA" if net == "-5V" else net, *rest) for n, net, *rest in pads], cy)
                for r, v, lib, x, y, rot, pads, cy in parts]
    monkeypatch.setattr(CF, "PARTS", vssa(inverting_parts("ground") + [D2]))
    p = str(CF.write_board(tmp_path))
    assert "VSSA" in build(load(p))["summary"]["grounds"]
    br = build(load(p), inverting=True)
    assert "VSSA" not in br["summary"]["grounds"]
    s = _cells(br)[CELL]
    assert (s["vout"], s["gnd"]) == ("VSSA", "VSSA")


TPS65131 = {("U1", "3"): ("VIN", "INN", "power_in"), ("U1", "5"): ("Net-(U1-OUTN)", "OUTN", "output"),
            ("U1", "1"): ("-5V", "VNEG", "input"), ("L1", "1"): ("Net-(U1-OUTN)", "", "passive"),
            ("L1", "2"): ("GND", "", "passive"), ("C2", "1"): ("-5V", "", "passive")}
D_OUTN = ("D2", "PMEG4010", "Diode_SMD:D_SOD-123", 126.0, 114.5, 0.0,
          [("1", "Net-(U1-OUTN)", -1.65, 0.0, 0.9, 1.2, "smd", 0.0, "K", "passive"),
           ("2", "-5V", 1.65, 0.0, 0.9, 1.2, "smd", 0.0, "A", "passive")], (2.4, 1.0))


def test_a_tps65131s_inverter_is_read_through_its_pin_names(tmp_path, monkeypatch):
    """The TPS6513x names its inverter's switch node OUTN and its power input INN (its boost's switch node INP): no
    switch pin was found, so cameranexus' four TPS65131s had no cell. PIN_ALIAS reads them as SWN and PVINN, and
    the inverter (its rectifier D6 from OUTN into -8VA) is a dedicated inverting cell."""
    import critical_fixtures as CF
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in TPS65131:
                net, f2, pt = TPS65131[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS65131RGE" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(CF, "PARTS", parts + [D_OUTN])
    s = _cells(build(load(str(CF.write_board(tmp_path))), inverting=True))[CELL]
    assert (s["vin"], s["vout"], s["gnd"], s["sw"]) == ("VIN", "-5V", "GND", "Net-(U1-OUTN)")


def test_an_inverting_bucks_dc_feed_balances(tmp_path, monkeypatch):
    """The inverting buck feeds -5V in the DC band (dc-signed's convention): its IC takes the output current in at
    its switch pin (the inductor runs from -5V into it), the input current at its input pins, and returns both
    through its ground; every piece balances (planned_injections raises otherwise)."""
    import critical_fixtures as CF
    from hotloop_fixtures import J2
    from kae.excite import dc as DC
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in INV_BUCK:
                net, f2, pt = INV_BUCK[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS63710" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(CF, "PARTS", parts + [FLY, J2])
    monkeypatch.setenv("KAE_CELLS_INVBUCK", "1")
    b = load(str(CF.write_board(tmp_path)))
    br = build(b, inverting=True)
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 12.0}, "-5V": {"V_V": -5.0}}}
    inj = DC.planned_injections(b, intent, brief=br)
    out = inj["J2.1"]
    assert out > 0 and inj["J2.2"] == pytest.approx(-out)
    assert inj["U1.5"] == pytest.approx(-out)            # the inductor's current into the switch pin
    assert inj["U1.3"] < 0 and inj["U1.4"] > 0           # drawn from VIN, returned to ground
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)


def _inv_buck_parts():
    import critical_fixtures as CF
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in INV_BUCK:
                net, f2, pt = INV_BUCK[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS63710" if ref == "U1" else val, lib, x, y, rot, out, cy))
    return parts + [FLY]


def test_an_inverting_bucks_bus_and_duty_are_a_bucks(tmp_path, monkeypatch):
    """Its switch stands off V_in (the flying capacitor holds the swing), not V_in + |V_out|, and its D is
    |V_out| / V_in, in the evaluator's parameters and the router's operating point alike."""
    import critical_fixtures as CF
    from types import SimpleNamespace

    from kae.excite import params as PA
    from kae.excite.beliefs import Ledger
    from kae.route.critical_modules import cell_operating
    monkeypatch.setattr(CF, "PARTS", _inv_buck_parts())
    monkeypatch.setenv("KAE_CELLS_INVBUCK", "1")
    br = build(load(str(CF.write_board(tmp_path))))
    br["nets"]["VIN"]["volts"] = 12.0
    s = _cells(br)[CELL]
    assert s["excite"]["V"] in (None, 12.0)
    src = SimpleNamespace(meta={"cell": CELL, "cls": "inverting", "bus": "VIN"}, name=CELL)
    P = PA.cell(Ledger(), src, br, None, None, "")
    assert P["V"].typ == pytest.approx(12.0) and P["D"].typ == pytest.approx(5.0 / 12.0)
    ctx = SimpleNamespace(volts=lambda n: {"VIN": 12.0, "-5V": 5.0}.get(n), terms=None, opts={}, brief=br, parts={},
                          nets=br["nets"])
    assert cell_operating(ctx, SimpleNamespace(id=CELL, kind="cell", spec=s))[2] == pytest.approx(5.0 / 12.0)


def test_the_evaluator_prices_an_inverting_bucks_hot_loop(tmp_path, monkeypatch):
    """The inverting buck on the routed hot-loop board (its loop the buck's: C1, U1's input and ground pins): its
    observations are emitted, the losses positive, the overshoot bound at its V_in bus."""
    import critical_fixtures as CF
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from kae.excite.evaluate import evaluate
    from kae.physics import criteria as CR
    monkeypatch.setattr(CF, "PARTS", _inv_buck_parts())
    monkeypatch.setenv("KAE_CELLS_INVBUCK", "1")
    p = write_hotloop_board(tmp_path, "closed")
    p.write_text(p.read_text().replace('(net "+3V3")', '(net "-5V")').replace('(net "VIN")', '(net "+12V")'))
    ev = evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125)
    obs = {o["id"]: o for o in ev["observations"] if o["scope"].get("source") == f"cell:{CELL}"}
    assert ev["open_cells"] == [] and min(obs["loss.loop"]["values"]) > 0 and min(obs["loss.loop_ac"]["values"]) > 0
    assert obs["overshoot.peak"]["reference"]["value"] == pytest.approx(CR.overshoot_limits(12.0)[0])


def test_the_evaluator_and_the_dc_band_take_a_dual_rail_ics_negative_half(tmp_path, monkeypatch):
    """With KAE_CELLS_DUALRAIL the evaluator excites and prices the negative half (here unrouted: an open loop,
    priced at its caps, its bus V_in + |V_out|), and its DC feed (the IC's VNEG pin takes the output current back)
    balances."""
    import critical_fixtures as CF
    from hotloop_fixtures import J2, plane_fills
    from kae.excite import dc as DC
    from kae.excite.evaluate import evaluate
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in DUAL:
                net, f2, pt = DUAL[(ref, n)]
                fn = f2 or fn
            out.append((n, "+12V" if net == "VIN" else net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "TPS65133" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(CF, "PARTS", parts + [J2])
    monkeypatch.setenv("KAE_CELLS_DUALRAIL", "1")
    p = str(CF.write_board(tmp_path))
    b = load(p)
    inj = DC.planned_injections(b, {"nets": {"+12V": {"source": "J1", "V_V": 12.0}, "-5V": {"V_V": -5.0}}},
                                brief=build(b, inverting=True))
    assert inj["J2.1"] > 0 and sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    ev = evaluate(p, pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125)
    obs = {o["id"]: o for o in ev["observations"] if o["scope"].get("source") == f"cell:{CELL}"}
    assert min(obs["loss.loop"]["values"]) > 0 and min(obs["loss.loop_ac"]["values"]) > 0
    assert any(o["source"] == f"cell:{CELL}" for o in ev["open_cells"])
