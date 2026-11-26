#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""coverage: how well the corpus and the tier suites cover each mechanism and standard kind of circuit.

  python3 tools/haslamres/coverage.py --tags DIR [--index FILE] [--corpus DIR] [--suites bench/suites] [--dry-run]

Writes bench/suites/COVERAGE.md and, for kinds the suites hold too few boards of, the lists
sprint-quality-additions.txt and ladder-additions.txt beside the originals (which stay as they are, so
runs stored on them stay valid). The kinds are mechsuites.MECHANISMS; run mechsuites.py first, the
table reads the suites it wrote. The same inputs give the same files.
"""
import argparse
import json
import os
from pathlib import Path

import mechsuites as M
import suites as S

SIZES = (("small", 5, 50), ("medium", 51, 150), ("large", 151, 400), ("very large", 401, 10 ** 9))  # footprints
LAYERS = (("2", 0, 2), ("4", 3, 4), ("6+", 5, 10 ** 9))                                           # copper layers
HOLE_OWNERS, HOLE_CLEAN = 20, 10   # a kind with fewer owners of usable boards, or fewer human-clean boards, is a hole
TIERS = ("sprint-frontier", "sprint-quality", "ladder", "canary")
ADD = {"sprint-quality": 5, "ladder": 10}   # boards of each kind a suite should hold, its additions included
# what to look for, for the kinds the corpus cannot supply
SOURCE = {
    "ddr4-ddr5": "boards with DDR4 or DDR5 memory-down or (SO-)DIMM routing: SBCs, FPGA and SoM carriers; 8 exist",
    "sata": "boards with a SATA host or device port (NAS, SBC and M.2 carriers) that route the pairs",
    "flex": "flex and rigid-flex designs with a stackup that says polyimide",
    "passive-01005": "phone-class or wearable designs with 01005 passives",
    "microvias": "HDI designs (microvias, blind or buried vias) whose human layout is DRC-clean; 5 clean ones exist",
    "bga-pitch-0.4": "boards with a 0.4 mm ball grid and a DRC-clean human layout (HDI rules in the project)",
    "bga-pitch-0.5": "boards with a 0.5 mm ball grid and a DRC-clean human layout",
    "bga-pitch-0.65": "boards with a 0.65 mm ball grid; none has a DRC-clean human layout",
    "bga-pitch-0.8": "more boards with a 0.8 mm ball grid and a DRC-clean human layout",
    "bga-pitch-1.0-1.27": "boards with a 1.0 or 1.27 mm ball grid and a DRC-clean human layout",
    "bga-balls-9-64": "boards with wafer-level or small ball grids and a DRC-clean human layout",
    "bga-balls-65-144": "boards with 65-144 ball grids and a DRC-clean human layout",
    "bga-balls-145-324": "boards with 145-324 ball grids and a DRC-clean human layout",
    "bga-balls-325plus": "FPGA, SoC and DDR boards (325+ balls) with a DRC-clean human layout",
    "ddr3": "DDR3 boards with a DRC-clean human layout",
}


def cell_of(inp, b):
    fp, ly = inp.footprints.get(b, 0), inp.layers.get(b, 0)
    return (next((n for n, lo, hi in SIZES if lo <= fp <= hi), None), next(n for n, lo, hi in LAYERS if lo <= ly <= hi))


def kinds(inp, mech):
    """name -> dict(group, expr, about, members, usable, clean, owners, suite, tier, holes)."""
    out = {}
    for name, group, expr, about, *_ in M.MECHANISMS:
        boards = inp.members(expr)
        ok = M.usable(inp, boards)
        clean = ok & inp.human_clean
        owners = {inp.owner[b] for b in ok}
        holes = ([f"{len(owners)} owners"] if len(owners) < HOLE_OWNERS else []) + ([f"{len(clean)} human-clean"] if len(clean) < HOLE_CLEAN else [])
        out[name] = dict(group=group, expr=expr, about=about, members=boards, usable=ok, clean=clean, owners=owners,
                         suite=set(mech.get(name, {}).get("ids", [])), tier=mech.get(name, {}).get("tier", "-"), holes=holes)
    return out


def additions(inp, ks, base, eligible, need, owners):
    """Boards to add to a suite (`base`: its ids) so that it holds `need` boards of every kind where
    `eligible` boards exist: each step takes the board of an unused owner that serves the most kinds
    still short, the cheapest of those. Returns the ids; `owners` is updated."""
    cost = M.costs(inp)
    have = {k: len(v["members"] & set(base)) for k, v in ks.items()}
    cand = sorted(eligible - set(base), key=lambda b: (cost(b), b))
    out = []
    while True:
        short = [k for k in ks if have[k] < need]
        best, gain = None, 0
        for b in cand:
            if inp.owner[b] in owners:
                continue
            g = sum(b in ks[k]["members"] for k in short)
            if g > gain:
                best, gain = b, g
        if not best:
            return out
        out.append(best)
        owners.add(inp.owner[best])
        cand.remove(best)
        for k in short:
            have[k] += best in ks[k]["members"]


def build_additions(inp, ks):
    """name -> ids for sprint-quality and ladder, under the rules of the suite each extends."""
    owners = {inp.owner[b] for n in ("sprint-frontier", "sprint-quality", "ladder") for b in inp.fixed.get(n, []) if b in inp.owner}
    lo, hi = S.QUALITY_FOOTPRINTS
    usable = M.usable(inp, inp.human_clean)
    quality = {b for b in usable if lo <= inp.footprints[b] <= hi and inp.layers[b] in (2, 4) and inp.hist.get(b, 0) <= S.SPRINT_BOARD_CPU_H}
    ladder = {b for b in usable if S.LADDER_BANDS[0][0] <= inp.footprints[b] <= S.LADDER_BANDS[-1][1]}
    out = {"sprint-quality": additions(inp, ks, inp.fixed.get("sprint-quality", []), quality, ADD["sprint-quality"], owners)}
    out["ladder"] = additions(inp, ks, inp.fixed.get("ladder", []), ladder, ADD["ladder"], owners)
    return out


def report(inp, ks, added):
    cost = M.costs(inp)
    fixed = {n: set(inp.fixed.get(n, [])) for n in TIERS}
    plus = {n: set(v) for n, v in added.items()}
    L = ["# Coverage of mechanisms and standard circuit kinds", "",
         "Written by `tools/haslamres/coverage.py` from the board tags, the corpus manifest and the results index; do not edit. "
         "Kinds and their tag expressions: `tools/haslamres/mechsuites.py` (`MECHANISMS`); the suites: [mech/README](mech/README.md).", "",
         "- **usable**: can run as a route and as a place task (netlist, prepared task, closed outline, 5+ footprints). "
         "**human-clean**: usable, and the human layout is complete with no DRC error. **owners**: accounts of the repositories of the usable boards.",
         f"- **hole**: fewer than {HOLE_OWNERS} owners of usable boards, or fewer than {HOLE_CLEAN} human-clean boards.",
         "- Suite columns count the kind's boards in `sprint-frontier`, `sprint-quality`, `ladder`, `canary` (`+n`: in the suite's "
         "`-additions.txt`) and in the kind's own suite `mech/<kind>.txt`.", "",
         "## Summary", "",
         "| group | kind | usable | human-clean | owners | frontier | quality | ladder | canary | own suite (tier) | hole |", "|---|---|---|---|---|---|---|---|---|---|---|"]

    def n_in(k, name):
        base = len(k["members"] & fixed[name])
        extra = len(k["members"] & plus.get(name, set()))
        return f"{base}+{extra}" if extra else str(base)

    for name, k in ks.items():
        L.append(f"| {k['group']} | `{name}` | {len(k['usable'])} | {len(k['clean'])} | {len(k['owners'])} | "
                 + " | ".join(n_in(k, t) for t in TIERS) + f" | {len(k['suite'])} ({k['tier']}) | {'; '.join(k['holes']) or '-'} |")
    holes = [n for n, k in ks.items() if k["holes"]]
    L += ["", "## Holes: what the corpus cannot supply", "",
          "Nothing was fetched. To close a hole, source boards of other owners (one board per owner counts):", "",
          "| kind | boards have | usable / human-clean / owners | source |", "|---|---|---|---|"]
    for n in holes:
        k = ks[n]
        L.append(f"| `{n}` | {k['about']} | {len(k['usable'])} / {len(k['clean'])} / {len(k['owners'])} | "
                 f"{SOURCE.get(n, 'boards of more owners with ' + k['about'] + ', with a DRC-clean human layout')} |")
    L += ["", "## Additions to the tier suites", "",
          f"A suite should hold at least {ADD['sprint-quality']} (`sprint-quality`) or {ADD['ladder']} (`ladder`) boards of every kind. "
          "Where it held fewer and the corpus has boards that meet the suite's own rules (human-clean, its footprint and layer range, "
          "an owner not yet in a sprint suite or the ladder), boards were added, each step taking the board that serves the most "
          "kinds still short, the cheapest first. The additions are separate lists: the originals are unchanged.", "",
          "| list | boards | CPU-h per method-run of all |", "|---|---|---|"]
    for n, ids in added.items():
        L.append(f"| `{n}-additions.txt` | {len(ids)} | {sum(map(cost, ids)):.1f} |")
    L += ["", "| kind | sprint-quality before | after | ladder before | after | still short because |", "|---|---|---|---|---|---|"]
    for name, k in ks.items():
        q0, l0 = len(k["members"] & fixed["sprint-quality"]), len(k["members"] & fixed["ladder"])
        q1, l1 = q0 + len(k["members"] & plus["sprint-quality"]), l0 + len(k["members"] & plus["ladder"])
        if (q0, l0) != (q1, l1) or q1 < ADD["sprint-quality"] or l1 < ADD["ladder"]:
            why = "" if q1 >= ADD["sprint-quality"] and l1 >= ADD["ladder"] else f"{len(k['clean'])} human-clean boards in all; the rest are out of the suite's size or layer range, or their owner is taken"
            L.append(f"| `{name}` | {q0} | {q1} | {l0} | {l1} | {why or '-'} |")
    L += ["", "## By size and layer count", "",
          "Size by footprints: small 5-50, medium 51-150, large 151-400, very large over 400. Each cell: usable / human-clean / owners, "
          "then the kind's boards in frontier-quality-ladder-canary-own suite (additions counted in). Empty cells have no usable board.", "",
          "| kind | size | 2 layers | 4 layers | 6+ layers |", "|---|---|---|---|---|"]
    every = {n: fixed[n] | plus.get(n, set()) for n in TIERS}
    for name, k in ks.items():
        cells = {}
        for b in k["usable"]:
            cells.setdefault(cell_of(inp, b), []).append(b)
        for size, _, _ in SIZES:
            row = []
            for ly, _, _ in LAYERS:
                bs = cells.get((size, ly), [])
                if not bs:
                    row.append("")
                    continue
                s = set(bs)
                row.append(f"{len(bs)} / {len(s & k['clean'])} / {len({inp.owner[b] for b in bs})} · "
                           + "-".join(str(len(s & every[t])) for t in TIERS) + f"-{len(s & k['suite'])}")
            if any(row):
                L.append(f"| `{name}` | {size} | " + " | ".join(row) + " |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tags", required=True, help="board-tag folder (suites/, structural/, functional/features.jsonl)")
    ap.add_argument("--index", default=os.path.join(os.path.expanduser(os.environ.get("HASLAM_RESULTS", "~/haslam-baselines")), "index.sqlite"))
    ap.add_argument("--corpus", default=os.path.expanduser(os.environ.get("HASLAM_CORPUS", "~/haslam-boards")))
    ap.add_argument("--suites", default=str(M.REPO / "bench" / "suites"))
    ap.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    a = ap.parse_args()
    out = Path(a.suites)
    inp = M.Inputs(a.index, a.tags, a.corpus, out / "merit-213.txt", a.suites)
    for n in list(inp.fixed):   # the additions are rebuilt: an earlier run's lists are not an input
        if n.endswith("-additions"):
            del inp.fixed[n]
    mech = {p.stem: dict(ids=S.read_ids(p)) for p in sorted((out / "mech").glob("*.txt"))}
    man_path = out / "mech" / "suites.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {"suites": {}}
    for n, s in man["suites"].items():
        mech.setdefault(n, {})["tier"] = s["tier"]
    ks = kinds(inp, mech)
    added = build_additions(inp, ks)
    text = report(inp, ks, added)
    if a.dry_run:
        print(text)
        return
    for n, ids in added.items():
        (out / f"{n}-additions.txt").write_text("\n".join(ids) + "\n")
    (out / "COVERAGE.md").write_text(text)
    print(f"{out / 'COVERAGE.md'}: {len(ks)} kinds, {sum(bool(k['holes']) for k in ks.values())} holes; "
          + ", ".join(f"{n}-additions {len(v)}" for n, v in added.items()))


if __name__ == "__main__":
    main()
