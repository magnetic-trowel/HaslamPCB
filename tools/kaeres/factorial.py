#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Factorial experiments for kae: plan a two-level design, size it, analyse it.

    python3 tools/kaeres/factorial.py design  --factor NAME:on=K=V,K=V ... [--runs 8|16|32|12] [--foldover] [--rotate N] -o plan.json
    python3 tools/kaeres/factorial.py mde     --s-int X --s-dw Y [--boards B --seeds S --runs R | --rotate N --s-w Z --total-runs T]
    python3 tools/kaeres/factorial.py analyse --plan plan.json (--csv tidy.csv | --experiment NAME) [-o VERDICT.json]

Designs: regular 2^(k-p) fractions from a generator table (8, 16, 32 runs), the 12-run Plackett-Burman design and
fold-over. Resolution and alias groups are computed from the design matrix, never asserted.

Analysis: per-cell factor contrasts, board means, mean over boards; owner-cluster bootstrap intervals (2,000
resamples, fixed seed), sign-flip permutation p, Holm over factors. Default stopping rule: a fixed design with at
most one pre-registered extension (two looks at 97.1 %, Pocock). `--confseq` gives an anytime-valid interval for
accumulating designs only. Verdict words: better, worse, bounded, undecided, unknown.
"""
from __future__ import annotations

import argparse
import collections
import csv
import itertools
import json
import math
import os
import random
import re
import sqlite3
import statistics as st
import sys
from pathlib import Path

LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefg"     # I is skipped, as in the design literature

# Minimum-aberration generators (Montgomery, Design and Analysis of Experiments, table of 2^(k-p) fractions).
# runs -> k -> generators for the added factors (words over the base letters).
GENERATORS = {
    8: {4: ["ABC"], 5: ["AB", "AC"], 6: ["AB", "AC", "BC"], 7: ["AB", "AC", "BC", "ABC"]},
    16: {5: ["ABCD"], 6: ["ABC", "BCD"], 7: ["ABC", "BCD", "ACD"], 8: ["BCD", "ACD", "ABC", "ABD"],
         9: ["ABC", "BCD", "ACD", "ABD", "ABCD"], 10: ["ABC", "BCD", "ACD", "ABD", "ABCD", "AB"],
         11: ["ABC", "BCD", "ACD", "ABD", "ABCD", "AB", "AC"], 12: ["ABC", "BCD", "ACD", "ABD", "ABCD", "AB", "AC", "AD"],
         13: ["ABC", "BCD", "ACD", "ABD", "ABCD", "AB", "AC", "AD", "BC"],
         14: ["ABC", "BCD", "ACD", "ABD", "ABCD", "AB", "AC", "AD", "BC", "BD"],
         15: ["ABC", "BCD", "ACD", "ABD", "ABCD", "AB", "AC", "AD", "BC", "BD", "CD"]},
    32: {6: ["ABCDE"], 7: ["ABCD", "ABDE"], 8: ["ABC", "ABD", "BCDE"], 9: ["ABCD", "ABCE", "ABDE", "ACDE"],
         10: ["ABCD", "ABCE", "ABDE", "ACDE", "BCDE"]},
}
PB12 = [1, 1, -1, 1, 1, 1, -1, -1, -1, 1, -1]      # Plackett and Burman (1946) generating row for N = 12

# Pre-registered margins (log scale unless noted); a design records them in plan.json, analyse reads them from there.
DEFAULT_MARGINS = {"opens": math.log(1.10), "clean": 0.05, "length": math.log(1.05), "vias": math.log(1.10),
                   "physics": math.log(1.25)}
Z_TWO_LOOKS = 2.18      # Pocock: two looks at 97.1 % each keep the overall level at 95 %
LEVEL = {1: 0.95, 2: 0.971}
BOOT = 2000
SEED = 20261120


# ----------------------------------------------------------------------------------------------- design matrices
def word_column(rows, idx):
    out = []
    for r in rows:
        v = 1
        for i in idx:
            v *= r[i]
        out.append(v)
    return tuple(out)


def full_factorial(k):
    return [list(lv) for lv in itertools.product((-1, 1), repeat=k)]


def regular_fraction(k, runs, all_off=False):
    """(rows, generators as {letter: word}) of the 2^(k-p) fraction with `runs` runs from the generator table.
    all_off: negate even-length generator words (another fraction of the same family, same aliasing up to sign) so
    that one row has every factor off, i.e. the stored control is a design row."""
    base = int(math.log2(runs))
    if 2 ** base != runs:
        raise ValueError(f"{runs} runs is not a power of two")
    if k <= base:
        return full_factorial(k), {}
    gens = GENERATORS.get(runs, {}).get(k)
    if gens is None:
        raise ValueError(f"no generator table entry for {k} factors in {runs} runs")
    letters = LETTERS[:k]
    sign = [-1 if all_off and len(w) % 2 == 0 else 1 for w in gens]
    rows = []
    for lv in itertools.product((-1, 1), repeat=base):
        r = list(lv)
        for w, sg in zip(gens, sign):
            v = sg
            for ch in w:
                v *= lv[LETTERS.index(ch)]
            r.append(v)
        rows.append(r)
    return rows, {letters[base + i]: ("-" if sg < 0 else "") + w for i, (w, sg) in enumerate(zip(gens, sign))}


def plackett_burman12(k):
    if k > 11:
        raise ValueError("the 12-run Plackett-Burman design takes at most 11 factors")
    rows = [PB12[-i:] + PB12[:-i] if i else PB12[:] for i in range(11)] + [[-1] * 11]
    return [r[:k] for r in rows]


def foldover(rows):
    return [list(r) for r in rows] + [[-v for v in r] for r in rows]


def is_orthogonal(rows):
    k = len(rows[0])
    return all(sum(r[i] for r in rows) == 0 for i in range(k)) and \
        all(sum(r[i] * r[j] for r in rows) == 0 for i in range(k) for j in range(i))


def resolution(rows, max_len=6):
    """Smallest length of a word whose column is not orthogonal to the mean (min aberration word); None if none
    up to max_len. Also the generalized resolution of Deng and Tang (1999): R + 1 - max |sum| / n at that length."""
    k, n = len(rows[0]), len(rows)
    for L in range(1, min(k, max_len) + 1):
        worst = 0
        for idx in itertools.combinations(range(k), L):
            worst = max(worst, abs(sum(word_column(rows, idx))))
        if worst:
            return L, round(L + 1 - worst / n, 3)
    return None, None


def alias_structure(rows, letters):
    """Groups of main effects and two-factor interactions with identical columns up to sign (complete aliasing),
    plus partial aliases (|correlation| strictly between 0 and 1) of each main effect with two-factor interactions."""
    n = len(rows)
    cols = {}
    for i, l in enumerate(letters):
        cols[l] = word_column(rows, (i,))
    for (i, a), (j, b) in itertools.combinations(enumerate(letters), 2):
        cols[a + b] = word_column(rows, (i, j))
    groups = collections.OrderedDict()
    for w, c in cols.items():
        key = c if c[0] == 1 else tuple(-x for x in c)
        groups.setdefault(key, []).append(w)
    group_list = [g for g in groups.values()]
    main_alias = {l: [w for g in group_list if l in g for w in g if len(w) == 2] for l in letters}
    partial = {}
    for l in letters:
        p = []
        for w, c in cols.items():
            if len(w) != 2:
                continue
            r = sum(x * y for x, y in zip(cols[l], c)) / n
            if 0 < abs(r) < 1:
                p.append([w, round(r, 3)])
        if p:
            partial[l] = p
    two_groups = [g for g in group_list if all(len(w) == 2 for w in g)]
    return main_alias, two_groups, partial, group_list


def parse_factor(spec):
    """NAME:on=K=V,K=V[:off=K=V,...] -> dict(name, on=[K=V...], off=[K=V...])."""
    name, _, rest = spec.partition(":")
    if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError(f"bad factor name in {spec!r}")
    out = {"name": name, "on": [], "off": []}
    for part in filter(None, rest.split(":")):
        lvl, _, kv = part.partition("=")
        if lvl not in ("on", "off"):
            raise ValueError(f"factor {name}: level must be on= or off=, got {part!r}")
        for s in filter(None, kv.split(",")):
            if "=" not in s:
                raise ValueError(f"factor {name}: setting {s!r} is not K=V")
            out[lvl].append(s)
    if not out["on"]:
        raise ValueError(f"factor {name}: no on= settings")
    return out


def rotation_row(board_index, seed, n_rows):
    """Row of a rotated design carried by a stored control: (board index + seed) mod N."""
    return (board_index + seed) % n_rows


def make_plan(factors, runs=None, kind="regular", fold=False, rotate=None, boards=None, seeds=1, margins=None,
              all_off=False):
    k = len(factors)
    if k < 1:
        raise ValueError("no factors")
    if kind == "pb12":
        rows, gens = plackett_burman12(k), {}
        name = f"Plackett-Burman 12 runs, {k} factors"
    else:
        runs = runs or next(r for r in (8, 16, 32) if r >= k + 1 or r == 32)
        rows, gens = regular_fraction(k, runs, all_off)
        p = k - int(math.log2(len(rows)))
        name = f"2^({k}-{p})" + (" " + ", ".join(f"{g}={w}" for g, w in gens.items()) if gens else " full factorial")
    if fold:
        rows = foldover(rows)
        name += " with fold-over"
    letters = list(LETTERS[:k])
    if not is_orthogonal(rows):
        raise ValueError("design is not orthogonal")
    res, gres = resolution(rows)
    main_alias, two_groups, partial, _ = alias_structure(rows, letters)
    arms = []
    for i, r in enumerate(rows):
        sets = []
        for f, v in zip(factors, r):
            sets += f["on"] if v > 0 else f["off"]
        arms.append({"id": f"r{i:02d}", "row": r, "levels": {f["name"]: v for f, v in zip(factors, r)},
                     "settings": sets, "set_args": " ".join(f"--set {s}" for s in sets),
                     "all_off": all(v < 0 for v in r), "all_on": all(v > 0 for v in r)})
    plan = {"design": name, "kind": kind, "foldover": fold, "runs": len(rows), "letters": letters,
            "factors": [dict(f, letter=l) for f, l in zip(factors, letters)], "generators": gens,
            "resolution": res, "generalized_resolution": gres,
            "main_effect_aliases": {l: v for l, v in main_alias.items() if v},
            "two_factor_alias_groups": two_groups, "partial_aliases": partial, "arms": arms,
            "has_all_off": any(a["all_off"] for a in arms), "has_all_on": any(a["all_on"] for a in arms),
            "margins": dict(DEFAULT_MARGINS, **(margins or {})), "looks": 2}
    if rotate:
        if rotate != len(rows):
            raise ValueError(f"--rotate {rotate} must equal the number of design rows ({len(rows)})")
        plan["rotation"] = {"n": rotate, "rule": "row = (board index + seed) mod N"}
        if boards:
            plan["rotation"]["boards"] = list(boards)
            plan["rotation"]["assignment"] = [{"board": b, "seed": s, "arm": arms[rotation_row(i, s, rotate)]["id"]}
                                              for i, b in enumerate(boards) for s in range(seeds)]
    return plan


def print_plan(plan, out=sys.stdout):
    res = {None: "full (no aliasing up to length 6)", 3: "III", 4: "IV", 5: "V", 6: "VI"}.get(plan["resolution"],
                                                                                              str(plan["resolution"]))
    print(f"## {plan['design']}: {plan['runs']} runs, {len(plan['factors'])} factors, resolution {res}"
          f" (generalized {plan['generalized_resolution']})", file=out)
    print("factors: " + ", ".join(f"{f['letter']}={f['name']}" for f in plan["factors"]), file=out)
    print("main effects aliased with two-factor interactions:", plan["main_effect_aliases"] or "none", file=out)
    if plan["partial_aliases"]:
        print("partial aliases (main effect: [interaction, correlation]):", plan["partial_aliases"], file=out)
    print("two-factor alias groups: " + " ".join("{" + ",".join(g) + "}" for g in plan["two_factor_alias_groups"]),
          file=out)
    for a in plan["arms"]:
        tag = " all-off" if a["all_off"] else " all-on" if a["all_on"] else ""
        print(f"  {a['id']} {''.join('+' if v > 0 else '-' for v in a['row'])}  {a['set_args'] or '(defaults)'}{tag}",
              file=out)
    if not plan["has_all_off"]:
        print("note: no row is all-off; the stored control is not a design row", file=out)


# ----------------------------------------------------------------------------------------------------------- mde
def var_cells(s_int, s_dw, boards, seeds, runs):
    """Variance of a factor contrast's mean over boards, complete cells: s_int^2/boards + 2 s_dw^2/(boards seeds R)."""
    return s_int ** 2 / boards + 2 * s_dw ** 2 / (boards * seeds * runs)


