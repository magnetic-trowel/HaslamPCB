# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth.ds: section and grep over pdftotext output; the PDF link in an LCSC viewer page (no network)."""
import io

from haslamsynth import ds

TEXT = """Contents
6.1 Absolute Maximum Ratings ........................ 5
6.2 ESD Ratings .................................... 5
\f
6     Specifications
6.1   Absolute Maximum Ratings
                       MIN     MAX    UNIT
VDD                   -0.3      20      V
(1) Stresses beyond those listed under Absolute Maximum Ratings may cause damage.
6.2   ESD Ratings
HBM                            2000   V
\f
7     Detailed Description
IDD   Supply current   6   13   uA
"""


def test_section_skips_contents_and_stops_at_next_heading():
    out = ds.section(TEXT, "Absolute Maximum")
    assert len(out) == 1
    page, lines = out[0]
    assert page == 2 and lines[0].strip().startswith("6.1")
    assert any("VDD" in ln for ln in lines) and not any("ESD" in ln for ln in lines)


def test_grep_reports_pages():
    out = ds.grep(TEXT, r"\bIDD\b", context=0)
    assert out == [(3, ["IDD   Supply current   6   13   uA"])]


def test_viewer_page_links_the_pdf(monkeypatch, tmp_path):
    pages = {"https://www.lcsc.com/datasheet/x_C1.pdf":
             b'<html><a href="https://static.lcsc.com/pdfjs/web/viewer.html?file=a.pdf">'
             b'<a href="https://datasheet.lcsc.com/datasheet/pdf/abc.pdf?productCode=C1">',
             "https://datasheet.lcsc.com/datasheet/pdf/abc.pdf?productCode=C1": b"%PDF-1.7 ..."}

    class R(io.BytesIO):
        pass

    monkeypatch.setattr(ds.urllib.request, "urlopen", lambda req, timeout=0: R(pages[req.full_url]))
    dest = tmp_path / "a.pdf"
    got = ds._fetch("https://www.lcsc.com/datasheet/x_C1.pdf", dest)
    assert got.startswith("https://datasheet.lcsc.com/") and dest.read_bytes().startswith(b"%PDF")
