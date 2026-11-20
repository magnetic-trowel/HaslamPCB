#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Window-phase diagnosis (diag_windows runs of window_diag_run.sh): per window where the chain fails.
    python3 window_diag.py WDIAG_DIR"""
import collections
import json
import statistics as st
import sys
from pathlib import Path


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else 0.0


def load(root):
    W, finals = [], []
    for d in sorted(Path(root).iterdir()):
        f = d / "restarts" / "report-windows.json"
        if not f.exists():                      # the windows phase killed at its timeout: its own report, if written
            f = d / "restarts" / "policy2" / "report.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        sf = d / "restarts" / "summary.json"
        s = json.loads(sf.read_text()) if sf.exists() else {}
        prev = dict(unconnected=(r.get("initial") or {}).get("unconnected"), errors=(r.get("initial") or {}).get("errors"))
        for i in r.get("iterations") or []:
            if not i.get("window"):
                if i.get("accepted") and i.get("unconnected") is not None:
                    prev = dict(unconnected=i["unconnected"], errors=i.get("errors"))
                continue
            rep = i.get("repair") or {}
            dg = rep.get("diag") or {}
            rpl = rep.get("replace") or {}
            W.append(dict(board=d.name, kept=bool(i.get("accepted")), why=(i.get("why") or "")[:40],
                          outcome=rep.get("outcome"), unc=i.get("unconnected"), err=i.get("errors"),
                          inc_unc=prev["unconnected"], inc_err=prev["errors"],
                          moved=len(rpl.get("moved") or []), legalized=bool(rpl.get("legalize")),
                          reverted=bool(rpl.get("reverted")), rejected_place=rpl.get("rejected"),
                          rip=(rep.get("ripup") or {}).get("nets"), blk_in=dg.get("blocked_in_window"),
                          blk_tot=dg.get("blocked_total"), causes_in=dg.get("causes_in_window"),
                          ripped=dg.get("ripped"), open_before=dg.get("ripped_open_before"), fixed=dg.get("ripped_fixed"),
                          lost_own=dg.get("lost_own"), lost_disp=dg.get("lost_displaced"),
                          lost_unripped=dg.get("lost_unripped"), gained=dg.get("gained"),
                          newly=dg.get("newly_open_n"), newly_out=dg.get("newly_open_outside_ripped"),
                          newly_causes=dg.get("newly_open_causes"), router=(rep.get("route") or {}).get("stops"),
                          router_s=(rep.get("route") or {}).get("seconds"), cf=rep.get("cf_bridge"), s=i.get("seconds")))
            if i.get("accepted") and i.get("unconnected") is not None:
                prev = dict(unconnected=i["unconnected"], errors=i.get("errors"))
        finals.append((d.name, (r.get("initial") or {}).get("unconnected"), (r.get("final") or {}).get("unconnected"),
                       s.get("kept"), s.get("best_rank")))
    return W, finals


def main(root):
    W, finals = load(root)
    print(f"windows {len(W)} on {len(finals)} boards; kept {sum(w['kept'] for w in W)}")
    stage = collections.Counter()
    for w in W:
        if w["kept"]:
            stage["kept"] += 1
        elif w["rejected_place"]:
            stage["incoming: placement rejected"] += 1
        elif w["outcome"]:
            stage["incoming/core: " + w["outcome"][:30]] += 1
        else:
            stage["outgoing: " + w["why"][:30]] += 1
    print("where windows end:", stage.most_common(12))
    routed = [w for w in W if w["ripped"] is not None]
    causes = sum((collections.Counter(w["causes_in"] or {}) for w in routed), collections.Counter())
    print(f"incoming: windows covering >=1 blocked connection {sum((w['blk_in'] or 0) > 0 for w in routed)}/{len(routed)}; "
          f"blocked per incumbent median {med([w['blk_tot'] for w in routed])}; causes in windows {dict(causes)}")
    print(f"  legalized {sum(w['legalized'] for w in W)}, reverted {sum(w['reverted'] for w in W)}, "
          f"moved parts median {med([w['moved'] for w in W])}")
    print(f"core: ripped nets median {med([w['ripped'] for w in routed])}, open before median {med([w['open_before'] for w in routed])}; "
          f"per window: fixed {mean([w['fixed'] for w in routed]):.2f}, newly opened {mean([w['newly'] for w in routed]):.2f}, "
          f"newly opened outside the ripped nets {mean([w['newly_out'] for w in routed]):.2f}")
    print("  newly-open causes:", dict(sum((collections.Counter(w["newly_causes"] or {}) for w in routed), collections.Counter())))
    print("  router stops:", collections.Counter(str((w["router"] or {}).get("autorouter") if isinstance(w["router"], dict)
                                                     else w["router"]) for w in routed).most_common(5))
    cf = [w for w in routed if isinstance(w["cf"], dict) and w["cf"].get("unconnected") is not None and w["unc"] is not None]
    if cf:
        print(f"  bridge counterfactual on {len(cf)} windows: fewer opens than the incremental router "
              f"{sum(w['cf']['unconnected'] < w['unc'] for w in cf)}, more {sum(w['cf']['unconnected'] > w['unc'] for w in cf)}; "
              f"beats the incumbent {sum(w['cf']['unconnected'] < (w['inc_unc'] or 10**9) for w in cf)} "
              f"(incremental: {sum((w['unc'] or 10**9) < (w['inc_unc'] or 0) for w in cf)})")
    rej = [w for w in routed if not w["kept"] and w["unc"] is not None and w["inc_unc"] is not None]
    lo, ld, lu = (sum(w[k] or 0 for w in rej) for k in ("lost_own", "lost_disp", "lost_unripped"))
    print(f"decisive split, rejected windows: connections lost on the moved parts' own nets {lo}, on displaced (ripped) "
          f"nets {ld}, on unripped nets {lu}; gained {sum(w['gained'] or 0 for w in rej)}; windows where own > displaced "
          f"{sum((w['lost_own'] or 0) > (w['lost_disp'] or 0) for w in rej)}, displaced > own "
          f"{sum((w['lost_disp'] or 0) > (w['lost_own'] or 0) for w in rej)}")
    dd = collections.Counter(max(-3, min(5, w["unc"] - w["inc_unc"])) for w in rej)
    near = sum(1 for w in rej if w["unc"] - w["inc_unc"] == 1 and (w["err"] or 0) < (w["inc_err"] or 0))
    print(f"outgoing: rejected routed windows {len(rej)}; opens delta vs incumbent {sorted(dd.items())}; "
          f"+1 open with fewer errors {near}; equal opens {sum(1 for w in rej if w['unc'] == w['inc_unc'])}")
    print("finals (board, windows initial -> final, kept phase, best rank):")
    for x in finals:
        print("  ", x)
    (Path(root) / "windows.json").write_text(json.dumps(W, indent=0, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
