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

Where the held poses come from. A place task's input has its free parts staged off the board,
so its poses are not the human's: holding a tier there left the held parts off the outline and
the placement illegal (pose-transplant, 2026-11-21: 64 and 68 of 70 runs). With
`--set pose_source=DIR` the held parts are moved to the human poses of a pose oracle in DIR
(one JSON per board, keyed by board_key; built outside the method's sandbox from the task's
human placement by tools/research/diagnostics/pose_oracle.py, which also checks the held poses
with the harness's own placement DRC). A tier the oracle found illegal, or a board it lacks,
stops the run with the reason, before any placement or routing. Without pose_source the parts
are held where the input has them (the first build's behaviour), and an input with a held part
off the board is refused.
"""
import hashlib
import json
from pathlib import Path

TIERS = ("none", "big", "mid", "small", "all")
BIG_PADS = 16
ORACLE_SCHEMA = "kae-pose-oracle/1"


class PoseOracleError(RuntimeError):
    """The held poses cannot be used: the run stops with this reason."""


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
    return set(held_poses(board, opts))


def board_key(board):
    """A board's key in a pose oracle: its footprint uuids (the same in a task's input and its
    human placement), hashed."""
    return hashlib.sha256("\n".join(sorted(f.uuid for f in board.footprints)).encode()).hexdigest()[:16]


def oracle_path(source, board):
    return Path(source) / f"{board_key(board)}.json"


def held_poses(board, opts):
    """{uuid: (x, y, rot, side)}: the parts pose_tier holds and the poses they are held at (empty
    without a tier). Raises PoseOracleError when they cannot be held legally (module docstring)."""
    opts = opts or {}
    tier = opts.get("pose_tier") or "none"
    if tier == "none":
        return {}
    source = opts.get("pose_source")
    if not source:
        uu = tier_uuids(board, tier, int(opts.get("pose_big_pads") or BIG_PADS))
        off = sorted(f.ref for f in board.footprints if f.uuid in uu and not getattr(f, "on_board", True))
        if off:
            raise PoseOracleError(
                f"pose_tier={tier}: {len(off)} held parts are off the board ({', '.join(off[:8])}"
                f"{', ...' if len(off) > 8 else ''}); a place task's input stages its free parts there, so these are "
                "not the human's poses: give pose_source=DIR (tools/research/diagnostics/pose_oracle.py build)")
        return {f.uuid: (f.x, f.y, f.rot, f.side) for f in board.footprints if f.uuid in uu}
    p = oracle_path(source, board)
    if not p.is_file():
        raise PoseOracleError(f"pose_tier={tier}: no human poses for this board (key {board_key(board)}) in {source}")
    o = json.loads(p.read_text())
    if o.get("schema") != ORACLE_SCHEMA:
        raise PoseOracleError(f"pose_tier={tier}: {p.name} is not a {ORACLE_SCHEMA} file")
    t = (o.get("tiers") or {}).get(tier)
    if t is None:
        raise PoseOracleError(f"pose_tier={tier}: the pose oracle of {o.get('board')} has no tier {tier}")
    if int(opts.get("pose_big_pads") or BIG_PADS) != int(o.get("big_pads", BIG_PADS)):
        raise PoseOracleError(f"pose_tier={tier}: the oracle was built with big_pads={o.get('big_pads')}")
    if not t.get("legal"):
        raise PoseOracleError(f"pose_tier={tier}: {o.get('board')} excluded: {t.get('reason')}")
    have = {f.uuid for f in board.footprints}
    lost = sorted(set(t["held"]) - have)
    if lost:
        raise PoseOracleError(f"pose_tier={tier}: {len(lost)} held parts of the oracle are not on this board")
    return {u: (float(p[0]), float(p[1]), float(p[2]), p[3]) for u, p in t["held"].items()}
