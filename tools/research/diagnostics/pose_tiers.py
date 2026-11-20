# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose-transplant diagnostic (stage-regret ladder): kae's staged place-and-route with one tier
of parts held at the human's poses, to find which placement decision makes kae placements
route worse than human ones. The human poses are an oracle for diagnosis only, never a method.

Tiers: kae.place.pose_tiers (none = K, big = B, mid = M, small = P, all = H).

    pose_tiers.py refs BOARD --tier T [--big-pads 16]          comma-separated refs held
    pose_tiers.py run-arm IN OUT --tier T --seed S --time T [--set K=V ...] [--report R]
    pose_tiers.py pose-diff IN OUT --tier T                    JSON: held parts moved (must be 0)

run-arm is the stored staged control (`kae.joint.cli run --max-iters 0 --no-modules`: place,
then the bridge) with `--set pose_tier=TIER`: kae.joint.stages passes the tier to the placer as
fixed parts (kae.place.pipeline.place's `fixed`, the mechanism of `kae place --fix`). Tier none
adds no setting: the control unchanged. A kaeres arm can equally be the control's template plus
`--set pose_tier=TIER` (the sprint command's --set). The
caller sets KAE_BUDGET=work (the recipe template does; run-arm sets it when unset).
"""
import argparse
import json
import os
import sys

from kae.place.pose_tiers import BIG_PADS, TIERS, terminals, tier_uuids  # noqa: F401  (re-exported)


def tier_refs(board, tier, big_pads=BIG_PADS):
    held = tier_uuids(board, tier, big_pads)
    return sorted({f.ref for f in board.footprints if f.uuid in held})


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
    if a.tier != "none":
        argv += ["--set", f"pose_tier={a.tier}"]
        if a.big_pads != BIG_PADS:
            argv += ["--set", f"pose_big_pads={a.big_pads}"]
    _log(f"arm tier={a.tier}: kae.joint.cli {' '.join(argv)}")
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
