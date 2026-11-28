# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth datasheet: source order, failure reporting, text, page finding and rendering (network mocked)."""
import json
import shutil

import pytest

from haslamsynth import datasheet, fetch

POPPLER = shutil.which("pdftotext") and shutil.which("pdftoppm")


def tiny_pdf(pages):
    """A valid PDF with one line of Helvetica text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 18 Tf 72 700 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def jlc_body(items):
    return json.dumps({"code": 200, "data": {"componentPageInfo": {"list": items}}}).encode()


def test_maker_url_patterns():
    assert datasheet.maker_urls("TPS709B33DBVR", "Texas Instruments") == [
        ("TI", "https://www.ti.com/lit/ds/symlink/tps709.pdf"), ("TI", "https://www.ti.com/lit/ds/symlink/tps709b33.pdf")]
    assert datasheet.maker_urls("LM74610QDGKRQ1", "Texas Instruments")[0][1].endswith("/lm74610-q1.pdf")
    assert datasheet.maker_urls("LTC3115EDHD-1#PBF", "Analog Devices")[0][1].endswith("/data-sheets/LTC3115-1.pdf")
    assert datasheet.maker_urls("STM32G071KBT6", "")[0][1] == "https://www.st.com/resource/en/datasheet/stm32g071kb.pdf"
    assert datasheet.maker_urls("CN3767", "Consonance") == []
    assert datasheet.lcsc_mirrors("https://www.lcsc.com/datasheet/lcsc_datasheet_X_C1.pdf") == [
        ("LCSC (datasheet.lcsc.com)", "https://datasheet.lcsc.com/lcsc/lcsc_datasheet_X_C1.pdf")]


def test_parse_pages():
    assert datasheet.parse_pages("3, 32-34") == [3, 32, 33, 34]
    assert datasheet.parse_pages("auto", {"typical application": [1, 35, 36], "layout": [32, 40, 41],
                                          "package outline": [40]}) == [1, 32, 35, 41]


def test_contents_page_kept_apart():
    toc = "Typical Application ... 1\nLayout Guidelines ... 16\nPin Functions ... 3\nAbsolute Maximum Ratings ... 4"
    s = datasheet.section_pages("\f".join(["Typical Application", toc, "Layout Example"]))
    assert s["contents"] == [2] and s["typical application"] == [1] and s["layout"] == [3]
    with pytest.raises(ValueError):
        datasheet.parse_pages("1-40")


def test_falls_through_failures_to_jlc_url_and_says_why(tmp_path):
    pdf = tiny_pdf(["Features", "Typical Application"])
    jlc_item = dict(componentCode="C2864604", componentModelEn="TPS709B33DBVR", componentBrandEn="Texas Instruments",
                    dataManualUrl="https://www.lcsc.com/datasheet/x_C2864604.pdf")
    answers = {"https://jlcpcb.com": (200, {}, jlc_body([jlc_item])),
               "https://www.ti.com/lit/ds/symlink/tps709.pdf": (404, {}, b""),
               "https://www.ti.com/lit/ds/symlink/tps709b33.pdf": (200, {"content-type": "text/html"}, b"<html>"),
               "https://www.lcsc.com/datasheet/x_C2864604.pdf": (200, {"content-type": "application/pdf"}, pdf)}
    c = fetch.Client(root=tmp_path / "cache", sleep=lambda s: None)
    sent = []

    def transport(method, url, headers, body, timeout):
        sent.append(url)
        return next(v for k, v in answers.items() if url.startswith(k))
    c.transport = transport
    log = []
    rc = datasheet.run("C2864604", out=tmp_path / "ds", client=c, log=log.append)
    assert rc == 0
    text = "\n".join(log)
    assert "404" in text and "not a PDF" in text and "lcsc.com/datasheet/x_C2864604.pdf: PDF" in text
    assert (tmp_path / "ds" / "TPS709B33DBVR.pdf").read_bytes() == pdf
    meta = json.loads((tmp_path / "ds" / "TPS709B33DBVR.source.json").read_text())
    assert meta["url"].endswith("x_C2864604.pdf") and meta["lcsc"] == "C2864604"
    n = len(sent)
    assert datasheet.run("C2864604", out=tmp_path / "ds", client=c, log=log.append) == 0
    assert len(sent) == n                                     # saved: no request at all


def test_all_sources_fail_clearly_without_loops(tmp_path):
    c = fetch.Client(root=tmp_path / "cache", sleep=lambda s: None)
    sent = []

    def transport(method, url, headers, body, timeout):
        sent.append(url)
        if "jlcpcb" in url:
            return 200, {}, jlc_body([dict(componentCode="C1", componentModelEn="IP6559", componentBrandEn="INJOINIC",
                                           dataManualUrl="https://www.lcsc.com/datasheet/ip6559_C1.pdf")])
        return 403, {}, b""
    c.transport = transport
    log = []
    assert datasheet.run("IP6559", out=tmp_path / "ds", client=c, log=log.append) == 2
    assert len(sent) == 3                                     # JLC, lcsc.com, datasheet.lcsc.com: once each
    assert "--url" in log[-1] and "--pdf" in log[-1]
    assert datasheet.run("IP6559", out=tmp_path / "ds", client=c, log=log.append) == 2
    assert len(sent) == 3                                     # refusals remembered


@pytest.mark.skipif(not POPPLER, reason="needs poppler-utils")
def test_local_pdf_text_sections_and_render(tmp_path):
    src = tmp_path / "user.pdf"
    src.write_bytes(tiny_pdf(["Absolute Maximum Ratings", "Typical Application", "PCB Layout Guidelines"]))
    design = tmp_path / "designs" / "x"
    log = []
    assert datasheet.run("LTC3115-1", design=design, pdf=src, pages="auto", log=log.append) == 0
    d = design / "datasheets"
    assert (d / ".gitignore").read_text().strip().endswith("*")
    assert "Typical Application" in (d / "LTC3115-1.txt").read_text()
    text = "\n".join(log)
    assert "typical application: p. 2" in text and "layout: p. 3" in text and "absolute maximum: p. 1" in text
    assert (d / "LTC3115-1-p2.png").exists() and (d / "LTC3115-1-p3.png").exists()