def var_rotation(s_int, s_w, boards, total_runs):
    """Rotation (one design row per board and seed): s_int^2/boards + 4 s_w^2/N, N = total runs."""
    return s_int ** 2 / boards + 4 * s_w ** 2 / total_runs


def z_power(alpha=0.05, power=0.80, tests=1):
    nd = st.NormalDist()
    return nd.inv_cdf(1 - alpha / (2 * tests)) + nd.inv_cdf(power)


def mde(var, alpha=0.05, power=0.80, tests=1):
    """Smallest detectable effect (log scale) at the given power, two-sided, Bonferroni over `tests`."""
    return z_power(alpha, power, tests) * math.sqrt(var)


def pct(x):
    return (math.exp(x) - 1) * 100


# ------------------------------------------------------------------------------------------------------ analysis
ENDPOINTS_CORE = ("opens", "clean", "length", "vias")
LOWER_IS_BETTER = {"opens": True, "clean": False, "length": True, "vias": True}


def endpoint_value(ep, row):
    """Value of an endpoint for one run (row dict) or None."""
    try:
        if ep == "opens":
            return math.log1p(float(row["opens"]))
        if ep == "clean":
            return float(row["clean"])
        if ep == "length":
            v = float(row["length"])
            return math.log(v) if v > 0 else None
        if ep == "vias":
            return math.log1p(float(row["vias"]))
        if ep.startswith("phys_"):
            v = float(row[ep])
            return math.log(v) if v > 0 else None
    except (KeyError, TypeError, ValueError):
        return None
    return None


