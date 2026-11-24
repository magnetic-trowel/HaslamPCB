#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Report-only quality view of an experiment's stored results, for boards that already route.

Reads `experiments/NAME/results.csv` (attempt 0; write it with `kaeres exp report NAME`) and the stored physics
evaluations of the runs it names. Runs nothing, scores nothing and writes nothing into the store.

  kaeres quality NAME --control METHOD [--method METHOD ...] [--no-human] [--out FILE]

Each method B is paired per board with the control A, and each of them with the human layout where the experiment has
a human row. The endpoints are kept apart: near-miss closure, big-board opens, clean net of input, then quality on the
boards both arms finish (track length, vias, DRC errors added by type, physics per module kind) and reach. Intervals
are 95 % bootstraps that resample repository owners; a verdict is better, worse, undecided (the interval includes no
change) or unknown (fewer than MIN_N boards).
"""
import argparse
import csv
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "bench" / "src"))
from kaebench import stats  # noqa: E402  (stdlib only; shared with `kaebench report` and `kaeres exp report`)

MIN_N = 10            # fewer paired boards than this, or fewer owners to resample: "unknown", no estimate
NEAR_OPENS = 5        # near-miss: 1..NEAR_OPENS unconnected items left
BIG_PADS = 1000       # big board: more pads than this
N_BOOT = 2000
ERROR_TYPES = ("solder_mask_bridge", "silk_over_copper", "silk_overlap", "silk_edge_clearance")
PHYSICS_KINDS = (("cell", "hot-loop cell"), ("decap", "decap"), ("crystal", "crystal"), ("chain", "chain"))
HUMAN = "human"


# ------------------------------------------------------------------ rows
def _bool(x):
    if isinstance(x, bool) or x is None:
        return x
    return {"true": True, "false": False}.get(str(x).strip().lower())


def _num(x, cast=float):
    if x is None or x == "":
        return None
    try:
        return cast(float(x))
    except (TypeError, ValueError):
        return None


def owner_of(repo, board):
    """The bootstrap cluster of a board: host and owner of its repository (boards of one owner are not independent);
    the board itself when it has no repository."""
    if not repo:
        return f"board:{board}"
    u = urlparse(repo if "//" in repo else "//" + repo)
    parts = [p for p in u.path.split("/") if p]
    return f"{u.netloc.lower()}/{parts[0].lower()}" if parts else u.netloc.lower() or f"board:{board}"


def typed(row):
    """A results.csv row (strings) or an `exp_rows` row with the fields used here in their own types."""
    e = row.get("errors_by_type") or {}
    return dict(row, valid=_bool(row.get("valid")), xc=_bool(row.get("xc")), attempt=_num(row.get("attempt"), int) or 0,
                unconnected=_num(row.get("unconnected"), int), pads=_num(row.get("pads"), int),
                track_length_mm=_num(row.get("track_length_mm")), vias=_num(row.get("vias"), int),
                errors_by_type=json.loads(e) if isinstance(e, str) else dict(e),
                owner=owner_of(row.get("repo"), row.get("board")), kind=row.get("kind") or "route")


def load_rows(path):
    with open(path, newline="") as f:
        return [typed(r) for r in csv.DictReader(f)]


def by_method(rows):
    """{method: {board: attempt-0 row}}."""
    out = defaultdict(dict)
    for r in rows:
        if r["attempt"] == 0:
            out[r["method"]][r["board"]] = r
    return out


def scored(r):
    return r is not None and r.get("status") == "ok" and r["valid"] is True and r["unconnected"] is not None


def closed(r):
    return scored(r) and r["unconnected"] == 0


def pick(name, names):
    """A method of `names` by exact name, else by a case-insensitive part of its name that only one has."""
    if name in names:
        return name
    hit = [n for n in names if name.lower() in n.lower()]
    if len(hit) != 1:
        raise SystemExit(f"method {name!r}: {'no match' if not hit else 'matches ' + ', '.join(hit)} (have: {', '.join(names)})")
    return hit[0]


# ------------------------------------------------------------------ statistics
def boot_ci(groups, stat, n_boot=N_BOOT, seed=0):
    """95 % percentile interval of stat(values), resampling whole groups ({owner: [values]}) with replacement."""
    vals = [groups[k] for k in sorted(groups)]
    if not vals:
        return None, None
    rng = random.Random(seed)
    g = len(vals)
    out = []
    for _ in range(n_boot):
        s = []
        for _ in range(g):
            s.extend(vals[rng.randrange(g)])
        out.append(stat(s))
    out.sort()
    return out[int(0.025 * (n_boot - 1))], out[int(math.ceil(0.975 * (n_boot - 1)))]


def _mean(xs):
    return sum(xs) / len(xs)


def clopper_pearson(k, n, alpha=0.05):
    """Exact two-sided interval of a binomial share k / n."""
    if n == 0:
        return 0.0, 1.0

    def cdf(p, upto):
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(upto + 1))

    def solve(f, target):    # f falls as p rises
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) > target else (lo, mid)
        return (lo + hi) / 2
    low = 0.0 if k == 0 else solve(lambda p: cdf(p, k - 1), 1 - alpha / 2)
    high = 1.0 if k == n else solve(lambda p: cdf(p, k), alpha / 2)
    return low, high


def verdict(n, lo, hi, null, lower_better=True, min_n=MIN_N):
    """better / worse when the interval [lo, hi] excludes `null` (no change), undecided when it includes it,
    unknown under min_n pairs."""
    if n < min_n or lo is None or hi is None:
        return "unknown"
    if hi < null:
        return "better" if lower_better else "worse"
    if lo > null:
        return "worse" if lower_better else "better"
    return "undecided"


def _grouped(pairs):
    g = defaultdict(list)
    for own, x in pairs:
        g[own].append(x)
    return g


def ratio_row(pairs, min_n=MIN_N, n_boot=N_BOOT):
    """Median ratio B / A over (owner, board, ratio) pairs with its owner bootstrap; lower is better. No estimate
    under min_n boards or under min_n owners: a bootstrap over a few owners has no spread to resample."""
    boards = {b for _, b, _ in pairs}
    out = dict(n=len(boards), items=len(pairs), owners=len({o for o, _, _ in pairs}), est=None, lo=None, hi=None,
               lower=sum(1 for *_, x in pairs if x < 1), same=sum(1 for *_, x in pairs if x == 1),
               higher=sum(1 for *_, x in pairs if x > 1))
    if min(out["n"], out["owners"]) >= min_n:
        logs = _grouped((o, math.log(x)) for o, _, x in pairs)
        lo, hi = boot_ci(logs, statistics.median, n_boot)
        out.update(est=math.exp(statistics.median([x for v in logs.values() for x in v])), lo=math.exp(lo), hi=math.exp(hi))
    out["verdict"] = verdict(min(out["n"], out["owners"]), out["lo"], out["hi"], 1.0, min_n=min_n)
    return out


def diff_row(pairs, min_n=MIN_N, lower_better=True):
    """Mean paired difference B − A over (owner, board, difference) with its owner bootstrap (kaebench.stats)."""
    out = dict(n=len(pairs), owners=len({o for o, _, _ in pairs}), est=None, lo=None, hi=None,
               lower=sum(1 for *_, x in pairs if x < 0), same=sum(1 for *_, x in pairs if x == 0),
               higher=sum(1 for *_, x in pairs if x > 0))
    if min(out["n"], out["owners"]) >= min_n:
        lo, hi = stats.bootstrap_ci([x for *_, x in pairs], [o for o, _, _ in pairs], n_boot=N_BOOT)
        out.update(est=_mean([x for *_, x in pairs]), lo=lo, hi=hi)
    out["verdict"] = verdict(min(out["n"], out["owners"]), out["lo"], out["hi"], 0.0, lower_better, min_n)
    return out


# ------------------------------------------------------------------ endpoints
def near_miss(A, B, near=NEAR_OPENS, min_n=MIN_N):
    """Near-miss closure, both ways so that picking boards by one arm's outcome favours neither: boards A leaves
    1..near opens that B closes, against boards B leaves 1..near opens that A closes. Exact sign test on the two
    counts; the interval is Clopper-Pearson on B's share of those closures (no change: 0.5)."""
    both = sorted(set(A) & set(B))

    def nm(r):
        return scored(r) and 1 <= r["unconnected"] <= near
    na = [b for b in both if nm(A[b])]
    nb = [b for b in both if nm(B[b])]
    won = [b for b in na if closed(B[b])]
    lost = [b for b in nb if closed(A[b])]
    fewer = sum(1 for b in na if scored(B[b]) and 0 < B[b]["unconnected"] < A[b]["unconnected"])
    same = sum(1 for b in na if scored(B[b]) and B[b]["unconnected"] == A[b]["unconnected"])
    n = len(set(na) | set(nb))
    d = len(won) + len(lost)
    lo, hi = clopper_pearson(len(won), d) if d else (None, None)
    return dict(n=n, near_a=len(na), near_b=len(nb), won=won, lost=lost, fewer=fewer, same=same,
                more=len(na) - len(won) - fewer - same, won_xc=sum(1 for b in won if B[b]["xc"]),
                p=stats.mcnemar_exact(len(lost), len(won)), share=len(won) / d if d else None, lo=lo, hi=hi,
                verdict=verdict(n, lo, hi, 0.5, lower_better=False, min_n=min_n) if d else ("unknown" if n < min_n else "undecided"))


