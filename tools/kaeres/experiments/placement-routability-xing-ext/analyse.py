#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-registered analysis of placement-routability-xing-ext (PLAN.md): crossing term (xing) against control,
seeds 0-2 (Freerouting fork 2e1125a, experiment placement-routability) pooled with seeds 3-8 (fork d137fd1,
this experiment). Reads the run folders in the kaeres store; prints a markdown report.

  analyse.py [--store ~/kae-baselines] [--json out.json]
"""
import argparse, glob, gzip, json, math, os, random, re, statistics as S
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DRC_EVAL = "afa09d34bc94"   # the DRC evaluator of harness d21a9ac (both builds' runs are scored with it)
OLD = {"control": "58f42c5c1e1e", "xing": "97bab84cae24"}      # experiment placement-routability, seeds = attempts 0-2
NEW_NAMES = {"control": "kae routab control d21a9ac fr-d137fd1 seed+3", "xing": "kae routab xing d21a9ac fr-d137fd1 seed+3"}
INFEASIBLE = re.compile(r"the movable parts need (\d+)% of the free area")
L = math.log1p


def method_id(store, name):
    for f in glob.glob(f"{store}/methods/*.json"):
        m = json.load(open(f))
        if m.get("name") == name:
            return m["id"]
    raise SystemExit(f"no method {name!r}")


def own_footprint_rule(x):
    """A rule-blocked pad whose binding is against a pad of its own footprint: no placement can fix it."""
    if x.get("cause") != "rule":
        return False
    ag = ((x.get("binding") or {}).get("against") or "")
    m = re.match(r"pad (\S+)\.\S+", ag)
    return bool(m) and any(p.rsplit(".", 1)[0] == m.group(1) for p in x.get("pads", []))


def load_run(d):
    ev = json.load(open(f"{d}/evals/{DRC_EVAL}.json"))["score"]
    r = dict(opens=int(ev["unconnected"]), errors=int(ev["errors"]), etypes=ev.get("errors_by_type") or {},
             wl=float(ev.get("track_length_mm") or 0), vias=int(ev.get("vias") or 0), legal=bool(ev.get("legal")),
             valid=bool(ev.get("valid")))
    try:
        lines = gzip.open(f"{d}/adapter.log.gz", "rt").read().splitlines()
    except OSError:
        lines = []
    need = [int(m.group(1)) for l in lines for m in [INFEASIBLE.search(l)] if m]
    r["side_need_pct"] = max(need) if need else None
    try:
        st = json.loads(lines[0])["iterations"][0]["stages"]
        r["crossings"] = st["place"].get("crossings")
        bl = st["route"].get("blocked") or {}
        r["ownfp"] = sum(own_footprint_rule(x) for x in bl.get("blocked", []))
        r["undiag"] = bl.get("undiagnosed")
    except (IndexError, KeyError, ValueError, TypeError):
        r["crossings"] = r["ownfp"] = r["undiag"] = None
    r["addr"] = None if r["ownfp"] is None else max(0, r["opens"] - r["ownfp"])
    return r


def collect(store, boards):
    new = {a: method_id(store, n) for a, n in NEW_NAMES.items()}
    D = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))   # board -> build -> arm -> seed -> run
    for b in boards:
        for build, ids, off in (("2e1125a", OLD, 0), ("d137fd1", new, 3)):
            for arm, mid in ids.items():
                for d in glob.glob(f"{store}/boards/{b}/runs/*.{mid[:8]}.a*"):
                    att = int(d.rsplit(".a", 1)[1])
                    if os.path.exists(f"{d}/evals/{DRC_EVAL}.json"):
                        D[b][build][arm][att + off] = load_run(d)
    return D


def boot(items, f, n=10000, seed=1):
    rnd = random.Random(seed)
    v = sorted(f([items[rnd.randrange(len(items))] for _ in items]) for _ in range(n))
    return v[int(.025 * n)], v[int(.975 * n)]


def signflip(d, n=100000):
    rnd, o = random.Random(2), abs(sum(d) / len(d))
    return sum(abs(sum(x if rnd.random() < .5 else -x for x in d) / len(d)) >= o - 1e-12 for _ in range(n)) / n


def pct(x):
    return f"{(math.exp(x) - 1) * 100:+.1f} %"


def paired(D, boards, builds, val, label):
    """Per board: Δ = inverse-variance weighted mean over builds of [mean_seeds f(arm) - mean_seeds f(control)],
    f = log1p(val); weights 1/(1/n_arm + 1/n_ctl). Ratio of sums over per-board means of val over all seeds."""
    per, sw2n, sw2d = [], 0.0, 0
    for b in boards:
        num = den = 0.0
        raw = {"control": [], "xing": []}
        for bu in builds:
            g = D[b].get(bu, {})
            c = [L(v) for r in g.get("control", {}).values() for v in [val(r)] if v is not None]
            a = [L(v) for r in g.get("xing", {}).values() for v in [val(r)] if v is not None]
            if not c or not a:
                continue
            w = 1 / (1 / len(a) + 1 / len(c))
            num += w * (S.mean(a) - S.mean(c)); den += w
            raw["control"] += [math.expm1(x) for x in c]; raw["xing"] += [math.expm1(x) for x in a]
            for v in (a, c):
                if len(v) > 1:
                    sw2n += S.variance(v) * (len(v) - 1); sw2d += len(v) - 1
        if den:
            per.append(dict(b=b, d=num / den, rc=S.mean(raw["control"]), ra=S.mean(raw["xing"]),
                            kc=len(raw["control"]), ka=len(raw["xing"])))
    if len(per) < 3:
        return dict(label=label, n=len(per))
    d = [p["d"] for p in per]
    md, sd = S.mean(d), S.stdev(d)
    lo, hi = boot(per, lambda s: S.mean(p["d"] for p in s))
    ratio = sum(p["ra"] for p in per) / max(1e-9, sum(p["rc"] for p in per))
    rlo, rhi = boot(per, lambda s: sum(p["ra"] for p in s) / max(1e-9, sum(p["rc"] for p in s)))
    mde = 2.8 * sd / math.sqrt(len(per))
    return dict(label=label, n=len(per), ctl=sum(p["rc"] for p in per), arm=sum(p["ra"] for p in per),
                ratio=ratio, ratio_ci=(rlo, rhi), mean=md, ci=(lo, hi), p=signflip(d),
                lower=sum(x < 0 for x in d), higher=sum(x > 0 for x in d), sd=sd,
                seed_sd=math.sqrt(sw2n / sw2d) if sw2d else None, mde80=mde, per=per)


def row(r):
    if r["n"] < 3:
        return f"| {r['label']} | {r['n']} | - | - | - | - | - |"
    return (f"| {r['label']} | {r['n']} | {r['ctl']:.1f}→{r['arm']:.1f} ({r['ratio']:.3f}, {r['ratio_ci'][0]:.3f}-{r['ratio_ci'][1]:.3f})"
            f" | {pct(r['mean'])} ({pct(r['ci'][0])}, {pct(r['ci'][1])}) | {r['p']:.3f} | {r['lower']}/{r['higher']}"
            f" | ±{(math.exp(r['mde80']) - 1) * 100:.1f} % (SDΔ {r['sd']:.3f}, seed SD {r['seed_sd'] or 0:.3f}) |")


def interaction(D, boards):
    per = []
    for b in boards:
        dd = []
        for bu in ("2e1125a", "d137fd1"):
            g = D[b].get(bu, {})
            if g.get("control") and g.get("xing"):
                dd.append(S.mean(L(r["opens"]) for r in g["xing"].values()) - S.mean(L(r["opens"]) for r in g["control"].values()))
        if len(dd) == 2:
            per.append(dd[1] - dd[0])
    if len(per) < 3:
        return None
    lo, hi = boot(per, S.mean)
    return dict(n=len(per), mean=S.mean(per), ci=(lo, hi))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))
    ap.add_argument("--json")
    a = ap.parse_args()
    boards = open(f"{HERE}/boards.txt").read().split()
    D = collect(a.store, boards)
    both = ("2e1125a", "d137fd1")
    # pre-registered exclusion: a control run of the board logs that its movable parts need > 100 % of the free area
    infeasible = sorted(b for b in boards for bu in both for r in D[b].get(bu, {}).get("control", {}).values()
                        if (r["side_need_pct"] or 0) > 100)
    infeasible = sorted(set(infeasible))
    have = [b for b in boards if D[b].get("d137fd1", {}).get("control") and D[b].get("d137fd1", {}).get("xing")]
    main_set = [b for b in have if b not in infeasible]
    out = {}
    print("# placement-routability-xing-ext: analysis (PLAN.md)\n")
    print(f"Boards with seeds 3-8 in both arms: {len(have)} of {len(boards)}; excluded as infeasible (pre-registered): "
          f"{', '.join(infeasible) or 'none'}.")
    missing = {b: {bu: {arm: sorted(D[b].get(bu, {}).get(arm, {})) for arm in ('control', 'xing')} for bu in both}
               for b in boards}
    short = [b for b in boards if any(len(v) < (3 if bu == '2e1125a' else 6) for bu in both for v in missing[b][bu].values())]
    print(f"Boards missing a seed in some arm: {len(short)}" + (": " + ", ".join(b[:40] for b in short) if short else "") + "\n")
    print("## Primary and its sensitivities (opens per run, per-board mean over seeds)\n")
    print("| set | n | opens Σ ctl→xing (ratio, 95 % CI) | mean Δlog1p (95 % CI) | sign-flip p | lower/higher | MDE80 |")
    print("|---|---|---|---|---|---|---|")
    opens = lambda r: r["opens"]
    tests = [("PRIMARY: pooled k=9, feasible boards", main_set, both),
             ("seeds 3-8 alone (d137fd1)", main_set, ("d137fd1",)),
             ("seeds 0-2 alone (2e1125a)", main_set, ("2e1125a",)),
             ("pooled, all boards incl. infeasible", have, both)]
    for label, bs, bu in tests:
        r = paired(D, bs, bu, opens, label); out[label] = {k: v for k, v in r.items() if k != "per"}
        print(row(r))
    it = interaction(D, main_set)
    if it:
        out["interaction"] = it
        print(f"\nBuild interaction (Δ under d137fd1 minus Δ under 2e1125a, per board): mean {it['mean']:+.3f}, "
              f"95 % CI {it['ci'][0]:+.3f} to {it['ci'][1]:+.3f}, n {it['n']}. "
              + ("CI excludes 0: the pre-registered fallback applies (seeds 3-8 alone are the primary)."
                 if it['ci'][0] > 0 or it['ci'][1] < 0 else "CI includes 0: the pooled estimate stands as the primary."))
    print("\n## Secondary: placement-addressable opens (opens minus rule-blocked pads against their own footprint)\n")
    print("| set | n | Σ ctl→xing (ratio, 95 % CI) | mean Δlog1p (95 % CI) | p | lower/higher | MDE80 |")
    print("|---|---|---|---|---|---|---|")
    full = [b for b in main_set if all(r["undiag"] == 0 for bu in both for arm in ("control", "xing")
                                       for r in D[b].get(bu, {}).get(arm, {}).values())]
    for label, bs in (("feasible boards", main_set), ("boards with complete diagnosis", full)):
        r = paired(D, bs, both, lambda r: r["addr"], label); out["addr " + label] = {k: v for k, v in r.items() if k != "per"}
        print(row(r))
    print("\n## Guards and mechanism (pooled k=9, feasible boards)\n")
    print("| quantity | n | Σ ctl→xing (ratio, 95 % CI) | mean Δlog1p (95 % CI) | p | lower/higher | MDE80 |")
    print("|---|---|---|---|---|---|---|")
    g = [("DRC errors, total", lambda r: r["errors"]), ("wirelength (mm)", lambda r: r["wl"]),
         ("vias", lambda r: r["vias"]), ("ratsnest crossings", lambda r: r["crossings"])]
    tot = Counter()
    for b in main_set:
        for bu in both:
            for r in D[b].get(bu, {}).get("control", {}).values():
                tot.update(r["etypes"])
    for t, n in tot.most_common():
        if n >= 20:
            g.append((f"DRC {t}", lambda r, t=t: r["etypes"].get(t, 0)))
    for label, f in g:
        r = paired(D, main_set, both, f, label); out[label] = {k: v for k, v in r.items() if k != "per"}
        print(row(r))
    leg = {arm: [r["legal"] for b in main_set for bu in both for r in D[b].get(bu, {}).get(arm, {}).values()] for arm in ("control", "xing")}
    print(f"\nLegal placements: control {sum(leg['control'])}/{len(leg['control'])}, xing {sum(leg['xing'])}/{len(leg['xing'])}.")
    best = [(min(r["opens"] for bu in both for r in D[b][bu].get("control", {}).values()),
             min(r["opens"] for bu in both for r in D[b][bu].get("xing", {}).values())) for b in main_set]
    print(f"Best of k opens per board (delivered-style guard): control {sum(c for c, _ in best)}, xing {sum(x for _, x in best)}; "
          f"lower/higher/equal {sum(x < c for c, x in best)}/{sum(x > c for c, x in best)}/{sum(x == c for c, x in best)}.")
    out["legal"] = {k: [sum(v), len(v)] for k, v in leg.items()}
    print("\n## Per board (pooled Δlog1p of opens; z against seed noise)\n")
    r = paired(D, main_set, both, opens, "per board")
    print("| board | k ctl/xing | mean opens ctl → xing | Δlog1p |")
    print("|---|---|---|---|")
    for p in sorted(r["per"], key=lambda p: p["d"]):
        print(f"| {p['b'][:60]} | {p['kc']}/{p['ka']} | {p['rc']:.1f} → {p['ra']:.1f} | {p['d']:+.3f} |")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
