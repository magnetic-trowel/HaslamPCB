# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose-transplant diagnostic tiers: which parts a diagnostic run holds at their input pose
(the human's, on a prepared task board). A diagnostic oracle, never a method: off unless the
joint stages get `--set pose_tier=TIER` (kae.joint.stages, default: nothing held, the placer
call unchanged). See tools/research/diagnostics/pose_tiers.py and
tools/kaeres/experiments/pose-transplant/PLAN.md.

A part's size is its terminal count: distinct non-empty pad numbers over its copper pads
(split paste pads and repeated shield pads count once; NPTH holes do not count).
Connectors are those `kae place --fix-class connectors` holds (kae.place.fixed.classify).

    none   nothing held                                   arm K (the control)
    big    >= big_pads terminals (16), or a connector      arm B
    mid    big, plus every part with >= 3 terminals        arm M (kae places the 2-terminal parts)
    small  non-connector 2-terminal parts                  arm P (kae places parts with >= 3)
    all    every part                                     arm H

Parts with fewer than 2 terminals (holes, fiducials, test points) are held only in `all`.
Tiers nest: none < big < mid < all; mid and small are disjoint.
"""
TIERS = ("none", "big", "mid", "small", "all")
BIG_PADS = 16


def terminals(fp):
    """Distinct non-empty pad numbers over the part's copper pads."""
    return len({str(p.number) for p in fp.pads if p.kind != "np_thru_hole" and str(p.number or "").strip()})


def tier_uuids(board, tier, big_pads=BIG_PADS):
    """uuids of the footprints `tier` holds at their input pose."""
    if tier not in TIERS:
        raise ValueError(f"unknown pose tier {tier!r} (known: {', '.join(TIERS)})")
    fps = list(board.footprints)
    if tier == "none":
        return set()
    if tier == "all":
        return {f.uuid for f in fps}
    from .fixed import classify
    conn = {u for u, c in classify(board).items() if c["cls"] == "connectors"}
    big = {f.uuid for f in fps if f.uuid in conn or terminals(f) >= big_pads}
    if tier == "big":
        return big
    if tier == "mid":
        return big | {f.uuid for f in fps if terminals(f) >= 3}
    return {f.uuid for f in fps if f.uuid not in conn and terminals(f) == 2}      # small


def held(board, opts):
    """The parts the stage options' pose_tier holds (empty without one: the default)."""
    tier = (opts or {}).get("pose_tier") or "none"
    return tier_uuids(board, tier, int((opts or {}).get("pose_big_pads") or BIG_PADS))