def big_opens(A, B, big=BIG_PADS, min_n=MIN_N):
    """Boards over `big` pads that both arms scored: paired difference of log(1 + opens), B − A."""
    ran = [b for b in sorted(set(A) & set(B)) if (A[b]["pads"] or 0) > big]
    ok = [b for b in ran if scored(A[b]) and scored(B[b])]
    out = diff_row([(A[b]["owner"], b, math.log1p(B[b]["unconnected"]) - math.log1p(A[b]["unconnected"])) for b in ok], min_n)
    out.update(unscored=len(ran) - len(ok), opens_a=sum(A[b]["unconnected"] for b in ok), opens_b=sum(B[b]["unconnected"] for b in ok))
    return out


def xc_pair(A, B, min_n=MIN_N):
    """Clean net of input (xc), paired on the boards where both rows have it; a failed run is not clean."""
    ok = [b for b in sorted(set(A) & set(B)) if A[b]["xc"] is not None and B[b]["xc"] is not None]
    out = diff_row([(A[b]["owner"], b, float(B[b]["xc"]) - float(A[b]["xc"])) for b in ok], min_n, lower_better=False)
    out.update(share_a=_mean([float(A[b]["xc"]) for b in ok]) if ok else None, share_b=_mean([float(B[b]["xc"]) for b in ok]) if ok else None,
               p=stats.mcnemar_exact(out["lower"], out["higher"]),
               placing=any(r["kind"] != "route" for arm in (A, B) for r in (arm[b] for b in ok)))
    return out


