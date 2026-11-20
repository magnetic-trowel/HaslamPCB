#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0 (commander design, 2026-11-20): how persistent are open connections across stored attempts of one board
# by one method (same recipe, different seed)?  Reads index.sqlite and evals/*.drc.json.gz only.
# usage: persist.py [STORE] > persist.txt
import sqlite3, json, os, gzip, re, sys, collections, statistics, time

STORE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
T0 = time.time()
LIMIT_S = 420
c = sqlite3.connect(f"file:{STORE}/index.sqlite?mode=ro", uri=True)
nets_of = dict(c.execute("select id, nets from boards"))
fp_of = dict(c.execute("select id, footprints from boards"))
groups = collections.defaultdict(list)
q = """select r.board, r.method_id, r.method_name, r.attempt, r.path, max(e.unconnected)
       from runs r join evals e on e.board=r.board and e.run=r.run
       where e.unconnected is not null and r.method_name not like '%human%'
       group by r.board, r.run"""
for b, mid, mn, a, p, u in c.execute(q):
    groups[(b, mid, mn)].append((a, p, u))
groups = {k: sorted(v) for k, v in groups.items() if len(v) >= 2 and max(x[2] for x in v) > 0}
print("groups (method x board) with >= 2 scored attempts and some opens:", len(groups))

PAD = re.compile(r"^Pad (\S+) \[(.*?)\] of (\S+)")
NET = re.compile(r"\[(.*?)\]")


def opens(path):
    ev = os.path.join(path, "evals")
    try:
        fs = [f for f in os.listdir(ev) if f.endswith(".drc.json.gz")]
    except OSError:
        return None
    if not fs:
        return None
    try:
        d = json.load(gzip.open(os.path.join(ev, sorted(fs)[-1])))
    except Exception:
        return None
    nets, parts, conns = set(), set(), set()
    for it in d.get("unconnected_items") or []:
        ends, net = [], None
        for x in it.get("items", []):
            s = x.get("description", "")
            m = PAD.match(s)
            if m:
                ends.append(f"{m.group(3)}.{m.group(1)}")
                parts.add(m.group(3))
                net = m.group(2)
            else:
                n = NET.search(s)
                net = net or (n.group(1) if n else None)
                ends.append("copper")
        if net is None:
            continue
        nets.add(net)
        conns.add((net, frozenset(ends)))
    return nets, parts, conns


def kind(mn):
    s = mn.lower()
    if "fr-fork" in s or "freerouting" in s:
        return "fr"
    if any(w in s for w in ("staged", "joint", "place-and-route", "place ", "pnr", "legal", "routab", "decide")):
        return "replaced"   # every attempt re-places the parts
    return "route-only"     # bridge and similar: same placement, another routing seed


rows = []
for (b, mid, mn), v in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    if time.time() - T0 > LIMIT_S:
        print("time limit: stopped early")
        break
    got = []
    for a, p, u in v:
        o = opens(p)
        if o is not None:
            got.append((a, u, o))
    if len(got) < 2 or not any(o[0] for _, _, o in got):
        continue
    n = len(got)
    netc, partc, connc = collections.Counter(), collections.Counter(), collections.Counter()
    for _, _, (nets, parts, conns) in got:
        netc.update(nets); partc.update(parts); connc.update(conns)
    ks = [len(o[0]) for _, _, o in got]
    N = nets_of.get(b) or 0
    # chance: expected number of nets open in all n attempts if each attempt drew its k open nets at random
    exp_all = N
    for k in ks:
        exp_all *= (k / N) if N else 0
    rows.append(dict(board=b, method=mn, kind=kind(mn), n=n, fp=fp_of.get(b), nets=N, ks=ks,
                     nets_any=len(netc), nets_all=sum(1 for x in netc.values() if x == n),
                     nets_80=sum(1 for x in netc.values() if x >= 0.8 * n),
                     inst=sum(netc.values()), inst_all=sum(x for x in netc.values() if x == n),
                     conn_any=len(connc), conn_all=sum(1 for x in connc.values() if x == n),
                     parts_any=len(partc), parts_all=sum(1 for x in partc.values() if x == n),
                     exp_all=exp_all, always_open=min(ks) > 0))

json.dump(rows, open(os.path.join(os.getcwd(), "persist_rows.json"), "w"))
print("groups with DRC detail for >= 2 attempts:", len(rows), "boards:", len({r["board"] for r in rows}))


def table(sel, title):
    R = [r for r in rows if sel(r)]
    if not R:
        print(title, ": none"); return
    A = [r for r in R if r["always_open"]]   # open in every attempt: the premise case
    print(f"\n== {title}: groups {len(R)}, boards {len({r['board'] for r in R})}; open in every attempt: {len(A)} groups")
    print("   groups where some attempt was clean (restarts do close it):", len(R) - len(A))
    if not A:
        return
    tot_inst = sum(r["inst"] for r in A); tot_all = sum(r["inst_all"] for r in A)
    print(f"   net-level: open-net instances {tot_inst}; in nets open in EVERY attempt {tot_all} = {tot_all / tot_inst:.3f}")
    print(f"   nets open in every attempt: observed {sum(r['nets_all'] for r in A)}, expected by chance {sum(r['exp_all'] for r in A):.1f}")
    print(f"   distinct nets ever open {sum(r['nets_any'] for r in A)}; open in all {sum(r['nets_all'] for r in A)} "
          f"= {sum(r['nets_all'] for r in A) / max(1, sum(r['nets_any'] for r in A)):.3f}")
    print(f"   connections (net+same two ends): ever {sum(r['conn_any'] for r in A)}, in all {sum(r['conn_all'] for r in A)} "
          f"= {sum(r['conn_all'] for r in A) / max(1, sum(r['conn_any'] for r in A)):.3f}")
    print(f"   parts with an open end: ever {sum(r['parts_any'] for r in A)}, in all attempts {sum(r['parts_all'] for r in A)} "
          f"= {sum(r['parts_all'] for r in A) / max(1, sum(r['parts_any'] for r in A)):.3f}")
    g = [r for r in A if r["nets_all"] > 0]
    print(f"   groups with >= 1 net open in every attempt: {len(g)}/{len(A)} = {len(g) / len(A):.2f}; "
          f"with >= 1 part in every attempt: {sum(1 for r in A if r['parts_all'] > 0)}/{len(A)}")
    sh = [r["inst_all"] / r["inst"] for r in A]
    print(f"   per-group persistent share of open-net instances: median {statistics.median(sh):.2f}, mean {statistics.mean(sh):.2f}")
    small = [r for r in A if max(r["ks"]) <= 20]
    if small:
        sh = [r["inst_all"] / r["inst"] for r in small]
        print(f"   boards with <= 20 opens ({len(small)} groups): median share {statistics.median(sh):.2f}, mean {statistics.mean(sh):.2f}, "
              f"pooled {sum(r['inst_all'] for r in small) / sum(r['inst'] for r in small):.3f}")


for kd in ("route-only", "replaced", "fr"):
    for lo, hi, t in ((2, 2, "n=2"), (3, 99, "n>=3")):
        table(lambda r, kd=kd, lo=lo, hi=hi: r["kind"] == kd and lo <= r["n"] <= hi, f"{kd}, {t}")
print("\nseconds", round(time.time() - T0, 1))
