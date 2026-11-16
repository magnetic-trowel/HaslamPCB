#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The pre-registered analysis of place-history-b (PLAN.md beside this file).

Per board and seed: d = log1p(opens hist) - log1p(opens cong30), opens = the scorer's `unconnected` on the
resumed board. Per board: mean d, 95 % t CI, exact sign-flip p, SD and MDE80 = 2.8 SD / sqrt(n). Then the
decision rule (signs of the 4 helped and 4 hurt boards, and the helped - hurt contrast with a Welch CI),
the fresh attempts' own opens (`iter 0` of the joint run) the same way, map coverage and peak per board
(maps experiment, freeze.py), and the guards (legal, placement errors, DRC errors per type, ceiling hits,
failures, CPU).

    analyze.py [--results ~/kae-baselines] [--json out.json]
"""
import argparse
import gzip
import itertools
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

here = Path(__file__).resolve().parent
HELPED = ("undercontrol", "librewave", "rpi-display", "servo-hat")
HURT = ("dvhx", "pulse-express", "audio-latency", "zotino")
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 20: 2.086, 30: 2.042}


def t975(df):
    if df <= 0:
        return float("nan")
    ks = sorted(T975)
    for k in ks:
        if df <= k:
            return T975[k]
    return 1.96


def group(bid):
    for g, keys in (("helped", HELPED), ("hurt", HURT)):
        if any(k in bid for k in keys):
            return g
    return "?"


def stats(d):
    n = len(d)
    if n == 0:
        return dict(n=0)
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else float("nan")
    h = t975(n - 1) * sd / math.sqrt(n) if n > 1 else float("nan")
    # exact two-sided sign-flip p
    tot = hit = 0
    for signs in itertools.product((1, -1), repeat=n):
        tot += 1
        hit += abs(sum(s * x for s, x in zip(signs, d)) / n) >= abs(m) - 1e-12
    return dict(n=n, mean=round(m, 4), ci=[round(m - h, 4), round(m + h, 4)], sd=round(sd, 4),
                mde80=round(2.8 * sd / math.sqrt(n), 4) if n > 1 else None, p_signflip=round(hit / tot, 4),
                pct=round(100 * (math.exp(m) - 1), 1))


def welch(a, b):
    na, nb = len(a), len(b)
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)) if se > 0 else na + nb - 2
    h = t975(int(df)) * se
    return dict(diff=round(ma - mb, 4), ci=[round(ma - mb - h, 4), round(ma - mb + h, 4)], df=round(df, 1))


def read_run(r, drc_eval):
    run = json.loads((r / "run.json").read_text())
    ev = r / "evals" / f"{drc_eval}.json"
    sc = json.loads(ev.read_text()).get("score") if ev.exists() else None
    log = gzip.open(r / "adapter.log.gz", "rt", errors="replace").read() if (r / "adapter.log.gz").exists() else ""
    fresh = re.findall(r"phist-b joint: .*iter 0: (\d+) unconnected", log)
    ph = re.findall(r"place history: (.*)", log)
    ceil = [bool(json.loads(x).get("ceiling_hit")) for x in re.findall(r"\[kae\.budget\] (\{.*\})", log)]
    types = Counter()
    dj = r / "evals" / f"{drc_eval}.drc.json.gz"
    if dj.exists():
        for v in json.load(gzip.open(dj, "rt")).get("violations", []):
            types[v.get("type", "?")] += 1
    return dict(status=run.get("status"), opens=(sc or {}).get("unconnected"), legal=(sc or {}).get("legal"),
                valid=(sc or {}).get("valid"), placement_errors=(sc or {}).get("placement_errors") or {},
                fresh=int(fresh[-1]) if fresh else None, place_history=ph[0] if ph else None,
                ceiling_hit=any(ceil), drc_types=dict(types),
                cpu_s=((run.get("job_steps") or {}).get("run") or {}).get("cgroup_cpu_s"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("KAE_RESULTS", str(Path.home() / "kae-baselines")))
    ap.add_argument("--json")
    a = ap.parse_args()
    res = Path(a.results)
    exp = json.loads((res / "experiments" / "place-history-b" / "experiment.json").read_text())
    ids = {("hist" if " hist " in m["name"] else "cong30"): m["id"] for m in exp["methods"]}
    drc_eval = exp["evaluators"]["drc"]
    maps = {}
    try:
        mexp = json.loads((res / "experiments" / "place-history-b-maps" / "experiment.json").read_text())
        mid = mexp["methods"][0]["id"]
    except OSError:
        mid = None
    out, per_board, fresh_board = dict(boards={}), {}, {}
    guard = {arm: dict(attempts=0, scored=0, legal=0, failed=0, ceiling=0, drc=Counter(), pe=Counter(), cpu=0.0)
             for arm in ids}
    for bid in (here / "boards.txt").read_text().split():
        runs = res / "boards" / bid / "runs"
        rows = {}
        for arm, i in ids.items():
            for r in runs.glob(f"*.{i[:8]}.a*"):
                if (r / "run.json").exists() and re.fullmatch(r"a\d+", r.name.rsplit(".", 1)[-1]):
                    rows[(arm, int(r.name.rsplit(".a", 1)[-1]))] = read_run(r, drc_eval)
        for (arm, _), x in rows.items():
            g = guard[arm]
            g["attempts"] += 1
            g["scored"] += x["opens"] is not None
            g["legal"] += bool(x["legal"])
            g["failed"] += x["status"] != "ok"
            g["ceiling"] += x["ceiling_hit"]
            g["drc"].update(x["drc_types"])
            g["pe"].update(x["placement_errors"])
            g["cpu"] += x["cpu_s"] or 0.0
        d, df, pairs = [], [], []
        for s in range(int(exp.get("attempts", 6))):
            c, h = rows.get(("cong30", s)), rows.get(("hist", s))
            if not c or not h:
                continue
            ok = c["opens"] is not None and h["opens"] is not None and not (c["ceiling_hit"] or h["ceiling_hit"])
            pairs.append(dict(seed=10 + s, cong30=c["opens"], hist=h["opens"], fresh_cong30=c["fresh"],
                              fresh_hist=h["fresh"], ceiling=[c["ceiling_hit"], h["ceiling_hit"]],
                              legal=[c["legal"], h["legal"]]))
            if ok:
                d.append(math.log1p(h["opens"]) - math.log1p(c["opens"]))
                if c["fresh"] is not None and h["fresh"] is not None:
                    df.append(math.log1p(h["fresh"]) - math.log1p(c["fresh"]))
        if mid:
            mr = [r for r in runs.glob(f"*.{mid[:8]}.a0") if (r / "run.json").exists()]
            if mr:
                lg = gzip.open(mr[0] / "adapter.log.gz", "rt", errors="replace").read() \
                    if (mr[0] / "adapter.log.gz").exists() else ""
                maps[bid] = re.findall(r"#\d+ place history: (.*)", lg)
                rj = mr[0] / "restarts.json"
                if rj.exists():
                    w = json.loads(rj.read_text())
                    maps[bid] = dict(wave1=[(x.get("seed"), (x.get("rank") or [None] * 3)[2]) for x in w.get("attempt_log", [])],
                                     maps=(w.get("phist") or {}).get("maps"), lines=maps[bid])
        hl = next((x["place_history"] for x in rows.values() if x["place_history"]), None)
        per_board[bid] = stats(d)
        fresh_board[bid] = stats(df)
        out["boards"][bid] = dict(group=group(bid), opens=per_board[bid], fresh=fresh_board[bid], pairs=pairs,
                                  hist_read=hl, maps=maps.get(bid))
    # decision rule
    def rule(pb):
        rep = {g: [b for b, s in pb.items() if group(b) == g and s.get("n")
                   and ((s["mean"] < 0) if g == "helped" else (s["mean"] > 0))] for g in ("helped", "hurt")}
        hm = [s["mean"] for b, s in pb.items() if group(b) == "helped" and s.get("n")]
        um = [s["mean"] for b, s in pb.items() if group(b) == "hurt" and s.get("n")]
        con = welch(hm, um) if len(hm) > 1 and len(um) > 1 else None
        signs = len(rep["helped"]) >= 3 and len(rep["hurt"]) >= 3
        excl = bool(con and (con["ci"][1] < 0 or con["ci"][0] > 0))
        verdict = ("board-dependent" if signs and excl else "unknown: extend to m=12" if signs
                   else "regress to noise: run design A")
        pooled = stats([s["mean"] for s in pb.values() if s.get("n")])
        return dict(repeat=rep, contrast_helped_minus_hurt=con, verdict=verdict, pooled_board_means=pooled)
    out["decision"] = rule(per_board)
    out["fresh_decision"] = rule(fresh_board)
    out["guards"] = {arm: dict(g, drc=dict(g["drc"].most_common()), pe=dict(g["pe"].most_common()),
                               drc_total=sum(g["drc"].values()), cpu_h=round(g["cpu"] / 3600, 2))
                     for arm, g in guard.items()}
    txt = json.dumps(out, indent=1, default=str)
    if a.json:
        Path(a.json).write_text(txt)
    print(f"{'board':60s} grp    n  mean d   95% CI            p     SD    MDE80  fresh mean d")
    for b, x in out["boards"].items():
        s, f = x["opens"], x["fresh"]
        if s.get("n"):
            print(f"{b[:60]:60s} {x['group'][:5]:5s} {s['n']:2d} {s['mean']:+.3f} [{s['ci'][0]:+.3f},{s['ci'][1]:+.3f}] "
                  f"{s['p_signflip']:.3f} {s['sd']:.3f} {s['mde80'] or 0:.3f}  {f.get('mean', float('nan')):+.3f}")
        else:
            print(f"{b[:60]:60s} {x['group'][:5]:5s}  0")
    print(json.dumps(dict(decision=out["decision"], fresh_decision=out["fresh_decision"]), indent=1))
    print(json.dumps(out["guards"], indent=1))


if __name__ == "__main__":
    sys.exit(main())
