#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0 (commander design, 2026-11-20): how many stored A/B experiments could serve as labelled cases for the
# diagnosis-from-report test, and what do the labels look like?  index.sqlite + experiment.json only.
# A case = (experiment, treatment arm, board): control opens vs treatment opens, same attempt number.
# Label rule: helped if delta <= -max(2, 20 % of control opens) or the board flips to clean; hurt symmetric.
# The same rule applied to two seeds of ONE recipe (A/A) gives the rate at which noise alone makes a label.
# usage: cases.py [STORE] > cases0.txt
import sqlite3, json, os, re, sys, collections, glob, random

STORE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
c = sqlite3.connect(f"file:{STORE}/index.sqlite?mode=ro", uri=True)
ev = collections.defaultdict(dict)   # (board, run) -> evaluator -> (unconnected, clean, errors)
for b, r, e, u, cl, er in c.execute("select board, run, evaluator, unconnected, clean, errors from evals where unconnected is not null"):
    ev[(b, r)][e] = (u, cl, er or 0)
runs = collections.defaultdict(dict)  # method_id -> (board, attempt) -> run
for b, r, mid, a in c.execute("select board, run, method_id, attempt from runs"):
    runs[mid][(b, a)] = r
fp_of = dict(c.execute("select id, footprints from boards"))

CTL = re.compile(r"\b(control|ctl|base|baseline|off|ref)\b", re.I)
FAM = [("placement term", r"place|xing|chan|margin|barrier|array|matrix|escape|zone|side|bus-pose|anchor|heat|routab|untangle|area|label"),
       ("router setting", r"fr-|freerouting|neck|ripup|passes|plane|fanout|pad-entr|entries|rule|dru|quantize|diffpair|pair"),
       ("repair / last mile", r"repair|lastmile|last-mile|finish|taut|tail|drc"),
       ("budget / restarts", r"pk3|resume|restart|seed|screen|budget|time|portfolio|halving"),
       ("windows / joint", r"window|loop|joint|j10|legal|cf-"),
       ("physics", r"phys|critical|thermal|decap|module")]


def family(s):
    for f, pat in FAM:
        if re.search(pat, s, re.I):
            return f
    return "other"


def label(cu, ccl, tu, tcl):
    d = tu - cu
    thr = max(2, 0.2 * cu)
    if (tcl and not ccl) or d <= -thr:
        return "helped"
    if (ccl and not tcl) or d >= max(2, 0.2 * tu):
        return "hurt"
    return "same"


def score(mid, b, a, evaluator):
    r = runs[mid].get((b, a))
    if r is None:
        return None
    e = ev.get((b, r))
    if not e:
        return None
    if evaluator in e:
        return e[evaluator]
    return None


cases, aa = [], []
used, skipped = 0, collections.Counter()
for f in sorted(glob.glob(f"{STORE}/experiments/*/experiment.json")):
    try:
        x = json.load(open(f))
    except Exception:
        continue
    name = x.get("name") or os.path.basename(os.path.dirname(f))
    ms = x.get("methods") or []
    if "smoke" in name:
        skipped["smoke"] += 1; continue
    if len(ms) < 2:
        skipped["one arm"] += 1; continue
    ctl = [m for m in ms if CTL.search(m["name"])]
    ctl = ctl[0] if ctl else ms[0]
    drc = (x.get("evaluators") or {}).get("drc")
    twin = bool(re.search(r"twin|replicate", name + " ".join(m["name"] for m in ms), re.I))
    n0 = len(cases)
    keys = sorted(runs[ctl["id"]])
    for m in ms:
        if m["id"] == ctl["id"]:
            continue
        for (b, a) in keys:
            cs = score(ctl["id"], b, a, drc); ts = score(m["id"], b, a, drc)
            if cs is None or ts is None:
                continue
            cases.append(dict(exp=name, arm=re.sub(r"\b[0-9a-f]{7,12}\b", "", m["name"]).strip(), board=b, attempt=a,
                              c=cs[0], t=ts[0], lab=label(cs[0], cs[1], ts[0], ts[1]), fam=family(name + " " + m["name"]),
                              twin=twin, ctl_run=runs[ctl["id"]][(b, a)]))
    # A/A: the control's own attempt 0 against its attempt 1 (another seed of the same recipe)
    for (b, a) in keys:
        if a != 0:
            continue
        s0 = score(ctl["id"], b, 0, drc); s1 = score(ctl["id"], b, 1, drc)
        if s0 is None or s1 is None:
            continue
        aa.append(dict(exp=name, board=b, c=s0[0], t=s1[0], lab=label(s0[0], s0[1], s1[0], s1[1])))
    if len(cases) > n0:
        used += 1
    else:
        skipped["no paired scored boards"] += 1

json.dump(cases, open(os.path.join(os.getcwd(), "cases0.json"), "w"))


def dist(L):
    k = collections.Counter(x["lab"] for x in L); n = max(1, len(L))
    return f"n {len(L):6d}  helped {k['helped']:5d} ({k['helped'] / n:.3f})  same {k['same']:5d} ({k['same'] / n:.3f})  hurt {k['hurt']:5d} ({k['hurt'] / n:.3f})"