def closes(row):
    try:
        return float(row["opens"]) == 0
    except (KeyError, TypeError, ValueError):
        return False


def holm(ps):
    """Holm step-down adjusted p-values, same order as ps."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = [1.0] * len(ps)
    run = 0.0
    m = len(ps)
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        out[i] = run
    return out


def cluster_bootstrap(values, owners, level, n=BOOT, seed=SEED):
    """Percentile interval of the mean over boards, resampling owners (clusters) with replacement."""
    by = collections.defaultdict(list)
    for v, o in zip(values, owners):
        by[o].append(v)
    keys = sorted(by)
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        tot = cnt = 0
        for o in rng.choices(keys, k=len(keys)):
            tot += sum(by[o])
            cnt += len(by[o])
        means.append(tot / cnt)
    means.sort()
    a = (1 - level) / 2
    return means[int(a * n)], means[min(n - 1, int((1 - a) * n))]


def signflip_p(values, owners, n=BOOT, seed=SEED):
    """Two-sided sign-flip permutation p of the mean, flipping whole owner clusters (exact when <= 12 owners)."""
    by = collections.defaultdict(float)
    cnt = 0
    for v, o in zip(values, owners):
        by[o] += v
        cnt += 1
    sums = list(by.values())
    obs = abs(sum(sums))
    if len(sums) <= 12:
        tot = hit = 0
        for signs in itertools.product((1, -1), repeat=len(sums)):
            tot += 1
            hit += abs(sum(s * x for s, x in zip(signs, sums))) >= obs - 1e-12
        return hit / tot
    rng = random.Random(seed)
    hit = sum(abs(sum(x if rng.random() < 0.5 else -x for x in sums)) >= obs - 1e-12 for _ in range(n))
    return (hit + 1) / (n + 1)


def eb_confseq(xs, alpha=0.05, lo=-1.0, hi=1.0, c=0.5):
    """Predictable plug-in empirical-Bernstein confidence sequence for a mean (Waudby-Smith and Ramdas, JRSSB 2024,
    Theorem 2). xs are clipped to [lo, hi] and rescaled to [0, 1]; returns the running-intersection (lower, upper)
    after each observation, on the original scale."""
    out = []
    s = ssq = sl = slx = sv = 0.0
    mu_prev, var_prev = 0.5, 0.25
    L, U = 0.0, 1.0
    for t, x in enumerate(xs, 1):
        x = (min(max(x, lo), hi) - lo) / (hi - lo)
        lam = min(math.sqrt(2 * math.log(2 / alpha) / (var_prev * t * math.log(1 + t))), c)
        v = 4 * (x - mu_prev) ** 2
        psi = (-math.log(1 - lam) - lam) / 4
        sl += lam
        slx += lam * x
        sv += v * psi
        s += x
        mu = (0.5 + s) / (t + 1)
        ssq += (x - mu) ** 2
        var = (0.25 + ssq) / (t + 1)
        mu_prev, var_prev = mu, var
        m = slx / sl
        h = (math.log(2 / alpha) + sv) / sl
        L, U = max(L, m - h), min(U, m + h)
        out.append((lo + L * (hi - lo), lo + U * (hi - lo)))
    return out


def arm_columns(plan):
    """arm id -> {factor name or interaction word: +-1}; the letters of interactions are the plan's letters."""
    letters = plan["letters"]
    out = {}
    for a in plan["arms"]:
        d = {f["name"]: v for f, v in zip(plan["factors"], a["row"])}
        for (i, x), (j, y) in itertools.combinations(enumerate(letters), 2):
            d[x + y] = a["row"][i] * a["row"][j]
        out[a["id"]] = d
    return out


