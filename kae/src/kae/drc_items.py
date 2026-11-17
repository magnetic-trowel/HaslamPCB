# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a KiCad DRC report says, read one way everywhere: which violations count as errors, how
many unconnected items there are past kicad-cli's cap, and which checks make a placement illegal.

Standard library only: tools/kaeres/restart.py loads this file by path (as it loads stepcache.py),
so the restart judge and kae count the same way. kaebench keeps its own copies (the benchmark's
scorer stays independent of kae); kae/tests/test_drc_items.py asserts they are equal.
"""
import json
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
