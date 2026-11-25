# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The relations vocabulary of `haslam.intent/1` (docs/topics/placement/llm-relations-input.md, R2-R3):
what the commanding LLM may say about where parts go, as typed relations over named objects.

    {"id": "sw-edge", "kind": "on_edge", "part": "SW1", "edge": "edge:west", "facing": "out",
     "strength": "required", "why": "thumb reaches the slider from the card edge"}

This module checks the shape only (kinds, arguments, values, ids, why); names are resolved against a
board by haslam.place.relations. Loading is strict: an unknown kind, argument or value is an IntentError
that lists what exists. Every relation needs a unique `id` and a `why` or a `source`.

Magnitudes are ordinal (tight | close | loose) and resolve on the solver side. A length ("2 mm") is
allowed only for a datasheet distance (open question 1, proposed answer): with a `source` it is taken
as given; without one it is still used but marked `assumed` in the status. The relations_mm setting
"forbid" rejects lengths outright (RAC's rule).
"""
from __future__ import annotations

import fnmatch

from . import units as U

STRENGTHS = ("required", "strong", "medium", "weak")      # Cassowary order: each dominates the next
MAGS = ("tight", "close", "loose")
COMMON = ("id", "kind", "strength", "why", "source", "category", "note")
# kind: (required arguments, optional arguments, default strength)
KINDS = {
    "near": (("a", "b"), ("mag",), "medium"),
    "group": (("members",), ("mag", "exclusive"), "medium"),
    "region": (("members", "region"), ("exclusive",), "strong"),
    "on_edge": (("part", "edge"), ("facing",), "required"),
    "keep_away": (("a", "b"), ("mag",), "medium"),
    "row": (("members",), ("axis", "from", "pitch", "beside"), "strong"),
    "order": (("path",), (), "strong"),
    "orient": (("part",), ("allowed", "pins_toward"), "required"),
    "side": (("members", "side"), (), "required"),
    "hold": (("members",), ("as",), "required"),
}
VALUES = {
    "facing": ("out", "along", "any"),
    "allowed": ("right_angles", "x_axis", "y_axis", "as_drawn", "any"),
    "axis": ("x", "y"),
    "pitch": ("equal", "any"),
    "side": ("top", "bottom"),
    "as": ("drawn",),
    "exclusive": (True, False),
}
CATEGORIES = ("electrical", "manufacturing", "assembly", "thermal", "safety", "data")   # haslam.hazards
MM_POLICIES = ("sourced", "forbid")


def _err(msg):
    from .objective import IntentError
    return IntentError(msg)


def magnitude(v, rid, mm_policy="sourced"):
    """('mag', name) for an ordinal magnitude, ('mm', value) for a length; else an IntentError."""
    if v in MAGS:
        return "mag", v
    if mm_policy == "forbid":
        raise _err(f"relation {rid}: mag {v!r}: use one of {MAGS} (lengths are switched off: relations_mm forbid)")
    try:
        val, dim = U.quantity(v)
    except U.UnitError:
        raise _err(f"relation {rid}: mag {v!r}: use one of {MAGS}, or a datasheet length such as '2 mm' "
                   f"with its 'source'") from None
    if dim != "m" or val <= 0:
        raise _err(f"relation {rid}: mag {v!r} is not a positive length; use one of {MAGS} or e.g. '2 mm'")
    return "mm", val * 1e3


def _names(v, rid, key, single=False):
    if isinstance(v, str) and v:
        return
    if not single and isinstance(v, list) and v and all(isinstance(x, str) and x for x in v):
        return
    what = "a name" if single else "a name (a section) or a list of names"
    raise _err(f"relation {rid}: '{key}' must be {what}, got {v!r}")


def check(rels, mm_policy="sourced", defaults_off=None):
    """Shape check of an intent's `relations` list (and its `defaults_off` globs); raises IntentError.
    Returns the relations with their default strength filled in."""
    if mm_policy not in MM_POLICIES:
        raise _err(f"relations_mm '{mm_policy}' unknown; use one of {MM_POLICIES}")
    if defaults_off is not None and not (isinstance(defaults_off, list)
                                         and all(isinstance(x, str) and x.startswith("D-") for x in defaults_off)):
        raise _err(f"defaults_off must be a list of default-row globs such as 'D-label-*', got {defaults_off!r}")
    if rels is None:
        return []
    if not isinstance(rels, list):
        raise _err("relations must be a list of relation objects")
    out, seen = [], set()
    for r in rels:
        if not isinstance(r, dict):
            raise _err(f"relation {r!r}: every relation is an object with 'id' and 'kind'")
        rid = r.get("id")
        if not rid or not isinstance(rid, str) or rid in seen:
            raise _err(f"relation {r}: every relation needs a unique 'id'")
        if rid.startswith("D-"):
            raise _err(f"relation {rid}: ids starting 'D-' name haslam's own default rows; pick another id")
        seen.add(rid)
        kind = r.get("kind")
        if kind not in KINDS:
            raise _err(f"relation {rid}: kind {kind!r} unknown; kinds: {sorted(KINDS)}")
        req, opt, default = KINDS[kind]
        bad = [k for k in r if k not in COMMON + req + opt]
        if bad:
            raise _err(f"relation {rid}: arguments {bad} unknown for {kind}; it takes {list(req + opt)} "
                       f"and {list(COMMON)}")
        miss = [k for k in req if k not in r]
        if miss:
            raise _err(f"relation {rid}: {kind} needs {miss}")
        if not (r.get("why") or r.get("source")):
            raise _err(f"relation {rid}: say why (a 'why' or a 'source'): every relation is traceable")
        s = r.get("strength", default)
        if s not in STRENGTHS:
            raise _err(f"relation {rid}: strength {s!r} unknown; use one of {STRENGTHS}")
        if r.get("category") is not None and r["category"] not in CATEGORIES:
            raise _err(f"relation {rid}: category {r['category']!r} unknown; use one of {CATEGORIES}")
        for k, vals in VALUES.items():
            if k in r and r[k] not in vals:
                if k == "as" and r[k] == "relative":
                    raise _err(f"relation {rid}: hold as 'relative' (a block kept as drawn) is not built: it "
                               f"waits on open question 6 ('like the human did') of llm-relations-input.md")
                raise _err(f"relation {rid}: {k} {r[k]!r} unknown; use one of {list(vals)}")
        if "mag" in r:
            magnitude(r["mag"], rid, mm_policy)
        for k in ("a", "b", "part", "region", "edge", "from"):
            if k in r:
                _names(r[k], rid, k, single=True)
        for k in ("members",):
            if k in r:
                _names(r[k], rid, k)
        if kind == "order":
            if not (isinstance(r["path"], list) and len(r["path"]) >= 3 and all(isinstance(x, str) for x in r["path"])):
                raise _err(f"relation {rid}: order 'path' is a list of at least 3 parts or pins, from the "
                           f"first (e.g. the connector pin) to the last")
        if kind == "orient":
            if "allowed" not in r and "pins_toward" not in r:
                raise _err(f"relation {rid}: orient needs 'allowed' ({VALUES['allowed']}) or 'pins_toward'")
            pt = r.get("pins_toward")
            if pt is not None and not (isinstance(pt, list) and len(pt) == 2 and isinstance(pt[1], str)
                                       and (isinstance(pt[0], str) or isinstance(pt[0], list))):
                raise _err(f"relation {rid}: pins_toward is [pins, target], e.g. [['J1.1', 'J1.2'], 'edge:west']")
        if kind == "region" and not (r["region"].startswith(("region:", "area:", "edge:"))):
            raise _err(f"relation {rid}: region {r['region']!r}: name a compass cell (region:nw ... region:se, "
                       f"region:c), a rule area (area:<name>) or an edge band (edge:north ...)")
        if kind == "on_edge" and not r["edge"].startswith("edge:"):
            raise _err(f"relation {rid}: edge {r['edge']!r}: use edge:north|south|east|west|nearest")
        if kind == "row" and "beside" in r and r["beside"] != "labels":
            raise _err(f"relation {rid}: row beside {r['beside']!r}: only 'labels'")
        out.append(dict(r, strength=s))
    return out


def defaults_on(rid, defaults_off):
    """Is default row `rid` (D-...) on, given the intent's defaults_off globs?"""
    return not any(fnmatch.fnmatch(rid, g) for g in (defaults_off or ()))
