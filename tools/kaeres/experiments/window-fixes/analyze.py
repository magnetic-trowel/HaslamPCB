#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""window-fixes (PLAN.md): CF-W vs CF-W-fix, paired; windows kept/tried, fallback use, CPU.  python3 analyze.py"""
import collections, glob, json, math, random, statistics as st
from pathlib import Path

BASE = Path.home() / "kae-baselines"
E = json.loads((BASE / "experiments/window-fixes/experiment.json").read_text())
ids = {m["id"][:8]: m["name"].split()[2] for m in E["methods"]}


def sign_flip(xs, n=50000, seed=0):
    xs = [x for x in xs if x]
    if not xs:
        return 1.0
    rng = random.Random(seed); t = abs(sum(xs))
    return (1 + sum(abs(sum(x if rng.random() < 0.5 else -x for x in xs)) >= t - 1e-12 for _ in range(n))) / (n + 1)


D = collections.defaultdict(dict)
for b in (BASE / "experiments/window-fixes/boards.txt").read_text().split():
    for rd in glob.glob(str(BASE / "boards" / b / "runs" / "*.a0")):
        rd = Path(rd); mid = rd.name.split(".")[-2]
        if mid not in ids:
            continue
        r = dict(cpu=(json.loads((rd / "run.json").read_text()).get("method_usage") or {}).get("cpu_s") or 0)
        for f in rd.glob("evals/*.json"):
            d = json.loads(f.read_text())
            if (d.get("score") or {}).get("valid") is not None:
                r["s"] = d["score"]
        if (rd / "restart-report-windows.json").exists():
            r["w"] = json.loads((rd / "restart-report-windows.json").read_text())
        if (rd / "restarts.json").exists():
            r["sum"] = json.loads((rd / "restarts.json").read_text())
        if "s" in r:
            D[b][ids[mid]] = r
B = sorted(b for b in D if "CFW" in D[b] and "CFWfix" in D[b])
a, c = "CFWfix", "CFW"
oa = [D[b][a]["s"]["unconnected"] for b in B]; oc = [D[b][c]["s"]["unconnected"] for b in B]
d = [(x - y) / (x + y + 1) for x, y in zip(oa, oc)]; p = sign_flip(d)
g = lambda arm, k: sum(bool(D[b][arm]["s"].get(k)) if k in ("clean", "legal") else (D[b][arm]["s"].get(k) or 0) for b in B)  # noqa: E731
pe = lambda arm: sum(sum((D[b][arm]["s"].get("placement_errors") or {}).values()) for b in B)  # noqa: E731
print(f"{len(B)} boards: opens fix {sum(oa)} vs CF-W {sum(oc)} ({100 * (sum(oa) / max(1, sum(oc)) - 1):+.1f} %), fewer/more "
      f"{sum(x < y for x, y in zip(oa, oc))}/{sum(x > y for x, y in zip(oa, oc))}, mean d {st.mean(d):+.3f}, p {p:.4f}")
print(f"clean {g(a, 'clean')} vs {g(c, 'clean')}; errors {g(a, 'errors')} vs {g(c, 'errors')}; legal {g(a, 'legal')} vs {g(c, 'legal')}; "
      f"placement errors {pe(a)} vs {pe(c)}; CPU {sum(D[b][a]['cpu'] for b in B) / 3600:.1f} vs {sum(D[b][c]['cpu'] for b in B) / 3600:.1f} h")
win = st.mean(d) < 0 and p < 0.05 and sum(oa) <= 0.97 * sum(oc)
lose = st.mean(d) > 0 and p < 0.05 and sum(oa) >= 1.03 * sum(oc)
guards = g(a, "clean") >= g(c, "clean") - 2 and g(a, "errors") <= 1.03 * g(c, "errors") and g(a, "legal") >= g(c, "legal") - 2 and pe(a) <= 1.03 * pe(c)
print(f"verdict: {'fix wins' if win else 'CF-W wins' if lose else 'undecided'}; guards {'hold' if guards else 'fail'}")
for arm in (c, a):
    W = [i for b in B for i in ((D[b][arm].get("w") or {}).get("iterations") or []) if i.get("window")]
    rep = [i.get("repair") or {} for i in W]
    why = collections.Counter((i.get("why") or "")[:26] for i in W if not i.get("accepted"))
    print(f"{arm}: windows {len(W)} kept {sum(bool(i.get('accepted')) for i in W)} ({100 * sum(bool(i.get('accepted')) for i in W) / max(1, len(W)):.1f} %); "
          f"legalize used {sum(1 for x in rep if (x.get('replace') or {}).get('legalize'))}, reverted {sum(1 for x in rep if (x.get('replace') or {}).get('reverted'))}; "
          f"rip nets median {st.median([(x.get('ripup') or {}).get('nets') or 0 for x in rep if x.get('ripup')] or [0])}; rejects {why.most_common(4)}")
