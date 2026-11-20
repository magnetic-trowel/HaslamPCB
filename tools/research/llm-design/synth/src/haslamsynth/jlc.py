# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""JLCPCB/LCSC part numbers for a design's generic passives.

`haslamsynth jlc designs/<slug>/design.py` looks up every generic resistor and ceramic capacitor (no MPN, no
LCSC field) in the JLCPCB parts search and writes `designs/<slug>/jlc.json`: {key: {lcsc, model, basic, stock,
spec, describe, query, at}}. `haslamsynth build` reads that file (no network) and puts `LCSC` and `JLC` fields on
the parts, so the schematic, the board and the fab BOM (synth/scripts/fab_outputs.py) carry them.

A candidate matches when its package is the part's, its value is the part's (0.1 %), a resistor's tolerance is
no worse, and a capacitor's voltage is no lower and its dielectric no worse (X5R accepts X5R or X7R; X7R accepts
X7R, C0G/NP0). Parts with at least 1000 in stock come first, then basic parts (no per-order setup fee), then stock. A key with no match is written with
lcsc null and reported, so a person picks one by hand (add it to the part's fields in parts.py).
"""
from __future__ import annotations

import datetime
import json
import re
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
    Path(cache_path).write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")
    return cache


def apply(design, cache_path):
    """Put LCSC/JLC fields on the parts the cache resolves; returns [(ref, key)] still without a number."""
    if not Path(cache_path).exists():
        return [(p.ref or p.name, key_of(p)) for p in design.all_parts() if wants(p)]
    cache = json.loads(Path(cache_path).read_text())
    missing = []
    for p in design.all_parts():
        if not wants(p):
            continue
        hit = cache.get(key_of(p)) or {}
        if hit.get("lcsc"):
            p.fields["LCSC"] = hit["lcsc"]
            p.fields["JLC"] = ("base" if hit.get("basic") else "expand") + f", stock {hit.get('stock')} on {hit.get('at')}"
        else:
            missing.append((p.ref or p.name, key_of(p)))
    return missing
