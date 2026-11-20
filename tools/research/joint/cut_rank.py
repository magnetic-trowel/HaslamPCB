# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline rank test: does cut overflow (kae.place.cutflow), read from the placement alone, order a board's
placements the way KiCad's opens after routing do?

For an experiment whose arms share one routing recipe, every stored output board is re-measured from its
placement only (pads, layers, outline, rules; copper is not read). Per measure (ovfK primary; ovf0, hpwl, rudy,
crowd as same-data controls) the report gives, over boards with >= 4 distinct placements and non-constant opens:
the median and mean within-board Spearman correlation with `evals.unconnected`, a board-bootstrap 95 % interval,
the pooled pairwise concordance, and the same split by pad-count band and by 2 layers vs more. Placements with
identical measures count as one (their opens averaged); the opens SD inside such duplicate groups is the
routing-noise floor. References from the project docs: RUDY 0.13, a 60 s route 0.53; decision line 0.3.

Read-only on the results store ($KAE_RESULTS, layout in tools/kaeres/README.md). Rules: the Default net class of a
prepared task's project file under $KAE_TASK_CACHE/<board>.*/ when present, else the board file's (loader).

Usage:
  python tools/research/joint/cut_rank.py EXPERIMENT OUTDIR [--jobs N] [--max-pads 1500] [--seed 0]
  python tools/research/joint/cut_rank.py --report OUTDIR/EXPERIMENT.jsonl [--out REPORT.md]
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import glob
import gzip
import json
import os
import random
import sqlite3
import statistics
import sys
import tempfile
import time

import numpy as np

BASE_MEASURES = ["ovfK", "ovf0", "hpwl", "rudy", "crowd"]
MEASURES = list(BASE_MEASURES)   # analyse() adds EDGE when the measure file has them
EDGE = ["ovfK_edge", "ovf0_edge"]   # model='edge' (true pad edge distances + body corners), when measured
PRIMARY = "ovfK"
BANDS = [(0, 150, "<=150"), (150, 400, "150-400"), (400, 1500, "400-1500"), (1500, 10 ** 9, ">1500")]
REFERENCE = "RUDY 0.13, a 60 s route 0.53; decision line 0.3"
DECISION = 0.3


def results_root():
    root = os.environ.get("KAE_RESULTS")
    if not root:
        sys.exit("cut_rank: set KAE_RESULTS to the results store (tools/kaeres/README.md)")
    return root


def rules_of(board_id, bd):
    """(clearance, track width, source): a prepared task's project file, else the loaded board's Default class."""
    cache = os.environ.get("KAE_TASK_CACHE")
    if cache:
        for d in sorted(glob.glob(f"{cache}/{board_id}.*")):
            for sub in ("place-fixed/input", "route/input", "reference"):
                p = f"{d}/{sub}/board.kicad_pro"
                if os.path.exists(p):
                    try:
                        with open(p) as f:
                            cl = json.load(f)["net_settings"]["classes"][0]
                        return float(cl["clearance"]), float(cl["track_width"]), "project"
                    except (KeyError, IndexError, ValueError, TypeError):
                        pass
    from kae.place.cutflow import default_rules
    c, w = default_rules(bd)
    return c, w, "loader"


def stored_runs(root, experiment):
    db = sqlite3.connect(f"file:{root}/index.sqlite?mode=ro", uri=True)
    q = db.execute("select r.board, r.run, r.path, r.attempt, r.method_id, e.unconnected, e.errors, b.footprints, "
                   "b.layers from runs r join evals e on e.board = r.board and e.run = r.run "
                   "join boards b on b.id = r.board where r.experiment like ? and r.status = 'ok' "
                   "and e.unconnected is not null", (experiment + "%",))
    by = collections.defaultdict(dict)
    for b, run, path, att, mid, unc, err, nfp, lay in q:
        by[b][run] = dict(board=b, run=run, path=path, attempt=att, method=mid, opens=unc, errors=err, fps=nfp,
                          layers=lay)
    return by


