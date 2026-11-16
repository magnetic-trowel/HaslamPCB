# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The net-exempt keep-out pilot (hotloop_exempt_pilot.sh) side by side.

    python tools/research/routing/hotloop_exempt_summary.py BOARDS_DIR [ARM ...]   (default N N0 H S)

Per board and arm: DRC errors (by type), unconnected, route seconds; per cell the evaluator's L_loop (nH) and
R_loop (mOhm) at f_sw (kae.excite.hotloop rows of ARM/ev.json; an open cell shows as OPEN), and per arm the
median ratio against the first arm over the cells computed in both (kae.excite.hotloop.paired: a cell open in one
arm only counts as worst)."""
import json
import math
import sys
from pathlib import Path


def _load(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def main(argv):
    root = Path(argv[0])
    arms = argv[1:] or ["N", "N0", "H", "S"]
    boards = sorted(p.name for p in root.iterdir() if p.is_dir())
    ratios = {a: dict(L=[], R=[]) for a in arms[1:]}
    tot = {a: dict(u=0, e=0, s=0.0, by={}) for a in arms}
    for b in boards:
        print(f"## {b}")
        cells = {}
        for a in arms:
            sc, ev = _load(root / b / a / "score.json"), _load(root / b / a / "ev.json")
            if sc:
                d = sc["drc"]
                tot[a]["u"] += d["unconnected"] or 0
                tot[a]["e"] += d["errors"] or 0
                tot[a]["s"] += sc["route_s"]
                for k, v in (d.get("by_type") or {}).items():
                    tot[a]["by"][k] = tot[a]["by"].get(k, 0) + v
                print(f"  {a:3s} unconnected {d['unconnected']:4d} errors {d['errors']:4d} route {sc['route_s']:7.0f} s "
                      f"{d.get('by_type')}")
            for r in (ev or {}).get("cells") or []:
                cells.setdefault(r["source"], {})[a] = r
        for src, per in sorted(cells.items()):
            parts = []
            for a in arms:
                r = per.get(a)
                if r is None:
                    parts.append(f"{a} -")
                elif r["state"] != "ok":
                    parts.append(f"{a} {r['state'].upper()}")
                else:
                    parts.append(f"{a} {r['L_loop_nH']:.2f}/{r['R_loop_mohm']:.1f}")
            print(f"    {src:28s} " + "  ".join(parts))
            base = per.get(arms[0])
            for a in arms[1:]:
                r = per.get(a)
                if base is None or r is None or "not_computed" in (base["state"], r["state"]):
                    continue
                if base["state"] == "open" and r["state"] == "open":
                    continue
                for k, key in (("L", "L_loop_nH"), ("R", "R_loop_mohm")):
                    if r["state"] == "open":
                        ratios[a][k].append(math.inf)
                    elif base["state"] == "open":
                        ratios[a][k].append(0.0)
                    elif base[key] > 0:
                        ratios[a][k].append(r[key] / base[key])
    print("\n## totals")
    for a in arms:
        t = tot[a]
        print(f"  {a:3s} unconnected {t['u']} errors {t['e']} route {t['s']:.0f} s {t['by']}")
    for a, rr in ratios.items():
        med = {k: (sorted(v)[len(v) // 2] if v else None) for k, v in rr.items()}
        print(f"  {a}/{arms[0]} median per cell: L {med['L']}, R {med['R']} over {len(rr['L'])} cells")


if __name__ == "__main__":
    main(sys.argv[1:])
