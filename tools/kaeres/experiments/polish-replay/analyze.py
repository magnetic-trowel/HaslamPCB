# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""polish-replay analysis (PLAN.md): python3 analyze.py. Read-only on ~/kae-baselines/experiments/polish-replay.

Per board: copy = R's kept board rescored; polish = the polish arm's board, kept only when KiCad ranks it no worse
than copy (opens, then errors: restart.py's rule for --finish), raw = the polish board as written.
Primary: mean over boards of log1p(kept polish opens) - log1p(copy opens), bootstrap 95 % CI, sign counts,
MDE (2.8 SD / sqrt n). Guards: raw polish opens and errors, per-type errors, CPU."""
import csv
import json
import math
import os
import random
import statistics as st

E = os.path.expanduser("~/kae-baselines/experiments/polish-replay/results.csv")
rows = {}
for r in csv.DictReader(open(E)):
    if r["attempt"] == "0" and r["status"] == "ok":
        rows.setdefault(r["board"], {})["copy" if "copy" in r["method"] else "polish"] = r
d, raw, err, typ, cpu, better, worse = [], [0, 0, 0], [0, 0, 0], {}, 0.0, 0, 0
for b, v in sorted(rows.items()):
    if "copy" not in v or "polish" not in v:
        continue
    c, p = v["copy"], v["polish"]
    oc, op, ec, ep = int(c["unconnected"]), int(p["unconnected"]), int(c["errors"]), int(p["errors"])
    keep = (op, ep) <= (oc, ec)
    ok, ek = (op, ep) if keep else (oc, ec)
    d.append(math.log1p(ok) - math.log1p(oc))
    better += ok < oc; worse += op > oc
    raw[0] += oc; raw[1] += op; raw[2] += ok
    err[0] += ec; err[1] += ep; err[2] += ek
    cpu += float(p["cpu_s"] or 0)
    for i, r in enumerate((c, p)):
        for k, n in json.loads(r["errors_by_type"] or "{}").items():
            typ.setdefault(k, [0, 0])[i] += n
rng = random.Random(2611)
bs = sorted(st.mean(rng.choice(d) for _ in d) for _ in range(20000))
sd = st.stdev(d)
print(f"boards {len(d)}; PRIMARY kept-polish vs copy: gm {math.exp(st.mean(d)):.3f} [{math.exp(bs[500]):.3f}, {math.exp(bs[19499]):.3f}]"
      f" better {better} (raw worse {worse}); SD {sd:.3f}; MDE {100 * (1 - math.exp(-2.8 * sd / len(d) ** .5)):.1f}%")
print(f"opens copy {raw[0]} -> raw polish {raw[1]} -> kept {raw[2]}; errors copy {err[0]} -> raw {err[1]} -> kept {err[2]}; polish CPU {cpu / 3600:.1f} h")
for k, (a, b) in sorted(typ.items(), key=lambda kv: -max(kv[1])):
    if a != b:
        print(f"  {k:28s} {a:6d} -> {b:6d}")
