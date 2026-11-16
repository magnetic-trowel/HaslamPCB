# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""drc-parse-ab analysis (PLAN.md): per board, C vs P over attempts 0 and 1 from the scorer's final DRC.
    python3 analyze.py [C_ID P_ID]"""
import glob
import gzip
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "kae" / "src"))
from kae import drc_items as D  # noqa: E402

STORE = Path(os.environ.get("KAE_RESULTS", Path.home() / "kae-baselines"))
C, P = (sys.argv[1:3] if len(sys.argv) > 2 else ("0e6416d6a427", "c255ea366c4c"))
ATTEMPTS = (0, 1)


def run_stats(board, mid, k):
    runs = glob.glob(str(STORE / "boards" / board / "runs" / f"*.{mid[:8]}.a{k}"))
    if not runs:
        return None
    for ev in glob.glob(f"{runs[0]}/evals/*.json"):
        if ev.endswith(".drc.json"):
            continue
        s = json.load(open(ev)).get("score")
        drc = ev[:-5] + ".drc.json.gz"
        if not s or not os.path.exists(drc):
            continue
        r = json.load(gzip.open(drc))
        br = sum(1 for u in r.get("unconnected_items") or []
                 if any(("[" in n or "]" in n) for it in u.get("items") or [] for n in D.item_nets(it.get("description"))))
        return dict(bracket=br, unconnected=s.get("unconnected") or 0, errors=s.get("errors") or 0,
                    by_type=s.get("errors_by_type") or {})
    return None


def sign_p(wins, losses):
    n = wins + losses
    return sum(math.comb(n, i) for i in range(wins, n + 1)) / 2 ** n if n else 1.0


boards = [b for b in (HERE / "boards.txt").read_text().split() if b]
tot = {a: dict(bracket=0, unconnected=0, errors=0, by_type={}) for a in "CP"}
better = worse = done = 0
for b in boards:
    rc = [run_stats(b, C, k) for k in ATTEMPTS]
    rp = [run_stats(b, P, k) for k in ATTEMPTS]
    if None in rc or None in rp:
        continue
    done += 1
    for a, rs in (("C", rc), ("P", rp)):
        for r in rs:
            for f in ("bracket", "unconnected", "errors"):
                tot[a][f] += r[f]
            for t, n in r["by_type"].items():
                tot[a]["by_type"][t] = tot[a]["by_type"].get(t, 0) + n
    bc, bp = sum(r["bracket"] for r in rc), sum(r["bracket"] for r in rp)
    better += bp < bc
    worse += bp > bc
    print(f"{b[:60]:60s} bracket {bc:4d} -> {bp:4d}  open {sum(r['unconnected'] for r in rc):5d} -> "
          f"{sum(r['unconnected'] for r in rp):5d}  errors {sum(r['errors'] for r in rc):5d} -> {sum(r['errors'] for r in rp):5d}")
print(f"\n{done}/{len(boards)} boards with every attempt of both arms")
for f in ("bracket", "unconnected", "errors"):
    c, p = tot["C"][f], tot["P"][f]
    print(f"{f:12s} C {c:6d}  P {p:6d}  ratio {p / c if c else float('nan'):.3f}")
print(f"primary: P lower on {better} boards, higher on {worse}; one-sided sign test p = {sign_p(better, worse):.4f}")
for t in sorted(tot["C"]["by_type"]):
    c, p = tot["C"]["by_type"][t], tot["P"]["by_type"].get(t, 0)
    if c >= 20 and p > 1.10 * c:
        print(f"guard: {t} rose {c} -> {p}")
