# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""barrier-avoid-ab analysis (PLAN.md): paired by board and seed, board-clustered bootstrap.

  python3 analyze.py [EXPERIMENT] [--json OUT]

Reads each run's kae report (the JSON line of adapter.log: barrier_crossings, barrier_reweight) and its
DRC evaluation (kaebench place-fixed score: legal, placement_errors, hpwl_mm) from the kaeres store."""
import argparse
import gzip
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

STORE = Path(os.environ.get("KAE_RESULTS", Path.home() / "kae-baselines"))
ARMS = ("ctrl", "w3 all", "w3 avoidable", "w3 detour")


def report(run):
    for line in reversed(gzip.open(run / "adapter.log.gz", "rt", errors="replace").read().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


def score(run):
    for f in sorted((run / "evals").glob("*.json")):
        j = json.loads(f.read_text())
        if "score" in j:
            return j["score"]
    return None


def load(exp):
    e = json.loads((STORE / "experiments" / exp / "experiment.json").read_text())
    boards = (STORE / "experiments" / exp / "boards.txt").read_text().split()
    arm_of = {}
    for m in e["methods"]:
        arm_of[m["id"]] = next(a for a in reversed(ARMS) if f"barrier {a} " in m["name"])
    rows = []
    for b in boards:
        for run in sorted((STORE / "boards" / b / "runs").glob("*")):
            rj = run / "run.json"
            if not rj.exists():
                continue
            mid = run.name.split(".")[1]
            m = next((k for k in arm_of if k.startswith(mid)), None)
            if m is None:
                continue
            r = json.loads(rj.read_text())
            rep, sc = report(run), score(run)
            bc = (rep or {}).get("barrier_crossings") or {}
            pe = (sc or {}).get("placement_errors") or {}
            rows.append(dict(board=b, arm=arm_of[m], seed=r["attempt"], status=r.get("status"),
                             valid=(sc or {}).get("valid"), legal=(sc or {}).get("legal"),
                             hpwl=(sc or {}).get("hpwl_mm"), perr=sum(pe.values()), court=pe.get("courtyards_overlap", 0),
                             edges=bc.get("edges"), nets=bc.get("nets"), avoid=bc.get("avoidable_edges"),
                             anchored=bc.get("anchored_edges"), detour=bc.get("detour_mm"),
                             avoid_detour=bc.get("avoidable_detour_mm"), rw=(rep or {}).get("barrier_reweight"),
                             ceiling=bool(((rep or {}).get("budget") or {}).get("ceiling_hit")), wall=r.get("runtime_s")))
    return rows


def boot(per_board, n=5000, rng=random.Random(0)):
    """Mean over runs and its board-clustered bootstrap 95 % CI. per_board: {board: [deltas]}."""
    bs = [v for v in per_board.values() if v]
    allv = [x for v in bs for x in v]
    if not allv:
        return None
    mean = sum(allv) / len(allv)
    ms = []
    for _ in range(n):
        s = [rng.choice(bs) for _ in bs]
        flat = [x for v in s for x in v]
        ms.append(sum(flat) / len(flat))
    ms.sort()
    sd = math.sqrt(sum((x - mean) ** 2 for x in allv) / max(1, len(allv) - 1))
    se = (ms[int(0.975 * n)] - ms[int(0.025 * n)]) / (2 * 1.96)
    return dict(mean=mean, lo=ms[int(0.025 * n)], hi=ms[int(0.975 * n)], n_runs=len(allv), n_boards=len(bs),
                sd_run=sd, se=se, mde=2.8 * se)


def paired(rows, a, b, key, f=math.log1p):
    by = {(r["board"], r["seed"], r["arm"]): r for r in rows if r["status"] == "ok"}
    out = defaultdict(list)
    for (bd, sd, arm), r in by.items():
        if arm != a:
            continue
        o = by.get((bd, sd, b))
        if o is None or r[key] is None or o[key] is None:
            continue
        out[bd].append(f(o[key]) - f(r[key]))
    return dict(out)


def pct(x):
    return f"{100 * (math.exp(x) - 1):+.1f} %"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exp", nargs="?", default="barrier-avoid-ab")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = load(a.exp)
    print(f"{a.exp}: {len(rows)} runs; status {dict(collections_count(r['status'] for r in rows))}")
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm and r["status"] == "ok"]
        if not rs:
            continue
        s = lambda k: sum(r[k] or 0 for r in rs)
        print(f"  {arm:13s} runs {len(rs):3d}  legal {sum(1 for r in rs if r['legal'])}  valid {sum(1 for r in rs if r['valid'])}"
              f"  edges {s('edges')}  avoidable {s('avoid')}  anchored {s('anchored')}  detour {s('detour'):.0f} mm"
              f"  hpwl {s('hpwl'):.0f}  placement errors {s('perr')} (courtyards {s('court')})  ceiling {sum(r['ceiling'] for r in rs)}")
    out = {}
    for (x, y) in (("ctrl", "w3 avoidable"), ("ctrl", "w3 detour"), ("ctrl", "w3 all"), ("w3 all", "w3 avoidable")):
        print(f"\n{x} -> {y} (mean Delta log1p, board-clustered 95 % CI, MDE at 80 %)")
        for key in ("avoid", "detour", "edges", "nets", "anchored", "hpwl", "perr"):
            r = boot(paired(rows, x, y, key))
            if r is None:
                continue
            out[f"{x}->{y}:{key}"] = r
            print(f"  {key:9s} {pct(r['mean']):>9s} ({pct(r['lo'])} to {pct(r['hi'])})  runs {r['n_runs']} boards {r['n_boards']}"
                  f"  SD/run {r['sd_run']:.3f}  MDE {100 * r['mde']:.1f} %")
        by = {(r["board"], r["seed"], r["arm"]): r for r in rows if r["status"] == "ok"}
        disc = [(bool(by[(b, s, x)]["legal"]), bool(by[(b, s, y)]["legal"])) for (b, s, arm) in by if arm == x and (b, s, y) in by]
        lost, won = sum(1 for p, q in disc if p and not q), sum(1 for p, q in disc if q and not p)
        n = lost + won
        pmc = sum(math.comb(n, k) for k in range(0, min(lost, won) + 1)) / 2 ** n * 2 if n else 1.0
        print(f"  legal: {won} runs gained, {lost} lost (McNemar exact p {min(1.0, pmc):.3f})")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(rows=rows, effects=out), indent=1, default=str))


def collections_count(it):
    from collections import Counter
    return Counter(it)


if __name__ == "__main__":
    main()
