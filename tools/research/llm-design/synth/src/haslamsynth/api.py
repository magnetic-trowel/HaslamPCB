# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`haslamsynth api`: every call a design.py makes, with its signature and one-line doc, read from the code.

An agent learned the API by reading a 470-line example design and a 200-line parts file (~10k tokens; obd-solar
FRICTION.md #3). This prints the same surface in ~2k tokens and cannot go stale: it is introspection, so a new
method or argument appears here when it is added. Semantics and the checks: synth/README.md.
"""
from __future__ import annotations

import dataclasses
import inspect
import re

from . import ir, lib, placement, wiring
from .haslam_intent import HaslamIntent

# methods the build calls on a design, not the designer (kept out of the listing)
INTERNAL = {"Design": {"finalize", "all_nets", "all_parts", "find_part", "net_by_name", "domain_of", "board_names",
                       "board_spec"},
            "Placement": {"resolve"},
            "HaslamIntent": {"warnings", "empty", "defaults", "relations", "document", "knob"},
            "Part": {"label", "on_board", "pins"},
            "Net": {"is_global", "full_name"},
            "Block": {"board_name", "part"}}
DOC_CHARS = 150


# methods whose **kw go to a constructor: the listing shows that constructor's arguments in place of **kw
KW_TARGETS = {("Design", "block"): ir.Block, ("Design", "net"): ir.Net, ("Design", "domain"): ir.Domain,
              ("Design", "barrier"): ir.Barrier, ("Design", "require"): ir.Requirement,
              ("Design", "assume"): ir.Assumption, ("Design", "question"): ir.Question, ("Design", "hazard"): ir.Hazard,
              ("Design", "board"): placement.BoardSpec, ("Block", "add"): ir.Part, ("Block", "net"): ir.Net}
NOT_KW = {"self", "design", "block", "defn"}     # constructor arguments the method fills itself


def one_line(obj):
    """First sentence of the docstring's first paragraph, at most DOC_CHARS characters."""
    doc = inspect.getdoc(obj) or ""
    if isinstance(obj, type) and doc.startswith(obj.__name__ + "("):
        return ""                                   # the dataclass's generated docstring repeats the signature
    para = " ".join(doc.split("\n\n", 1)[0].split())
    m = re.match(r"(.+?(?<!e\.g)(?<!i\.e)\.)(\s+[A-Z(`]|$)", para)
    s = m.group(1) if m else para
    return s if len(s) <= DOC_CHARS else s[:DOC_CHARS - 3].rstrip() + "..."


def _params(target):
    """[(name, default repr or None)] a class takes: its dataclass fields, else its __init__ arguments."""
    if dataclasses.is_dataclass(target):
        return [(f.name, _default(f)) for f in dataclasses.fields(target) if f.init and not f.name.startswith("_")]
    sig = inspect.signature(target.__init__)
    return [(p.name, None if p.default is inspect.Parameter.empty else repr(p.default))
            for p in sig.parameters.values() if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]


def signature(fn, drop_self=True, kw_target=None):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return "(...)"
    params = list(sig.parameters.values())
    if drop_self and params and params[0].name in ("self", "cls"):
        params = params[1:]
    if kw_target is None or not any(p.kind is p.VAR_KEYWORD for p in params):
        return str(sig.replace(parameters=params, return_annotation=inspect.Signature.empty))
    named = {p.name for p in params}
    head = str(sig.replace(parameters=[p for p in params if p.kind is not p.VAR_KEYWORD],
                           return_annotation=inspect.Signature.empty))[1:-1]
    extra = [n if d is None else f"{n}={d}" for n, d in _params(kw_target) if n not in named | NOT_KW]
    return "(" + ", ".join([s for s in (head, ", ".join(extra)) if s]) + ")"


def methods(cls, prefix):
    skip = INTERNAL.get(cls.__name__, set())
    out = []
    for name, member in vars(cls).items():
        if name.startswith("_") or name in skip:
            continue
        if isinstance(member, property):
            out.append((f"{prefix}{name}", "", one_line(member.fget)))
        elif isinstance(member, staticmethod):
            out.append((f"{prefix}{name}", signature(member.__func__, drop_self=False), one_line(member.__func__)))
        elif inspect.isfunction(member):
            out.append((f"{prefix}{name}", signature(member, kw_target=KW_TARGETS.get((cls.__name__, name))),
                        one_line(member)))
    return out


def functions(module, prefix):
    out = []
    for name, fn in vars(module).items():
        if name.startswith("_") or not inspect.isfunction(fn) or fn.__module__ != module.__name__:
            continue
        out.append((f"{prefix}{name}", signature(fn, drop_self=False), one_line(fn)))
    return out


def constructor(cls, call):
    """A class's call signature: its dataclass fields, else __init__."""
    if dataclasses.is_dataclass(cls):
        args = [n if d is None else f"{n}={d}" for n, d in _params(cls)]
        return (call, "(" + ", ".join(args) + ")", one_line(cls))
    return (call, signature(cls.__init__), one_line(cls))


def _default(f):
    if f.default is not dataclasses.MISSING:
        return repr(f.default)
    if f.default_factory is not dataclasses.MISSING:
        return repr(f.default_factory())
    return None


def sections():
    """[(title, [(name, signature, doc)])] in the order a design.py uses them."""
    consts = [(f"lib.{n}", "", f"= {v!r}") for n, v in vars(lib).items() if n.startswith("PINMAP_")]
    return [
        ("Design: d = Design(...)", [constructor(ir.Design, "Design")] + methods(ir.Design, "d.")),
        ("Blocks: blk = d.block(...)", methods(ir.Block, "blk.")),
        ("Wiring helper: w = Wiring(d, name, ...), a block whose parts come with their pin -> net map",
         [constructor(wiring.Wiring, "Wiring")] + methods(wiring.Wiring, "w.")),
        ("Parts: u = blk.add(defn) (u[pin] is a pin)", methods(ir.Part, "u.")),
        ("Nets: n = d.net(...) / blk.net(...)", methods(ir.Net, "n.")),
        ("Placement relations: d.place.*", methods(placement.Placement, "d.place.")),
        ("Operating intent for haslam: d.haslam.*", methods(HaslamIntent, "d.haslam.")),
        ("Part cards: haslamsynth.lib", functions(lib, "lib.") + consts),
        ("Types: from haslamsynth import ...", [constructor(c, c.__name__) for c in
                                               (ir.PartDef, ir.PinDef, ir.Ratings, ir.VLimit, ir.Isolation,
                                                placement.Hole)]),
    ]


def text():
    lines = ["haslamsynth design API (generated from the code; semantics and checks: synth/README.md)"]
    for title, rows in sections():
        lines += ["", f"## {title}"]
        for name, sig, doc in rows:
            lines.append(f"{name}{sig}" + (f"  # {doc}" if doc else ""))
    return "\n".join(lines) + "\n"