def board_contrasts(runs, plan, ep, column):
    """board -> contrast of `column` for endpoint `ep`.

    A cell is (board, seed). Where a cell holds every design row, its contrast is mean(+) - mean(-) and the board's
    contrast is the mean over its complete cells. Otherwise (rotation, missing runs) the board's observations are
    pooled over seeds and the contrast is mean(+) - mean(-) when both levels are present. Length and vias use only
    cells (boards, for pooled boards) where every run closes."""
    cols = arm_columns(plan)
    n_rows = len(plan["arms"])
    cells = collections.defaultdict(dict)
    for r in runs:
        if r["arm"] in cols:
            cells[(r["board"], r["seed"])][r["arm"]] = r
    per_board = collections.defaultdict(list)
    pooled = collections.defaultdict(list)
    for (b, s), arms in cells.items():
        if len(arms) == n_rows:
            if ep in ("length", "vias") and not all(closes(x) for x in arms.values()):
                continue
            vals = {a: endpoint_value(ep, x) for a, x in arms.items()}
            if any(v is None for v in vals.values()):
                continue
            plus = [v for a, v in vals.items() if cols[a][column] > 0]
            minus = [v for a, v in vals.items() if cols[a][column] < 0]
            per_board[b].append(st.mean(plus) - st.mean(minus))
        else:
            pooled[b].extend(arms.items())
    out = {b: st.mean(v) for b, v in per_board.items()}
    for b, obs in pooled.items():
        if b in out:
            continue
        if ep in ("length", "vias") and not all(closes(x) for _, x in obs):
            continue
        plus = [endpoint_value(ep, x) for a, x in obs if cols[a][column] > 0]
        minus = [endpoint_value(ep, x) for a, x in obs if cols[a][column] < 0]
        plus = [v for v in plus if v is not None]
        minus = [v for v in minus if v is not None]
        if plus and minus:
            out[b] = st.mean(plus) - st.mean(minus)
    return out


