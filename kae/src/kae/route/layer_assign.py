# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-net layer sets for the bulk router: a layer assignment handed to Freerouting as bounds.

The setting `net_layers` (constraints.DEFAULTS; a KAE_NET_LAYERS project text variable, the run's
opts, or env KAE_NET_LAYERS) names a table of the copper layers each net's tracks may use. Unset
(the default), nothing here runs and the plan is unchanged.

The table reaches the router through what already exists: constraints.plan() adds the layers a
net may not use to the net's `off` layers, nets with different `off` get their own routing class,
translate writes the class's `(circuit (use_layer ...))`, and the Freerouting fork turns the other
layers off for that class (inactive layers get no trace width). Freerouting applies `use_layer`
per class only, so a table with many different layer sets makes many classes; the class-to-class
clearance matrix is quadratic in them, hence `net_layers_max_sets`.

The table is a JSON file, or a directory holding one file per board:

    {"version": 1, "source": "free text", "nets": {"<net name>": ["F.Cu", "In2.Cu"], ...}}

In a directory the board's file is `<board file stem>.json`, else `<fingerprint>.json`, where the
fingerprint is of the board's net names (fingerprint(); tools/research/routing/net_layers.py
writes both names), so a table made from a routed copy of a board finds the bare board.

What a table may hold: the output of a layer-assignment planner. A table extracted from a human
layout of the same board is an oracle for diagnosis only ("what can a perfect layer plan buy
through this router"): it is never committed and never used in a delivered method.

Rules that keep a restriction routable:
- the layers of a net's surface-mount pads are always allowed (a pad on a layer that is off for
  its class cannot be left; through-hole pads reach every layer and add nothing);
- a net whose allowed layers are all inner plane layers (translate.plane_layers: an attempt may
  type those as power layers, which carry no tracks) keeps every layer;
- a net absent from the table, with no listed layer on this board, or allowed everywhere, keeps
  every layer;
- past `net_layers_max_sets` different layer sets, the sets with the fewest nets are dropped.
"""
import hashlib
import json
from pathlib import Path


def fingerprint(net_names):
    """A board's identity for table lookup: 16 hex digits of the SHA-1 of its sorted net names."""
    names = sorted({n for n in net_names if n})
    return hashlib.sha1("\n".join(names).encode()).hexdigest()[:16]


def _table_file(where, board_path, info):
    p = Path(str(where)).expanduser()
    if not p.is_dir():
        return p
    for name in ((Path(str(board_path)).stem if board_path else None), fingerprint(info.get("nets") or ())):
        if name and (p / f"{name}.json").is_file():
            return p / f"{name}.json"
    return None


def assign(info, board_path, opts, cu):
    """({net: layers its tracks may NOT use}, summary) from the `net_layers` setting; ({}, None)
    when it is unset. The summary says what was restricted and what was not, and why."""
    from . import constraints as CN
    where = CN.setting_env("net_layers", board_path, opts)
    if not where:
        return {}, None
    f = _table_file(where, board_path, info)
    if f is None or not f.is_file():
        return {}, dict(table=str(where), found=False, restricted=0)
    doc = json.loads(f.read_text())
    table = doc.get("nets") or {}
    try:
        from .translate import plane_layers
        planes = set(plane_layers(info))
    except (KeyError, TypeError, ValueError):   # an info without outline or zones (unit fixtures): no planes
        planes = set()
    pad_layers = {}
    for pad in info.get("pads") or []:
        net = pad.get("net")
        if net and not pad.get("drilled"):
            pad_layers.setdefault(net, set()).update(l for l in pad.get("layers") or [] if l in cu)
    why = dict(absent=0, no_layer_here=0, everywhere=0, planes_only=0, rare_set=0)
    allowed = {}
    for net in info.get("nets") or ():
        if not net:
            continue
        if net not in table:
            why["absent"] += 1
            continue
        listed = {l for l in table[net] or [] if l in cu}
        if not listed:
            why["no_layer_here"] += 1
            continue
        a = listed | pad_layers.get(net, set())
        if len(a) == len(cu):
            why["everywhere"] += 1
        elif a <= planes:
            why["planes_only"] += 1
        else:
            allowed[net] = tuple(l for l in cu if l in a)
    cap = int(CN.setting("net_layers_max_sets", board_path, opts))
    count = {}
    for a in allowed.values():
        count[a] = count.get(a, 0) + 1
    keep = set(sorted(count, key=lambda a: (-count[a], a))[:max(cap, 0)])
    why["rare_set"] = sum(n for a, n in count.items() if a not in keep)
    off = {net: tuple(l for l in cu if l not in a) for net, a in allowed.items() if a in keep}
    summary = dict(table=str(f), found=True, source=doc.get("source"), restricted=len(off), layer_sets=len(keep),
                   unrestricted=why)
    return off, summary
