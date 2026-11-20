#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""suites: the board suites of the experiment tiers, built from the results index and the board tags.

  python3 tools/kaeres/suites.py --tags DIR [--index FILE] [--corpus DIR] [--out bench/suites] [--seed N] [--dry-run]

Writes four id lists (docs/topics/verification/experiment-tiers.md) and prints their summary table:
  sprint-frontier  cheap boards that responded in past two-arm A/Bs, plus a random fifth
  sprint-quality   small human-clean boards with a converter, rich decoupling or a crystal
  ladder           human-clean boards stratified by footprints and layers
  canary           the big boards: merit boards over 1,000 pads, human-clean boards over 400 footprints

  python3 tools/kaeres/suites.py --tags DIR --freeze control-w47     # after the tag's control has run
drops from the two sprint lists the boards that failed to prepare or run under a control arm, writes
sprint-manifest.csv (per board: owner, size, mechanism tags, each control arm's open connections, clean and CPU-h
per seed) and prints how many boards are inert between seeds and how many each arm leaves open.

Inputs, all read-only:
  --index   kaeres' index.sqlite (default $KAE_RESULTS/index.sqlite): runs, their CPU and their scores
  --tags    the board-tag folder: suites/<tag>.txt, structural/usability.jsonl, structural/features.jsonl
  --corpus  the board corpus (default $KAE_CORPUS): manifest.jsonl gives footprints, layers and the owner
  --merit   the merit board list (default bench/suites/merit-213.txt)