def judge(ep, contrasts, owners_of, margin, looks, confseq=None):
    boards = sorted(contrasts)
    xs = [contrasts[b] for b in boards]
    owners = [owners_of.get(b, b) for b in boards]
    n, n_own = len(xs), len(set(owners))
    e = {"boards": n, "owners": n_own, "boards_changed": sum(1 for x in xs if x != 0)}
    if n < 10 or n_own < 10:
        e["status"] = "unknown"
        e["why"] = f"{n} boards, {n_own} owners: under 10"
        return e
    level = LEVEL[looks]
    m = st.mean(xs)
    lo, hi = cluster_bootstrap(xs, owners, level)
    p = signflip_p(xs, owners)
    sd = st.stdev(xs)
    good_lower = LOWER_IS_BETTER.get(ep, True)
    if (hi < 0 and good_lower) or (lo > 0 and not good_lower):
        status = "better"
    elif (lo > 0 and good_lower) or (hi < 0 and not good_lower):
        status = "worse"
    elif lo > -margin and hi < margin:
        status = "bounded"
    else:
        status = "undecided"
    e.update(estimate=round(m, 4), interval=[round(lo, 4), round(hi, 4)], level=level, p=round(p, 4),
             margin=round(margin, 4), status=status)
    if ep != "clean":
        e.update(estimate_pct=round(pct(m), 1), interval_pct=[round(pct(lo), 1), round(pct(hi), 1)],
                 margin_pct=round(pct(margin), 1))
    if status == "undecided":
        z = st.NormalDist().inv_cdf(1 - (1 - level) / 2)
        e["boards_to_decide"] = max(n + 1, math.ceil((z * sd / margin) ** 2))
        e["why"] = (f"interval reaches past the {margin:.3g} margin; about {e['boards_to_decide']} boards of the same "
                    f"kind would bound it")
    if confseq:
        B = confseq
        cs = eb_confseq(xs, lo=-B, hi=B)
        cl, cu = cs[-1]
        fixed = st.NormalDist().inv_cdf(0.975) * sd / math.sqrt(n)
        e["confseq"] = {"clip": B, "interval": [round(cl, 4), round(cu, 4)],
                        "width_ratio_vs_fixed_n": round(((cu - cl) / 2) / fixed, 2) if fixed > 0 else None,
                        "excludes_zero": cl > 0 or cu < 0}
    return e