def measure_board(item):
    """All stored placements of one board -> rows (one per placement); errors as rows with 'error'."""
    board, runs, max_pads, seed, edge = item
    from kae.board.kicad_file import load
    from kae.place import cutflow
    rows, rule = [], None
    with tempfile.TemporaryDirectory() as td:
        for run, r in sorted(runs.items()):
            f = os.path.join(r["path"], "output.kicad_pcb.gz")
            if not os.path.exists(f):
                continue
            row = {k: v for k, v in r.items() if k != "path"}
            try:
                t1 = time.time()
                with gzip.open(f, "rb") as g, open(td + "/b.kicad_pcb", "wb") as h:
                    h.write(g.read())
                bd = load(td + "/b.kicad_pcb", rules=True)
                if sum(len(fp.pads) for fp in bd.footprints) > max_pads:
                    return [dict(board=board, skipped="max-pads")]
                if rule is None:
                    rule = rules_of(board, bd)
                m = cutflow.measure(bd, rule[0], rule[1], seed=seed)
                if m is None:
                    continue
                if edge:
                    me = cutflow.measure(bd, rule[0], rule[1], seed=seed, model="edge")
                    if me is not None:
                        m.update(ovfK_edge=me["ovfK"], ovf0_edge=me["ovf0"])
                row.update(m, rules=rule[2], secs=round(time.time() - t1, 2))
            except Exception as e:   # noqa: BLE001 - one bad board must not stop the sweep; recorded in the row
                row["error"] = repr(e)[:200]
            rows.append(row)
    return rows


def run_measure(a):
    root = results_root()
    by = stored_runs(root, a.experiment)
    boards = [b for b in sorted(by) if len(by[b]) >= 4 and len({r["opens"] for r in by[b].values()}) >= 2]
    os.makedirs(a.outdir, exist_ok=True)
    out = os.path.join(a.outdir, f"{a.experiment}.jsonl")
    done = set()
    if os.path.exists(out):
        with open(out) as f:
            done = {json.loads(ln)["board"] for ln in f if ln.strip()}
    todo = [(b, by[b], a.max_pads, a.seed, not a.no_edge) for b in boards if b not in done]
    print(f"{len(boards)} boards with >= 4 placements and differing opens; {len(todo)} to measure", flush=True)
    t0 = time.time()
    with open(out, "a") as fo, cf.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for i, rows in enumerate(ex.map(measure_board, todo, chunksize=1)):
            for row in rows:
                fo.write(json.dumps(row) + "\n")
            fo.flush()
            print(i, rows[0]["board"] if rows else "-", round(time.time() - t0), flush=True)
    return out


# ---------------------------------------------------------------- statistics

def spearman(x, y):
    from scipy.stats import spearmanr
    if len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return float(spearmanr(x, y).statistic)


def partial_spearman(x, y, z):
    """Spearman correlation of x and y with z partialled out (on ranks); None when undefined."""
    from scipy.stats import rankdata
    if min(len(set(x)), len(set(y)), len(set(z))) < 2 or len(x) < 4:
        return None
    rx, ry, rz = (rankdata(v) for v in (x, y, z))
    def resid(a):
        A = np.column_stack([np.ones(len(rz)), rz])
        return a - A @ np.linalg.lstsq(A, a, rcond=None)[0]
    ex, ey = resid(rx), resid(ry)
    den = float(np.sqrt((ex @ ex) * (ey @ ey)))
    return float(ex @ ey / den) if den > 1e-12 else None


def dedupe(rows):
    """Placements with identical measures -> one (opens averaged). Returns (placements, duplicate opens SDs)."""
    groups = collections.defaultdict(list)
    for r in rows:
        key = tuple(round(float(r[m]), 6) for m in MEASURES) + (r.get("npad"),)
        groups[key].append(r)
    out, sds = [], []
    for g in groups.values():
        opens = [r["opens"] for r in g]
        if len(g) > 1:
            sds.append(statistics.stdev(opens))
        p = dict(g[0], opens=sum(opens) / len(opens), dup=len(g))
        out.append(p)
    return out, sds


def concordance(placements, m):
    """(concordant, discordant, ties-in-measure) over pairs with differing opens."""
    c = d = t = 0
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            a, b = placements[i], placements[j]
            do = a["opens"] - b["opens"]
            if do == 0:
                continue
            dm = a[m] - b[m]
            if dm == 0:
                t += 1
            elif (dm > 0) == (do > 0):
                c += 1
            else:
                d += 1
    return c, d, t