The same inputs and seed give the same lists. A board's owner is the account of its repository (host and
first path part of the manifest's `repo`): one board per owner, so that boards are independent.
"""
import argparse
import csv
import json
import math
import os
import random
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
SEED = 20261120
SWEEP_BOARDS = 1500          # an experiment over more boards is a corpus sweep: not in the history
AB_BOARDS = (15, SWEEP_BOARDS)  # board count of the two-arm experiments response is read from
MIN_PAIRS = 3                # two-arm pairs a board needs before its response share means anything
MIN_RESPONSE = 1 / 3         # share of pairs whose open connections differ, to count as responding
COST_FLOOR_H = 0.02          # CPU-h per run below this ranks alike (else the tiniest boards lead)
SPRINT_BOARD_CPU_H = 0.5     # the sprint tier's cap on a board's history, CPU-h per method-run
FRONTIER_FOOTPRINTS = 400
QUALITY_TAGS = ("pw_dcdc", "pw_cell_buck", "dec_rich", "an_crystal")
QUALITY_FOOTPRINTS = (15, 150)
LADDER_BANDS = ((5, 20), (21, 50), (51, 100), (101, 150), (151, 250), (251, 400))  # footprints
CANARY_PADS, CANARY_FOOTPRINTS = 1000, 400
HISTORY_BANDS = (20, 50, 100, 150, 200, 400)  # footprint band edges for boards without history
PLACING = ("place", "place-fixed", "joint", "joint-fixed")
SIZES = dict(frontier=60, quality=80, ladder=300)
SPRINT = ("sprint-frontier", "sprint-quality")
MECHANISM_TAGS = QUALITY_TAGS + ("bga", "qfn_dfn_leadless", "diffpair_nets", "parallel_bus", "power_pours", "inner_planes", "rf_any")
ARMS = {"route": "bridge"}   # a control method's kind -> its arm's name; every placing kind is "staged"


# ------------------------------------------------------------------ the results index
def open_index(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


_RUNS = ("FROM runs r LEFT JOIN methods m ON m.id = r.method_id "
         "WHERE COALESCE(r.experiment, '') != '' AND COALESCE(m.runner, '') != 'reference' ")


def history(c):
    """board -> mean CPU-h per method-run in the index: every run with a recorded CPU time that an
    experiment asked for, the human reference and corpus sweeps (over SWEEP_BOARDS boards) left out."""
    size = dict(c.execute("SELECT experiment, COUNT(DISTINCT board) FROM runs GROUP BY 1"))
    tot = defaultdict(lambda: [0.0, 0])
    for b, e, cpu in c.execute(f"SELECT r.board, r.experiment, r.cpu_s {_RUNS} AND r.cpu_s > 0 ORDER BY r.board, r.run"):
        if size[e] <= SWEEP_BOARDS:
            tot[b][0] += cpu
            tot[b][1] += 1
    return {b: s / n / 3600 for b, (s, n) in tot.items()}


def estimator(hist, footprints):
    """est(board) -> (CPU-h per method-run, from its own history?). A board without history gets the
    mean history of the boards in its footprint band (`footprints`: board -> count), else of all."""
    def band(b):
        fp = footprints.get(b) or 0
        return sum(fp > edge for edge in HISTORY_BANDS)
    groups = defaultdict(list)
    for b, h in sorted(hist.items()):
        groups[band(b)].append(h)
    means = {k: statistics.fmean(v) for k, v in groups.items()}
    overall = statistics.fmean(hist.values()) if hist else 0.0

    def est(b):
        return (hist[b], True) if b in hist else (means.get(band(b), overall), False)
    return est


def response(c):
    """board -> dict(pairs, resp, flip) from past two-arm experiments (A/Bs over AB_BOARDS boards):
    a pair is one board and attempt that both arms scored; resp is the share of pairs whose open
    connections differ, flip the share where exactly one arm is clean. Boards under MIN_PAIRS left out."""
    score = {}
    for b, run, unconnected, clean in c.execute("SELECT board, run, unconnected, clean FROM evals "
                                                "WHERE unconnected IS NOT NULL ORDER BY board, run, evaluator"):
        score[(b, run)] = (unconnected, bool(clean))
    cells = defaultdict(lambda: defaultdict(dict))
    for b, run, mid, attempt, exp in c.execute(f"SELECT r.board, r.run, r.method_id, r.attempt, r.experiment {_RUNS}"):
        if (b, run) in score:
            cells[exp][(b, attempt)][mid] = score[(b, run)]
    out = defaultdict(lambda: [0, 0, 0])
    for cs in cells.values():
        arms = {m for ms in cs.values() for m in ms}
        if len(arms) != 2 or not AB_BOARDS[0] <= len({b for b, _ in cs}) <= AB_BOARDS[1]:
            continue
        for (b, _), ms in cs.items():
            if len(ms) == 2:
                x, y = ms.values()
                o = out[b]
                o[0] += 1
                o[1] += x[0] != y[0]
                o[2] += x[1] != y[1]
    return {b: dict(pairs=p, resp=d / p, flip=f / p) for b, (p, d, f) in out.items() if p >= MIN_PAIRS}


def placed(c):
    """Boards a placing method has run on without failing: usable as a place task."""
    q = ",".join("?" * len(PLACING))
    return {b for b, in c.execute("SELECT DISTINCT r.board FROM runs r JOIN methods m ON m.id = r.method_id "
                                  f"WHERE m.kind IN ({q}) AND r.status = 'ok'", PLACING)}


# ------------------------------------------------------------------ corpus and tags
def owner_of(repo):
    """The account a repository belongs to: host and first path part, lower case."""
    u = urlparse(repo if "//" in repo else "//" + repo)
    return f"{u.netloc}/{u.path.strip('/').split('/')[0]}".lower()


def read_ids(path):
    return [w for line in Path(path).read_text().splitlines() for w in line.split("#")[0].split()]


def jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def pads_of(features, ids):
    """n_pads of the boards `ids` from the tag folder's features.jsonl."""
    out = {}
    with open(features) as f:
        for line in f:
            r = json.loads(line)
            if r.get("id") in ids:
                out[r["id"]] = r.get("n_pads") or 0
    return out


class Inputs:
    """What the suites are built from; tests fill the fields directly."""

    def __init__(self, index, tags, corpus, merit):
        tags = Path(tags)
        c = open_index(index)
        self.hist, self.resp, self.placed = history(c), response(c), placed(c)
        c.close()
        rows = jsonl(Path(corpus) / "manifest.jsonl")
        self.footprints = {r["id"]: r.get("footprints") or 0 for r in rows}
        self.layers = {r["id"]: r.get("layers") or 0 for r in rows}
        self.owner = {r["id"]: owner_of(r.get("repo") or r["id"]) for r in rows}
        use = next(p for p in (tags / "usability.jsonl", tags / "structural" / "usability.jsonl") if p.exists())
        use = [r for r in jsonl(use) if r["id"] in self.owner]
        self.routable = {r["id"] for r in use if r.get("usable_route_test")}
        self.tag = {t: set(read_ids(tags / "suites" / f"{t}.txt")) for t in QUALITY_TAGS}
        # human-clean: the human layout has no DRC error (tag) and the prepared task confirms it clean and complete
        self.human_clean = (set(read_ids(tags / "suites" / "human_drc_errors.clean.txt")) & self.routable
                            & {r["id"] for r in use if r.get("usable_with_reference")})
        self.merit = [b for b in read_ids(merit) if b in self.owner]
        self.pads = pads_of(tags / "structural" / "features.jsonl", set(self.merit))