def analyse(runs, plan, owners_of=None, looks=None, confseq=None, reach=None, margins=None):
    owners_of = owners_of or {}
    looks = looks or plan.get("looks", 2)
    mg = dict(DEFAULT_MARGINS, **plan.get("margins", {}), **(margins or {}))
    phys = sorted({k for r in runs for k in r if k.startswith("phys_") and r[k] not in (None, "")})
    endpoints = list(ENDPOINTS_CORE) + phys
    names = [f["name"] for f in plan["factors"]]
    out = {"design": plan["design"], "runs": plan["runs"], "resolution": plan["resolution"], "looks": looks,
           "level": LEVEL[looks], "stopping_rule": "fixed design, at most one pre-registered extension (Pocock, two "
           "looks at 97.1 %)" if looks == 2 else "fixed design, one look at 95 %",
           "boards": len({r["board"] for r in runs}), "factors": {}, "interactions": {}}
    if confseq:
        out["confseq_note"] = ("anytime-valid empirical-Bernstein interval for accumulating designs; at 60 boards it is "
                               "about 5x wider than the fixed-n interval")
    reach_sets = None
    if reach:
        reach_sets = reach.get("factors", reach)
    for ep in endpoints:
        margin = mg.get(ep, mg["physics"] if ep.startswith("phys_") else math.log(1.25))
        res = {}
        for f in names:
            con = board_contrasts(runs, plan, ep, f)
            e = judge(ep, con, owners_of, margin, looks, confseq)
            if reach_sets is not None and f in reach_sets:
                rb = set(reach_sets[f])
                e["reached"] = judge(ep, {b: v for b, v in con.items() if b in rb}, owners_of, margin, looks)
            res[f] = e
        ps = [(f, res[f]["p"]) for f in names if "p" in res[f]]
        for (f, _), adj in zip(ps, holm([p for _, p in ps])):
            res[f]["p_holm"] = round(adj, 4)
        for f in names:
            out["factors"].setdefault(f, {})[ep] = res[f]
        # two-factor interactions, one estimate per alias group (the group's first word stands for all of it)
        for g in plan.get("two_factor_alias_groups", []):
            con = board_contrasts(runs, plan, ep, g[0])
            e = judge(ep, con, owners_of, margin, looks)
            aliased_main = [l for l, v in plan.get("main_effect_aliases", {}).items() if g[0] in v]
            if aliased_main:
                e["aliased_with_main_effect"] = aliased_main
            out["interactions"].setdefault("=".join(g), {})[ep] = e
    return out


# --------------------------------------------------------------------------------------------------- data input
def read_csv(path):
    """Tidy CSV: board, seed, arm, opens, clean, length, vias, optional owner and phys_<kind> columns."""
    runs, owners = [], {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            r = dict(r)
            r["seed"] = int(r["seed"])
            if r.get("owner"):
                owners[r["board"]] = r["owner"]
            runs.append(r)
    return runs, owners


def store_dir():
    return Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))


def owner_from_store(store, board):
    try:
        repo = json.loads((store / "boards" / board / "board.json").read_text()).get("repo") or ""
    except (OSError, ValueError):
        return board
    m = re.match(r"https?://[^/]+/([^/]+)/", repo)
    return m.group(1).lower() if m else board


