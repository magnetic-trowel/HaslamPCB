# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a KiCad DRC report says, read one way everywhere: which violations count as errors, how
many unconnected items there are past kicad-cli's cap, and which checks make a placement illegal.

Standard library only: tools/kaeres/restart.py loads this file by path (as it loads stepcache.py),
so the restart judge and kae count the same way. kaebench keeps its own copies (the benchmark's
scorer stays independent of kae); kae/tests/test_drc_items.py asserts they are equal.
"""
import json
import re
from pathlib import Path

# Violation types that depend on the local library setup, not on the board (kaebench.tools
# ENV_DEPENDENT_CHECKS).
ENV_DEPENDENT = ("lib_footprint_issues", "lib_footprint_mismatch")

# kicad-cli lists at most this many unconnected items (kaebench.score DRC_UNCONNECTED_CAP); past it,
# or when the project ignores the check (unconnected_ignored), the count comes from pcbnew's
# connectivity after a zone fill (UNCONNECTED_PY), as the scorer counts (score._uncapped). On
# polarfire-som every repair round and ~150 restart attempts read 499 and chose blind.
DRC_UNCONNECTED_CAP = 499
UNCONNECTED_PY = ("import json, sys, pcbnew\n"
                  "b = pcbnew.LoadBoard(sys.argv[1]); zs = pcbnew.ZONES()\n"
                  "for i in range(b.GetAreaCount()): zs.append(pcbnew.Cast_to_ZONE(b.GetArea(i)))\n"
                  "len(zs) and pcbnew.ZONE_FILLER(b).Fill(zs)\n"
                  "b.BuildConnectivity()\n"
                  "print(json.dumps(dict(unconnected=b.GetConnectivity().GetUnconnectedCount(False))))\n")

# KiCad DRC types that make a placement illegal: kaebench.score PLACEMENT_ERROR_TYPES, the
# benchmark's `legal`. kae's own legality counts (joint stages, spots) use exactly this set.
PLACEMENT_TYPES = ("courtyards_overlap", "copper_edge_clearance", "clearance", "hole_clearance", "hole_to_hole",
                   "holes_co_located", "items_not_allowed", "malformed_courtyard", "npth_inside_courtyard",
                   "pth_inside_courtyard", "shorting_items")
# What the placer's KiCad feedback (place.legalize.kicad_violations) reacts to: the illegal types plus
# solder mask bridges. A bridge between two parts' pads is the placement's doing (the mask web
# between them is gone) though the benchmark does not count it; one inside a footprint (about 9 in
# 10 of all bridges in the corpus) is the footprint's, and the placer drops those as fixed-only.
PLACER_TYPES = PLACEMENT_TYPES + ("solder_mask_bridge",)


def errors(report, ignore=ENV_DEPENDENT, types=None):
    """Error-level violations of a DRC report (unconnected items aside), `ignore`d types dropped,
    only `types` when given. KiCad writes every violation's severity."""
    return [v for v in (report or {}).get("violations") or []
            if v.get("severity") == "error" and v.get("type") not in ignore and (types is None or v.get("type") in types)]


def errors_by_type(report, ignore=ENV_DEPENDENT):
    """{type: count} of errors(report)."""
    by = {}
    for v in errors(report, ignore):
        by[v.get("type")] = by.get(v.get("type"), 0) + 1
    return by


def unconnected_ignored(board):
    """True when the project beside `board` sets the unconnected_items check to "ignore": KiCad's
    DRC then lists no unconnected items at all, even with --severity-all, so its count says nothing
    about connectivity (kaebench boardfiles.unconnected_ignored). gamaphy-freedom-rp2040 is one."""
    try:
        pro = json.loads(Path(board).with_suffix(".kicad_pro").read_text(encoding="utf-8"))
        return pro["board"]["design_settings"]["rule_severities"]["unconnected_items"] == "ignore"
    except (OSError, ValueError, KeyError, TypeError):
        return False


# --- the items a violation names ------------------------------------------------------------
# KiCad writes each item as text: "Pad 2 [GND] of C3 on F.Cu", "PTH pad 6 [GND] of J11",
# "NPTH pad of H1", "Footprint U1", "Footprint text of U3 (${REV})", "Reference field of D1",
# "Track [SDA] on F.Cu, length 1.2 mm", "Via [VCC] on F.Cu - B.Cu", "Zone [GND] on L1 [Top],
# priority 0", "Segment on Edge.Cuts". Net names are shown unescaped ("A/B" for the board's
# "A{slash}B": unescape) and may hold brackets themselves ("sdram_dq[0]"), and user layer names
# may too ("Via [GND] on L1 [TOP] - L4 [BOT]"): an item names at most one net, opened by its first
# bracket and closed by the bracket followed by " of ", " on " or the end.
_NET = re.compile(r"^([^\[]*)\[(.*?)\](?= of | on |\s*$)", re.S)   # the first bracket opens the net
_OF = re.compile(r"\bof (\S.*?)(?= on | \(|\s*$)", re.S)        # references may hold spaces ("On - Off")
_FOOTPRINT = re.compile(r"^Footprint (?!text of )(\S.*?)(?= \(|\s*$)")   # "Footprint U1", "Footprint ADS4 (0x4B)"
_KINDS = (("pad", ("pad", "pth pad", "npth pad", "smd pad")), ("track", ("track", "arc")), ("via", ("via",)),
          ("zone", ("zone", "teardrop")), ("footprint", ("footprint",)))
_ESCAPES = {"{slash}": "/", "{backslash}": "\\", "{lt}": "<", "{gt}": ">", "{colon}": ":", "{dblquote}": '"',
            "{quote}": "'", "{space}": " ", "{tab}": "\t", "{return}": "\n", "{brace}": "{", "{comma}": ","}


def item_kind(desc):
    """pad | track | via | zone | footprint | other, from an item's description."""
    low = (desc or "").lower()
    return next((k for k, heads in _KINDS if low.startswith(heads)), "other")


def item_nets(desc):
    """Net names an item's description shows, "<no net>" left out."""
    d = desc or ""
    m = None if d.startswith("PCB text") else _NET.match(d)
    return [m.group(2)] if m and m.group(2) and m.group(2) != "<no net>" else []


def item_ref(desc):
    """The reference of the footprint an item belongs to ("C3" of "Pad 2 [GND] of C3 on F.Cu",
    "U1" of "Footprint U1"), None for a board item (a track, a zone, board text, Edge.Cuts)."""
    d = desc or ""
    if d.startswith("PCB text"):
        return None
    d = _NET.sub(r"\1[]", d, count=1)
    m = _FOOTPRINT.match(d) or _OF.search(d)
    return m.group(1) if m else None


def open_nets(report):
    """Nets of the unconnected items of a DRC report, sorted (as shown: see unescape)."""
    return sorted({n for u in (report or {}).get("unconnected_items") or [] for it in u.get("items") or []
                   for n in item_nets(it.get("description"))})


def unescape(name):
    """A board net name as KiCad's DRC report shows it."""
    for k, v in _ESCAPES.items():
        name = name.replace(k, v)
    return name


def board_nets(shown, known):
    """The board's names (`known`) of nets a report shows (`shown`); a name not known stays as is."""
    known = list(known)
    have, by_shown = set(known), {unescape(n): n for n in known}
    return [n if n in have else by_shown.get(n, n) for n in shown]
