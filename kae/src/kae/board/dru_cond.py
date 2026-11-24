# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate .kicad_dru rule conditions for a pair of pads (the subset kae models).

    ast = parse("A.NetName == '/SW' && B.hasNetclass('HV')")   # None: not evaluable here
    pair_matches(ast, Item(net='/SW', ...), Item(net='VIN', netclass='HV', ...))

Tokens come from kae.board.dru_check (one tokenizer for checking and evaluating). The
grammar follows KiCad 10's libeval (drc-rule-language-reference.md): `||` binds tighter than
`&&` ('a && b || c' is 'a && (b || c)'), `!` negates, parentheses group. Atoms understood:

    X.NetName == / != 'glob'          X.NetClass == / != 'glob' (any member of a comma list,
    X.hasNetclass('name')               or the whole list)
    X.hasExactNetclass('name')        X.Type == / != 'Pad' (items here are pads)
    X.Reference == / != 'glob'        X.memberOfFootprint('ref glob' or 'lib:fp glob')

with X = A or B; the literal may also come first ('x' == A.NetName). String equality is
KiCad's: case-insensitive, `*` and `?` wildcards. Anything else (areas, layers, other
properties or functions, numbers) makes parse() return None, so a rule kae cannot evaluate
stays unapplied rather than half-applied.

KiCad tests a rule with the two items in both orders (pair_matches does too).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .dru_check import _TOK

NET_KINDS = frozenset({"net", "netclass", "hasnc", "hasexactnc"})
PART_KINDS = frozenset({"ref", "fp"})

_PROPS = {"netname": "net", "netclass": "netclass", "type": "type", "reference": "ref"}
_FUNCS = {"hasnetclass": "hasnc", "hasexactnetclass": "hasexactnc", "memberoffootprint": "fp"}


@dataclass(frozen=True)
class Item:
    """One side of a pair: a pad, its net and effective net class, its footprint."""
    net: str = ""
    netclass: str = "Default"
    ref: str = ""
    lib: str = ""
    type: str = "Pad"


class _Unsupported(Exception):
    pass


@lru_cache(maxsize=4096)
def _rx(pat: str):
    return re.compile("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pat),
                      re.IGNORECASE | re.DOTALL)


def wild(pat: str, s: str) -> bool:
    """KiCad's string equality in conditions: case-insensitive, `*`/`?` wildcards."""
    return _rx(pat).fullmatch(s or "") is not None


def _tokens(text: str) -> list:
    out, pos = [], 0
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        kind = m.lastgroup
        if kind == "bad":
            raise _Unsupported(m.group(kind))
        out.append((kind, m.group(kind)))
    if text[pos:].strip():
        raise _Unsupported(text[pos:])
    return out


class _Parser:
    def __init__(self, toks):
        self.t, self.k = toks, 0

    def peek(self):
        return self.t[self.k] if self.k < len(self.t) else (None, None)

    def take(self, want=None):
        tok = self.peek()
        if tok[0] is None or (want is not None and tok[1] != want):
            raise _Unsupported(f"expected {want!r}")
        self.k += 1
        return tok

    def expr(self):                      # && binds loosest
        xs = [self.disj()]
        while self.peek()[1] == "&&":
            self.take()
            xs.append(self.disj())
        return xs[0] if len(xs) == 1 else ("and", tuple(xs))

    def disj(self):
        xs = [self.unary()]
        while self.peek()[1] == "||":
            self.take()
            xs.append(self.unary())
        return xs[0] if len(xs) == 1 else ("or", tuple(xs))

    def unary(self):
        kind, t = self.peek()
        if t == "!":
            self.take()
            return ("not", self.unary())
        if t == "(" and kind == "op":
            self.take()
            x = self.expr()
            self.take(")")
            return x
        return self.atom()

    @staticmethod
    def _member(t):
        obj, _, name = t.partition(".")
        if obj not in ("A", "B") or not name or "." in name:
            raise _Unsupported(t)
        return obj, name.lower().replace("_", "")

    @staticmethod
    def _str(tok):
        if tok[0] != "str":
            raise _Unsupported(tok[1])
        return tok[1][1:-1]

    def atom(self):
        kind, t = self.take()
        if kind == "str":                 # 'x' == A.NetName
            op = self.take()[1]
            k2, t2 = self.take()
            if k2 != "id":
                raise _Unsupported(t2)
            return self._cmp(t2, op, t[1:-1])
        if kind != "id":
            raise _Unsupported(t)
        if self.peek()[1] == "(":
            obj, name = self._member(t)
            if name not in _FUNCS:
                raise _Unsupported(t)
            self.take("(")
            arg = self._str(self.take())
            self.take(")")
            if "${" in arg:
                raise _Unsupported(arg)    # component-class forms
            return ("atom", obj, _FUNCS[name], arg, True)
        op = self.take()[1]
        return self._cmp(t, op, self._str(self.take()))

    def _cmp(self, t, op, lit):
        obj, name = self._member(t)
        if op not in ("==", "!=") or name not in _PROPS:
            raise _Unsupported(t)
        return ("atom", obj, _PROPS[name], lit, op == "==")