print("experiments usable:", used, "skipped:", dict(skipped))
A0 = [x for x in cases if x["attempt"] == 0 and not x["twin"]]
print("cases, all attempts:", len(cases), " attempt 0, non-twin:", len(A0), " boards:", len({x['board'] for x in A0}),
      " arms:", len({(x['exp'], x['arm']) for x in A0}))
print("\nA/B, attempt 0:        ", dist(A0))
op = [x for x in A0 if x["c"] > 0]
print("A/B, control has opens:", dist(op))
print("A/A seed 0 vs seed 1:  ", dist(aa))
print("A/A, seed 0 has opens: ", dist([x for x in aa if x["c"] > 0]))
tw = [x for x in cases if x["twin"] and x["attempt"] == 0]
print("twin/replicate arms:   ", dist(tw))
print("\nby family (control has opens):")
for fam in sorted({x["fam"] for x in op}):
    print(f"  {fam:20s}", dist([x for x in op if x["fam"] == fam]))
print("\nby size (control has opens):")
for lo, hi in ((0, 50), (50, 100), (100, 200), (200, 400), (400, 10 ** 6)):
    L = [x for x in op if lo <= (fp_of.get(x["board"]) or 0) < hi]
    A = [x for x in aa if x["c"] > 0 and lo <= (fp_of.get(x["board"]) or 0) < hi]
    print(f"  fp {lo:4d}-{hi:<7d} A/B {dist(L)}\n                  A/A {dist(A)}")

# confirmed labels: the same sign on every stored attempt (>= 2 attempts)
by = collections.defaultdict(list)
for x in cases:
    if not x["twin"]:
        by[(x["exp"], x["arm"], x["board"])].append(x)
multi = {k: v for k, v in by.items() if len(v) >= 2}
conf = collections.Counter()
for k, v in multi.items():
    labs = {x["lab"] for x in v}
    conf["helped on every attempt" if labs == {"helped"} else "hurt on every attempt" if labs == {"hurt"} else
         "same on every attempt" if labs == {"same"} else "mixed helped+hurt" if {"helped", "hurt"} <= labs else "partly"] += 1
print("\ncases with >= 2 attempts:", len(multi), dict(conf))
ch = collections.Counter()
for k, v in multi.items():
    if any(x["c"] > 0 for x in v):
        ch[(v[0]["lab"], v[1]["lab"])] += 1
h0 = sum(n for (a, b), n in ch.items() if a == "helped")
print("  P(helped on attempt 1 | helped on attempt 0) =", round(ch[("helped", "helped")] / max(1, h0), 3), f"(n {h0});",
      "P(helped on attempt 1 | not helped on 0) =",
      round(sum(n for (a, b), n in ch.items() if a != "helped" and b == "helped") / max(1, sum(n for (a, b), n in ch.items() if a != "helped")), 3))

# does the label depend on the board, or does one knob win everywhere?
bb = collections.defaultdict(lambda: collections.defaultdict(set))
for x in op:
    bb[x["board"]][x["lab"]].add((x["exp"], x["arm"]))
nb = len(bb)
print("\nboards with opens in some control:", nb)
print("  with >= 1 arm that helped:", sum(1 for v in bb.values() if v["helped"]),
      " >= 2 arms helped:", sum(1 for v in bb.values() if len(v["helped"]) >= 2),
      " helped by some AND hurt by others:", sum(1 for v in bb.values() if v["helped"] and v["hurt"]),
      " tested by >= 3 arms:", sum(1 for v in bb.values() if sum(len(s) for s in v.values()) >= 3))
arms = collections.defaultdict(collections.Counter)
for x in op:
    arms[(x["exp"], x["arm"])][x["lab"]] += 1
print("\narms with the highest helped share (>= 20 boards with opens):")
L = [(v["helped"] / sum(v.values()), v["hurt"] / sum(v.values()), sum(v.values()), k) for k, v in arms.items() if sum(v.values()) >= 20]
for h, hu, n, k in sorted(L, reverse=True)[:12]:
    print(f"  helped {h:.2f} hurt {hu:.2f} n {n:4d}  {k[0]} :: {k[1][:60]}")
print("  median helped share over", len(L), "arms:", round(sorted(x[0] for x in L)[len(L) // 2], 3),
      " median hurt share:", round(sorted(x[1] for x in L)[len(L) // 2], 3))

# does the control's stored report carry a blocked diagnosis? (sample of helped cases)
random.seed(0)
H = [x for x in op if x["lab"] == "helped"]
S = random.sample(H, min(250, len(H)))
have, rep = 0, 0
for x in S:
    p = os.path.join(STORE, "boards", x["board"], "runs", x["ctl_run"], "restart-report.json")
    try:
        d = json.load(open(p)); rep += 1
    except Exception:
        continue
    bl = d.get("blocked") or (d.get("final") or {}).get("blocked")
    if bl and (bl.get("blocked") or bl.get("congestion")):
        have += 1
print(f"\nhelped cases sampled {len(S)}: control has restart-report.json {rep}, with a non-empty blocked diagnosis {have}")