def read_store(experiment, plan, store=None, arm_map=None):
    """Runs of a stored experiment as tidy rows (read-only on the store). A method is a design arm when its name
    contains the arm id as a word (r00, r01, ...); with a rotation plan every method's runs are assigned to
    row (board index + seed) mod N. arm_map {method-name substring: arm id} overrides the name match."""
    store = store or store_dir()
    ej = json.loads((store / "experiments" / experiment / "experiment.json").read_text())
    ev = ej.get("evaluators") or {}
    drc, phy = ev.get("drc"), ev.get("physics")
    mids = {m["id"]: m["name"] for m in ej.get("methods") or []}
    arm_ids = [a["id"] for a in plan["arms"]]
    rot = plan.get("rotation")
    board_index = {b: i for i, b in enumerate(rot.get("boards", []))} if rot else {}
    method_arm = {}
    for mid, name in mids.items():
        hit = [a for a in arm_ids if re.search(rf"\b{a}\b", name)]
        if len(hit) == 1:
            method_arm[mid] = hit[0]
        for sub_, arm in (arm_map or {}).items():
            if sub_ in name:
                method_arm[mid] = arm
    if not method_arm and not rot:
        raise SystemExit(f"no method of {experiment} names a design arm (r00 ...); methods: {sorted(mids.values())}")
    c = sqlite3.connect(f"file:{store / 'index.sqlite'}?mode=ro", uri=True)
    q = ("select r.board, r.method_id, r.attempt, e.evaluator, e.unconnected, e.clean, e.valid, e.json from runs r "
         "join evals e on e.board = r.board and e.run = r.run where r.experiment = ? and e.evaluator in (?, ?)")
    rows = {}
    for b, mid, att, evid, u, cl, va, js in c.execute(q, (experiment, drc, phy)):
        if rot:
            if b not in board_index:
                continue
            arm = arm_ids[rotation_row(board_index[b], att, rot["n"])]
        else:
            arm = method_arm.get(mid)
            if arm is None:
                continue
        r = rows.setdefault((b, att, arm), {"board": b, "seed": att, "arm": arm})
        try:
            js = json.loads(js) if js else {}
        except ValueError:
            js = {}
        if evid == drc:
            if not va or u is None:
                r["invalid"] = True
                continue
            s = js.get("score") or {}
            r.update(opens=u, clean=cl, length=s.get("track_length_mm"), vias=s.get("vias"))
        else:
            kinds = collections.defaultdict(list)
            for m in ((js.get("physics") or {}).get("modules") or {}).values():
                v = m.get("value")
                if v and v > 0 and not (m.get("open_hops") or 0):
                    kinds[m.get("kind")].append(math.log(v))
            for kd, vs in kinds.items():
                r[f"phys_{kd}"] = math.exp(st.mean(vs))      # geometric mean of the board's modules of that kind
    runs = [r for r in rows.values() if not r.get("invalid") and "opens" in r]
    owners = {b: owner_from_store(store, b) for b in {r["board"] for r in runs}}
    return runs, owners