def summarize(boards, m, rng, nboot=2000):
    rhos = [b["rho"][m] for b in boards if b["rho"].get(m) is not None]
    if not rhos:
        return dict(n=0)
    arr = np.array(rhos)
    idx = np.array([rng.integers(0, len(arr), len(arr)) for _ in range(nboot)])
    meds = np.median(arr[idx], axis=1)
    means = arr[idx].mean(axis=1)
    c = d = t = 0
    for b in boards:
        cc, dd, tt = b["conc"][m]
        c, d, t = c + cc, d + dd, t + tt
    zero = [b["rho"][m] if b["rho"].get(m) is not None else 0.0 for b in boards]
    return dict(n=len(rhos), n_all=len(zero), median_all=float(np.median(zero)), median=float(np.median(arr)),
                mean=float(arr.mean()),
                median_ci=[float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))],
                mean_ci=[float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
                concordance=(c + 0.5 * t) / (c + d + t) if c + d + t else None, pairs=c + d + t)


def analyse(path, seed=0):
    global MEASURES
    with open(path) as f:
        rows = [json.loads(ln) for ln in f if ln.strip()]
    ok = [r for r in rows if "error" not in r and "skipped" not in r]
    b = BASE_MEASURES
    MEASURES = b[:1] + EDGE[:1] + b[1:2] + EDGE[1:] + b[2:] if ok and all(m in r for r in ok for m in EDGE) else list(b)
    by = collections.defaultdict(list)
    errors = skipped = 0
    with open(path) as f:
        for ln in f:
            r = json.loads(ln)
            if "error" in r:
                errors += 1
            elif "skipped" in r:
                skipped += 1
            elif all(m in r for m in MEASURES):
                by[r["board"]].append(r)
    boards, sds, nplace, ndup = [], [], 0, 0
    for b, rows in sorted(by.items()):
        pl, s = dedupe(rows)
        sds += s
        nplace += len(rows)
        ndup += len(rows) - len(pl)
        if len(pl) < 4 or len({p["opens"] for p in pl}) < 2:
            continue
        opens = [p["opens"] for p in pl]
        boards.append(dict(board=b, npad=pl[0]["npad"], layers=pl[0].get("layers") or pl[0].get("nsig"),
                           n=len(pl), rho={m: spearman([p[m] for p in pl], opens) for m in MEASURES},
                           partial={PRIMARY + "|hpwl": partial_spearman([p[PRIMARY] for p in pl], opens,
                                                                         [p["hpwl"] for p in pl])},
                           conc={m: concordance(pl, m) for m in MEASURES}))
    res = dict(source=os.path.basename(path), placements=nplace, merged_duplicates=ndup, errors=errors,
               skipped_big=skipped, boards=len(boards),
               noise=dict(groups=len(sds), median_sd=float(np.median(sds)) if sds else None,
                          rms_sd=float(np.sqrt(np.mean(np.square(sds)))) if sds else None))
    rng = np.random.default_rng(seed)
    res["all"] = {m: summarize(boards, m, rng) for m in MEASURES}
    res["band"] = {}
    for lo, hi, name in BANDS:
        sub = [b for b in boards if lo < b["npad"] <= hi] if lo else [b for b in boards if b["npad"] <= hi]
        if sub:
            res["band"][name] = {m: summarize(sub, m, rng) for m in MEASURES}
    res["layers"] = {}
    for name, pred in (("2 layers", lambda b: (b["layers"] or 2) <= 2), ("4+ layers", lambda b: (b["layers"] or 2) > 2)):
        sub = [b for b in boards if pred(b)]
        if sub:
            res["layers"][name] = {m: summarize(sub, m, rng) for m in MEASURES}
    part = [b["partial"][PRIMARY + "|hpwl"] for b in boards if b["partial"][PRIMARY + "|hpwl"] is not None]
    if part:
        arr = np.array(part)
        meds = np.median(arr[rng.integers(0, len(arr), (2000, len(arr)))], axis=1)
        res["partial"] = dict(measure=PRIMARY + "|hpwl", n=len(part), median=float(np.median(arr)),
                              median_ci=[float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))])
    res["per_board"] = [dict(board=b["board"], npad=b["npad"], layers=b["layers"], n=b["n"], rho=b["rho"])
                        for b in boards]
    return res


