# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`haslamsynth parts search`: JLCPCB parts search, one line per hit (FRICTION #10, #42).

Each line: LCSC code | MPN | basic/ext | stock | package and pitch | maker | description | datasheet URL.
Filters (`--min-stock`, `--basic`, `--package REGEX`, `--min-pitch MM`) run on up to 100 API results, so
ask a specific keyword ("buck-boost", "TPS5528", "USB-C receptacle 16P").

Pitch (pitch_of), in order of trust:

| Form | Example | Shown |
|---|---|---|
| explicit in package or description | `VQFN-21_L5.0-W3.0-P0.50`, `0.5mm pitch` | `P0.5` |
| a family with one pitch | SOIC/SOP 1.27, TSSOP/HTSSOP 0.65, MSOP-8 0.65, MSOP-10 0.5, SOT-23 0.95 | `P0.65` |
| a common QFN/DFN body x pin count | QFN-24 4x4 0.5, QFN-16 3x3 0.5 | `~P0.5` |
| upper bound from a square QFP/QFN body | LQFP-32 7x7: 8 per side in 7 mm | `<=P0.8` |
| nothing known | `0603`, `SMD` | `P?` |

`--min-pitch` drops a part only when its pitch (or its upper bound) is known to be below the limit; `P?` and
bounds at or above the limit stay in the list for a datasheet check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import jlc

# (family regex on the upper-cased package, pin-count condition or None, pitch mm)
FAMILY = [
    (r"^(H|E|P)?TSSOP", None, 0.65),
    (r"^(V|H)?SSOP-?(8|10|12)\b", None, None),        # SSOP-10 is 1.0 (CN3767) or 0.5: ambiguous
    (r"^(H|E|P)?MSOP-?8\b|^VSSOP-?8\b", None, 0.65),
    (r"^(H|E|P)?MSOP-?(10|12|16)\b|^VSSOP-?10\b", None, 0.5),
    (r"^(E|H|P)?SO(IC|P)?-?\d+", None, 1.27),
    (r"^(P|C)?DIP-?\d+|^SIP-?\d+", None, 2.54),
    (r"^SOT-?23(-3)?$|^SOT-?23-?(5|6)\b|^TSOT-?23-?(5|6)\b|^SOT-?23$", None, 0.95),
    (r"^SOT-?23-?8\b|^TSOT-?23-?8\b", None, 0.65),
    (r"^SC-?70|^SOT-?323|^SOT-?363|^SC-?88", None, 0.65),
    (r"^SOT-?223", None, 2.3),
    (r"^SOT-?89", None, 1.5),
    (r"^TO-?252|^DPAK", None, 2.28),
    (r"^TO-?263|^D2PAK", None, 2.54),
    (r"^SOD-?123|^SOD-?323|^SMA$|^SMB$|^SMC$|^\d{4}$", None, None),   # two-terminal: no lead pitch
]

# common JEDEC MO-220/MO-229 bodies: (family, pins, "LxW") -> pitch; shown with "~"
TYPICAL = {
    ("QFN", 12, "3x3"): 0.5, ("QFN", 16, "3x3"): 0.5, ("QFN", 20, "3x3"): 0.4, ("QFN", 16, "4x4"): 0.65,
    ("QFN", 20, "4x4"): 0.5, ("QFN", 24, "4x4"): 0.5, ("QFN", 28, "4x4"): 0.4, ("QFN", 32, "5x5"): 0.5,
    ("QFN", 28, "5x5"): 0.5, ("QFN", 40, "5x5"): 0.4, ("QFN", 40, "6x6"): 0.5, ("QFN", 48, "6x6"): 0.4,
    ("QFN", 48, "7x7"): 0.5, ("QFN", 56, "7x7"): 0.4, ("QFN", 64, "9x9"): 0.5,
    ("DFN", 6, "2x2"): 0.65, ("DFN", 8, "2x2"): 0.5, ("DFN", 8, "3x3"): 0.65, ("DFN", 10, "3x3"): 0.5,
    ("LQFP", 32, "7x7"): 0.8, ("LQFP", 48, "7x7"): 0.5, ("LQFP", 64, "10x10"): 0.5, ("LQFP", 44, "10x10"): 0.8,
    ("LQFP", 100, "14x14"): 0.5, ("LQFP", 64, "7x7"): 0.4, ("TQFP", 32, "7x7"): 0.8, ("TQFP", 44, "10x10"): 0.8,
}
STD_PITCHES = (0.3, 0.35, 0.4, 0.5, 0.65, 0.8, 1.0, 1.27)

