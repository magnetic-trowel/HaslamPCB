# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The re-pilot (hotloop_exempt_portfolio.sh) side by side: per board and seed DRC and opens of N0, H, S; per cell
L_loop nH / R_loop mOhm / loop_ac mW (median over corners); medians of H/N0 and S/N0 paired by seed.

    python tools/research/routing/hotloop_exempt_portfolio_summary.py BOARDS_DIR"""
import json, math, sys, statistics as st
from pathlib import Path
root = Path(sys.argv[1]); arms = ["N0", "H", "S"]; seeds = [0, 1]
def load(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return None
tot = {a: dict(u=[], e=[], st=[], mb=[], w=[]) for a in arms}
rat = {a: dict(L=[], R=[], AC=[]) for a in arms[1:]}
for b in sorted(x.name for x in root.iterdir() if x.is_dir()):
    print(f"## {b[:40]}")
    for a in arms:
        row = []
        for s in seeds:
            sc = load(root / b / f"{a}-s{s}" / "score.json")
            if sc:
                d = sc["drc"]; tot[a]["u"].append(d["unconnected"]); tot[a]["e"].append(d["errors"]); tot[a]["w"].append(sc["wall_s"])
                row.append(f"s{s} u{d['unconnected']} e{d['errors']} {sc['wall_s']}s {d.get('by_type')}")
        print(f"  {a:3s} " + " | ".join(row))
    cells = {}
    for a in arms:
        for s in seeds:
            ev = load(root / b / f"{a}-s{s}" / "ev.json")
            if not ev: continue
            ac = {}
            for o in ev.get("observations") or []:
                if o.get("id") == "loss.loop_ac" and o.get("values"):
                    ac[(o.get("scope") or {}).get("source")] = st.median(o["values"]) * 1e3
            for r in ev.get("cells") or []:
                cells.setdefault(r["source"], {})[(a, s)] = (r, ac.get(r["source"]))
    for src, per in sorted(cells.items()):
        parts = []
        for a in arms:
            for s in seeds:
                v = per.get((a, s))
                if v is None: parts.append(f"{a}{s} -"); continue
                r, ac = v
                parts.append(f"{a}{s} " + (f"{r['L_loop_nH']:.2f}/{r['R_loop_mohm']:.1f}/{ac:.3g}" if r["state"] == "ok" else r["state"].upper()))
        print(f"    {src[5:]:22s} " + "  ".join(parts))
        for s in seeds:
            base = per.get(("N0", s))
            for a in arms[1:]:
                v = per.get((a, s))
                if not base or not v: continue
                (rb, acb), (rv, acv) = base, v
                if rb["state"] == "ok" and rv["state"] == "ok":
                    rat[a]["L"].append(rv["L_loop_nH"] / rb["L_loop_nH"]); rat[a]["R"].append(rv["R_loop_mohm"] / rb["R_loop_mohm"])
                    if acb and acv: rat[a]["AC"].append(acv / acb)
                elif rb["state"] == "ok" and rv["state"] == "open":
                    rat[a]["L"].append(math.inf); rat[a]["R"].append(math.inf)
                elif rb["state"] == "open" and rv["state"] == "ok":
                    rat[a]["L"].append(0.0); rat[a]["R"].append(0.0)
print("\n## totals (seed 0, seed 1)")
for a in arms:
    t = tot[a]; print(f"  {a:3s} unconnected {t['u']} sum {sum(t['u'])}  errors {t['e']} sum {sum(t['e'])}  wall {sum(t['w'])} s")
for a, r in rat.items():
    md = {k: (round(st.median(v), 3) if v else None) for k, v in r.items()}
    print(f"  {a}/N0 median per cell (paired by seed): L {md['L']} R {md['R']} loop_ac {md['AC']} over {len(r['L'])} cell-runs")