def _f(x, nd=2):
    return "-" if x is None else f"{x:.{nd}f}"


def _table(block):
    lines = ["| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |",
             "|---|---|---|---|---|---|"]
    for m in MEASURES:
        s = block.get(m, {})
        if not s.get("n"):
            lines.append(f"| {m} | 0 | - | - | - | - |")
            continue
        lines.append(f"| {m} | {s['n']} | {_f(s['median'])} [{_f(s['median_ci'][0])}, {_f(s['median_ci'][1])}] | "
                     f"{_f(s['mean'])} [{_f(s['mean_ci'][0])}, {_f(s['mean_ci'][1])}] | {_f(s['concordance'])} | "
                     f"{_f(s['median_all'])} |")
    return lines


def report_md(res, experiment):
    p = res["all"].get(PRIMARY, {})
    lines = [f"# Cut-overflow rank test: {experiment}", "",
             f"Placements measured: {res['placements']} ({res['merged_duplicates']} merged as duplicates), "
             f"errors {res['errors']}, boards over the pad limit {res['skipped_big']}. "
             f"Boards with >= 4 distinct placements and non-constant opens: {res['boards']}.", "",
             f"Within-board Spearman correlation of each measure with KiCad opens (higher measure, more opens: "
             f"positive is right). References: {REFERENCE}. A board where a measure is constant has no rho for it and "
             f"is left out of that measure's n; the last column counts such boards as 0.", ""]
    if p.get("n"):
        verdict = "above" if p["median_ci"][0] > DECISION else ("below" if p["median_ci"][1] < DECISION else
                                                               "not separable from")
        lines += [f"**{PRIMARY}: median {_f(p['median'])} [{_f(p['median_ci'][0])}, {_f(p['median_ci'][1])}] over "
                  f"{p['n']} boards: {verdict} the {DECISION} decision line.**", ""]
    nz = res["noise"]
    pc = res.get("partial")
    if pc:
        lines += [f"Partial within-board Spearman of {PRIMARY} with opens given HPWL: median {_f(pc['median'])} "
                  f"[{_f(pc['median_ci'][0])}, {_f(pc['median_ci'][1])}] over {pc['n']} boards (plan threshold "
                  f"0.15 with an interval excluding 0).", ""]
    lines += [f"Routing-noise floor: opens SD inside {nz['groups']} groups of identical placements: median "
              f"{_f(nz['median_sd'])}, RMS {_f(nz['rms_sd'])}.", "", "## All boards", ""] + _table(res["all"])
    for name, block in res["band"].items():
        lines += ["", f"## Pads {name}", ""] + _table(block)
    for name, block in res["layers"].items():
        lines += ["", f"## {name}", ""] + _table(block)
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("experiment", nargs="?")
    ap.add_argument("outdir", nargs="?")
    ap.add_argument("--report", metavar="JSONL", help="only write the report for an existing measure file")
    ap.add_argument("--out", help="report path (default: next to the JSONL, .md)")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--max-pads", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-edge", action="store_true", help="skip the 'edge' model variant")
    a = ap.parse_args(argv)
    if a.report:
        path = a.report
        experiment = os.path.basename(path).rsplit(".", 1)[0]
    else:
        if not (a.experiment and a.outdir):
            ap.error("EXPERIMENT and OUTDIR are required unless --report is given")
        random.seed(a.seed)
        path = run_measure(a)
        experiment = a.experiment
    res = analyse(path, seed=a.seed)
    base = a.out or path.rsplit(".", 1)[0] + ".md"
    with open(base, "w") as f:
        f.write(report_md(res, experiment))
    with open(base.rsplit(".", 1)[0] + ".summary.json", "w") as f:
        json.dump(res, f, indent=1)
    p = res["all"].get(PRIMARY, {})
    print(f"{experiment}: {res['boards']} boards; {PRIMARY} median rho {_f(p.get('median'))}; report {base}")


if __name__ == "__main__":
    main()
