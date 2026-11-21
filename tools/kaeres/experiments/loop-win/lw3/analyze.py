# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import pickle, math, random, collections, statistics as st, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "kae" / "src"))
from kae.rank import board_rank
X = pickle.load(open(WORK + "data.pkl", "rb"))
D = X["D"]
ARMS = ["R", "W0", "We", "Wt", "Wx", "Wall"]
op = lambda r: r["s"]["unconnected"]
er = lambda r: r["s"]["errors"] or 0
def pe(r):
    p = r["s"].get("placement_errors") or 0
    return sum(p.values()) if isinstance(p, dict) else p
legal = lambda r: bool(r["s"].get("legal"))
rank = lambda r: board_rank(op(r), er(r), 0 if legal(r) else 1)
boards = sorted({b for b, _ in D})
def full(b): return all(a in D.get((b, s), {}) for a in ARMS for s in (0, 1))
FB = [b for b in boards if full(b)]
def sf(xs, n=40000, seed=0):
    xs = [x for x in xs if x]
    if not xs: return 1.0
    rng = random.Random(seed); t = abs(sum(xs))
    return (1 + sum(abs(sum(x if rng.random() < .5 else -x for x in xs)) >= t - 1e-12 for _ in range(n))) / (n + 1)
def boot(xs, n=20000, seed=1):
    rng = random.Random(seed); m = []
    for _ in range(n):
        s = [xs[rng.randrange(len(xs))] for _ in xs]; m.append(sum(s) / len(s))
    m.sort(); return m[int(.025 * n)], m[int(.975 * n)]
def contrast(a, b, bs, kind):
    """per-board log ratio of (opens+1): per-attempt = mean over seeds of each seed's log ratio;
    delivered = the best of the two seeds by the ranked judge, per arm."""
    L = []; ta = tb = 0
    for x in bs:
        if kind == "attempt":
            v = [math.log((op(D[(x, s)][a]) + 1) / (op(D[(x, s)][b]) + 1)) for s in (0, 1)]
            L.append(sum(v) / 2); ta += sum(op(D[(x, s)][a]) for s in (0, 1)); tb += sum(op(D[(x, s)][b]) for s in (0, 1))
        else:
            ra = min((D[(x, s)][a] for s in (0, 1)), key=rank); rb = min((D[(x, s)][b] for s in (0, 1)), key=rank)
            L.append(math.log((op(ra) + 1) / (op(rb) + 1))); ta += op(ra); tb += op(rb)
    lo, hi = boot(L)
    sd = st.pstdev(L); mde = math.exp(2.8 * sd / math.sqrt(len(L))) - 1
    return dict(gm=math.exp(sum(L) / len(L)), lo=math.exp(lo), hi=math.exp(hi), better=sum(l < 0 for l in L),
                worse=sum(l > 0 for l in L), p=sf(L), mde=mde, ta=ta, tb=tb, n=len(L), L=dict(zip(bs, L)))
def prereg(a, b, bs):
    ds = []; ta = tb = 0
    for x in bs:
        v = [(op(D[(x, s)][a]) - op(D[(x, s)][b])) / (op(D[(x, s)][a]) + op(D[(x, s)][b]) + 1) for s in (0, 1)]
        ds.append(sum(v) / 2); ta += sum(op(D[(x, s)][a]) for s in (0, 1)); tb += sum(op(D[(x, s)][b]) for s in (0, 1))
    return sum(ds) / len(ds), sf(ds), (ta - tb) / tb if tb else 0
print(f"boards with all arms and both seeds: {len(FB)} of {len(boards)}")
OPEN = [b for b in FB if any(op(D[(b, s)][a]) for a in ARMS for s in (0, 1))]
print(f"boards any arm leaves open: {len(OPEN)}")
out = {}
print("\n| contrast | per-attempt gm [95%] | b/w | p | MDE | opens | delivered gm [95%] | b/w | p | delivered opens |")
for a, b in [(x, "R") for x in ARMS[1:]] + [(x, "W0") for x in ARMS[2:]]:
    c1 = contrast(a, b, OPEN, "attempt"); c2 = contrast(a, b, OPEN, "delivered"); out[(a, b)] = (c1, c2)
    print(f"| {a} vs {b} | {c1['gm']:.3f} [{c1['lo']:.3f}, {c1['hi']:.3f}] | {c1['better']}/{c1['worse']} | {c1['p']:.3f} | "
          f"{100*c1['mde']:.1f}% | {c1['tb']} -> {c1['ta']} | {c2['gm']:.3f} [{c2['lo']:.3f}, {c2['hi']:.3f}] | "
          f"{c2['better']}/{c2['worse']} | {c2['p']:.3f} | {c2['tb']} -> {c2['ta']} |")
m, p, rel = prereg("Wall", "R", FB)
print(f"\npre-registered primary Wall vs R (mean d over seeds, sign-flip, alpha 0.0125, -3% total): mean d {m:+.3f}, p {p:.4f}, total {100*rel:+.1f}%")
m, p, rel = prereg("W0", "R", FB); print(f"W0 vs R same statistic: mean d {m:+.3f}, p {p:.4f}, total {100*rel:+.1f}%")
# DRC by type, legality, CPU, clean
print("\n| arm | runs | opens | DRC errors | placement errors | legal | clean | CPU h |")
T = {}
for a in ARMS:
    rs = [D[(b, s)][a] for b in FB for s in (0, 1)]
    ty = collections.Counter()
    for r in rs: ty.update(r["s"].get("errors_by_type") or {})
    T[a] = ty
    print(f"| {a} | {len(rs)} | {sum(map(op, rs))} | {sum(map(er, rs))} | {sum(map(pe, rs))} | {sum(map(legal, rs))} | "
          f"{sum(1 for r in rs if r['s'].get('clean'))} | {sum(r['cpu'] for r in rs)/3600:.1f} |")
types = sorted({t for a in ARMS for t in T[a]}, key=lambda t: -T["R"][t])
print("\nDRC by type (R / W0 / We / Wt / Wx / Wall):")
for t in types: print(f"- {t}: " + " / ".join(str(T[a][t]) for a in ARMS))
# near-miss: board-seeds where R is within 5 of clean (0 < opens <= 5 or opens == 0)
print("\nNear-miss closure (board-seeds with R opens <= 5), per arm: closed (arm 0, R>0) / opened (arm >0, R==0) / better / worse")
for a in ARMS[1:]:
    cl = opn = bt = wr = n = 0
    for b in FB:
        for s in (0, 1):
            o_r, o_a = op(D[(b, s)]["R"]), op(D[(b, s)][a])
            if o_r <= 5:
                n += 1; cl += (o_r > 0 and o_a == 0); opn += (o_r == 0 and o_a > 0); bt += o_a < o_r; wr += o_a > o_r
    print(f"- {a}: n {n}, closed {cl}, opened {opn}, better {bt}, worse {wr}")
pickle.dump(dict(out=out, FB=FB, OPEN=OPEN), open(WORK + "contrasts.pkl", "wb"))