_EXPLICIT = [
    re.compile(r"(?:^|[-_ (])P(\d+(?:\.\d+)?)(?:MM)?(?=$|[-_ )])"),            # KiCad/EasyEDA style _P0.50
    re.compile(r"PITCH\s*[:=]?\s*(\d+(?:\.\d+)?)\s*MM"),
    re.compile(r"(\d+(?:\.\d+)?)\s*MM\s*PITCH"),
]
_BODY = re.compile(r"(\d+(?:\.\d+)?)\s*[X×*]\s*(\d+(?:\.\d+)?)")
_FAM_PINS = re.compile(r"(?:^|[^A-Z])(?:[A-Z]{0,2})(QFN|DFN|SON|QFP)-?(\d+)")


@dataclass
class Pitch:
    mm: float | None
    how: str            # explicit | family | typical | bound | unknown

    def __str__(self):
        if self.mm is None:
            return "P?"
        return {"typical": "~", "bound": "<="}.get(self.how, "") + f"P{self.mm:g}"


def pitch_of(package, description=""):
    pkg = (package or "").upper().strip()
    for text in (pkg, (description or "").upper()):
        for rx in _EXPLICIT:
            m = rx.search(text)
            if m:
                v = float(m.group(1))
                if 0.2 <= v <= 5.08:
                    return Pitch(v, "explicit")
    for rx, _, mm in FAMILY:
        if re.search(rx, pkg):
            return Pitch(mm, "family") if mm else Pitch(None, "unknown")
    fm, body = _FAM_PINS.search(pkg), _BODY.search(pkg)
    if fm and body:
        fam, pins = fm.group(1), int(fm.group(2))
        fam = {"SON": "DFN"}.get(fam, fam)
        if "QFP" in pkg and fam == "QFP":
            fam = "TQFP" if "TQFP" in pkg else "LQFP"
        a, b = float(body.group(1)), float(body.group(2))
        dims = f"{a:g}x{b:g}"
        for p in (pins, pins - 1):          # QFN-17 is often 16 + exposed pad
            if (fam, p, dims) in TYPICAL:
                return Pitch(TYPICAL[(fam, p, dims)], "typical")
        if abs(a - b) < 1e-6 and fam in ("QFN", "LQFP", "TQFP"):
            n = pins - (pins % 4)
            per_side = n // 4
            if per_side >= 2:
                fit = [p for p in STD_PITCHES if (per_side - 1) * p <= a - 0.5]
                if fit:
                    return Pitch(max(fit), "bound")
    return Pitch(None, "unknown")


@dataclass
class Hit:
    lcsc: str
    mpn: str
    maker: str
    basic: bool
    stock: int
    package: str
    pitch: Pitch
    description: str
    datasheet: str
    raw: dict

    def line(self, width=70):
        d = re.sub(r"\s+", " ", self.description or "").strip()
        d = d if len(d) <= width else d[:width - 1] + "…"
        return " | ".join([self.lcsc, self.mpn, "basic" if self.basic else "ext", f"stk {self.stock}",
                           f"{self.package} {self.pitch}", self.maker or "?", d, self.datasheet or "-"])


def hit_of(c):
    pkg = str(c.get("componentSpecificationEn") or "")
    desc = str(c.get("describe") or "")
    return Hit(lcsc=str(c.get("componentCode") or ""), mpn=str(c.get("componentModelEn") or ""),
               maker=str(c.get("componentBrandEn") or ""), basic=c.get("componentLibraryType") == "base",
               stock=int(c.get("stockCount") or 0), package=pkg, pitch=pitch_of(pkg, desc), description=desc,
               datasheet=str(c.get("dataManualUrl") or ""), raw=c)


def keep(h, min_stock=0, basic=False, package=None, min_pitch=None):
    if h.stock < min_stock or (basic and not h.basic):
        return False
    if package and not re.search(package, h.package, re.I):
        return False
    if min_pitch is not None and h.pitch.mm is not None and h.pitch.mm < min_pitch - 1e-6:
        return False
    return True


def search(keyword, n=20, min_stock=0, basic=False, package=None, min_pitch=None, client=None, refresh=False):
    """(kept hits sorted basic first then by stock, number of API results looked at)."""
    raw = jlc.search(keyword, n=100, client=client, refresh=refresh)
    hits = [h for h in map(hit_of, raw) if keep(h, min_stock, basic, package, min_pitch)]
    hits.sort(key=lambda h: (not h.basic, -h.stock))
    return hits[:n], len(raw)
