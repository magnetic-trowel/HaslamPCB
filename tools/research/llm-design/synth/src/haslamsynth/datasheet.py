# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`haslamsynth datasheet <MPN or C-number>`: fetch a datasheet once, keep the PDF, its text and page images
(FRICTION #11, #44).

Sources, tried in this order until one returns a PDF (each URL once, through `haslamsynth.fetch`):

1. `--url URL` (a mirror found by hand), or `--pdf FILE` (a copy the user supplied; nothing is fetched);
2. the maker's own URL pattern, from the JLC brand or the MPN prefix:
   TI `https://www.ti.com/lit/ds/symlink/<base>.pdf`, ADI/Linear/Maxim
   `https://www.analog.com/media/en/technical-documentation/data-sheets/<BASE>.pdf`,
   ST `https://www.st.com/resource/en/datasheet/<base>.pdf` (at most 2 guesses per maker);
3. the datasheet URL the JLC parts API gives (`dataManualUrl`, usually on lcsc.com);
4. the same LCSC file on `datasheet.lcsc.com`.

Seen from a cloud host on 2026-11-27: every lcsc.com datasheet URL answered 403, st.com stalled, analog.com
dropped requests; TI worked. A 403 or a timeout is reported and remembered (fetch.FAIL_TTL), never retried
in a loop; when nothing works the command says so and suggests `--url` or `--pdf`.

Output, in `<design>/datasheets/` (`--design`) or `~/.cache/haslamsynth/datasheets/`: `<MPN>.pdf`,
`<MPN>.txt` (`pdftotext -layout`, pages separated by form feeds), `<MPN>.source.json` (URL, date, sha256),
and `<MPN>-p<N>.png` for `--pages` (`pdftoppm`; schematics and layout figures do not survive text
extraction). The command prints the pages whose text names a typical application, layout, pin functions,
absolute maximum ratings or the package outline, so the next call can render just those. The datasheets
folder gets a `.gitignore` of `*`: datasheets are the vendor's copyright; cite the URL in the part card.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path

from . import fetch, jlc

SECTIONS = {
    "typical application": r"typical\s+application|application\s+circuit|reference\s+design",
    "layout": r"layout\s+(example|guidelines?|considerations?)|pcb\s+layout|board\s+layout",
    "pin functions": r"pin\s+(functions|configuration|description|assignment)",
    "absolute maximum": r"absolute\s+maximum",
    "package outline": r"package\s+(outline|drawing|dimensions)|mechanical\s+(data|drawing)|land\s+pattern",
}
AUTO_SECTIONS = ("typical application", "layout")
TI_PREFIX = ("TPS", "TLV", "LMR", "LMZ", "LM", "OPA", "INA", "TPD", "SN74", "SN65", "BQ", "UCC", "CSD", "TMP", "DRV",
             "TCAN", "ISO", "REF", "LP", "TL", "ADS", "DAC", "TXS", "TXB", "TUSB", "HD3SS")
ADI_PREFIX = ("LTC", "LT", "LTM", "ADP", "ADM", "AD", "MAX", "ADUM", "ADA")
ST_PREFIX = ("STM32", "STM8", "STGAP", "L6", "L7", "LD", "VN", "VNH", "TS", "LSM", "LIS", "ST")


def is_lcsc_code(s):
    return re.fullmatch(r"C\d{3,}", s.strip(), re.I) is not None


def safe_stem(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "part"


def lookup(query, client=None):
    """JLC record for a C-number or MPN: dict(mpn, lcsc, maker, url) (empty values when not found)."""
    q = query.strip()
    try:
        items = jlc.search(q, n=20, client=client)
    except fetch.FetchError as e:
        return dict(mpn="" if is_lcsc_code(q) else q, lcsc=q.upper() if is_lcsc_code(q) else "", maker="", url="",
                    error=str(e))
    if is_lcsc_code(q):
        hit = next((c for c in items if str(c.get("componentCode", "")).upper() == q.upper()), None)
    else:
        u = q.upper()
        hit = (next((c for c in items if str(c.get("componentModelEn", "")).upper() == u), None)
               or next((c for c in items if str(c.get("componentModelEn", "")).upper().startswith(u)), None))
    if not hit:
        return dict(mpn="" if is_lcsc_code(q) else q, lcsc=q.upper() if is_lcsc_code(q) else "", maker="", url="")
    return dict(mpn=str(hit.get("componentModelEn") or q), lcsc=str(hit.get("componentCode") or ""),
                maker=str(hit.get("componentBrandEn") or ""), url=str(hit.get("dataManualUrl") or ""))


def maker_of(mpn, brand=""):
    b = (brand or "").lower()
    if "texas" in b or b.strip() in ("ti", "ti(texas instruments)"):
        return "ti"
    if any(k in b for k in ("analog devices", "linear tech", "maxim", "adi")):
        return "adi"
    if "stmicro" in b or b.strip() == "st":
        return "st"
    if b:
        return None
    u = mpn.upper()
    for maker, prefixes in (("st", ST_PREFIX), ("adi", ADI_PREFIX), ("ti", TI_PREFIX)):
        if any(u.startswith(p) and (p[-1].isdigit() or u[len(p):len(p) + 1].isdigit()) for p in prefixes):
            return maker
    return None


def _numeric_prefixes(mpn):
    """'TPS709B33DBVR' -> ['TPS709', 'TPS709B33']: prefixes that end on a digit group, shortest first."""
    out, acc = [], ""
    for tok in re.findall(r"[A-Z]+|\d+|[^A-Z\d]+", mpn.upper()):
        acc += tok
        if tok.isdigit() and re.search(r"[A-Z]", acc):
            out.append(acc)
    return out


def maker_urls(mpn, brand=""):
    m = maker_of(mpn, brand)
    u = re.sub(r"#.*", "", mpn.upper()).strip()
    if not u or m is None:
        return []
    if m == "ti":
        pre = _numeric_prefixes(u)
        names = []
        if re.search(r"Q1$", u) and pre:
            names.append(pre[0].lower() + "-q1")
        names += [p.lower() for p in pre[:2]]
        names = list(dict.fromkeys(names))[:2]
        return [("TI", f"https://www.ti.com/lit/ds/symlink/{n}.pdf") for n in names]
    if m == "adi":
        mm = re.match(r"([A-Z]+\d+)[A-Z]*(-\d+)?", u)
        if not mm:
            return []
        names = [mm.group(1) + (mm.group(2) or ""), mm.group(1)]
        names = list(dict.fromkeys(names))[:2]
        return [("ADI", f"https://www.analog.com/media/en/technical-documentation/data-sheets/{n}.pdf") for n in names]
    if m == "st":
        n = re.sub(r"[A-Z]\d[A-Z]?$", "", u) if u.startswith("STM") else (_numeric_prefixes(u) or [u])[0]
        return [("ST", f"https://www.st.com/resource/en/datasheet/{n.lower()}.pdf")]
    return []


def lcsc_mirrors(url):
    p = urllib.parse.urlsplit(url or "")
    if (p.hostname or "").endswith("lcsc.com") and p.path.startswith("/datasheet/"):
        return [("LCSC (datasheet.lcsc.com)", "https://datasheet.lcsc.com/lcsc/" + p.path.rsplit("/", 1)[1])]
    return []


def candidates(info, extra_url=None):
    c = [("--url", extra_url)] if extra_url else []
    c += maker_urls(info.get("mpn") or "", info.get("maker") or "")
    if info.get("url"):
        c.append(("JLC API", info["url"]))
        c += lcsc_mirrors(info["url"])
    seen, out = set(), []
    for label, u in c:
        if u and u not in seen:
            seen.add(u)
            out.append((label, u))
    return out


def fetch_pdf(cands, client=None, log=print, refresh=False):
    """(label, url, bytes) of the first candidate that is a PDF, or (None, None, None); logs each try."""
    c = client or fetch.client()
    for label, url in cands:
        try:
            r = c.get(url, timeout=40, refresh=refresh, headers={"Accept": "application/pdf,*/*"})
        except fetch.FetchError as e:
            log(f"  {label}: FAILED {e}")
            continue
        if not r.body.startswith(b"%PDF"):
            c.forget("GET", url)
            log(f"  {label}: {url}: not a PDF ({r.content_type or 'no content-type'}, {len(r.body)} bytes; "
                "probably a landing or login page)")
            continue
        log(f"  {label}: {url}: PDF, {len(r.body) // 1024} kB" + (" (cached)" if r.from_cache else ""))
        return label, url, r.body
    return None, None, None


def pdftotext(pdf, txt):
    exe = shutil.which("pdftotext")
    if not exe:
        return "pdftotext not found (apt install poppler-utils)"
    p = subprocess.run([exe, "-layout", str(pdf), str(txt)], capture_output=True, text=True)
    return None if p.returncode == 0 else f"pdftotext failed: {p.stderr.strip()[:200]}"


def section_pages(text, limit=6):
    """{section: [1-based page numbers whose text matches]} from form-feed separated pdftotext output."""
    pages = text.split("\f")
    rx = {name: re.compile(r, re.I) for name, r in SECTIONS.items()}
    # a page naming four or more sections is the table of contents (or a revision history): listed apart
    contents = [i + 1 for i, pg in enumerate(pages) if sum(bool(r.search(pg)) for r in rx.values()) >= 4]
    out = {}
    for name, r in rx.items():
        hits = [i + 1 for i, pg in enumerate(pages) if i + 1 not in contents and r.search(pg)]
        if hits:
            out[name] = hits[:limit]
    if contents:
        out["contents"] = contents[:limit]
    return out


def parse_pages(spec, sections=None):
    """'3,32-35' -> [3, 32, 33, 34, 35]; 'auto' -> typical-application and layout pages (at most 4)."""
    if spec.strip().lower() == "auto":
        sections = sections or {}
        drawings = set(sections.get("package outline", []))       # land-pattern pages also say "layout"
        got = []
        for s in AUTO_SECTIONS:
            got += [p for p in sections.get(s, []) if p not in got and p not in drawings][:2]
        return sorted(got)[:4]
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        if hi < lo or hi - lo > 20:
            raise ValueError(f"page range {part!r}: give at most 21 pages, low-high")
        out += list(range(lo, hi + 1))
    return sorted(dict.fromkeys(out))


def render(pdf, pages, out_dir, stem, dpi=110):
    exe = shutil.which("pdftoppm")
    if not exe:
        return [], "pdftoppm not found (apt install poppler-utils)"
    made = []
    for n in pages:
        prefix = Path(out_dir) / f"{stem}-p{n}"
        p = subprocess.run([exe, "-r", str(dpi), "-png", "-f", str(n), "-l", str(n), "-singlefile", str(pdf),
                            str(prefix)], capture_output=True, text=True)
        if p.returncode != 0:
            return made, f"pdftoppm page {n}: {p.stderr.strip()[:200]}"
        made.append(prefix.with_suffix(".png"))
    return made, None


def out_dir_for(design=None, out=None):
    if out:
        d = Path(out)
    elif design:
        d = Path(design) / "datasheets"
    else:
        d = fetch.cache_root() / "datasheets"
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if design and not out and not gi.exists():
        gi.write_text("# datasheets are the vendor's copyright: cite the URL in the part card, do not commit\n*\n")
    return d


def _existing(d, query):
    """(stem, pdf bytes, source.json dict) of a datasheet already saved for this MPN or C-number, else None."""
    q = query.strip().upper()
    for meta_path in sorted(Path(d).glob("*.source.json")):
        stem = meta_path.name[:-len(".source.json")]
        try:
            meta = json.loads(meta_path.read_text())
        except ValueError:
            continue
        if q in (stem.upper(), str(meta.get("mpn") or "").upper(), str(meta.get("lcsc") or "").upper(),
                 str(meta.get("query") or "").upper()) and (Path(d) / f"{stem}.pdf").exists():
            return stem, (Path(d) / f"{stem}.pdf").read_bytes(), meta
    return None


def run(query, design=None, out=None, pages=None, url=None, pdf=None, refresh=False, dpi=110, client=None,
        log=print):
    """Returns an exit code; prints what it tried and where everything went."""
    d = out_dir_for(design, out)
    info = dict(mpn=query, lcsc="", maker="", url="")
    if pdf:
        stem = safe_stem(query)
        body = Path(pdf).read_bytes()
        if not body.startswith(b"%PDF"):
            log(f"{pdf}: not a PDF")
            return 2
        src = dict(url=None, label="--pdf", file=str(pdf))
    else:
        have = _existing(d, query) if not (refresh or url) else None
        if have:
            stem, body, src = have
            info.update({k: src.get(k) or "" for k in ("mpn", "lcsc", "maker")})
            log(f"{query}: already have {d / (stem + '.pdf')} (no request; --refresh fetches again)")
        else:
            info = lookup(query, client=client)
            if info.get("error"):
                log(f"  JLC lookup failed ({info['error']}); trying maker URLs only")
            stem = safe_stem(info.get("mpn") or query)
            have = _existing(d, stem) if not (refresh or url) else None
            if have:
                stem, body, src = have
                log(f"{query}: already have {d / (stem + '.pdf')}")
        if not have:
            cands = candidates(info, url)
            log(f"{query}: {info.get('mpn') or '?'} {info.get('lcsc') or ''} {info.get('maker') or ''}".rstrip()
                + f"; trying {len(cands)} source(s)")
            if not cands:
                log("  no candidate URL (maker unknown and no JLC datasheet URL): find one and pass --url URL, "
                    "or save the PDF and pass --pdf FILE")
                return 2
            label, got, body = fetch_pdf(cands, client=client, log=log, refresh=refresh)
            if body is None:
                log(f"{query}: no source returned a PDF. Find a mirror and pass --url URL, or ask the user for the "
                    "PDF and pass --pdf FILE. Do not loop on the failed hosts.")
                return 2
            src = dict(url=got, label=label)
    pdf_path = d / f"{stem}.pdf"
    if not pdf_path.exists() or pdf_path.read_bytes() != body:
        pdf_path.write_bytes(body)
    txt_path = d / f"{stem}.txt"
    err = pdftotext(pdf_path, txt_path)
    text = txt_path.read_text(errors="replace") if txt_path.exists() else ""
    secs = section_pages(text) if text else {}
    npages = text.count("\f") or None
    meta = dict(query=query, mpn=info.get("mpn"), lcsc=info.get("lcsc"), maker=info.get("maker"),
                url=src.get("url"), source=src.get("label") or src.get("source"), sha256=hashlib.sha256(body).hexdigest(),
                fetched=src.get("fetched") or datetime.date.today().isoformat(), pages=npages)
    (d / f"{stem}.source.json").write_text(json.dumps(meta, indent=1) + "\n")
    log(f"  pdf  {pdf_path}" + (f" ({npages} pages)" if npages else ""))
    log(f"  text {txt_path}" if not err else f"  text: {err}")
    if meta["url"]:
        log(f"  cite {meta['url']}")
    for s, pp in secs.items():
        log(f"  {s}: p. {', '.join(map(str, pp))}")
    if pages:
        try:
            want = parse_pages(pages, secs)
        except ValueError as e:
            log(f"  --pages: {e}")
            return 2
        if not want:
            log("  --pages auto: no typical-application or layout page found in the text; give page numbers")
        made, rerr = render(pdf_path, want, d, stem, dpi)
        for m in made:
            log(f"  png  {m}")
        if rerr:
            log(f"  render: {rerr}")
            return 2
    return 0
