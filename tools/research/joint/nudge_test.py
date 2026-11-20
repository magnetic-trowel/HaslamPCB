# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline multi-atom nudge test (design 2, spec A), stage 1: classify what each open's gaps are against.

Input: per-board diagnosis JSON files (as written by the coupling test 1 re-diagnosis: `conns[*].near[*]` with
`kind`, `net`, `required`, `available`, and for pads `ref`, `small`, `locked`). For every diagnosed open the
gaps with available < required are the deficits; the atom to move is another net's via (first choice) or a small
unlocked part, each by deficit + 0.02 mm along the gap normal. This stage reports which opens have a CANDIDATE
nudge set (every gap against a movable atom: vias only, parts only, both), the nudge sizes and what blocks the
rest. It is an upper bound: joint feasibility (copper following elastically, the cut test of the coupling
`t2_elastic.py` with the via as moving atom) is the remaining stage; see NOTES-d2-nudge.md.

Decision lines (on the jointly feasible share, not on this bound): >= 20 % build multi-atom nudges into the
last-mile engine; < 10 % dead.
Usage: python nudge_test.py DIAG_DIR [--p22 SUITE] [--json OUT] [--seed 0]
"""
import argparse, collections, glob, json, os, random, statistics as st, sys

SLACK = 0.02


def atom(g, own_net):
    """'via', 'part', or the reason the gap's atom is not movable."""
    k = g.get("kind")
    if g.get("net") is not None and g.get("net") == own_net:
        return "own net"
    if g.get("locked"):
        return "locked " + str(k)
    if k == "via":
        return "via"
    if k == "pad":
        return "part" if g.get("small") else "large part"
    return "fixed " + str(k)        # tracks (rip-up, not a nudge), shapes, outline, keepouts


def classify(conn):
    gaps = [g for g in conn.get("near", []) if g.get("available", 0) < g.get("required", 0)]
    if not gaps:
        return None
    atoms = [atom(g, conn.get("net")) for g in gaps]
    sizes = [g["required"] - g["available"] + SLACK for g in gaps]
    kinds = set(atoms)
    if kinds <= {"via"}:
        verdict = "vias only"
    elif kinds <= {"part"}:
        verdict = "parts only"
    elif kinds <= {"via", "part"}:
        verdict = "both"
    else:
        verdict = "not nudgeable"
    return dict(verdict=verdict, sizes=sizes, blockers=sorted(kinds - {"via", "part"}), n=len(gaps))


def load(d):
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            j = json.load(open(f))
        except ValueError:
            continue
        if "conns" in j:
            out[j.get("board", os.path.basename(f))] = j
    return out


def boot(rows, key, rng, n=1000):
    """Board-bootstrap 95 % interval of the pooled share of opens with rows[b][key] true."""
    bs = list(rows)
    if not bs:
        return None
    vals = []
    for _ in range(n):
        s = [bs[rng.randrange(len(bs))] for _ in bs]
        tot = sum(len(rows[b]) for b in s)
        vals.append(sum(key(c) for b in s for c in rows[b]) / tot if tot else 0)
    vals.sort()
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def report(rows, label, rng):
    opens = [c for b in rows for c in rows[b]]
    if not opens:
        print(f"{label}: no diagnosed opens with a deficit")
        return {}
    v = collections.Counter(c["verdict"] for c in opens)
    cand = lambda c: c["verdict"] != "not nudgeable"
    lo_hi = boot(rows, cand, rng)
    sizes = [s for c in opens if cand(c) for s in c["sizes"]]
    bl = collections.Counter(x for c in opens for x in c["blockers"])
    print(f"{label}: {len(opens)} opens on {len(rows)} boards; " + ", ".join(f"{k} {n}" for k, n in v.most_common()))
    print(f"   candidate share {sum(map(cand, opens)) / len(opens):.3f} (board bootstrap {lo_hi[0]:.3f}-{lo_hi[1]:.3f})")
    if sizes:
        print(f"   nudge sizes mm: median {st.median(sizes):.3f}, max {max(sizes):.3f}")
    print("   not nudgeable because: " + ", ".join(f"{k} {n}" for k, n in bl.most_common(6)))
    return dict(label=label, opens=len(opens), verdicts=dict(v), ci=lo_hi, blockers=dict(bl))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("diag_dir")
    p.add_argument("--p22", help="suite file of the P22 boards")
    p.add_argument("--json")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    rng = random.Random(a.seed)
    rows = {}
    for b, j in load(a.diag_dir).items():
        rows[b] = [c for c in map(classify, j["conns"]) if c]
    p22 = set(open(a.p22).read().split()) if a.p22 else set()
    splits = {"all": rows,
              "P22": {b: r for b, r in rows.items() if b in p22},
              "<=12 opens": {b: r for b, r in rows.items() if b not in p22 and len(r) <= 12},
              "rest": {b: r for b, r in rows.items() if b not in p22 and len(r) > 12}}
    res = [report(r, k, rng) for k, r in splits.items()]
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
