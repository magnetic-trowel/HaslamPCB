#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0 (commander design, 2026-11-20): summary of persist_rows.json without place-only methods (every net open) and by open count.
import json, os, statistics as st, collections
R = json.load(open(os.path.join(os.getcwd(), "persist_rows.json")))
def ok(r):
    m = r["method"].lower()
    if " place place" in m or m.startswith("kae place") or "place-fixed" in m: return False
    return r["nets"] and max(r["ks"]) <= 0.3 * r["nets"]
R = [r for r in R if ok(r)]
print("groups kept:", len(R), "boards:", len({r['board'] for r in R}))
print(collections.Counter(r["kind"] for r in R))
def show(L, t):
    if not L: print(t, "none"); return
    A = [r for r in L if r["always_open"]]
    print(f"\n== {t}: groups {len(L)} on {len({r['board'] for r in L})} boards; never clean in any attempt {len(A)} ({len(A)/len(L):.2f})")
    if not A: return
    inst = sum(r["inst"] for r in A); ia = sum(r["inst_all"] for r in A)
    print(f"   share of open-net instances that are nets open in EVERY attempt: pooled {ia/inst:.2f}, per-group median {st.median(r['inst_all']/r['inst'] for r in A):.2f}")
    print(f"   nets open in every attempt: observed {sum(r['nets_all'] for r in A)}, chance {sum(r['exp_all'] for r in A):.1f} (ratio {sum(r['nets_all'] for r in A)/max(1e-9,sum(r['exp_all'] for r in A)):.0f}x)")
    print(f"   same connection (net + same two ends) in every attempt: {sum(r['conn_all'] for r in A)}/{sum(r['conn_any'] for r in A)} = {sum(r['conn_all'] for r in A)/max(1,sum(r['conn_any'] for r in A)):.2f} of distinct connections")
    print(f"   parts with an open end in every attempt: {sum(r['parts_all'] for r in A)}/{sum(r['parts_any'] for r in A)} = {sum(r['parts_all'] for r in A)/max(1,sum(r['parts_any'] for r in A)):.2f} of parts ever touched")
    print(f"   groups with >= 1 net open every time: {sum(1 for r in A if r['nets_all']>0)}/{len(A)}; >= 1 part every time: {sum(1 for r in A if r['parts_all']>0)}/{len(A)}; "
          f"median opens per attempt {st.median(st.mean(r['ks']) for r in A):.0f}")
for kd in ("route-only", "replaced"):
    for lo, hi, tn in ((2, 2, "2 attempts"), (3, 99, ">= 3 attempts")):
        for olo, ohi, to in ((1, 5, "1-5 opens"), (6, 20, "6-20 opens"), (21, 10**9, "> 20 opens")):
            show([r for r in R if r["kind"] == kd and lo <= r["n"] <= hi and olo <= max(r["ks"]) <= ohi], f"{kd}, {tn}, max {to}")
# near-miss view: groups where the worst attempt had <= 5 opens: how often does some attempt come out clean?
for kd in ("route-only", "replaced"):
    L = [r for r in R if r["kind"] == kd and max(r["ks"]) <= 5]
    print(f"\nnear-miss ({kd}): groups {len(L)}; some attempt clean {sum(1 for r in L if not r['always_open'])}")
print("\nmethods (top 12):", collections.Counter(r["method"][:50] for r in R).most_common(12))
