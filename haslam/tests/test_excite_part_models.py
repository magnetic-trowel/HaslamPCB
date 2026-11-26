# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Component priors of haslam.excite.models: MLCC DC bias and ESR, polarized ESL and ESR (docs/research/physics/component-priors.md)."""
import pytest

from haslam.circuit import values as V
from haslam.excite import models as M


# ----------------------------------------------------------------------------- MLCC
@pytest.mark.parametrize("C,v,size,lo,hi", [
    (10e-6, 5.0, "0402", 0.1, 0.3),       # decoupling-pdn.md: 10 uF 6.3 V 0402 X5R ~1.5 uF at 5 V
    (10e-6, 3.3, "0805", 0.6, 0.9),       # EPCI: 10 uF 6.3 V 0805 keeps 68-88 % at 3.3 V (3 vendors)
    (100e-9, 3.3, "0402", 0.85, 0.97),
    (100e-9, 5.0, "0603", 0.88, 1.0),
])
def test_mlcc_bias_factor_matches_vendor_points(C, v, size, lo, hi):
    k, _ = M.mlcc_bias_factor(C, v, size)
    assert lo <= k <= hi


def test_mlcc_bias_factor_physics():
    assert M.mlcc_bias_factor(10e-6, 0.0, "0402")[0] == 1.0
    assert M.mlcc_bias_factor(1e-9, 12.0, "0402")[0] == 1.0             # unmarked 1 nF: class 1
    assert M.mlcc_bias_factor(100e-9, 12.0, "0402", "C0G")[0] == 1.0
    ks = [M.mlcc_bias_factor(10e-6, 5.0, s)[0] for s in ("0402", "0603", "0805", "1206")]
    assert ks == sorted(ks)                                              # a bigger body loses less
    assert M.mlcc_bias_factor(10e-6, 5.0, "0805", "Y5V")[0] < M.mlcc_bias_factor(10e-6, 5.0, "0805", "X5R")[0]
    assert M.dielectric("100nF 50V X7R 0603") == "X7R" and M.dielectric("10pF NP0") == "C0G"


def test_mlcc_esr_falls_with_capacitance():
    assert M.mlcc_esr(100e-9) == pytest.approx(0.0316, rel=0.01)
    assert M.mlcc_esr(10e-6) == pytest.approx(0.00316, rel=0.01)
    assert M.mlcc_esr(1e-12) == 0.5 and M.mlcc_esr(1e-3) == 0.002


# ----------------------------------------------------------------------------- polarized
@pytest.mark.parametrize("lib,text,esl_nH,esr", [
    ("Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A", "10uF", 1.2, 3.0),
    ("Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D", "100uF", 2.7, 0.5),
    ("Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D", "100uF T520 polymer", 2.7, 0.04),
    ("Capacitor_SMD:CP_Elec_6.3x5.8", "100uF", 4.0, 0.36),
    ("Capacitor_SMD:CP_Elec_10x10", "1000uF", 4.0, 0.08),
    ("Capacitor_THT:CP_Radial_D5.0mm_P2.00mm", "47uF", 10.0, 0.3),
    ("Capacitor_THT:CP_Radial_D10.0mm_P5.00mm", "1000uF", 20.0, 0.08),
    ("Capacitor_THT:CP_Radial_D18.0mm_P7.50mm", "4700uF", 34.0, 0.04),
])
def test_polarized_models_by_body(lib, text, esl_nH, esr):
    pkg = V.package(lib)
    assert pkg.polarized
    l, r, why = M.polar_model(pkg, text)
    assert l * 1e9 == pytest.approx(esl_nH) and r == pytest.approx(esr) and why


def test_legacy_switch(monkeypatch):
    monkeypatch.delenv("HASLAM_PART_MODELS", raising=False)
    assert not M.legacy_parts()
    monkeypatch.setenv("HASLAM_PART_MODELS", "legacy")
    assert M.legacy_parts()


def test_an_unclassified_part_is_an_ic_only_with_a_supply_pin(tmp_path):
    """An 'unknown' part with more than 3 pads was an IC by pad count: a 4-pin tactile switch between 3V3 and GND got
    a die capacitance across the rail. Its pins now must say it draws supply (or say nothing at all)."""
    from test_excite_physics_set import _board, _fp, _pad
    from haslam.circuit import brief as B
    from haslam.excite import models as M
    pads = [_pad("1", 0, 1, "3V3", "A", "passive"), _pad("2", 1, 1, "3V3", "A", "passive"),
            _pad("3", 2, 2, "GND", "B", "passive"), _pad("4", 3, 2, "GND", "B", "passive")]
    b = _board(tmp_path, ["3V3", "GND"], [_fp("XX1", "Thing", "Lib:Thing", 10, pads, 1)])
    br = B.build(b)
    br["nets"]["3V3"].update(role="rail", volts=3.3)
    next(p for p in br["parts"].values() if p["ref"] == "XX1")["kind"] = "unknown"
    bd = M.build(b, br)
    assert "XX1" not in bd.ic_nodes
    pads[0] = _pad("1", 0, 1, "3V3", "VDD", "power_in")
    b = _board(tmp_path, ["3V3", "GND"], [_fp("XX1", "Thing", "Lib:Thing", 10, pads, 1)])
    bd = M.build(b, br)
    assert "XX1" in bd.ic_nodes
