# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth parts search: pitch from package names, filters, output line (network mocked)."""
import json

import pytest

from haslamsynth import cli, fetch, partsearch
from haslamsynth.partsearch import pitch_of


@pytest.mark.parametrize("pkg,desc,mm,how", [
    ("VQFN-21_L5.0-W3.0-P0.50-TL", "", 0.5, "explicit"),
    ("TSSOP-20_L6.5-W4.4-P0.65-LS6.4-BL", "", 0.65, "explicit"),
    ("HTSSOP-20", "", 0.65, "family"),
    ("SOIC-8_150mil", "", 1.27, "family"),
    ("SOP-8", "", 1.27, "family"),
    ("SOIC-7", "", 1.27, "family"),
    ("DIP-8", "", 2.54, "family"),
    ("MSOP-10", "", 0.5, "family"),
    ("SOT-23-6", "", 0.95, "family"),
    ("SOT-23-8", "", 0.65, "family"),
    ("QFN-24(4x4)", "", 0.5, "typical"),
    ("WSON-8(2x2)", "", 0.5, "typical"),
    ("LQFP-48(7x7)", "", 0.5, "typical"),
    ("QFN-36(6x6)", "", 0.65, "bound"),
    ("SSOP-10", "", None, "unknown"),          # 1.0 mm (CN3767) or 0.5 mm: not guessed
    ("0603", "", None, "unknown"),
    ("SMD", "0.4mm pitch WLCSP", 0.4, "explicit"),
])
def test_pitch_of(pkg, desc, mm, how):
    p = pitch_of(pkg, desc)
    assert (p.mm, p.how) == (mm, how)


def comp(code, model, pkg, kind="expand", stock=5000, desc="", ds="https://x/ds.pdf", brand="TI"):
    return dict(componentCode=code, componentModelEn=model, componentSpecificationEn=pkg, componentLibraryType=kind,
                stockCount=stock, describe=desc, dataManualUrl=ds, componentBrandEn=brand)


LIST = [comp("C1", "TPS552892RYQR", "VQFN-21_L5.0-W3.0-P0.50-TL", stock=900, desc="buck-boost 3A"),
        comp("C2", "TPS55165QPWPRQ1", "HTSSOP-20", stock=3000, desc="buck-boost 1A"),
        comp("C3", "XYZ123", "SSOP-10", kind="base", stock=20000, brand="Other"),
        comp("C4", "LT9999", "QFN-24(4x4)", stock=0)]


def client_with(tmp_path, items):
    c = fetch.Client(root=tmp_path, sleep=lambda s: None)
    body = json.dumps({"code": 200, "data": {"componentPageInfo": {"list": items}}}).encode()
    c.transport = lambda *a: (200, {}, body)
    return c


def test_filters_and_order(tmp_path):
    c = client_with(tmp_path, LIST)
    hits, seen = partsearch.search("buck-boost", client=c)
    assert seen == 4 and [h.lcsc for h in hits] == ["C3", "C2", "C1", "C4"]      # basic first, then stock
    assert [h.lcsc for h in partsearch.search("x", min_pitch=0.65, client=c)[0]] == ["C3", "C2"]  # P? kept
    assert [h.lcsc for h in partsearch.search("x", min_stock=1000, client=c)[0]] == ["C3", "C2"]
    assert [h.lcsc for h in partsearch.search("x", basic=True, client=c)[0]] == ["C3"]
    assert [h.lcsc for h in partsearch.search("x", package="qfn", client=c)[0]] == ["C1", "C4"]


def test_cli_line(tmp_path, monkeypatch, capsys):
    c = client_with(tmp_path, LIST[:1])
    monkeypatch.setattr(fetch, "_default", c)
    assert cli.main(["parts", "search", "TPS552892"]) == 0
    out = capsys.readouterr().out
    assert "C1 | TPS552892RYQR | ext | stk 900 | VQFN-21_L5.0-W3.0-P0.50-TL P0.5 | TI | buck-boost 3A | " \
           "https://x/ds.pdf" in out


def test_cli_reports_fetch_failure(tmp_path, monkeypatch, capsys):
    c = fetch.Client(root=tmp_path, sleep=lambda s: None)
    c.transport = lambda *a: (403, {}, b"")
    monkeypatch.setattr(fetch, "_default", c)
    assert cli.main(["parts", "search", "x"]) == 2
    assert "403" in capsys.readouterr().err
