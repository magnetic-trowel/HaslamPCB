# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamsynth command line: build designs, inspect KiCad library symbols and footprints."""
import argparse
import re
import signal
import sys

from .kicadlib import FootprintLibs, SymbolLibs


def cmd_build(a):
    from .build import build
    rc = 0
    for path in a.design:
        d, findings, status, kicad = build(path, a.out if len(a.design) == 1 else None,
                                           use_kicad=not a.no_kicad, date=a.date)
        active = [f for f in findings if not f.waived_by]
        shown = [f for f in active if f.severity == "error" or (a.verbose and f.severity == "warning")]
        for f in shown:
            print(f"  {f.severity:7s} {f.check}: {f.message}")
        kc = (f"ERC {kicad['erc_summary']}, netlist {'identical' if not kicad['netlist_problems'] else 'MISMATCH'}"
              if kicad.get("ran") else f"KiCad: {kicad.get('reason')}")
        print(f"{d.slug}: {status['error']} errors, {status['warning']} warnings, {status['waived']} waived; {kc}"
              + (f"; BLOCKING questions open: {', '.join(status['blocking_questions'])}" if status["blocking_questions"] else ""))
        if status["error"]:
            rc = 1
    return rc


def cmd_jlc(a):
    from pathlib import Path
    from .build import load_design
    from . import jlc
    for path in a.design:
        d = load_design(path).finalize()
        cache = Path(path).resolve().parent / "jlc.json"
        print(f"{d.slug}: looking up generic passives -> {cache}")
        jlc.resolve(d, cache)
        left = jlc.apply(d, cache)
        print(f"{d.slug}: {len(left)} generic parts without an LCSC number"
              + (": " + ", ".join(f"{r} ({k})" for r, k in left) if left else ""))
    return 0


def cmd_parts_search(a):
    from . import fetch, partsearch
    try:
        hits, seen = partsearch.search(a.keyword, n=a.n, min_stock=a.min_stock, basic=a.basic, package=a.package,
                                       min_pitch=a.min_pitch, refresh=a.refresh)
    except fetch.FetchError as e:
        print(f"parts search failed: {e}", file=sys.stderr)
        return 2
    filt = [f for f, on in ((f"stock >= {a.min_stock}", a.min_stock), ("basic", a.basic),
                            (f"package ~ /{a.package}/", a.package), (f"pitch >= {a.min_pitch} mm", a.min_pitch)) if on]
    print(f"== {a.keyword}: {len(hits)} shown of {seen} JLC results" + (f" ({', '.join(filt)})" if filt else ""))
    print("   LCSC | MPN | basic/ext | stock | package pitch | maker | description | datasheet")
    for h in hits:
        print("  " + h.line())
    if any(h.pitch.how in ("typical", "bound", "unknown") for h in hits):
        print("   pitch: ~ typical for that body, <= upper bound, P? unknown: read the datasheet's package drawing")
    return 0


def cmd_sym(a):
    libs = SymbolLibs()
    if ":" in a.query and libs.has(a.query):
        s = libs.get(a.query)
        print(f"{s.lib_id}: {s.units} unit(s){' power' if s.power else ''}")
        for p in sorted(s.pins, key=lambda p: (p.unit, _nat(p.number))):
            print(f"  unit {p.unit} pin {p.number:>4} {p.name:20s} {p.type:14s} at ({p.x:g}, {p.y:g})"
                  f"{' HIDDEN' if p.hidden else ''}")
        fp = sexpr_prop(s, "Footprint")
        if fp:
            print(f"  default footprint: {fp}")
        return 0
    rx = re.compile(a.query, re.I)
    n = 0
    for lib in libs.libraries():
        if a.lib and lib != a.lib:
            continue
        for name in libs.names(lib):
            if rx.search(f"{lib}:{name}"):
                print(f"{lib}:{name}")
                n += 1
                if n >= a.limit:
                    return 0
    return 0


def cmd_fp(a):
    fl = FootprintLibs()
    if ":" in a.query and fl.has(a.query):
        print(f"{a.query}: pads {sorted(fl.pads(a.query), key=_nat)}")
        return 0
    rx = re.compile(a.query, re.I)
    n = 0
    for d in sorted(fl.root.glob("*.pretty")):
        for f in sorted(d.glob("*.kicad_mod")):
            lid = f"{d.stem}:{f.stem}"
            if rx.search(lid):
                print(lid)
                n += 1
                if n >= a.limit:
                    return 0
    return 0


def sexpr_prop(sym, name):
    from . import sexpr
    for p in sexpr.find_all(sym.node, "property"):
        if p[1] == name:
            return p[2]
    return None


def _nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]


def main(argv=None):
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)     # `haslamsynth sym ... | head`
    ap = argparse.ArgumentParser(prog="haslamsynth", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="check a design and write its KiCad project, intent, BOM and report")
    b.add_argument("design", nargs="+", help="path(s) to designs/<slug>/design.py")
    b.add_argument("-o", "--out", help="output directory (default: <design dir>/out)")
    b.add_argument("--no-kicad", action="store_true", help="skip kicad-cli ERC and netlist round trip")
    b.add_argument("--date", help="title-block date (default: today)")
    b.add_argument("-v", "--verbose", action="store_true", help="also print warnings")
    b.set_defaults(fn=cmd_build)
    j = sub.add_parser("jlc", help="look up JLCPCB/LCSC numbers for the generic passives (writes jlc.json)")
    j.add_argument("design", nargs="+")
    j.set_defaults(fn=cmd_jlc)
    pa = sub.add_parser("parts", help="part selection: `parts search KEYWORD` (JLCPCB parts, one line per hit)")
    psub = pa.add_subparsers(dest="parts_cmd", required=True)
    ps = psub.add_parser("search", help="search JLCPCB parts: LCSC, MPN, basic/ext, stock, package, pitch, datasheet")
    ps.add_argument("keyword")
    ps.add_argument("--min-stock", type=int, default=0)
    ps.add_argument("--basic", action="store_true", help="basic parts only (no per-order setup fee)")
    ps.add_argument("--package", help="regex on the package name, e.g. 'TSSOP|SOIC'")
    ps.add_argument("--min-pitch", type=float, help="drop parts whose lead pitch is known to be below this (mm)")
    ps.add_argument("-n", type=int, default=20, help="lines to print (default 20)")
    ps.add_argument("--refresh", action="store_true", help="ask the API again instead of the day-old cache")
    ps.set_defaults(fn=cmd_parts_search)
    s = sub.add_parser("sym", help="search KiCad symbols by regex, or show pins of Lib:Name")
    s.add_argument("query")
    s.add_argument("--lib")
    s.add_argument("--limit", type=int, default=200)
    s.set_defaults(fn=cmd_sym)
    f = sub.add_parser("fp", help="search KiCad footprints by regex, or show pads of Lib:Name")
    f.add_argument("query")
    f.add_argument("--limit", type=int, default=200)
    f.set_defaults(fn=cmd_fp)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
