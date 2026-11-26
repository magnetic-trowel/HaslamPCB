# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The assumption ledger: every circuit parameter the physics uses, as an interval with its source.

No parameter is a bare number. Each is a Param (typical value, low, high, unit) with the source it
came from, in order of trust:

    intent      the commanding program's intent file (a datasheet it read, a design target, a
                measurement); points or intervals as it states them
    board       the board's own fields (part values, net names)
    part_table  a curated table of part data in this package (parts.json), each entry citing its
                document
    physics     derived from other parameters by a stated law (e.g. a voltage edge from the switch
                node's capacitance and the current that charges it)
    prior       a class default, always as a wide interval, flagged

Results are computed across the intervals (`corners`): seeded Latin-hypercube samples plus the
extremes, so a decision that holds only at one assumed value shows up as one that flips.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

SOURCES = ("intent", "board", "part_table", "physics", "prior")
PARTS_FILE = Path(__file__).with_name("parts.json")


@dataclass
class Param:
    subject: str          # what it describes (a part ref, a cell id, a net)
    name: str             # e.g. f_sw_Hz, t_i_s, I_A
    typ: float
    lo: float
    hi: float
    unit: str
    source: str
    basis: str

    def __post_init__(self):
        self.lo, self.hi = min(self.lo, self.hi), max(self.lo, self.hi)
        self.typ = min(max(self.typ, self.lo), self.hi)

    @property
    def spread(self):
        """hi / lo (1 for a point)."""
        return self.hi / self.lo if self.lo > 0 else float("inf")


@dataclass
class Ledger:
    params: dict = field(default_factory=dict)      # (subject, name) -> Param

    def add(self, p: Param):
        self.params[(p.subject, p.name)] = p
        return p

    def get(self, subject, name):
        return self.params.get((subject, name))

    def rows(self):
        return [asdict(p) for p in self.params.values()]

    def flagged(self):
        """Parameters resting on a prior: what the commander could supply."""
        return [p for p in self.params.values() if p.source == "prior"]


def load_intent(path):
    """The intent file (JSON): {"parts": {ref: {name: value | [lo, hi]}}, "nets": {net: {...}},
    "cells": {cell id: {...}}, "requirements": {...}}. Missing file: empty intent."""
    if not path:
        return {}
    return json.loads(Path(path).read_text())


def board_facts(intent, board_path):
    """The facts the physics reads for a board: `intent` (a facts dict or a haslam.intent/1 document) when given,
    else the board's own intent file beside it (haslam.intent.facts); {} when there is neither."""
    from haslam.intent import facts as F
    if intent is None:
        intent, _ = F.for_board(board_path)
    return F.facts_of(intent)


def parts_table():
    """The curated part table: list of {match (regex), data {name: value | [lo, hi]}, source}."""
    if not PARTS_FILE.exists():
        return []
    return json.loads(PARTS_FILE.read_text()).get("parts", [])


def match_rank(pattern, text, value=None):
    """How well a part-table or datasheet-library pattern names a part: None when it does not match, else a
    sortable key (it matched the value itself, the length of the match). A match must start at a word
    boundary ('CM5' names a Compute Module 5, not the 'PCM5102' it sits inside), and the longest match is the
    most specific ('AP2112K-1.8' beats a family-wide 'AP2112' that a 3.3 V variant's entry carries)."""
    pat = re.sub(r"^\(\?i\)", "", pattern or "")
    if not pat:
        return None
    try:
        rx = re.compile(r"(?<![A-Za-z0-9])(?:" + pat + ")", re.I)
    except re.error:
        return None
    for on_value, t in ((True, value), (False, text)):
        m = rx.search(t or "") if t is not None else None
        if m:
            return (on_value, len(m.group(0)))
    return None


def best_match(entries, pattern_of, text, value=None, name_of=None):
    """The entry whose pattern names the part best, or None: an entry whose own part number is the value
    first (name_of), then match_rank; ties go to the earlier entry."""
    norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())
    best, key = None, None
    for e in entries:
        k = match_rank(pattern_of(e), text, value)
        if k is not None:
            k = (bool(value) and name_of is not None and norm(name_of(e)) == norm(value),) + k
        if k is not None and (key is None or k > key):
            best, key = e, k
    return best


def lookup(text):
    """{name: (typ, lo, hi, source text)} for the table entry whose regex names the part text best
    (match_rank: from a word boundary, the most specific)."""
    e = best_match(parts_table(), lambda e: e["match"], text)
    if e is None:
        return {}
    out = {}
    for k, v in e.get("data", {}).items():
        if isinstance(v, list):
            lo, hi = float(v[0]), float(v[-1])
            out[k] = (math.sqrt(lo * hi) if lo > 0 else (lo + hi) / 2, lo, hi, e.get("source", ""))
        else:
            out[k] = (float(v), float(v), float(v), e.get("source", ""))
    return out


def intent_value(intent, section, key, name):
    """(typ, lo, hi) from the intent file, or None: haslam.intent.facts.interval, the checker's own reader."""
    from haslam.intent.facts import interval
    v = ((intent or {}).get(section) or {}).get(key, {}).get(name)
    if v is None:
        return None
    return interval(v, f"facts.{section}.{key}.{name}")


