# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply the pre-registered gate to the screen's outputs (PLAN.md): mean over seeds 0-2 of the pairs whose
channel halos overlap at the end of the w = 0 anneal >= 10; boards whose movable parts need more than 100 % of
a side's free area, or with an error on any seed, are left out. gate.py OUT_DIR screen.txt > boards.txt"""
import json
import statistics
import sys
from pathlib import Path

out, order = Path(sys.argv[1]), Path(sys.argv[2]).read_text().split()
keep, why = [], {}
for b in order:
    f = out / f"{b}.json"
    if not f.exists():
        why[b] = "not screened"
        continue
    d = json.loads(f.read_text())
    s = d.get("seeds") or []
    if d.get("error") or len(s) < 3 or any("error" in x for x in s):
        why[b] = "error: " + str(d.get("error") or [x.get("error") for x in s if "error" in x] or "seeds missing")[:120]
        continue
    if max(max(x["util"]) for x in s) > 1.0:
        why[b] = "infeasible"
        continue
    m = statistics.mean(x["final_chan"][1] for x in s)
    why[b] = f"overlap {m:.1f}"
    if m >= 10:
        keep.append(b)
print("\n".join(keep))
cnt = {}
for v in why.values():
    k = v.split(":")[0].split(" ")[0]
    cnt[k] = cnt.get(k, 0) + 1
print(f"kept {len(keep)} of {len(order)}; {cnt}", file=sys.stderr)
