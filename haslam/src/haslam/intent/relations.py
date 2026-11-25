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
"forbid" rejects lengths outright (RAC's rule). `on_edge` takes a length too: how far its courtyard may
sit from the edge (default EDGE_TOL, 1 mm).

The intent-relations spelling (haslamsynth's first emitter) is read for a transition (`normalize`, a note on
the row says so): `within_mm: 5` / `min_mm: 5` is `mag: "5 mm"`, and `{"kind": "edge", "edge": "west"}` is
`{"kind": "on_edge", "edge": "edge:west", "facing": "any", "strength": "medium"}` (a soft pull: that
spelling never pinned a part). docs/topics/placement/relations-unified.md compares the two designs.
"""
from __future__ import annotations

import fnmatch
import json

from . import units as U

STRENGTHS = ("required", "strong", "medium", "weak")      # Cassowary order: each dominates the next
MAGS = ("tight", "close", "loose")
COMMON = ("id", "kind", "strength", "why", "source", "category", "note")
# kind: (required arguments, optional arguments, default strength)
KINDS = {
    "near": (("a", "b"), ("mag",), "medium"),
    "group": (("members",), ("mag", "exclusive"), "medium"),
    "region": (("members", "region"), ("exclusive",), "strong"),
    "on_edge": (("part", "edge"), ("facing", "mag"), "required"),
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


# the intent-relations spelling, read for a transition (normalize)
ALIAS_MM = {"within_mm": ("near", "group", "edge", "on_edge"), "min_mm": ("keep_away",)}


def normalize(r):
    """A relation in the intent-relations spelling rewritten in this one, with a note saying so; any other
    relation as it is. Raises IntentError on a spelling that is neither."""
    if not isinstance(r, dict):
        return r
    rid = r.get("id")
    old = [k for k in ALIAS_MM if k in r]
    if not old and r.get("kind") != "edge":
        return r
    out = dict(r)
    notes = []
    for k in old:
        v = out.pop(k)
        if r.get("kind") not in ALIAS_MM[k]:
            raise _err(f"relation {rid}: {k} is for {list(ALIAS_MM[k])}; write mag \"<length> mm\" instead")
        if "mag" in r:
            raise _err(f"relation {rid}: both mag and {k}; keep mag")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise _err(f"relation {rid}: {k} is a distance in mm (a number >= 0), not {v!r}")
        out["mag"] = f"{float(v):g} mm"
        notes.append(f"{k}: {v:g} read as mag '{out['mag']}'")
    if r.get("kind") == "edge":
        e = str(out.get("edge", ""))
        out["kind"] = "on_edge"
        out["edge"] = e if e.startswith("edge:") else f"edge:{e}"
        out.setdefault("facing", "any")
        out.setdefault("strength", "medium")
        out.setdefault("mag", "5 mm")              # the old spelling's default distance from the edge
        notes.append(f"kind edge read as on_edge {out['edge']}, facing {out['facing']}, {out['strength']}")
    note = "intent-relations spelling: " + "; ".join(notes)
    out["note"] = f"{r['note']}; {note}" if r.get("note") else note
    return out


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
        r = normalize(r)
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
            mk, _ = magnitude(r["mag"], rid, mm_policy)
            if kind == "on_edge" and mk != "mm":
                raise _err(f"relation {rid}: an on_edge mag is a length (how far its courtyard may sit from "
                           f"the edge, e.g. '3 mm'), not {r['mag']!r}")
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
        if kind == "on_edge" and not (r["edge"].startswith("edge:")
                                      and r["edge"][5:] in ("north", "south", "east", "west", "nearest")):
            raise _err(f"relation {rid}: edge {r['edge']!r}: use edge:north|south|east|west|nearest")
        if kind == "row" and "beside" in r and r["beside"] != "labels":
            raise _err(f"relation {rid}: row beside {r['beside']!r}: only 'labels'")
        out.append(dict(r, strength=s))
    return out


def defaults_on(rid, defaults_off):
    """Is default row `rid` (D-...) on, given the intent's defaults_off globs?"""
    return not any(fnmatch.fnmatch(rid, g) for g in (defaults_off or ()))


def for_brief(board_path):
    """The relations part of the board's own intent file, for the brief (haslam.circuit.brief.build):
    {origin, intent: {relations, defaults_off, sections, terms, generation}}, or {origin, error} when the file
    does not load; None without a file or without relations. Never raises: the brief has many readers."""
    if not board_path:
        return None
    from .facts import sidecar           # the one place the file's name is defined (facts.INTENT_EXT)
    p = sidecar(board_path)
    if not p.is_file():
        return None
    from .objective import IntentError, load
    try:
        it = load(json.loads(p.read_text()))
    except (IntentError, ValueError, OSError) as e:
        return dict(origin=p.name, error=f"{type(e).__name__}: {e}")
    if not it.get("relations") and not it.get("defaults_off"):
        return None
    return dict(origin=p.name, intent={k: it[k] for k in ("schema", "relations", "defaults_off", "sections", "terms",
                                                          "generation") if k in it})
