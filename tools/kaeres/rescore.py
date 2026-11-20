#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Re-score every stored A/B on the two endpoints the experiment procedure decides on. Read-only on the store.

For each experiment with two or more methods, the first method is the control (A) and every other method is an arm
(B). Rows are paired on (board, attempt) where both runs have a valid DRC evaluation by the experiment's evaluator.

- Near-miss closure: pairs where one arm has 1-5 opens and the other 0, counted both ways (B closes, A closes), at
  pair level and at board level (a board counts for the side with more closures on it); exact two-sided sign test.
- Big-board opens: boards over 1,000 pads, per-board mean of log1p(opens B) - log1p(opens A), mean +- 1.96 se over
  boards. Pads come from the prepared task (`task.json`, the route input's pad count); a board without a task record
  falls back to "over 400 footprints" from the index. Other boards are reported separately.
- Identical pairs: opens, DRC errors, track length and vias all equal; their share and CPU-hours.
- Pooling: a fixed-effect (inverse-variance) mean over a named list of arms (`--pool FILE`), with Cochran's Q.

  rescore.py [--store DIR] [--since DATE] [--exp NAME ...] [--pool FILE] [--out DIR]

`--pool FILE` lines are `experiment<TAB>arm`, where arm is the method's exact name, a method-id prefix, or a substring
that names exactly one arm of that experiment; `#` starts a comment. `--out DIR` writes RESCORE.md and rescore.csv.
"""
import argparse
import csv
import json
import math
import os
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

NEAR_MAX = 5            # a near miss: 1..NEAR_MAX opens
BIG_PADS = 1000         # a big board: over this many pads
BIG_FOOTPRINTS = 400    # fallback when no prepared task gives pads
MAX_BOARDS = 1500       # experiments over this many boards are corpus sweeps, not A/Bs
MIN_RUNS = 20
MIN_PAIRS = 10


def default_store():
    return Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))


def signp(a, b):
    """Exact two-sided sign test p for a successes against b."""
    n = a + b
    if n == 0:
        return 1.0
    return min(1.0, sum(comb(n, i) for i in range(max(a, b), n + 1)) * 2 / 2 ** n)


def _task_pads(path):
    try:
        rec = json.loads(Path(path).read_text()).get("record") or {}
    except (OSError, ValueError):
        return None
    for v in (((rec.get("tasks") or {}).get("route") or {}).get("input_stats") or {},
              ((rec.get("reference") or {}).get("stats") or {})):
        if isinstance(v.get("pads"), (int, float)):
            return v["pads"]
    return None


class Sizes:
    """Pads per board from its prepared task (the runs' task when known), else footprints from the index."""

    def __init__(self, store, conn):
        self.store = Path(store)
        self.fp = {b: fp for b, fp in conn.execute("SELECT id, footprints FROM boards")}
        self.pads = {}
        self.source = Counter()

    def pads_of(self, board, task_ids=()):
        if board not in self.pads:
            tdir = self.store / "boards" / board / "tasks"
            p = None
            for t in task_ids:
                if t and p is None:
                    p = _task_pads(tdir / t / "task.json")
            if p is None and tdir.is_dir():
                for t in sorted(tdir.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
                    p = _task_pads(t / "task.json")
                    if p is not None:
                        break
            self.pads[board] = p
        return self.pads[board]

    def big(self, board, task_ids=()):
        p = self.pads_of(board, task_ids)
        if p is not None:
            self.source["task pads"] += 1
            return p > BIG_PADS
        self.source["footprints"] += 1
        return (self.fp.get(board) or 0) > BIG_FOOTPRINTS


def connect(store):
    return sqlite3.connect(f"file:{Path(store) / 'index.sqlite'}?mode=ro", uri=True)


def load(store, conn, since="2026-11-01", only=None, max_boards=MAX_BOARDS, min_runs=MIN_RUNS):
    """experiment -> dict(created, mids, names, data[method][board][attempt] = row)."""
    out = {}
    root = Path(store) / "experiments"
    for exp in sorted(os.listdir(root)) if root.is_dir() else []:
        if only and exp not in only:
            continue
        if not only and "smoke" in exp:
            continue
        try:
            ej = json.loads((root / exp / "experiment.json").read_text())
        except (OSError, ValueError):
            continue
        mids = [m["id"] for m in ej.get("methods") or []]
        if len(mids) < 2 or (since and (ej.get("created") or "") < since):
            continue
        try:
            boards = set((root / exp / "boards.txt").read_text().split())
        except OSError:
            boards = None
        if boards is not None and len(boards) > max_boards:
            continue
        drc = (ej.get("evaluators") or {}).get("drc")
        natt = ej.get("attempts") or 99
        data = {m: defaultdict(dict) for m in mids}
        q = ("SELECT r.board, r.run, r.method_id, r.attempt, r.cpu_s, r.path, r.task_id, e.unconnected, e.errors, e.valid, e.json "
             "FROM runs r JOIN evals e ON e.board = r.board AND e.run = r.run "
             f"WHERE r.method_id IN ({','.join('?' * len(mids))}) AND e.evaluator = ?")
        n = 0
        for b, run, m, a, cpu, path, task, u, er, va, js in conn.execute(q, mids + [drc]):
            if (boards is not None and b not in boards) or a is None or a >= natt:
                continue
            row = dict(run=run, cpu=cpu, path=path, task=task, u=u, err=er, valid=va)
            try:
                s = json.loads(js)["score"]
                row.update(len=s.get("track_length_mm"), vias=s.get("vias"))
            except (TypeError, ValueError, KeyError):
                pass
            data[m][b][a] = row
            n += 1
        if n < min_runs:
            continue
        out[exp] = dict(created=ej.get("created") or "", mids=mids, names={m["id"]: m["name"] for m in ej["methods"]},
                        data={m: dict(d) for m, d in data.items()})
    return out


def identical(ra, rb):
    return all(ra.get(k) == rb.get(k) for k in ("u", "err", "len", "vias"))


def score(x, B, sizes, boardset=None):
    """One arm B against the experiment's control: the counts and per-board differences."""
    A = x["mids"][0]
    r = dict(pairs=0, nearA=0, nm_b=0, nm_a=0, ident=0, cpu_ident=0.0, cpu_all=0.0, big={}, mid={})
    per_board = Counter()
    pbi = defaultdict(list)
    for b, at in x["data"][A].items():
        if boardset is not None and b not in boardset:
            continue
        ds = []
        tasks = set()
        for s, ra in at.items():
            rb = x["data"][B].get(b, {}).get(s)
            if rb is None or ra.get("u") is None or rb.get("u") is None or not ra.get("valid") or not rb.get("valid"):
                continue
            r["pairs"] += 1
            ua, ub = ra["u"], rb["u"]
            r["nearA"] += 1 <= ua <= NEAR_MAX
            if 1 <= ua <= NEAR_MAX and ub == 0:
                r["nm_b"] += 1
                per_board[b] += 1
            if 1 <= ub <= NEAR_MAX and ua == 0:
                r["nm_a"] += 1
                per_board[b] -= 1
            same = identical(ra, rb)
            r["ident"] += same
            pbi[b].append((s, same))
            cc = ((ra.get("cpu") or 0) + (rb.get("cpu") or 0)) / 3600
            r["cpu_all"] += cc
            r["cpu_ident"] += cc * same
            ds.append(math.log1p(ub) - math.log1p(ua))
            tasks.update((ra.get("task"), rb.get("task")))
        if ds:
            (r["big"] if sizes.big(b, sorted(t for t in tasks if t)) else r["mid"])[b] = st.mean(ds)
    r["bb"] = sum(v > 0 for v in per_board.values())
    r["ba"] = sum(v < 0 for v in per_board.values())
    r["pbi"] = dict(pbi)
    return r


def mean_se(d):
    """(mean, se, n) over per-board differences, or None under three boards."""
    v = list(d.values())
    if len(v) < 3:
        return None
    return st.mean(v), st.stdev(v) / math.sqrt(len(v)), len(v)


def rows_of(exps, sizes, min_pairs=MIN_PAIRS):
    rows = []
    for exp, x in sorted(exps.items(), key=lambda kv: kv[1]["created"]):
        for B in x["mids"][1:]:
            r = score(x, B, sizes)
            if r["pairs"] < min_pairs:
                continue
            r.update(exp=exp, arm=x["names"][B], method_id=B, control=x["names"][x["mids"][0]], created=x["created"][:10])
            rows.append(r)
    return rows


def pool(rows):
    """Pooled endpoints over arms: sign tests on summed counts, fixed-effect mean with Q per board class."""
    out = dict(arms=len(rows))
    for k in ("nm_b", "nm_a", "bb", "ba", "nearA", "pairs", "ident"):
        out[k] = sum(r[k] for r in rows)
    out["p_pair"] = signp(out["nm_b"], out["nm_a"])
    out["p_board"] = signp(out["bb"], out["ba"])
    for key in ("big", "mid"):
        t = [mean_se(r[key]) for r in rows]
        t = [x for x in t if x and x[1] > 0]
        if not t:
            out[key] = None
            continue
        w = [1 / x[1] ** 2 for x in t]
        m = sum(wi * x[0] for wi, x in zip(w, t)) / sum(w)
        se = 1 / math.sqrt(sum(w))
        q = sum(wi * (x[0] - m) ** 2 for wi, x in zip(w, t))
        out[key] = dict(arms=len(t), mean=m, se=se, lo=m - 1.96 * se, hi=m + 1.96 * se, Q=q, df=len(t) - 1,
                        median_boards=st.median(x[2] for x in t), median_mde=st.median(2.8 * x[1] for x in t))
    return out


def read_pool_list(path):
    sel = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        exp, _, arm = line.partition("\t")
        if not arm:
            raise SystemExit(f"{path}: expected 'experiment<TAB>arm': {line!r}")
        sel.append((exp.strip(), arm.strip()))
    return sel


def pick(rows, exp, arm):
    """The one row naming `arm` in `exp`: exact name, then method-id prefix, then a unique substring."""
    cand = [r for r in rows if r["exp"] == exp]
    for test in (lambda r: r["arm"] == arm, lambda r: r["method_id"].startswith(arm), lambda r: arm in r["arm"]):
        m = [r for r in cand if test(r)]
        if m:
            return m[0] if len(m) == 1 else m
    return None


def select(rows, sel):
    got, problems = [], []
    for exp, arm in sel:
        m = pick(rows, exp, arm)
        if isinstance(m, dict):
            got.append(m)
        else:
            problems.append(f"{exp}\t{arm}: " + ("no arm" if not m else "ambiguous: " + "; ".join(r["arm"] for r in m)))
    return got, problems


def _pct(t):
    return f"{t[0] * 100:+.1f}% ± {1.96 * t[1] * 100:.1f} (n {t[2]})" if t else "-"


def csv_rows(rows):
    for r in rows:
        bg, md = mean_se(r["big"]), mean_se(r["mid"])
        yield dict(experiment=r["exp"], created=r["created"], control=r["control"], arm=r["arm"], method_id=r["method_id"],
                   pairs=r["pairs"], control_near=r["nearA"], b_closes=r["nm_b"], a_closes=r["nm_a"],
                   b_boards=r["bb"], a_boards=r["ba"], p_pair=round(signp(r["nm_b"], r["nm_a"]), 4), p_board=round(signp(r["bb"], r["ba"]), 4),
                   big_n=bg[2] if bg else len(r["big"]), big_dlog1p=round(bg[0], 5) if bg else "", big_se=round(bg[1], 5) if bg else "",
                   other_n=md[2] if md else len(r["mid"]), other_dlog1p=round(md[0], 5) if md else "", other_se=round(md[1], 5) if md else "",
                   identical=r["ident"], identical_share=round(r["ident"] / r["pairs"], 4),
                   cpu_h=round(r["cpu_all"], 2), cpu_h_identical=round(r["cpu_ident"], 2))


def pool_text(p, label):
    s = (f"**{label}**: {p['arms']} arms; near-miss closures by B {p['nm_b']} vs by A {p['nm_a']} pair-level (sign p {p['p_pair']:.3f}); "
         f"board-level {p['bb']} vs {p['ba']} (p {p['p_board']:.3f}); control near-miss pairs {p['nearA']}")
    for key, nm in (("big", "big boards"), ("mid", "other boards")):
        v = p.get(key)
        if v:
            s += (f"; {nm}: {v['arms']} arms, fixed effect {v['mean'] * 100:+.1f}% [{v['lo'] * 100:+.1f}, {v['hi'] * 100:+.1f}], "
                  f"Q {v['Q']:.1f} on {v['df']} df, median boards/arm {v['median_boards']}, median per-arm MDE {v['median_mde'] * 100:.0f}%")
    return s


def markdown(rows, pools, sizes, problems=()):
    L = ["# Re-score of stored A/Bs", "",
         f"Near miss: {1}-{NEAR_MAX} opens in one arm, 0 in the other, same board and seed. Big boards: over {BIG_PADS} pads "
         f"(prepared task; else over {BIG_FOOTPRINTS} footprints). dlog1p: per-board mean of log1p(opens B) - log1p(opens A), "
         "mean ± 1.96 se over boards (negative: B leaves fewer opens). Identical: opens, errors, track length and vias equal.",
         f"Board size from: {dict(sizes.source)}.", "",
         "| experiment | arm | pairs | A near | B closes / A closes | boards B/A | p | big boards | other boards | identical |",
         "|---|---|---:|---:|---:|---:|---:|---|---|---:|"]
    for r in rows:
        L.append(f"| {r['exp']} | {r['arm']} | {r['pairs']} | {r['nearA']} | {r['nm_b']} / {r['nm_a']} | {r['bb']} / {r['ba']} | "
                 f"{signp(r['nm_b'], r['nm_a']):.2f} | {_pct(mean_se(r['big']))} | {_pct(mean_se(r['mid']))} | "
                 f"{r['ident'] / r['pairs'] * 100:.0f}% |")
    if pools:
        L += ["", "## Pooled", ""] + [pool_text(p, label) + "\n" for label, p in pools]
    if problems:
        L += ["", "## Pool list entries not found", ""] + [f"- {x}" for x in problems]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", type=Path, default=default_store())
    ap.add_argument("--since", default="2026-11-01", help="experiments created on or after (ISO date); '' for all")
    ap.add_argument("--exp", nargs="*", help="only these experiments")
    ap.add_argument("--pool", type=Path, help="named arms to pool (experiment<TAB>arm per line)")
    ap.add_argument("--out", type=Path, help="write RESCORE.md and rescore.csv here")
    a = ap.parse_args(argv)
    conn = connect(a.store)
    sizes = Sizes(a.store, conn)
    rows = rows_of(load(a.store, conn, since=a.since, only=set(a.exp or ())), sizes)
    pools, problems = [], []
    if a.pool:
        sel, problems = select(rows, read_pool_list(a.pool))
        pools.append((f"named arms ({a.pool.name})", pool(sel)))
    pools.append(("every arm vs its control", pool(rows)))
    md = markdown(rows, pools, sizes, problems)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "RESCORE.md").write_text(md)
        with open(a.out / "rescore.csv", "w", newline="") as f:
            cr = list(csv_rows(rows))
            w = csv.DictWriter(f, fieldnames=list(cr[0]) if cr else ["experiment"])
            w.writeheader()
            w.writerows(cr)
    sys.stdout.write(md)
    for p in problems:
        print("pool list:", p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