# ---------------------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("design", help="write plan.json for a two-level design")
    d.add_argument("--factor", action="append", required=True, help="NAME:on=K=V,K=V[:off=K=V,...]")
    d.add_argument("--runs", default=None, help="8, 16, 32 (regular fraction) or 12 (Plackett-Burman)")
    d.add_argument("--foldover", action="store_true")
    d.add_argument("--with-all-off", action="store_true",
                   help="regular fractions: pick generator signs so one row is all-off (the stored control)")
    d.add_argument("--rotate", type=int, help="rotation rows for a stored control: row = (board index + seed) mod N")
    d.add_argument("--boards", help="file of board ids (for the rotation assignment)")
    d.add_argument("--seeds", type=int, default=1)
    d.add_argument("--margin", action="append", default=[], help="pre-registered margin ENDPOINT=VALUE (log scale)")
    d.add_argument("-o", "--out", default="plan.json")
    m = sub.add_parser("mde", help="smallest detectable effect of a design")
    m.add_argument("--s-int", type=float, required=True, help="board x arm interaction sd")
    m.add_argument("--s-dw", type=float, help="sd of a same-seed difference (complete cells)")
    m.add_argument("--s-w", type=float, help="within-board seed sd (rotation)")
    m.add_argument("--boards", type=int, required=True)
    m.add_argument("--seeds", type=float, default=1)
    m.add_argument("--runs", type=int, default=8, help="design rows R")
    m.add_argument("--rotate", action="store_true", help="rotation design: one row per (board, seed)")
    m.add_argument("--total-runs", type=float, help="N for rotation (default boards x seeds)")
    m.add_argument("--power", type=float, default=0.80)
    m.add_argument("--alpha", type=float, default=0.05)
    m.add_argument("--factors", type=int, default=1, help="Bonferroni over this many factors")
    m.add_argument("--bonferroni", action="store_true")
    m.add_argument("--cost-per-run", type=float, help="CPU-h per run (board x row x seed)")
    a = sub.add_parser("analyse", help="verdict per factor; writes VERDICT.json")
    a.add_argument("--plan", required=True)
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--experiment", help="experiment name in $KAE_RESULTS")
    a.add_argument("--looks", type=int, choices=(1, 2), help="1: fixed design at 95 %%; 2 (default): Pocock 97.1 %%")
    a.add_argument("--confseq", type=float, nargs="?", const=1.0, default=None,
                   help="accumulating designs only: confidence sequence with contrasts clipped to +-B (default 1)")
    a.add_argument("--arm", action="append", default=[], metavar="METHOD_SUBSTRING=ARM",
                   help="map stored methods to design arms, e.g. 'control=r00'")
    a.add_argument("--reach", help="reach.json: {factor: [boards the factor reaches]}")
    a.add_argument("-o", "--out", default="VERDICT.json")
    args = ap.parse_args(argv)

    if args.cmd == "design":
        factors = [parse_factor(s) for s in args.factor]
        margins = {k: float(v) for k, _, v in (s.partition("=") for s in args.margin)}
        boards = Path(args.boards).read_text().split() if args.boards else None
        kind = "pb12" if args.runs == "12" else "regular"
        plan = make_plan(factors, runs=int(args.runs) if args.runs and kind == "regular" else None, kind=kind,
                         fold=args.foldover, rotate=args.rotate, boards=boards, seeds=args.seeds, margins=margins,
                         all_off=args.with_all_off)
        Path(args.out).write_text(json.dumps(plan, indent=1) + "\n")
        print_plan(plan)
        print(f"wrote {args.out}")
    elif args.cmd == "mde":
        tests = args.factors if args.bonferroni else 1
        if args.rotate:
            if args.s_w is None:
                ap.error("--rotate needs --s-w")
            N = args.total_runs or args.boards * args.seeds
            var = var_rotation(args.s_int, args.s_w, args.boards, N)
            runs_total = N
        else:
            if args.s_dw is None:
                ap.error("complete cells need --s-dw")
            var = var_cells(args.s_int, args.s_dw, args.boards, args.seeds, args.runs)
            runs_total = args.boards * args.seeds * args.runs
        e = mde(var, args.alpha, args.power, tests)
        print(f"detectable effect at {args.power:.0%} power, two-sided {args.alpha:g}"
              f"{f', Bonferroni over {tests}' if tests > 1 else ''}: {e:.4f} (log) = {pct(e):.1f}%"
              f"  [{args.boards} boards, {runs_total:g} runs]")
        if args.cost_per_run:
            print(f"CPU: {runs_total * args.cost_per_run:.1f} CPU-h")
    else:
        plan = json.loads(Path(args.plan).read_text())
        if args.csv:
            runs, owners = read_csv(args.csv)
        else:
            arm_map = dict(x.rsplit("=", 1) for x in args.arm)
            runs, owners = read_store(args.experiment, plan, arm_map=arm_map)
        reach = json.loads(Path(args.reach).read_text()) if args.reach else None
        v = analyse(runs, plan, owners, args.looks, args.confseq, reach)
        if args.experiment:
            v["experiment"] = args.experiment
        Path(args.out).write_text(json.dumps(v, indent=1) + "\n")
        for f, eps in v["factors"].items():
            for ep, e in eps.items():
                if e["status"] == "unknown":
                    continue
                lo, hi = e["interval"]
                extra = f"  p={e['p']:.3f} holm={e.get('p_holm', 1):.3f}"
                if "boards_to_decide" in e:
                    extra += f"  ({e['boards_to_decide']} boards would decide it)"
                if "confseq" in e:
                    extra += f"  confseq {e['confseq']['interval']} ({e['confseq']['width_ratio_vs_fixed_n']}x fixed-n)"
                print(f"{f:12s} {ep:14s} n={e['boards']:3d} {e['estimate']:+.4f} [{lo:+.4f}, {hi:+.4f}] "
                      f"-> {e['status']}{extra}")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
