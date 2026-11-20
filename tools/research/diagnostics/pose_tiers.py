# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose-transplant diagnostic (stage-regret ladder): kae's staged place-and-route with one tier
of parts held at the human's poses, to find which placement decision makes kae placements
route worse than human ones. The human poses are an oracle for diagnosis only, never a method.

Tiers (a part's size is its terminal count: distinct non-empty pad numbers over its copper
pads, so split paste pads and repeated shield pads count once; NPTH holes do not count):

    none   nothing held                                      arm K (kae places everything)
    big    >= BIG_PADS terminals, or a connector              arm B
    mid    every part except non-connector 2-terminal parts   arm M (kae places only 2-pad parts)
    small  non-connector 2-terminal parts (= all - mid)       arm P (kae places the rest)
    all    every part                                         arm H (the bridge on the human poses)

Connectors are those `kae place --fix-class connectors` holds (kae.place.fixed.classify). Tiers
nest (none < big < mid < all) and small is mid's complement, so M and P are mirrors. Parts
locked in the input stay where they are in every arm, as in the control.

    pose_tiers.py refs BOARD --tier T [--big-pads 16]          comma-separated refs held
    pose_tiers.py run-arm IN OUT --tier T --seed S --time T [--set K=V ...] [--report R]
    pose_tiers.py pose-diff IN OUT --tier T                    JSON: held parts moved (must be 0)

run-arm is the stored staged control (`kae.joint.cli run --max-iters 0 --no-modules`: place,
then the bridge) with the tier passed to the placer as fixed parts (kae.place.pipeline.place's
`fixed`, the same mechanism as `kae place --fix`). Tier none calls the control unchanged. The
caller sets KAE_BUDGET=work (the recipe template does; run-arm sets it when unset).
"""
import argparse
import contextlib
import json
import os
import sys

TIERS = ("none", "big", "mid", "small", "all")
BIG_PADS = 16


def terminals(fp):
    """Distinct non-empty pad numbers over the part's copper pads."""
    return len({str(p.number) for p in fp.pads if p.kind != "np_thru_hole" and str(p.number or "").strip()})


def tier_uuids(board, tier, big_pads=BIG_PADS):
    """uuids of the footprints held at their input pose for `tier` (see the module docstring)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r} (known: {', '.join(TIERS)})")
    fps = list(board.footprints)
    if tier == "none":
        return set()
    if tier == "all":
        return {f.uuid for f in fps}
    from kae.place.fixed import classify
    conn = {u for u, c in classify(board).items() if c["cls"] == "connectors"}
    if tier == "big":
        return {f.uuid for f in fps if f.uuid in conn or terminals(f) >= big_pads}
    small = {f.uuid for f in fps if f.uuid not in conn and terminals(f) == 2}
    if tier == "small":
        return small
    return {f.uuid for f in fps} - small          # mid


def tier_refs(board, tier, big_pads=BIG_PADS):
    held = tier_uuids(board, tier, big_pads)
    return sorted({f.ref for f in board.footprints if f.uuid in held})


@contextlib.contextmanager
def placer_holding(tier, big_pads=BIG_PADS, log=None):
    """Within the block, kae.place.pipeline.place holds `tier`'s parts as fixed (added to any
    `fixed` the caller passes). Tier none leaves the placer untouched."""
    if tier == "none":
        yield
        return
    import kae.place.pipeline as P
    orig = P.place

    def place(board, *args, **kw):
        held = tier_uuids(board, tier, big_pads)
        if log:
            log(f"pose tier {tier}: {len(held)} of {len(board.footprints)} parts held at their input pose")
        kw["fixed"] = set(kw.get("fixed") or ()) | held
        return orig(board, *args, **kw)

    P.place = place
    try:
        yield
    finally:
        P.place = orig


def pose_diff(inp, out, tier, big_pads=BIG_PADS, tol_mm=1e-3, tol_deg=1e-3):
    """Held parts whose pose differs between the input and output boards, and how many others moved."""
    from kae.board.kicad_file import load
    a, b = load(inp), load(out)
    held = tier_uuids(a, tier, big_pads)
    ob = {f.uuid: f for f in b.footprints}

    def moved(f, g):
        dr = abs(((f.rot - g.rot) + 180.0) % 360.0 - 180.0)
        return abs(f.x - g.x) > tol_mm or abs(f.y - g.y) > tol_mm or dr > tol_deg or f.side != g.side

    bad, free_moved, missing = [], 0, []
    for f in a.footprints:
        g = ob.get(f.uuid)
        if g is None:
            missing.append(f.ref)
        elif f.uuid in held and moved(f, g):
            bad.append(dict(ref=f.ref, input=(f.x, f.y, f.rot, f.side), output=(g.x, g.y, g.rot, g.side)))
        elif f.uuid not in held and moved(f, g):
            free_moved += 1
    return dict(tier=tier, parts=len(a.footprints), held=len(held), held_moved=bad, free_moved=free_moved,
                free=len(a.footprints) - len(held), missing=missing, ok=not bad and not missing)


def _log(msg):
    print(f"[pose_tiers] {msg}", file=sys.stderr, flush=True)


def run_arm(a):
    os.environ.setdefault("KAE_BUDGET", "work")
    from kae.joint import cli as J
    argv = ["run", a.input, a.output, "--seed", str(a.seed), "--time", str(a.time), "--max-iters", "0",
            "--no-modules"]
    for kv in a.set or []:
        argv += ["--set", kv]
    if a.report:
        argv += ["--report", a.report]
    _log(f"arm tier={a.tier} big_pads={a.big_pads}: kae.joint.cli {' '.join(argv)}")
    with placer_holding(a.tier, a.big_pads, log=_log):
        return J.main(argv)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pose_tiers", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("refs", "run-arm", "pose-diff"):
        s = sub.add_parser(name)
        s.add_argument("input")
        if name != "refs":
            s.add_argument("output")
        s.add_argument("--tier", required=True, choices=TIERS)
        s.add_argument("--big-pads", type=int, default=BIG_PADS, help="terminals that make a part big (16)")
        if name == "run-arm":
            s.add_argument("--seed", type=int, default=0)
            s.add_argument("--time", type=float, default=900.0)
            s.add_argument("--set", action="append", metavar="KEY=VALUE", help="passed to kae.joint.cli run")
            s.add_argument("--report")
    a = ap.parse_args(argv)
    if a.cmd == "refs":
        from kae.board.kicad_file import load
        print(",".join(tier_refs(load(a.input), a.tier, a.big_pads)))
        return 0
    if a.cmd == "pose-diff":
        r = pose_diff(a.input, a.output, a.tier, a.big_pads)
        print(json.dumps(r))
        return 0 if r["ok"] else 1
    return run_arm(a)


if __name__ == "__main__":
    sys.exit(main())