def finished(A, B):
    return [b for b in sorted(set(A) & set(B)) if closed(A[b]) and closed(B[b])]


def quality(A, B, modules=None, types=ERROR_TYPES, min_n=MIN_N, n_boot=N_BOOT, return_path_of=None):
    """Quality rows on the boards both arms finish (0 opens). `modules(row)` gives a run's physics modules
    ({id: {kind, value, open_hops}}) or None; modules pair by id, and only when one physics evaluator scored both runs.
    `return_path_of(row)` gives a run's stored board file; with it, the return-path rows of `return_board.py` are added
    (report-only, mean B - A per board).
    The physics rows come twice: on the finished boards, and on every board both arms scored (the module itself still
    closed in both), because the hot loops and crystals sit mostly on boards that one arm leaves open."""
    fin = finished(A, B)
    rows = []
    tl = [(A[b]["owner"], b, B[b]["track_length_mm"] / A[b]["track_length_mm"]) for b in fin
          if (A[b]["track_length_mm"] or 0) > 0 and (B[b]["track_length_mm"] or 0) > 0]
    rows.append(dict(ratio_row(tl, min_n, n_boot), key="track length", unit="median ratio B / A"))
    vias = [(A[b]["owner"], b, (1 + B[b]["vias"]) / (1 + A[b]["vias"])) for b in fin
            if A[b]["vias"] is not None and B[b]["vias"] is not None]
    rows.append(dict(ratio_row(vias, min_n, n_boot), key="vias", unit="median ratio (1 + B) / (1 + A)"))
    for t in types:
        d = [(A[b]["owner"], b, B[b]["errors_by_type"].get(t, 0) - A[b]["errors_by_type"].get(t, 0)) for b in fin]
        rows.append(dict(diff_row(d, min_n), key=f"errors added: {t}", unit="mean B − A per board"))
    if return_path_of is not None:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import return_board  # noqa: E402  (needs shapely; only loaded when the rows are asked for)
        rows += [dict(diff_row(d, min_n, lower_better=k == "unc_mm"), key=f"return: {k}", unit="mean B − A per board")
                 for k, d in return_board.paired(A, B, fin, return_path_of, measure_fn=return_board.measure_cached).items()]
    foreign = 0
    if modules is not None:
        fin_set, per, anyb = set(fin), defaultdict(list), defaultdict(list)
        for b in sorted(set(A) & set(B)):
            if not (scored(A[b]) and scored(B[b])):
                continue
            if A[b].get("evaluator_physics") != B[b].get("evaluator_physics"):
                foreign += b in fin_set
                continue
            ma, mb = modules(A[b]) or {}, modules(B[b]) or {}
            for k in sorted(set(ma) & set(mb)):
                va, vb = ma[k].get("value"), mb[k].get("value")
                if va and vb and va > 0 and vb > 0 and not ma[k].get("open_hops") and not mb[k].get("open_hops"):
                    anyb[ma[k].get("kind")].append((A[b]["owner"], b, vb / va))
                    if b in fin_set:
                        per[ma[k].get("kind")].append((A[b]["owner"], b, vb / va))
        if fin and foreign == len(fin):
            rows.append(dict(ratio_row([], min_n, n_boot), key="physics: every kind", unit="not paired: evaluators differ", modules=True))
        else:
            kinds = list(PHYSICS_KINDS) + [(k, str(k)) for k in sorted(set(anyb) - {k for k, _ in PHYSICS_KINDS}, key=str)]
            for src, where in ((per, "physics"), (anyb, "physics, unfinished boards too")):
                for kind, label in kinds:
                    rows.append(dict(ratio_row(src.get(kind, []), min_n, n_boot), key=f"{where}: {label}",
                                     unit="median module ratio B / A", modules=True))
    return dict(n=len(fin), rows=rows, foreign_physics=foreign, placing=sorted({r["kind"] for arm in (A, B) for r in (arm[b] for b in fin)} - {"route"}),
                foreign_drc=sum(1 for b in fin if A[b].get("evaluator_drc") != B[b].get("evaluator_drc")))


