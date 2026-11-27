# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth.jlc: which JLC search results match a generic passive; search filters, stock and setup fees
(no network: the parts search is replaced by canned results)."""
import json

from haslamsynth import Design, PartDef, PinDef, jlc


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


def test_search_filters(monkeypatch):
    rows = [dict(cand("1.8V~5.5V 75nA buck-boost", "WSON-10", "TPS63900", "expand", 17000), componentCode="C1"),
            dict(cand("3V~17V 4uA buck", "SOT-583", "TPS629203", "expand", 50), componentCode="C2"),
            dict(cand("LDO 1uA", "SOT-23", "XC6206", "base", 900000), componentCode="C3")]
    monkeypatch.setattr(jlc, "_search", lambda q, n=100: rows)
    assert [r["lcsc"] for r in jlc.search("x")] == ["C3", "C1", "C2"]       # >= 1000 in stock, basic, then stock
    assert [r["lcsc"] for r in jlc.search("x", basic=True)] == ["C3"]
    assert [r["lcsc"] for r in jlc.search("x", min_stock=100)] == ["C3", "C1"]
    assert [r["lcsc"] for r in jlc.search("x", match="nA")] == ["C1"]           # case-sensitive: units


def _ic_design(quantity=None, sensors=16):
    d = Design("stk")
    d.net("GND", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.net("V", domain="LV", v=(0, 3.6), kind="power")
    card = PartDef(mpn="BME280", category="ic", footprint="Package_TO_SOT_SMD:SOT-23",
                   pins=[PinDef("1", "VDD"), PinDef("2", "GND")], fields={"LCSC": "C92489"})
    res = PartDef(mpn="R1M", category="resistor", footprint="Resistor_SMD:R_0402_1005Metric",
                  pins=[PinDef("1"), PinDef("2")], fields={"LCSC": "C26082"})
    b = d.block("b")
    for _ in range(sensors):
        u = b.add(card)
        d.nets["V"].connect(u["VDD"]); d.nets["GND"].connect(u["GND"])
    r = b.add(res)
    d.nets["V"].connect(r["1"]); d.nets["GND"].connect(r["2"])
    d.board(width_mm=50, height_mm=50, quantity=quantity)
    return d.finalize()


def _run(d, cache, tmp_path):
    p = tmp_path / "jlc.json"
    p.write_text(json.dumps(cache))
    out = []
    summary = jlc.stock_findings(d, p, lambda c, s, m, o=(): out.append((c, s, m)))
    return out, summary


def test_stock_against_quantity(tmp_path):
    """FRICTION F6: 1 BME280 in stock for 16 per board, and nothing warned."""
    cache = {"LCSC|C92489": dict(lcsc="C92489", model="BME280", basic=False, stock=1, at="2026-11-26"),
             "R|1M|0402|1%": dict(lcsc="C26082", basic=False, stock=50000, at="2026-11-26")}
    out, s = _run(_ic_design(), cache, tmp_path)
    warn = [m for c, sev, m in out if c == "bom.stock" and sev == "warning"]
    assert len(warn) == 1 and "C92489" in warn[0] and "80 needed" in warn[0]        # 16 x 5 boards
    fees = [m for c, sev, m in out if c == "bom.setup_fees"]
    assert fees and "2 extended" in fees[0] and "C26082" in fees[0].split(";")[1]   # the resistor: maybe movable
    cache["LCSC|C92489"]["stock"] = 0
    out, _ = _run(_ic_design(quantity=1), cache, tmp_path)
    assert [sev for c, sev, m in out if c == "bom.stock"] == ["error"]
    cache["LCSC|C92489"]["stock"] = 100
    out, _ = _run(_ic_design(quantity=2), cache, tmp_path)
    assert not [m for c, sev, m in out if c == "bom.stock"]


def test_stock_unknown_codes_warn_once(tmp_path):
    out, s = _run(_ic_design(), {}, tmp_path)
    assert [sev for c, sev, m in out if c == "bom.stock"] == ["warning"] and s["unknown"] == ["C26082", "C92489"]


def test_apply_marks_carded_parts(tmp_path):
    d = _ic_design(sensors=1)
    p = tmp_path / "jlc.json"
    p.write_text(json.dumps({"LCSC|C92489": dict(lcsc="C92489", basic=False, stock=779, at="2026-11-26")}))
    jlc.apply(d, p)
    u = [x for x in d.all_parts() if x.defn.mpn == "BME280"][0]
    assert u.fields["JLC"] == "expand, stock 779 on 2026-11-26"
