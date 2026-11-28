# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth fp-fetch and the footprint reader on legacy `(module ...)` files (network mocked)."""
import json

import pytest

from haslamsynth import fetch, fpfetch
from haslamsynth.kicadlib import FootprintLibs, read_footprint

# a synthetic 4-pad legacy footprint in easyeda2kicad's layout (not EasyEDA data)
LEGACY = """(module easyeda2kicad:TEST-4_P0.50 (layer F.Cu) (tedit 5DC5F6A4)
\t(attr smd)
\t(fp_text reference REF** (at 0 -2) (layer F.SilkS)
\t\t(effects (font (size 1 1) (thickness 0.15)))
\t)
\t(fp_text value TEST-4_P0.50 (at 0 2) (layer F.Fab)
\t\t(effects (font (size 1 1) (thickness 0.15)))
\t)
\t(pad 1 smd rect (at -0.75 0 0) (size 0.25 0.6) (layers F.Cu F.Paste F.Mask))
\t(pad 2 smd rect (at -0.25 0 0) (size 0.25 0.6) (layers F.Cu F.Paste F.Mask))
\t(pad 3 smd rect (at 0.25 0 0) (size 0.25 0.6) (layers F.Cu F.Paste F.Mask))
\t(pad 4 smd rect (at 0.75 0 0) (size 0.25 0.6) (layers F.Cu F.Paste F.Mask))
\t(pad "" np_thru_hole circle (at 0 1 0) (size 0.5 0.5) (drill 0.5) (layers *.Cu *.Mask))
)
"""

PARTS = """
from haslamsynth import PinDef
from haslamsynth.lib import IC
U = IC("TEST4", footprint="custom:TEST", pins=[PinDef("1", "VIN", "power_in"), PinDef("2", "GND", "power_in"),
       PinDef("3", "SW", "power_out"), PinDef("4", "FB", "input")])
U5 = IC("TEST5", footprint="custom:TEST", pins=[PinDef(str(i), f"P{i}") for i in range(1, 6)])
"""


def test_reader_reads_legacy_module_pads(tmp_path):
    lib = tmp_path / "custom.pretty"
    lib.mkdir()
    (lib / "T.kicad_mod").write_text(LEGACY)
    fl = FootprintLibs(root=tmp_path / "none", local=[tmp_path])
    assert fl.pads("custom:T") == {"1", "2", "3", "4"}          # was frozenset() with the quoted-pad regex
    assert fl.legacy("custom:T")
    assert read_footprint(lib / "T.kicad_mod")[1] == "module"


def test_part_pins_and_check(tmp_path):
    p = tmp_path / "parts.py"
    p.write_text(PARTS)
    pins = fpfetch.part_pins(f"{p}:U")
    assert pins == {"1": "VIN", "2": "GND", "3": "SW", "4": "FB"}
    assert fpfetch.check_pads({"1", "2", "3", "4", "21"}, pins) == ([], ["21"])
    assert fpfetch.check_pads({"1", "2"}, pins) == (["3", "4"], [])
    with pytest.raises(fpfetch.FpFetchError, match="no part card"):
        fpfetch.part_pins(f"{p}:NOPE")


def test_fetch_cad_reports_missing_component(tmp_path):
    c = fetch.Client(root=tmp_path, sleep=lambda s: None)
    c.transport = lambda *a: (200, {}, json.dumps({"success": False, "code": 404, "message": "not found"}).encode())
    with pytest.raises(fpfetch.FpFetchError, match="no CAD data"):
        fpfetch.fetch_cad("C1", client=c)
    assert c.cached("GET", fpfetch.EASYEDA_API.format(lcsc="C1")) is None      # a refusal body is not cached


def test_add_source_and_rename():
    s = fpfetch.add_source(LEGACY, "C123", date="2026-11-28")
    assert s.splitlines()[1].startswith('\t(property "Source" "EasyEDA/LCSC C123') and "no licence stated" in s
    assert fpfetch.rename('(footprint "OLD"\n\t(version 1)\n)', "NEW").startswith('(footprint "NEW"')


def _fake_pipeline(monkeypatch, tmp_path):
    c = fetch.Client(root=tmp_path / "cache", sleep=lambda s: None)
    sent = []

    def transport(method, url, headers, body, timeout):
        sent.append(url)
        return 200, {}, json.dumps({"success": True, "result": {"packageDetail": {"dataStr": {"head": {}}}}}).encode()
    c.transport = transport
    monkeypatch.setattr(fpfetch, "to_legacy", lambda cad: ("TEST-4_P0.50", LEGACY))
    return c, sent


@pytest.mark.kicad
def test_run_upgrades_renames_and_checks(tmp_path, monkeypatch):
    c, sent = _fake_pipeline(monkeypatch, tmp_path)
    design = tmp_path / "designs" / "x"
    (tmp_path / "parts.py").write_text(PARTS)
    log = []
    rc = fpfetch.run("C123", design=design, name="TEST4_X", check_part=f"{tmp_path / 'parts.py'}:U", client=c,
                     log=log.append)
    out = design / "footprints" / "custom.pretty" / "TEST4_X.kicad_mod"
    text = "\n".join(log)
    assert rc == 0, text
    body = out.read_text()
    assert body.startswith('(footprint "TEST4_X"') and "Source" in body and "no licence stated" in body
    assert read_footprint(out) == (frozenset({"1", "2", "3", "4"}), "footprint")
    assert "no stated licence" in text and "pads match" in text and 'custom:TEST4_X' in text
    # exists -> refused; a card with a pin the land pattern lacks -> exit 1; EasyEDA asked only once
    assert fpfetch.run("C123", design=design, name="TEST4_X", client=c, log=log.append) == 1
    rc = fpfetch.run("C123", design=design, name="TEST4_X", force=True, check_part=f"{tmp_path / 'parts.py'}:U5",
                     client=c, log=log.append)
    assert rc == 1 and "card pins ['5'] have no pad" in log[-1]
    assert len(sent) == 1


def test_run_without_kicad_cli_says_so(tmp_path, monkeypatch):
    c, _ = _fake_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr("haslamsynth.build.kicad_cli", lambda: None)
    log = []
    assert fpfetch.run("C123", out=tmp_path / "o.pretty", client=c, log=log.append) == 2
    assert "kicad-cli not found" in log[-1]