# ------------------------------------------------------------------ the four suites
def round_robin(pool, cells, cells_of, n, owners, owner):
    """Up to n boards from `pool` (in its order), one per owner, taking one board per cell in turn so
    that the cells fill evenly and a cell that runs out leaves its share to the others. `owners` is
    updated with the owners taken."""
    queues = {cell: [b for b in pool if cell in cells_of(b)] for cell in cells}
    out, taken = [], set()
    while len(out) < n and any(queues.values()):
        for cell in cells:
            q = queues[cell]
            while q and (q[0] in taken or owner[q[0]] in owners):
                q.pop(0)
            if q and len(out) < n:
                b = q.pop(0)
                out.append(b)
                taken.add(b)
                owners.add(owner[b])
    return out


def frontier(inp, n, rng, max_cpu_h=SPRINT_BOARD_CPU_H):
    """Four fifths: responding boards (MIN_RESPONSE) ranked by response per CPU-hour, at most
    max_cpu_h per run and FRONTIER_FOOTPRINTS footprints, one per owner, a quarter of the suite with 4+
    layers. One fifth: boards drawn at random from the same cost and footprint range, whatever their
    response, so the suite is not fitted only to the knobs already tried. All usable as route and
    place tasks. Returns (response part, random part)."""
    ok = lambda b: b in inp.routable and b in inp.placed and b in inp.hist  # noqa: E731
    n_resp, need4 = n - n // 5, math.ceil(n / 4)
    cand = [b for b, r in inp.resp.items() if ok(b) and r["resp"] >= MIN_RESPONSE
            and inp.hist[b] <= max_cpu_h and inp.footprints[b] <= FRONTIER_FOOTPRINTS]
    cand.sort(key=lambda b: (-inp.resp[b]["resp"] / max(inp.hist[b], COST_FLOOR_H), b))
    chosen, owners, n4 = [], set(), 0
    for quota in (True, False):  # second pass: places the quota kept free and could not fill
        for b in cand:
            left, four = n_resp - len(chosen), inp.layers[b] >= 4
            if not left:
                break
            if inp.owner[b] in owners or (quota and not four and left <= need4 - n4):
                continue  # the last places are kept for boards with 4+ layers while the quarter is not met
            chosen.append(b)
            owners.add(inp.owner[b])
            n4 += four
    if not chosen:
        return [], []
    cost = [inp.hist[b] for b in chosen]
    fp = [inp.footprints[b] for b in chosen]
    pool = sorted(b for b in inp.hist if ok(b) and b not in chosen and min(cost) <= inp.hist[b] <= max(cost)
                  and min(fp) <= inp.footprints[b] <= max(fp))
    rng.shuffle(pool)
    return chosen, round_robin(pool, [0], lambda b: (0,), n // 5, owners, inp.owner)


def quality(inp, n, rng, owners):
    """Human-clean boards with one of QUALITY_TAGS, QUALITY_FOOTPRINTS footprints, 2 or 4 layers, no
    history over the sprint cap; drawn at random, evenly over tag x layer count, one per owner."""
    lo, hi = QUALITY_FOOTPRINTS
    tags_of = lambda b: {(t, inp.layers[b]) for t in QUALITY_TAGS if b in inp.tag[t]}  # noqa: E731
    pool = sorted(b for b in inp.human_clean if lo <= inp.footprints[b] <= hi and inp.layers[b] in (2, 4)
                  and tags_of(b) and inp.hist.get(b, 0) <= SPRINT_BOARD_CPU_H)
    rng.shuffle(pool)
    return round_robin(pool, [(t, ly) for t in QUALITY_TAGS for ly in (2, 4)], tags_of, n, owners, inp.owner)


def ladder(inp, n, rng, owners):
    """Human-clean boards drawn at random, evenly over LADDER_BANDS x (under 4 layers, 4+), one per owner."""
    def cell(b):
        return {(i, inp.layers[b] >= 4) for i, (lo, hi) in enumerate(LADDER_BANDS) if lo <= inp.footprints[b] <= hi}
    pool = sorted(b for b in inp.human_clean if cell(b))
    rng.shuffle(pool)
    return round_robin(pool, [(i, four) for i in range(len(LADDER_BANDS)) for four in (False, True)], cell, n, owners, inp.owner)


def canary(inp):
    """Merit boards over CANARY_PADS pads and human-clean boards over CANARY_FOOTPRINTS footprints."""
    return sorted({b for b in inp.merit if inp.pads.get(b, 0) > CANARY_PADS}
                  | {b for b in inp.human_clean if inp.footprints[b] > CANARY_FOOTPRINTS})


def build(inp, seed=SEED, sizes=SIZES):
    """The four suites, name -> ids. The sprint suites share no owner, and the ladder shares none with
    them: a ladder run confirms on boards the sprint did not see."""
    rng = lambda name: random.Random(f"{seed}:{name}")  # noqa: E731
    resp, rand = frontier(inp, sizes["frontier"], rng("sprint-frontier"))
    owners = {inp.owner[b] for b in resp + rand}
    out = {"sprint-frontier": resp + rand}
    out["sprint-quality"] = quality(inp, sizes["quality"], rng("sprint-quality"), owners)
    out["ladder"] = ladder(inp, sizes["ladder"], rng("ladder"), owners)
    out["canary"] = canary(inp)
    return out, len(rand)


def summary(inp, suites, n_random):
    """Markdown table: size, independence, layers, footprints, and CPU-h for one run of each board."""
    est = estimator(inp.hist, inp.footprints)
    lines = ["| suite | boards | owners | 4+ layers | footprints, median (range) | CPU-h per method-run of all | boards with own history |",
             "|---|---|---|---|---|---|---|"]
    for name, ids in suites.items():
        fp = [inp.footprints[b] for b in ids] or [0]
        e = [est(b) for b in ids]
        lines.append(f"| `{name}` | {len(ids)} | {len({inp.owner[b] for b in ids})} | {sum(inp.layers[b] >= 4 for b in ids)} "
                     f"| {statistics.median(fp):.0f} ({min(fp)}-{max(fp)}) | {sum(h for h, _ in e):.0f} | {sum(k for _, k in e)} |")
    part = suites["sprint-frontier"][:len(suites["sprint-frontier"]) - n_random]
    if part:
        lines.append(f"\n`sprint-frontier`: {len(part)} responding boards (mean past response "
                     f"{statistics.fmean(inp.resp[b]['resp'] for b in part):.2f}, clean flips "
                     f"{statistics.fmean(inp.resp[b]['flip'] for b in part):.3f} per pair) and {n_random} random ones.")
    return "\n".join(lines)


# ------------------------------------------------------------------ freezing the sprint suites on a stored control
def freeze(rows, arms, seeds, suites, board):
    """The sprint suites with only the boards every control arm ran on every seed, their manifest rows and
    a report. rows: the control's runs (kaeres.exp_rows: board, method_id, attempt, status, unconnected,
    clean, cpu_s); arms: method id -> arm name; suites: name -> ids; board: id -> dict(owner, layers,
    footprints, tags)."""
    run = {(r["board"], arms[r["method_id"]], r["attempt"]): r for r in rows
           if r["method_id"] in arms and r["status"] == "ok" and r["unconnected"] is not None}
    cells = [(arm, k) for arm in sorted(set(arms.values())) for k in range(seeds)]
    kept = {name: [b for b in ids if all((b, arm, k) in run for arm, k in cells)] for name, ids in suites.items()}
    out, manifest = [], []
    for name, ids in suites.items():
        gone = [b for b in ids if b not in kept[name]]
        out.append(f"{name}: {len(kept[name])} of {len(ids)} boards kept" + (f"; dropped (a control arm did not prepare or run): {', '.join(gone)}" if gone else ""))
        for b in kept[name]:
            row = dict(board=b, suite=name, **board[b])
            for arm, k in cells:
                r = run[(b, arm, k)]
                row.update({f"{arm}_opens_s{k}": r["unconnected"], f"{arm}_clean_s{k}": int(bool(r["clean"])),
                            f"{arm}_cpu_h_s{k}": round((r["cpu_s"] or 0) / 3600, 3)})
            manifest.append(row)
    n = len(manifest)
    for arm in sorted(set(arms.values())):
        opens = [[m[f"{arm}_opens_s{k}"] for k in range(seeds)] for m in manifest]
        clean = [[m[f"{arm}_clean_s{k}"] for k in range(seeds)] for m in manifest]
        out.append(f"{arm}: open connections left on {sum(min(o) > 0 for o in opens)} of {n} boards on every seed, on "
                   f"{sum(max(o) > 0 for o in opens)} on some seed; clean on every seed {sum(min(c) for c in clean)}; inert between "
                   f"seeds (same open connections and clean) {sum(len(set(o)) == 1 and len(set(c)) == 1 for o, c in zip(opens, clean))}; "
                   f"{sum(m[f'{arm}_cpu_h_s{k}'] for m in manifest for k in range(seeds)):.1f} CPU-h in all, "
                   f"{statistics.fmean(m[f'{arm}_cpu_h_s{k}'] for m in manifest for k in range(seeds)) if n else 0:.2f} per run")
    inert = sum(all(len({m[f"{arm}_opens_s{k}"] for k in range(seeds)}) == 1 and len({m[f"{arm}_clean_s{k}"] for k in range(seeds)}) == 1
                    for arm in set(arms.values())) for m in manifest)
    out.append(f"inert between seeds under every arm: {inert} of {n} boards")
    return kept, manifest, "\n".join(out)


def main_freeze(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kaeres
    e = kaeres.load_exp(a.freeze)
    arms = {m["id"]: ARMS.get(kaeres.find_method(m["id"])["recipe"]["kind"], "staged") for m in e["methods"]}
    rows = kaeres.exp_rows(e)[0]
    tags = {t: set(read_ids(Path(a.tags) / "suites" / f"{t}.txt")) for t in MECHANISM_TAGS}
    board = {r["id"]: dict(owner=owner_of(r.get("repo") or r["id"]), layers=r.get("layers"), footprints=r.get("footprints"),
                           tags=";".join(t for t in MECHANISM_TAGS if r["id"] in tags[t]))
             for r in jsonl(Path(a.corpus) / "manifest.jsonl")}
    suites = {name: read_ids(Path(a.out) / f"{name}.txt") for name in SPRINT}
    kept, manifest, report = freeze(rows, arms, e["attempts"], suites, board)
    if not a.dry_run:
        for name, ids in kept.items():
            (Path(a.out) / f"{name}.txt").write_text("\n".join(ids) + "\n")
        with open(Path(a.out) / "sprint-manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(manifest[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(manifest)
    print(report)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tags", required=True, help="board-tag folder (suites/, structural/usability.jsonl, structural/features.jsonl)")
    ap.add_argument("--index", default=os.path.join(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")), "index.sqlite"))
    ap.add_argument("--corpus", default=os.path.expanduser(os.environ.get("KAE_CORPUS", "~/kae-boards")))
    ap.add_argument("--merit", default=str(REPO / "bench" / "suites" / "merit-213.txt"))
    ap.add_argument("--out", default=str(REPO / "bench" / "suites"))
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--dry-run", action="store_true", help="print the summary, write nothing")
    ap.add_argument("--freeze", metavar="EXPERIMENT", help="the stored control: keep the sprint boards it ran, write sprint-manifest.csv")
    a = ap.parse_args()
    if a.freeze:
        return main_freeze(a)
    inp = Inputs(a.index, a.tags, a.corpus, a.merit)
    suites, n_random = build(inp, a.seed)
    if not a.dry_run:
        for name, ids in suites.items():
            (Path(a.out) / f"{name}.txt").write_text("\n".join(ids) + "\n")
    print(summary(inp, suites, n_random))


if __name__ == "__main__":
    main()
