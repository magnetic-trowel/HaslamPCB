# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Default-off identity check for d6-place-terms: place a board with a fixed seed under counted work
(KAE_BUDGET=work, one worker) and print the footprint poses as JSON, so two trees can be compared.

    KAE_BUDGET=work PYTHONPATH=<tree>/kae/src python3 identity.py BOARD OUT.json [--time S] [--seed N] [--set K=V ...]

Run it once with each tree's kae/src on PYTHONPATH and diff the outputs (`--compare A.json B.json`).
"""
import argparse
import json
import sys


def poses(board_path, seed, time_s, opts):
    from kae.board.kicad_file import load
    from kae.place.pipeline import place
    board = load(board_path)
    res = place(board, seed=seed, time_s=time_s, workers=1, board_path=board_path, opts=opts or None,
                log=lambda *a, **k: None)
    out = {}
    for k, v in (res.poses or {}).items():
        out[str(k)] = [round(float(x), 6) if isinstance(x, (int, float)) else x for x in
                       (v if isinstance(v, (list, tuple)) else [v])]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("board", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--time", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    a = ap.parse_args(argv)
    if a.compare:
        A, B = (json.load(open(p)) for p in a.compare)
        diff = sorted(k for k in set(A) | set(B) if A.get(k) != B.get(k))
        print(json.dumps(dict(footprints=len(set(A) | set(B)), differ=len(diff), first=diff[:5])))
        return 1 if diff else 0
    opts = {}
    for kv in a.set:
        k, v = kv.split("=", 1)
        opts[k] = json.loads(v)
    P = poses(a.board, a.seed, a.time, opts)
    json.dump(P, open(a.out, "w"), indent=0, sort_keys=True)
    print(f"{len(P)} footprints placed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