def parse(text: str):
    """The condition as a tree, or None when it uses anything outside the subset above (or
    is empty: a rule without a condition is not a pair rule)."""
    try:
        toks = _tokens(text or "")
        if not toks:
            return None
        p = _Parser(toks)
        x = p.expr()
        if p.k != len(toks):
            return None
        return x
    except _Unsupported:
        return None


def kinds(ast) -> set:
    """The atom kinds a tree uses."""
    if ast[0] == "atom":
        return {ast[2]}
    if ast[0] == "not":
        return kinds(ast[1])
    return set().union(*(kinds(x) for x in ast[1]))


# the other pad of a pair, unknown but for being a pad (could_match)
_SOME_PAD = Item(net=None, netclass=None, ref=None, lib=None, type="Pad")


def _atom(kind, pat, it: Item) -> bool:
    if kind != "type" and it is _SOME_PAD:
        return None
    if kind == "net":
        return wild(pat, it.net)
    if kind == "netclass":
        nc = it.netclass or "Default"
        return wild(pat, nc) or any(wild(pat, m) for m in nc.split(","))
    if kind == "hasnc":
        return pat in (it.netclass or "Default").split(",")
    if kind == "hasexactnc":
        return pat == (it.netclass or "Default")
    if kind == "type":
        return wild(pat, it.type)
    if kind == "ref":
        return wild(pat, it.ref)
    if kind == "fp":
        return wild(pat, it.lib) if ":" in pat else wild(pat, it.ref)
    raise ValueError(kind)


def evaluate(ast, a: Item, b: Item) -> bool:
    op = ast[0]
    if op == "atom":
        _, obj, kind, pat, eq = ast
        return _atom(kind, pat, a if obj == "A" else b) == eq
    if op == "not":
        return not evaluate(ast[1], a, b)
    if op == "and":
        return all(evaluate(x, a, b) for x in ast[1])
    return any(evaluate(x, a, b) for x in ast[1])


def _eval3(ast, a, b):
    """Kleene three-valued evaluate (True, False or None for unknown); _SOME_PAD's fields
    other than its type are unknown."""
    op = ast[0]
    if op == "atom":
        _, obj, kind, pat, eq = ast
        v = _atom(kind, pat, a if obj == "A" else b)
        return None if v is None else v == eq
    if op == "not":
        v = _eval3(ast[1], a, b)
        return None if v is None else not v
    vs = [_eval3(x, a, b) for x in ast[1]]
    if op == "and":
        return False if False in vs else True if all(v is True for v in vs) else None
    return True if True in vs else False if all(v is False for v in vs) else None


def could_match(ast, it: Item) -> bool:
    """Whether some other pad could make the rule apply to a pair with `it` (either order):
    False only when the rule can never name it in a pad pair."""
    return _eval3(ast, it, _SOME_PAD) is not False or _eval3(ast, _SOME_PAD, it) is not False


def pair_matches(ast, a: Item, b: Item) -> bool:
    """Whether the rule applies to the pair, as KiCad tests it: either item as A."""
    return evaluate(ast, a, b) or evaluate(ast, b, a)