# The points a band is evaluated at: the typical point, N_LHS Latin-hypercube samples, the all-low and all-high
# vertices, and the benign and adverse vertices (each parameter at the end that lowers, raises the band's harm)
EXTRA_POINTS = 5
# parameters whose low end is the harmful one when nothing measures the direction: an efficiency (more input
# current and loss), a cooling coefficient (heat stays), a commutation or edge time (faster edges ring and radiate
# more). Every other parameter does more harm at its high end (a current, a voltage, a theta, an on-resistance, an
# ambient). corners(score=...) measures the direction instead
LOW_IS_WORSE = ("eta", "h_W_m2K", "G_W_K", "t_i_s", "t_v_s")


def n_points(n_corners):
    """How many points corners(n=n_corners) returns (every band's per-corner lists have this length)."""
    return n_corners + EXTRA_POINTS


def _stream(seed, p):
    """A parameter's own random stream, keyed by its name: its samples do not depend on which other parameters the
    band has (a shared stream re-drew every column when one parameter was added: martinberlin's D1 read a worst T_j
    of 133 C, then 117 C, when an inductor's theta_jb joined the heat band). crc32, not hash(): stable across runs."""
    import zlib
    return np.random.default_rng([int(seed) & 0xFFFFFFFF, zlib.crc32(f"{p.subject}\x00{p.name}".encode())])


def _at(p, x):
    """The value at fraction x of p's interval (log-uniform where lo > 0)."""
    if p.lo > 0 and p.hi > p.lo:
        return math.exp(math.log(p.lo) + x * (math.log(p.hi) - math.log(p.lo)))
    return p.lo + x * (p.hi - p.lo)


def corners(params, n=16, seed=0, score=None):
    """Sample points over the parameters' intervals, a list of {(subject, name): value} of length n_points(n):

    0           the typical point;
    1 .. n      a Latin hypercube: each parameter's n strata in its own seeded order with its own jitter (log-uniform
                where lo > 0), from a stream keyed by the parameter's name (_stream), so adding or removing a
                parameter leaves every other parameter's samples as they were;
    n+1, n+2    the all-low and the all-high vertex;
    n+3, n+4    the benign and the adverse vertex: each parameter at the end that does the band less (more) harm.
                The direction is measured one parameter at a time from the typical point when `score` (point ->
                the band's harm, larger is worse) is given, else LOW_IS_WORSE.

    Why the adverse vertex: the worst of n random samples over k parameters is a random variable (the chance that
    one sample has every parameter in its harmful fifth is 0.2^k per sample), so the robust and worst totals moved
    with the seed and with any change to the parameter set. For a harm monotone in each parameter (a junction
    temperature in ambient, theta, current and cooling; a drop in each load current) the adverse vertex is the exact
    worst over the box, the same for every seed. A harm that is not monotone (an emission in the switching
    frequency) is still covered at both ends of each parameter by the all-low and all-high vertices and the
    hypercube; a parameter that raises one observer of the band and lowers another takes the band total's
    direction."""
    ps = list(params)
    typ = {(p.subject, p.name): p.typ for p in ps}
    pts = [dict(typ)]
    if not ps:
        return pts + [dict(typ) for _ in range(n + EXTRA_POINTS - 1)]
    cols = {}
    for p in ps:
        r = _stream(seed, p)
        cols[(p.subject, p.name)] = (r.permutation(n) + r.random(n)) / n
    for i in range(n):
        pts.append({(p.subject, p.name): _at(p, cols[(p.subject, p.name)][i]) for p in ps})
    pts.append({(p.subject, p.name): p.lo for p in ps})
    pts.append({(p.subject, p.name): p.hi for p in ps})
    worse_hi = {}
    for p in ps:
        k = (p.subject, p.name)
        if score is not None and p.hi != p.lo:
            s_lo, s_hi = score({**typ, k: p.lo}), score({**typ, k: p.hi})
            worse_hi[k] = s_hi >= s_lo
        else:
            worse_hi[k] = p.name not in LOW_IS_WORSE
    pts.append({(p.subject, p.name): (p.lo if worse_hi[(p.subject, p.name)] else p.hi) for p in ps})
    pts.append({(p.subject, p.name): (p.hi if worse_hi[(p.subject, p.name)] else p.lo) for p in ps})
    return pts
    k = len(ps)
    u = (rng.permuted(np.tile(np.arange(n), (k, 1)), axis=1).T + rng.random((n, k))) / n
    for row in u:
        d = {}
        for p, x in zip(ps, row):
            if p.lo > 0 and p.hi > p.lo:
                d[(p.subject, p.name)] = math.exp(math.log(p.lo) + x * (math.log(p.hi) - math.log(p.lo)))
            else:
                d[(p.subject, p.name)] = p.lo + x * (p.hi - p.lo)
        pts.append(d)
    pts.append({(p.subject, p.name): p.lo for p in ps})
    pts.append({(p.subject, p.name): p.hi for p in ps})
    return pts
