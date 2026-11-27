# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Datasheets: fetch a PDF once, keep its `pdftotext -layout` text, print the lines or section asked for.

`haslamsynth ds SOURCE [--grep REGEX] [--section "Absolute Maximum"] [--design designs/<slug>/design.py]`

SOURCE is a URL, an MPN, an LCSC code (C92489) or, with --design, a reference or MPN of that design (its card's
`datasheet=`). An MPN or code without a usable vendor URL goes to the JLC/LCSC parts search, whose record carries the
LCSC-hosted PDF (brief-to-board G15: vendor sites often refuse scripts; LCSC serves the same PDF). A download that is
not a PDF (an HTML landing page) falls back the same way.

The cache is `$HASLAMSYNTH_DS_CACHE` (default `~/.cache/haslamsynth/ds`): `<name>-<hash>.pdf` and `.txt`. Page
numbers come from pdftotext's form feeds. A section runs from a heading that matches to the next numbered heading of
the same or a higher level (`7.3 ...` ends at `7.4 ...` or `8 ...`), or `max_lines`; table-of-contents lines (dot
leaders, a trailing page number) are skipped.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) haslamsynth-ds"}
_HEAD = re.compile(r"^\s{0,6}(\d+(?:\.\d+){0,3})\.?\s+[A-Z][A-Za-z]")
_TOC = re.compile(r"(\.\s?){4,}|\s{3,}\d{1,3}\s*$")


def cache_dir():
    d = Path(os.environ.get("HASLAMSYNTH_DS_CACHE") or Path.home() / ".cache" / "haslamsynth" / "ds")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_url(s):
    return str(s).startswith(("http://", "https://"))


_PDF_LINK = re.compile(rb"""https?://[^"'\s<>]+?\.pdf(?:\?[^"'\s<>]*)?""")


def _fetch(url, dest, hops=1):
    """Download url to dest; an HTML page (LCSC's datasheet viewer, a product page) is searched for the PDF it
    links (datasheet.lcsc.com first) and that is fetched instead, once."""
    req = urllib.request.Request(url, headers=UA)
    data = urllib.request.urlopen(req, timeout=60).read()
    if data.startswith(b"%PDF"):
        dest.write_bytes(data)
        return url
    links = [m.decode() for m in dict.fromkeys(_PDF_LINK.findall(data))]
    links = [u for u in links if u != url and "viewer.html" not in u]
    links.sort(key=lambda u: "datasheet.lcsc.com" not in u)
    if hops > 0 and links:
        return _fetch(links[0], dest, hops - 1)
    raise ValueError(f"{url} did not return a PDF ({len(data)} bytes, starts {data[:15]!r}) nor link one")


def _lcsc_pdf(query):
    """(LCSC datasheet URL, what matched) for an MPN or LCSC code, from the JLC parts search, else (None, None)."""
    from . import jlc
    rows = [r for r in jlc.search(query) if r.get("datasheet")]
    exact = [r for r in rows if query in (r["lcsc"], r["model"])]
    pick = (exact or rows or [None])[0]
    return (pick["datasheet"], f"{pick['lcsc']} {pick['model']}") if pick else (None, None)


def resolve_source(source, design=None):
    """[(url, note)] to try in order for SOURCE (see the module doc)."""
    tries = []
    mpn = source
    if design is not None:
        for p in design.all_parts():
            if source in (p.ref, p.defn.mpn, p.value):
                ds = p.defn.datasheet
                if ds and _is_url(ds):
                    tries.append((ds, f"{p.ref} card datasheet"))
                code = str({**p.defn.fields, **p.fields}.get("LCSC") or "")
                mpn = code or p.defn.mpn or source
                break
    if _is_url(source):
        tries.append((source, "URL"))
        return tries
    url, what = _lcsc_pdf(mpn)
    if url:
        tries.append((url, f"LCSC datasheet of {what}"))
    return tries


def fetch(source, design=None, log=print):
    """(pdf path, txt path, note) for SOURCE, downloading and converting once."""
    errors = []
    for url, note in resolve_source(source, design):
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(url.split("?")[0]).stem)[:40] or "datasheet"
        base = cache_dir() / f"{stem}-{hashlib.sha1(url.encode()).hexdigest()[:10]}"
        pdf, txt = base.with_suffix(".pdf"), base.with_suffix(".txt")
        try:
            if not pdf.exists():
                _fetch(url, pdf)
            if not txt.exists():
                subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True, capture_output=True)
            return pdf, txt, f"{note}: {url}"
        except Exception as e:  # noqa: BLE001 - try the next source; all failures are reported
            errors.append(f"{note} {url}: {type(e).__name__}: {e}")
            log(f"  {note} failed ({type(e).__name__}); trying the next source")
    hint = " (a vendor page that is not a PDF: give the MPN or LCSC code instead, which uses LCSC's copy)" \
        if _is_url(source) else ""
    raise SystemExit("no datasheet found for " + source + hint + (":\n  " + "\n  ".join(errors) if errors else
                                                                  ": the JLC/LCSC search found no datasheet"))


def pages(text):
    """[(page number, line)] for every line of pdftotext output (pages split at form feeds)."""
    out = []
    for i, pg in enumerate(text.split("\f"), 1):
        out += [(i, ln) for ln in pg.splitlines()]
    return out


def grep(text, pattern, context=2):
    """Blocks of lines around each match: [(page, [lines])], overlapping blocks merged."""
    lines = pages(text)
    rx = re.compile(pattern, re.I)
    hits = [i for i, (_, ln) in enumerate(lines) if rx.search(ln)]
    blocks, cur = [], None
    for i in hits:
        lo, hi = max(0, i - context), min(len(lines), i + context + 1)
        if cur and lo <= cur[1]:
            cur[1] = hi
        else:
            cur = [lo, hi]
            blocks.append(cur)
    return [(lines[lo][0], [ln for _, ln in lines[lo:hi]]) for lo, hi in blocks]


def _level(num):
    return num.count(".") + 1


def section(text, title, max_lines=80, max_hits=3):
    """[(page, [lines])]: each body occurrence of a heading matching `title` (case-insensitive) up to the next
    numbered heading of the same or a higher level, at most max_lines lines."""
    lines = pages(text)
    rx = re.compile(re.escape(title) if not any(c in title for c in "\\[]()|*+?^$") else title, re.I)
    hits = [i for i, (_, ln) in enumerate(lines) if rx.search(ln) and not _TOC.search(ln)]
    heads = [i for i in hits if _HEAD.match(lines[i][1])]
    out, covered = [], -1
    for i in heads or hits:               # a numbered heading beats a mention in running text
        if i <= covered:
            continue
        m = _HEAD.match(lines[i][1])
        lvl = _level(m.group(1)) if m else None
        body = [lines[i][1]]
        for j in range(i + 1, min(len(lines), i + max_lines)):
            h = _HEAD.match(lines[j][1])
            if h and not _TOC.search(lines[j][1]) and (lvl is None or _level(h.group(1)) <= lvl):
                break
            body.append(lines[j][1])
        covered = i + len(body) - 1
        out.append((lines[i][0], body))
        if len(out) >= max_hits:
            break
    return out
