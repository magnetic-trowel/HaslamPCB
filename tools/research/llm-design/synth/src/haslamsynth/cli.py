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
    if a.search:
        for q in a.search:
            rows = jlc.search(q, basic=a.basic, min_stock=a.min_stock, match=a.match)[:a.limit]
            print(f"{q}: {len(rows)} candidate(s)" + (" (basic only)" if a.basic else "")
                  + (f", stock >= {a.min_stock}" if a.min_stock else "") + (f", matching /{a.match}/" if a.match else ""))
            for r in rows:
                print(f"  {r['lcsc']:>9} {'basic' if r['basic'] else 'pref ' if r['preferred'] else 'ext  '} "
                      f"stock {r['stock']:>9} {str(r['model'])[:24]:24s} {str(r['spec'])[:18]:18s} {r['describe'][:90]}")
        if not a.design:
            return 0
    if not a.design:
        print("haslamsynth jlc: give design.py path(s) or --search QUERY ...", file=sys.stderr)
        return 2
    for path in a.design:
        d = load_design(path).finalize()
        cache = Path(path).resolve().parent / "jlc.json"
        print(f"{d.slug}: looking up generic passives and carded LCSC codes -> {cache}")
        jlc.resolve(d, cache)
        left = jlc.apply(d, cache)
        print(f"{d.slug}: {len(left)} generic parts without an LCSC number"
              + (": " + ", ".join(f"{r} ({k})" for r, k in left) if left else ""))
        jlc.stock_findings(d, cache, lambda chk, sev, msg, objs=(): print(f"  {sev:7s} {chk}: {msg}"))
    return 0


def cmd_ds(a):
    from . import ds
    design = None
    if a.design:
        from .build import load_design
        design = load_design(a.design).finalize()
    pdf, txt, note = ds.fetch(a.source, design)
    text = txt.read_text(errors="replace")
    npages = text.count("\f") + 1
    print(f"{a.source}: {note}\n  {pdf} ({npages} pages), text {txt}")
    blocks = []
    if a.section:
        blocks += ds.section(text, a.section, max_lines=a.lines)
        if not blocks:
            print(f"  no heading matching {a.section!r} outside the contents; try --grep")
    if a.grep:
        blocks += ds.grep(text, a.grep, context=a.context)
        if not blocks:
            print(f"  no line matches /{a.grep}/")
    for pg, lines in blocks[:a.max_blocks]:
        print(f"--- page {pg}")
        print("\n".join(ln.rstrip() for ln in lines))
    if len(blocks) > a.max_blocks:
        print(f"... {len(blocks) - a.max_blocks} more blocks (--max-blocks)")
    return 0


def cmd_check_board(a):
    import json
    from pathlib import Path
    from . import boardcheck, boardgeom
    from .build import load_design
    d = load_design(a.design).finalize()
    geometry = boardgeom.board_json(d)[0]
    hand = Path(a.design).resolve().parent / "board.json"
    if hand.exists():
        geometry = boardgeom.merge(geometry, json.loads(hand.read_text()))[0]
    meas, rows, failed = boardcheck.check_board(d, a.board, geometry)
    print(f"{d.slug}: {a.board}")
    for name, m in meas.items():
        print(f"  measure {name}: " + ", ".join(f"{k} {v}" for k, v in m.items() if v not in ([], None)))
    print(f"  {'calc':28s} {'designed':>12s} {'as built':>12s}  limit")
    for c, v, ok in rows:
        if v is None and not a.all:
            continue
        lim = f"{c.op} {c.limit:g}" if c.limit is not None else ""
        built = f"{v:.4g}" if v is not None else "-"
        flag = "" if ok is None or v is None else ("  ok" if ok else "  FAIL")
        print(f"  {c.name:28s} {c.value:12.4g} {built:>12s}  {lim} {c.unit}{flag}")
    if not any(v is not None for _, v, _ in rows):
        print("  no calc has board= (d.calc(..., board=lambda m: ...)); nothing re-evaluated")
    if failed:
        print(f"{d.slug}: {len(failed)} calc limit(s) broken on the board: {', '.join(failed)}")
    return 1 if failed else 0


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
    j = sub.add_parser("jlc", help="look up JLCPCB/LCSC numbers, stock and basic/extended for a design's parts "
                                   "(writes jlc.json), or --search parts by MPN/keyword")
    j.add_argument("design", nargs="*", help="path(s) to designs/<slug>/design.py")
    j.add_argument("--search", nargs="+", metavar="QUERY", help="MPNs, LCSC codes or keywords (one query each)")
    j.add_argument("--basic", action="store_true", help="--search: basic parts only (no setup fee)")
    j.add_argument("--min-stock", type=int, default=0, help="--search: at least this many in stock")
    j.add_argument("--match", help="--search: regex the model, package or description must match (e.g. '1.8V~5.5V')")
    j.add_argument("--limit", type=int, default=15, help="--search: rows per query")
    j.set_defaults(fn=cmd_jlc)
    x = sub.add_parser("ds", help="fetch a datasheet once (vendor URL, else LCSC's copy) and print a section or "
                                  "the lines matching a regex, with page numbers")
    x.add_argument("source", help="URL, MPN, LCSC code, or (with --design) a reference of that design")
    x.add_argument("--design", help="designs/<slug>/design.py: SOURCE may be a reference; its card's datasheet first")
    x.add_argument("--section", help="heading text, e.g. 'Absolute Maximum' or 'Recommended Operating'")
    x.add_argument("--grep", help="regex (case-insensitive); prints matching lines with --context lines around")
    x.add_argument("--context", type=int, default=2)
    x.add_argument("--lines", type=int, default=80, help="--section: at most this many lines per section")
    x.add_argument("--max-blocks", type=int, default=12)
    x.set_defaults(fn=cmd_ds)
    k = sub.add_parser("check-board", help="re-evaluate the design's calcs that have board= on a laid-out board "
                                           "(tracks crossing a barrier, copper area in a rule area); exit 1 on a "
                                           "broken limit")
    k.add_argument("design", help="designs/<slug>/design.py")
    k.add_argument("board", help="the laid-out .kicad_pcb")
    k.add_argument("--all", action="store_true", help="also list calcs without board= (designed values)")
    k.set_defaults(fn=cmd_check_board)
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
