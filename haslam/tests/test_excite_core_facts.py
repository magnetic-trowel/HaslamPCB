# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A part's core source reads its facts (bme280-array F48: a 2 uA TCA9548A I2C switch kept a 10 mA, 50 MHz class
core and showed a 245 mV supply.peak), and haslam says which parts run on class priors (F36)."""
import math
from types import SimpleNamespace as NS

import pytest

from haslam.circuit import brief as B
from haslam.excite import models as M, params as PA, prior_parts as PP, sources as S
from haslam.excite.beliefs import Ledger
from haslam.intent import facts as F

from test_excite_physics_set import _board, _fp, _pad


def _core(meta=None):
    tr = 2e-9
    return NS(name="core:U4:+1V8", kind="core",
              meta=dict(dict(kind="core", ref="U4", rail="+1V8", I=0.01, f_e=1 / (math.pi * tr), f_rep=50e6), **(meta or {})))


def _gen(facts):
    return PA.generic(Ledger(), _core(), "core", facts)


def test_without_facts_a_core_is_its_class_prior():
    p = _gen(None)
    assert (p["I"].typ, p["I"].lo, p["I"].hi, p["I"].source) == (0.01, pytest.approx(0.01 / 3), 0.03, "prior")
    assert p["t_i"].source == p["f_sw"].source == "prior"
    assert _gen({"parts": {"U9": {"core": False}}})["I"].source == "prior"


def test_a_stated_supply_draw_caps_the_core_current_by_charge_balance():
    p = _gen({"parts": {"U4": {"I_A": [1e-7, 2e-6, 1e-5]}}})["I"]
    # I <= I_A / (t f): 2 uA / (2 ns x 50 MHz) = 20 uA, each end by the same end of I_A
    assert p.typ == pytest.approx(2e-5) and p.lo == pytest.approx(1e-6) and p.hi == pytest.approx(1e-4)
    assert p.source == "intent" and "parts.U4.I_A" in p.basis and "core_I_A" in p.basis
    # an MCU whose stated draw allows the class step keeps it (cap 200 mA > 10 mA), and its basis says so
    m = _gen({"parts": {"U4": {"I_A": 0.02}}})["I"]
    assert (m.typ, m.source) == (0.01, "prior") and "within the stated supply draw" in m.basis


def test_core_facts_replace_the_class_values_and_the_basis_names_them():
    p = _gen({"parts": {"U4": {"I_A": 0.02, "core_I_A": [1e-6, 1e-5, 1e-4], "core_t_s": [5e-9, 2e-8],
                               "core_f_Hz": 1e5}}})
    assert (p["I"].typ, p["I"].source) == (1e-5, "intent") and "parts.U4.core_I_A" in p["I"].basis
    assert (p["t_i"].typ, p["t_i"].source) == (pytest.approx(1e-8), "intent") and "core_t_s" in p["t_i"].basis
    assert (p["f_sw"].typ, p["f_sw"].source) == (1e5, "intent") and "core_f_Hz" in p["f_sw"].basis
    # the cap uses the stated edge and repetition: a 100 kHz core may draw far more per edge than at 50 MHz
    q = _gen({"parts": {"U4": {"I_A": 2e-6, "core_f_Hz": 1e5}}})["I"]
    assert q.typ == pytest.approx(0.01)


@pytest.mark.parametrize("bad, msg", [
    ({"parts": {"U4": {"core": "no"}}}, "true or false"),
    ({"parts": {"U4": {"core_f_Hz": 0}}}, "positive"),
    ({"parts": {"U4": {"core_t_s": [-1e-9, 1e-9]}}}, "positive"),
    ({"parts": {"U4": {"core_I_A": [1e-3, 1e-5, 1e-4]}}}, "lo <= typ <= hi"),
])
def test_check_facts_validates_the_core_keys(bad, msg):
    with pytest.raises(F.FactsError, match=msg):
        F.check_facts(bad)


def test_check_facts_takes_the_core_keys():
    F.check_facts({"parts": {"U4": {"core": False, "core_I_A": 0, "core_t_s": 1e-9, "core_f_Hz": [1e5, 4e5]}}})
    assert "core_I_A" in F.PART_CORE_KEYS


def _i2c_switch_board(tmp_path):
    nets = ["+3V3", "GND", "SDA"]
    j1 = [_pad("1", 0, 1, "+3V3"), _pad("2", 1, 2, "GND")]
    u1 = [_pad("1", 0, 1, "+3V3", "VCC", "power_in"), _pad("2", 1, 2, "GND", "GND", "power_in"),
          _pad("3", 2, 3, "SDA", "SDA", "bidirectional")]
    return _board(tmp_path, nets, [_fp("J1", "Conn_01x02", "Connector:Conn_01x02", 5, j1, 1),
                                   _fp("U1", "TCA9548A", "Interface_Expansion:TCA9548A", 20, u1, 2)])


def test_core_false_removes_the_core_source(tmp_path):
    b = _i2c_switch_board(tmp_path)
    br = B.build(b)
    assert [s.name for s in S.add_all(M.build(b, br), br) if s.kind == "core"] == ["core:U1:+3V3"]
    bd = M.build(b, br)
    srcs = S.add_all(bd, br, intent={"parts": {"U1": {"core": False}}})
    assert not [s for s in srcs if s.kind == "core"]
    assert any("core:U1" in a and "core: false" in a for a in bd.assumptions)
    # a haslam.intent/1 document is read through its facts
    bd = M.build(b, br)
    doc = {"schema": F.SCHEMA, "facts": {"parts": {"U1": {"core": False}}}}
    assert not [s for s in S.add_all(bd, br, intent=doc) if s.kind == "core"]


def test_parts_on_priors_names_the_parts_and_the_facts_that_fix_them(tmp_path):
    b = _i2c_switch_board(tmp_path)
    rows = PP.parts_on_priors(b, {})
    assert [r["ref"] for r in rows] == ["U1"]
    fixes = {it["fix"] for it in rows[0]["items"]}
    assert fixes == {"parts.U1.I_A", "parts.U1.core_I_A (or core: false)"}
    ln = PP.lines(rows)
    assert len(ln) == 1 and ln[0].startswith("U1") and "parts.U1.I_A" in ln[0] and "class prior" in ln[0]
    # a stated draw: no supply prior, and it caps the core (source intent)
    assert PP.parts_on_priors(b, {"parts": {"U1": {"I_A": [1e-7, 2e-6, 1e-5]}}}) == []
    # core: false and a stated draw: nothing on priors; core_I_A alone leaves the draw
    assert PP.parts_on_priors(b, {"parts": {"U1": {"I_A": 2e-6, "core": False}}}) == []
    rows = PP.parts_on_priors(b, {"parts": {"U1": {"core_I_A": 1e-5}}})
    assert [it["fix"] for it in rows[0]["items"]] == ["parts.U1.I_A"]


def test_the_priors_cli_prints_one_line_per_part(tmp_path, capsys):
    import json

    from haslam.intent.__main__ import main
    _i2c_switch_board(tmp_path)
    f = tmp_path / "facts.json"
    f.write_text(json.dumps({"parts": {}}))
    assert main(["priors", str(tmp_path / "t.kicad_pcb"), "--intent", str(f)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("U1") and out[-1].startswith("1 part(s) on class priors")
    assert main(["priors", str(tmp_path / "t.kicad_pcb"), "--intent", str(f), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["ref"] == "U1"