def reach(A, B):
    """Share of the boards both arms scored where the outcomes are identical: opens and errors by type."""
    ran = sorted(set(A) & set(B))
    ok = [b for b in ran if scored(A[b]) and scored(B[b])]
    same = [b for b in ok if A[b]["unconnected"] == B[b]["unconnected"] and A[b]["errors_by_type"] == B[b]["errors_by_type"]]
    copper = [b for b in same if A[b]["track_length_mm"] == B[b]["track_length_mm"] and A[b]["vias"] == B[b]["vias"]]
    return dict(n=len(ok), unscored=len(ran) - len(ok), same=len(same), same_copper=len(copper))


# ------------------------------------------------------------------ rendering
def _f(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


def _ci(r, nd=3):
    if r["est"] is None:
        return "unknown"
    return f"{_f(r['est'], nd)} [{_f(r['lo'], nd)}, {_f(r['hi'], nd)}]"


def _quality_table(q):
    out = ["| measure | statistic | n boards (owners) | estimate [95 % interval] | B lower / same / higher | verdict |", "|---|---|---|---|---|---|"]
    for r in q["rows"]:
        n = f"{r['n']} ({r['owners']})" + (f", {r['items']} modules" if r.get("modules") else "")
        out.append(f"| {r['key']} | {r['unit']} | {n} | {_ci(r)} | {r['lower']} / {r['same']} / {r['higher']} | {r['verdict']} |")
    return out


def _placing_note(q):
    if not q["placing"]:
        return ""
    return f" One arm places parts (task kind {', '.join(q['placing'])}): the two layouts differ in placement as well as in routing."


def _verdict_rows(qs, mark=""):
    """One line per quality row: its verdict under each method of qs ({method: quality()}); `mark` flags the rows
    read from the DRC score where the two arms' scorers differ."""
    keys = list(dict.fromkeys(r["key"] for q in qs.values() for r in q["rows"]))
    out = []
    for key in keys:
        cells = []
        for q in qs.values():
            r = next((r for r in q["rows"] if r["key"] == key), None)
            cells.append(f"{r['verdict']}{mark if q['foreign_drc'] and not r.get('modules') else ''} (n {r['n']})" if r else "—")
        out.append(f"| {key} | " + " | ".join(cells) + " |")
    return out


def report(rows, control, names, modules=None, title="", source="", human=HUMAN, types=ERROR_TYPES, min_n=MIN_N, near=NEAR_OPENS,
           big=BIG_PADS, n_boot=N_BOOT, return_path_of=None):
    """The Markdown report: each method of `names` against `control`, then each of them against `human` when it has rows."""
    by = by_method(rows)
    A = by[control]
    out = [f"# Quality report{': ' + title if title else ''}", "",
           f"Control (A): **{control}**. Report-only: attempt 0 of stored runs, read from `results.csv` and the stored physics "
           "evaluations; no score is recomputed or changed." + (f" Source: {source}." if source else ""), "",
           f"- Each method B is paired with A on the same board. Intervals are 95 % bootstraps ({n_boot} resamples, seed 0) that resample "
           "repository owners; the near-miss interval is exact (Clopper-Pearson).",
           f"- Verdict: **better** / **worse** when the interval excludes no change, **undecided** when it includes it, **unknown** under "
           f"{min_n} paired boards or under {min_n} owners to resample (no estimate is printed).",
           "- The two completion endpoints answer different questions and are never pooled.", ""]
    res = {}
    for n in names:
        B = by[n]
        res[n] = dict(near=near_miss(A, B, near, min_n), big=big_opens(A, B, big, min_n), xc=xc_pair(A, B, min_n),
                      q=quality(A, B, modules, types, min_n, n_boot, return_path_of), reach=reach(A, B),
                      lost=len(set(A) ^ set(B)))
    out += ["## 1. Completion endpoints", "",
            f"### 1a. Near-miss closure (1-{near} opens from closed)", "",
            f"Boards A leaves with 1-{near} opens that B closes (0 opens), against boards B leaves with 1-{near} opens that A closes: "
            "counted both ways because picking boards by one arm's outcome alone favours the other arm. p: exact sign test on the "
            "two counts. Share: B's part of those closures, 0.5 is no change. n: boards near-miss in either arm.", "",
            "| B | n | A near-miss | B closes (clean net of input) | there: B fewer / same / more opens or no score | B near-miss | A closes | p | B's share [95 % interval] | verdict |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        r = res[n]["near"]
        share = "unknown" if r["n"] < min_n or r["share"] is None else f"{_f(r['share'], 2)} [{_f(r['lo'], 2)}, {_f(r['hi'], 2)}]"
        out.append(f"| {n} | {r['n']} | {r['near_a']} | {len(r['won'])} ({r['won_xc']}) | {r['fewer']} / {r['same']} / {r['more']} | {r['near_b']} | "
                   f"{len(r['lost'])} | {_f(r['p'], 3)} | {share} | {r['verdict']} |")
    out += ["", f"### 1b. Big-board opens (over {big:,} pads)", "",
            "Paired difference of log(1 + opens), B − A, on the boards both scored; negative is fewer opens. Sums of opens are the raw data, not the estimate.", "",
            "| B | n boards (owners) | not scored by one | opens A → B (sum) | mean difference [95 % interval] | B fewer / same / more | verdict |",
            "|---|---|---|---|---|---|---|"]
    for n in names:
        r = res[n]["big"]
        out.append(f"| {n} | {r['n']} ({r['owners']}) | {r['unscored']} | {r['opens_a']} → {r['opens_b']} | {_ci(r)} | "
                   f"{r['lower']} / {r['same']} / {r['higher']} | {r['verdict']} |")
    dag = any(res[n]["xc"]["placing"] for n in names)
    out += ["", "### 1c. Clean net of input (`xc`)", "",
            "Share of boards valid, with 0 opens and no DRC error type above the route input's count; boards where both rows have it. p: exact McNemar."
            + (" † one arm places parts, which do not inherit the input's errors: not comparable (tools/kaeres/README.md, Report columns)." if dag else ""), "",
            "| B | n boards (owners) | xc A → B | + gained / − lost | p | B − A [95 % interval] | verdict |", "|---|---|---|---|---|---|---|"]
    for n in names:
        r = res[n]["xc"]
        d = "†" if r["placing"] else ""
        out.append(f"| {n} | {r['n']} ({r['owners']}) | {_f(r['share_a'])} → {_f(r['share_b'])}{d} | +{r['higher']} / −{r['lower']} | {_f(r['p'], 4)} | "
                   f"{_ci(r)} | {r['verdict']}{d} |")
    out += ["", "## 2. Quality on boards both methods finish (0 opens)", "",
            "Paired per board; lower is better in every row except the return rows (`return: cov_*`, share of signal track "
            "length over ground copper, higher is better; `return_board.py`). Track length and vias: median of the per-board ratio. Errors added: mean of the "
            "per-board count difference (most boards have none, so a ratio does not exist). Physics: ratio of the same module's value in the two "
            "layouts, both without open hops, by module kind, never the summed score; modules of one owner are resampled together. "
            "\"unfinished boards too\" repeats the physics rows on every board both scored, the module still closed in both.", ""]
    for n in names:
        q = res[n]["q"]
        out += [f"### {n} vs {control}", "", f"{q['n']} boards finished by both." + _placing_note(q), ""] + _quality_table(q) + [""]
    out += ["## 3. Reach", "",
            "Boards where the two methods' outcomes are identical (same opens, same DRC errors by type): the change did not touch them as far as the score sees.", "",
            "| B | boards both scored | not scored by one | identical opens and errors | share | of those, same track length and vias |", "|---|---|---|---|---|---|"]
    for n in names:
        r = res[n]["reach"]
        out.append(f"| {n} | {r['n']} | {r['unscored']} | {r['same']} | {_f(r['same'] / r['n'], 3) if r['n'] else '—'} | {r['same_copper']} |")
    out += ["", f"## 4. Verdicts against {control}", "", "| endpoint | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    out.append("| near-miss closure | " + " | ".join(f"{res[n]['near']['verdict']} (n {res[n]['near']['n']})" for n in names) + " |")
    out.append("| big-board opens | " + " | ".join(f"{res[n]['big']['verdict']} (n {res[n]['big']['n']})" for n in names) + " |")
    out.append("| clean net of input | " + " | ".join(f"{res[n]['xc']['verdict']}{'†' if res[n]['xc']['placing'] else ''} (n {res[n]['xc']['n']})" for n in names) + " |")
    out += _verdict_rows({n: res[n]["q"] for n in names})
    out.append("")
    H = by.get(human) or {}
    if H and human != control:
        out += [f"## 5. Against the human layout ({len(H)} boards have a human row)", "",
                "Same quality rows, B = the method, A = the human layout, on the boards both finish."]
        hres = {}
        for n in [control] + list(names):
            q = hres[n] = quality(H, by[n], modules, types, min_n, n_boot, return_path_of)
            notes = []
            if q["foreign_drc"]:
                notes.append(f"‡ on {q['foreign_drc']} of them the human row was scored by another DRC evaluator than the method's: "
                             "track length, vias and error counts are compared across scorer versions")
            if q["foreign_physics"]:
                notes.append(f"on {q['foreign_physics']} the two physics evaluations come from different evaluators and are not paired")
            out += ["", f"### {n} vs {human}", "", f"{q['n']} boards finished by both" + ("; " + "; ".join(notes) if notes else "") + "." + _placing_note(q), ""] + _quality_table(q)
        cols = [control] + list(names)
        out += ["", f"Verdicts against {human}:", "", "| endpoint | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        out += _verdict_rows(hres, "‡")
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------ command
def store_modules(store):
    """modules(row) reading `boards/<board>/runs/<run>/evals/<physics evaluator>.json` of a results.csv row."""
    def modules(r):
        if not r.get("evaluator_physics") or not r.get("run"):
            return None
        p = Path(store) / "boards" / r["board"] / "runs" / r["run"] / "evals" / f"{r['evaluator_physics']}.json"
        try:
            ph = json.loads(p.read_text()).get("physics") or {}
        except (OSError, ValueError):
            return None
        return None if ph.get("error") else ph.get("modules")
    return modules


def return_paths(store):
    """return_path_of(row): the stored output board of a results.csv row."""
    return lambda r: Path(store) / "boards" / r["board"] / "runs" / r["run"] / "output.kicad_pcb.gz"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kaeres quality", description=__doc__.split("\n\n")[0])
    ap.add_argument("name", help="experiment (its results.csv is read)")
    ap.add_argument("--control", required=True, help="the control method: its name, or a part of it only one method has")
    ap.add_argument("--method", action="append", help="method to compare (repeatable; default: every other method)")
    ap.add_argument("--no-human", action="store_true", help="leave out the section against the human layout")
    ap.add_argument("--csv", help="read this results.csv instead of the experiment's")
    ap.add_argument("--out", help="write the report here instead of printing it")
    ap.add_argument("--return-rows", action="store_true",
                    help="add the return-path rows (return_board.py; needs shapely; about 3 s per stored board)")
    a = ap.parse_args(argv)
    store = Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))
    src = Path(a.csv) if a.csv else store / "experiments" / a.name / "results.csv"
    if not src.exists():
        raise SystemExit(f"{src}: not found; write it with `kaeres exp report {a.name}`")
    rows = load_rows(src)
    names = list(dict.fromkeys(r["method"] for r in rows))
    control = pick(a.control, names)
    others = [pick(m, names) for m in a.method] if a.method else [n for n in names if n not in (control, HUMAN)]
    when = datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = report(rows, control, others, store_modules(store), title=a.name, source=f"`{src.name}` written {when}, {len(rows)} rows",
                  human=None if a.no_human else HUMAN, return_path_of=return_paths(store) if a.return_rows else None)
    if a.out:
        Path(a.out).write_text(text + "\n")
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
