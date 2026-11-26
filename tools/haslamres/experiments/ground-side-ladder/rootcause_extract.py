# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per board and arm (seed 0): router and repair trace from the stored adapter.log, scored opens/errors from results.csv."""
import csv, gzip, json, sys
from pathlib import Path

E = Path.home() / "haslam-baselines/experiments/ground-side-ladder"
STORE = Path.home() / "haslam-baselines/boards"
ARMS = {"71e60a91475d": "ctl", "e4f3e4f5aa53": "gs4", "9aa13b1dae71": "gs2"}
attempt = int(sys.argv[1]) if len(sys.argv) > 1 else 0
csvp = Path(sys.argv[2]) if len(sys.argv) > 2 else E / "results.csv"
rows = [r for r in csv.DictReader(open(csvp)) if r["method_id"] in ARMS and int(r["attempt"]) == attempt]


def trace(r):
    p = STORE / r["board"] / "runs" / r["run"] / "adapter.log.gz"
    d = None
    for ln in gzip.open(p, "rt", errors="replace"):
        if ln.startswith("{"):
            try:
                d = json.loads(ln)
            except ValueError:
                pass
    if not d:
        return {}
    rt = (d.get("router") or {}).get("report") or {}
    ph = rt.get("phases") or {}
    rep = d.get("repair") or {}
    r0 = (rep.get("rounds") or [{}])[0]
    opens = [h for h in d.get("hazards", []) if h.get("code") == "drc_unconnected_items"]
    return dict(gs=(d.get("translate") or {}).get("ground_side"), unrouted0=ph.get("unrouted0"),
                router_left=(ph.get("unrouted_after") or [None])[-1], router_state=rt.get("final_state"),
                timed_out=(d.get("router") or {}).get("timed_out"), budget=d.get("budget_s"),
                rep0_unc=r0.get("unconnected"), rep0_err=r0.get("by_type"),
                final=(rep.get("final") or {}), open_nets=sorted({o for h in opens for o in h.get("objects", [])}),
                rounds=len(rep.get("rounds") or []))


out = {}
for r in rows:
    t = trace(r)
    out.setdefault(r["board"], {})[ARMS[r["method_id"]]] = dict(
        unc=int(r["unconnected"] or 0), errors=json.loads(r["errors_by_type"] or "{}"), xc=r["xc"] == "True",
        vias=int(r["vias"] or 0), track=float(r["track_length_mm"] or 0), pads=int(r["pads"] or 0),
        fp=int(r["footprints"] or 0), cpu=float(r["cpu_s"] or 0), **t)
json.dump(out, open(E / f"rootcause_seed{attempt}.json", "w"), indent=1)
print(len(out), "boards")
