# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""JLCPCB/LCSC part numbers, stock and basic/extended flags for a design's parts.

`haslamsynth jlc designs/<slug>/design.py` looks up every generic resistor and ceramic capacitor (no MPN, no
LCSC field) in the JLCPCB parts search, and every part that carries an `LCSC` field (ICs, FETs, connectors) by
its code, and writes `designs/<slug>/jlc.json`: {key: {lcsc, model, basic, preferred, stock, spec, describe,
datasheet, query, at}} (passives keyed `R|value|pkg|tol` / `C|value|pkg|V|dielectric`, carded parts `LCSC|Cnnn`).
`haslamsynth build` reads that file (no network), puts `LCSC` and `JLC` fields on the parts, so the schematic,
the board and the fab BOM (synth/scripts/fab_outputs.py) carry them, checks stock against quantity x boards
(`bom.stock`) and counts setup fees (`bom.setup_fees`): `stock_findings`.

`haslamsynth jlc --search MPN_or_keyword ... [--basic] [--min-stock N] [--match REGEX]` prints candidates (code,
basic/extended, stock, package, description) to pick an IC, or to check a part before it goes on a card.

A candidate matches when its package is the part's, its value is the part's (0.1 %), a resistor's tolerance is
no worse, and a capacitor's voltage is no lower and its dielectric no worse (X5R accepts X5R or X7R; X7R accepts
X7R, C0G/NP0). Parts with at least 1000 in stock come first, then basic parts (no per-order setup fee), then stock. A key with no match is written with
lcsc null and reported, so a person picks one by hand (add it to the part's fields in parts.py).
"""
from __future__ import annotations

import datetime
import json
import re
import time
import urllib.request
from pathlib import Path

from .units import parse_value

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
DIELECTRIC_OK = {"X5R": ("X5R", "X7R", "X7S", "C0G", "NP0"), "X7R": ("X7R", "X7S", "C0G", "NP0"),
                 "C0G": ("C0G", "NP0"), "NP0": ("C0G", "NP0")}
_VAL = re.compile(r"(\d+(?:\.\d+)?)\s*([pnuµmkKM]?)(Ω|ohm|F)\b")
_VOLT = re.compile(r"(\d+(?:\.\d+)?)\s*V\b")
_TOL = re.compile(r"±\s*(\d+(?:\.\d+)?)\s*%")
_MULT = {"": 1, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6}


def kind_of(part):
    c = part.defn.category
    if c == "resistor":
        return "R"
    if c in ("capacitor", "capacitor_ceramic"):
        return "C"
    return None


def wants(part):
    """The part needs a looked-up number: generic, a resistor or ceramic capacitor, no LCSC field yet."""
    f = {**part.defn.fields, **part.fields}
    return part.on_board and part.defn.generic and kind_of(part) and not f.get("LCSC") and not part.dnp


def key_of(part):
    f = part.defn.fields
    pkg = f.get("Package") or re.sub(r".*_(\d{4})_\d{4}Metric$", r"\1", part.defn.footprint or "")
    if kind_of(part) == "R":
        return f"R|{part.value}|{pkg}|{f.get('Tolerance', '1%')}"
    return f"C|{part.value}|{pkg}|{f.get('Voltage', '')}|{f.get('Dielectric', '')}"


def _query(key):
    k = key.split("|")
    if k[0] == "R":
        return f"{k[1]}Ω {k[2]} {k[3]}"
    # value and package only: the voltage and dielectric are filtered after, so a basic 50 V part can serve a
    # 16 V line (a 16 V query found only extended 16 V parts)
    return f"{k[1]} {k[2]}"


def _search(q, n=100):
    req = urllib.request.Request(API, data=json.dumps({"keyword": q, "currentPage": 1, "pageSize": n}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    return ((d.get("data") or {}).get("componentPageInfo") or {}).get("list") or []


def _value(text, unit):
    for num, pre, u in _VAL.findall(text):
        if (u == "F") == (unit == "F"):
            return float(num) * _MULT.get(pre, 1)
    return None


def matches(key, c):
    k = key.split("|")
    text = " ".join(str(c.get(x) or "") for x in ("describe", "componentModelEn", "componentSpecificationEn"))
    if str(c.get("componentSpecificationEn") or "") != k[2]:
        return False
    want = parse_value(k[1])
    got = _value(text, "F" if k[0] == "C" else "Ω")
    if want is None or got is None or abs(got - want) > 1e-3 * want:
        return False
    if k[0] == "R":
        t = _TOL.search(text)
        return t is not None and float(t.group(1)) <= float(k[3].rstrip("%"))
    v = _VOLT.search(text)
    if not v or float(v.group(1)) < float(k[3].rstrip("V") or 0):
        return False
    ok = DIELECTRIC_OK.get(k[4].upper(), (k[4].upper(),))
    return any(d in text.upper() for d in ok)


def resolve(design, cache_path, log=print):
    """Look up the design's missing keys; returns the cache dict (also written to cache_path)."""
    cache = json.loads(Path(cache_path).read_text()) if Path(cache_path).exists() else {}
    keys = sorted({key_of(p) for p in design.all_parts() if wants(p)})
    for key in keys:
        if key in cache and cache[key].get("lcsc"):
            continue
        q = _query(key)
        try:
            cands = [c for c in _search(q) if matches(key, c)]
        except Exception as e:  # noqa: BLE001 - network: reported, retried next time
            log(f"  {key}: search failed ({type(e).__name__}: {e})")
            continue
        # in stock first, then basic (no setup fee), then the most stock
        cands.sort(key=lambda c: ((c.get("stockCount") or 0) < 1000, c.get("componentLibraryType") != "base",
                                  -(c.get("stockCount") or 0)))
        at = datetime.date.today().isoformat()
        if not cands:
            cache[key] = dict(lcsc=None, query=q, at=at)
            log(f"  {key}: no match for '{q}'")
            continue
        c = cands[0]
        cache[key] = dict(lcsc=c.get("componentCode"), model=c.get("componentModelEn"),
                          basic=c.get("componentLibraryType") == "base", stock=c.get("stockCount"),
                          spec=c.get("componentSpecificationEn"), describe=(c.get("describe") or "")[:120],
                          query=q, at=at)
        log(f"  {key}: {c.get('componentCode')} {c.get('componentModelEn')} "
            f"{'basic' if cache[key]['basic'] else 'extended'}, stock {c.get('stockCount')}")
    refresh_carded(design, cache, log)
    Path(cache_path).write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")
    return cache


def apply(design, cache_path):
    """Put LCSC/JLC fields on the parts the cache resolves; returns [(ref, key)] still without a number."""
    if not Path(cache_path).exists():
        return [(p.ref or p.name, key_of(p)) for p in design.all_parts() if wants(p)]
    cache = json.loads(Path(cache_path).read_text())
    missing = []
    for p in design.all_parts():
        code = lcsc_of(p)
        hit = cache.get(f"LCSC|{code}") if code else None
        if hit and hit.get("stock") is not None:       # a carded part: the looked-up flags replace hand-typed ones
            p.fields["JLC"] = ("base" if hit.get("basic") else "expand") + f", stock {hit['stock']} on {hit.get('at')}"
        if not wants(p):
            continue
        hit = cache.get(key_of(p)) or {}
        if hit.get("lcsc"):
            p.fields["LCSC"] = hit["lcsc"]
            p.fields["JLC"] = ("base" if hit.get("basic") else "expand") + f", stock {hit.get('stock')} on {hit.get('at')}"
        else:
            missing.append((p.ref or p.name, key_of(p)))
    return missing


# ------------------------------------------------------------------------------------------- any part, by code or text
def row(c):
    """A search result as the fields haslamsynth keeps."""
    prices = c.get("componentPrices") or []
    return dict(lcsc=c.get("componentCode"), model=c.get("componentModelEn"), brand=c.get("componentBrandEn"),
                basic=c.get("componentLibraryType") == "base", preferred=bool(c.get("preferredComponentFlag")),
                stock=c.get("stockCount") or 0, spec=c.get("componentSpecificationEn"),
                describe=(c.get("describe") or "")[:160], price=prices[0].get("productPrice") if prices else None,
                datasheet=c.get("dataManualUrl"), url=c.get("lcscGoodsUrl"))


def search(query, basic=False, min_stock=0, match=None, n=50):
    """Candidates for one query (an MPN, an LCSC code or keywords): >= 1000 in stock first, then basic, then by
    stock. basic: basic parts only (no setup fee); min_stock: at least this many in stock; match: a regex the
    model, package or description must match, a crude parametric filter ('1.8V~5.5V', 'SOT-23', 'nA')."""
    rx = re.compile(match) if match else None          # case-sensitive: units (nA, mA, MHz) differ by case
    out = []
    for c in _search(query, n):
        r = row(c)
        if (basic and not r["basic"]) or r["stock"] < min_stock:
            continue
        if rx and not rx.search(" ".join(str(r[k] or "") for k in ("model", "spec", "describe", "brand"))):
            continue
        out.append(r)
    out.sort(key=lambda r: (r["stock"] < 1000, not r["basic"], -r["stock"]))
    return out


def lookup(code):
    """The JLC record of one LCSC code (exact match), or None."""
    for c in _search(code, 10):
        if str(c.get("componentCode")) == code:
            return row(c)
    return None


def lcsc_of(part):
    """The part's LCSC code from its card or instance fields, or None."""
    v = str({**part.defn.fields, **part.fields}.get("LCSC") or "").strip()
    return v or None


PAUSE_S = 1.0           # between carded-part lookups (refresh_carded)


def refresh_carded(design, cache, log=print):
    """Look up every LCSC code a part card names (stock, basic/extended, datasheet URL); updates cache in place.
    Codes the passive lookup chose are already fresh and are not asked again."""
    chosen = {v.get("lcsc") for k, v in cache.items() if not k.startswith("LCSC|")}
    codes = sorted({lcsc_of(p) for p in design.all_parts() if p.on_board and lcsc_of(p)} - chosen)
    at = datetime.date.today().isoformat()
    for i, code in enumerate(codes):
        if i:
            time.sleep(PAUSE_S)                        # one public search endpoint, shared: ask gently
        try:
            r = lookup(code)
        except Exception as e:  # noqa: BLE001 - network: reported, retried next time
            log(f"  {code}: lookup failed ({type(e).__name__}: {e})")
            continue
        if r is None:
            cache[f"LCSC|{code}"] = dict(lcsc=code, stock=None, at=at, missing=True)
            log(f"  {code}: not found at JLC")
            continue
        cache[f"LCSC|{code}"] = dict(r, query=code, at=at)
        log(f"  {code}: {r['model']} {'basic' if r['basic'] else 'extended'}, stock {r['stock']}")
    return cache


def by_code(cache):
    """{LCSC code: cache record}: the newest record of each code, whichever key found it."""
    out = {}
    for v in cache.values():
        code = v.get("lcsc")
        if code and (code not in out or str(v.get("at", "")) >= str(out[code].get("at", ""))):
            out[code] = v
    return out


DEFAULT_QUANTITY = 5        # boards per order when d.board(..., quantity=) is not given (JLC's minimum)


def stock_findings(design, cache_path, add):
    """`bom.stock` and `bom.setup_fees` from the cache (no network); add(check, severity, message, objects).

    Needed per code = its placed, assembled parts (on a board, in the BOM, not DNP) x their board's `quantity`.
    Stock 0 is an error, stock below the need a warning; codes the cache does not know are one warning (run
    `haslamsynth jlc`). Returns a summary dict for the report."""
    cache = json.loads(Path(cache_path).read_text()) if Path(cache_path).exists() else {}
    recs = by_code(cache)
    need, refs = {}, {}
    for p in design.all_parts():
        code = lcsc_of(p)
        if not code or not p.on_board or p.dnp or not p.defn.in_bom:
            continue
        q = getattr(design.boards.get(p.block.board_name), "quantity", None) or DEFAULT_QUANTITY
        need[code] = need.get(code, 0) + q
        refs.setdefault(code, []).append(p.ref)
    unknown = []
    for code in sorted(need):
        r = recs.get(code)
        who = ", ".join(refs[code][:6]) + (" ..." if len(refs[code]) > 6 else "")
        if r is None or r.get("stock") is None:
            unknown.append(code)
            continue
        stock, at, what = r["stock"], r.get("at", "?"), r.get("model") or who
        per = f"{len(refs[code])} per board x quantity, {who}"
        if stock <= 0:
            add("bom.stock", "error", f"{code} ({what}): JLC stock 0 on {at}; {need[code]} needed ({per}): pick "
                f"another part, or arrange global sourcing/consignment and waive this with the arrangement",
                refs[code])
        elif stock < need[code]:
            add("bom.stock", "warning", f"{code} ({what}): JLC stock {stock} on {at} < {need[code]} needed ({per})",
                refs[code])
    if unknown:
        add("bom.stock", "warning", f"stock unknown for {len(unknown)} LCSC codes (run `haslamsynth jlc`): "
            + ", ".join(unknown[:12]) + (" ..." if len(unknown) > 12 else ""), [])
    ext = sorted(c for c in need if c in recs and recs[c].get("basic") is False and not recs[c].get("preferred"))
    passive = [c for c in ext if any(design.find_part(r).defn.category in ("resistor", "capacitor_ceramic")
                                     for r in refs[c])]
    if need:
        add("bom.setup_fees", "info",
            f"{len(need)} distinct LCSC parts, {len(ext)} extended (a JLC setup fee each per order)"
            + (f": {', '.join(ext)}" if ext else "")
            + (f"; {len(passive)} of them resistors/capacitors ({', '.join(passive)}): where the value is free to "
               f"move, a basic value saves the fee (brief-to-board G17)" if passive else ""), [])
    return dict(codes=len(need), extended=ext, extended_passives=passive, unknown=unknown, need=need,
                stock={c: (recs.get(c) or {}).get("stock") for c in need})
