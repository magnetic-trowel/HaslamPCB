#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""window-ends (PLAN.md): control vs an arm, paired per board: opens, clean, errors (by type), legality, windows
kept/tried, near-miss closure (start within 5 opens of clean), CPU.    python3 analyze.py EXPERIMENT"""
import collections, glob, json, random, statistics as st, sys
from pathlib import Path

BASE = Path.home() / "kae-baselines"


def sign_flip(xs, n=50000, seed=0):
    xs = [x for x in xs if x]
    if not xs:
        return 1.0
    rng = random.Random(seed); t = abs(sum(xs))
    return (1 + sum(abs(sum(x if rng.random() < 0.5 else -x for x in xs)) >= t - 1e-12 for _ in range(n))) / (n + 1)


def main(exp):
    E = json.loads((BASE / "experiments" / exp / "experiment.json").read_text())
    ids = {m["id"][:8]: m["name"].split()[2] for m in E["methods"]}
    D = collections.defaultdict(dict)
    for b in (BASE / "experiments" / exp / "boards.txt").read_text().split():
        for rd in glob.glob(str(BASE / "boards" / b / "runs" / "*.a0")):
            rd = Path(rd); mid = rd.name.split(".")[-2]
            if mid not in ids:
                continue
            r = dict(cpu=(json.loads((rd / "run.json").read_text()).get("method_usage") or {}).get("cpu_s") or 0)
            for f in rd.glob("evals/*.json"):
                s = json.loads(f.read_text()).get("score")
                if s and s.get("valid") is not None:
                    r["s"] = s
            f = rd / "restart-report-windows.json"
            if f.exists():
                w = json.loads(f.read_text())
                W = [i for i in w.get("iterations") or [] if i.get("window")]
                r["tried"], r["kept"] = len(W), sum(bool(i.get("accepted")) for i in W)
                r["start"] = (w.get("initial") or {}).get("unconnected")
            if "s" in r:
                D[b][ids[mid]] = r
    arms = sorted({a for b in D for a in D[b]} - {"control"})
    for a in arms:
        B = sorted(b for b in D if "control" in D[b] and a in D[b])
        oa = [D[b][a]["s"]["unconnected"] for b in B]; oc = [D[b]["control"]["s"]["unconnected"] for b in B]
        d = [(x - y) / (x + y + 1) for x, y in zip(oa, oc)]; p = sign_flip(d)
        g = lambda arm, k: sum(bool(D[b][arm]["s"].get(k)) if k in ("clean", "legal") else (D[b][arm]["s"].get(k) or 0) for b in B)  # noqa: E731
        print(f"{a} vs control, {len(B)} boards: opens {sum(oa)} vs {sum(oc)} ({100 * (sum(oa) / max(1, sum(oc)) - 1):+.1f} %), "
              f"fewer/more {sum(x < y for x, y in zip(oa, oc))}/{sum(x > y for x, y in zip(oa, oc))}, mean d {st.mean(d):+.3f}, p {p:.4f}")
        print(f"  clean {g(a, 'clean')} vs {g('control', 'clean')}; legal {g(a, 'legal')} vs {g('control', 'legal')}; "
              f"errors {g(a, 'errors')} vs {g('control', 'errors')}; CPU {sum(D[b][a]['cpu'] for b in B) / 3600:.1f} vs "
              f"{sum(D[b]['control']['cpu'] for b in B) / 3600:.1f} h")
        for arm in ("control", a):
            print(f"  {arm}: windows kept/tried {sum(D[b][arm].get('kept', 0) for b in B)}/{sum(D[b][arm].get('tried', 0) for b in B)}")
        near = [b for b in B if (D[b]["control"].get("start") or 99) <= 5]
        print(f"  near-miss boards (start <= 5 opens) {len(near)}: closed to clean {sum(D[b][a]['s']['unconnected'] == 0 for b in near)} vs "
              f"{sum(D[b]['control']['s']['unconnected'] == 0 for b in near)}; opens {sum(D[b][a]['s']['unconnected'] for b in near)} vs "
              f"{sum(D[b]['control']['s']['unconnected'] for b in near)}")
        ta, tc = collections.Counter(), collections.Counter()
        for b in B:
            ta.update(D[b][a]["s"].get("errors_by_type") or {}); tc.update(D[b]["control"]["s"].get("errors_by_type") or {})
        print("  errors by type (arm vs control):", {k: (ta[k], tc[k]) for k in sorted(set(ta) | set(tc))})
        for b in B:
            print(f"   {b[:40]:40s} {D[b]['control'].get('start')} -> control {D[b]['control']['s']['unconnected']}, {a} {D[b][a]['s']['unconnected']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "window-ends5")
