# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kaesynth.jlc: which JLC search results match a generic passive (no network)."""
from kaesynth import jlc


def cand(desc, spec, model="M", kind="base", stock=1000):
    return dict(describe=desc, componentSpecificationEn=spec, componentModelEn=model, componentLibraryType=kind,
                stockCount=stock)


def test_resistor_value_package_tolerance():
    k = "R|4.99M|0603|1%"
    assert jlc.matches(k, cand("4.99MΩ ±1% 100mW Thick Film", "0603"))
    assert not jlc.matches(k, cand("4.99MΩ ±5% Thick Film", "0603"))       # worse tolerance
    assert not jlc.matches(k, cand("4.99MΩ ±1%", "0402"))                  # other package
    assert not jlc.matches(k, cand("4.7MΩ ±1%", "0603"))                   # other value


def test_capacitor_voltage_and_dielectric_floor():
    k = "C|100nF|0603|16V|X7R"
    assert jlc.matches(k, cand("50V 100nF X7R ±10% 0603", "0603"))         # higher voltage serves
    assert not jlc.matches(k, cand("10V 100nF X7R", "0603"))               # lower voltage does not
    assert not jlc.matches(k, cand("50V 100nF Y5V", "0603"))               # worse dielectric
    assert jlc.matches("C|10uF|1206|35V|X5R", cand("50V 10uF X7R", "1206"))  # X7R serves an X5R line
    assert not jlc.matches("C|22pF|0603|50V|C0G", cand("50V 22pF X7R", "0603"))
