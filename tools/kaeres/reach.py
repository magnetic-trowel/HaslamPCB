#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reach pre-check: did a change reach a board at all, and where did the two arms first part? Read-only on the store.

A run's fingerprint has three stages:
- place: (hpwl, scorecard, crossings) after kae's place stage, from the adapter log's JSON report (the line from
  `{"seed"`); None for methods without a place stage;
- board: a hash of the output board's placement (reference, layer, position) and one of its copper (segments, arcs,
  vias; uuids left out), from `output.kicad_pcb.gz`;
- final: (opens, DRC errors, track length, vias) from the run's DRC evaluation.
Fingerprints are cached outside the store (`--cache`, `$KAE_REACH_CACHE`, default `~/.cache/kaeres/reach`).

Two runs at the same seed first diverge at `place` (place tuples differ; without a place tuple, placement hashes),
at `route` (same placement, different copper or final tuple) or `none` (the change never reached the board).

  reach.py compare --experiment NAME [--arm M] [--final-only]   per arm: stages, unreached boards, CPU-h, pilot value
  reach.py precheck --arm M --control M [--boards @FILE] [--pilot 0] [--seeds 3] --out DIR
                                                                cells still worth running + reach.json for the analyser
  reach.py retro [--since DATE] [--fingerprint EXP ...]         every stored A/B (final tuple; fingerprints for EXPs)

Methods are named by id prefix or exact name. In the analyser's all-board estimate an unreached cell is a zero
difference (`fill_unreached`). Fingerprinting reads two gzip files per run: run `retro --fingerprint` and big
`compare`s through kaeq.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

TOP = re.compile(r"^(?:\t| {2})\(([a-z_]+)", re.M)
AT = re.compile(r"\(at ([-\d.e]+) ([-\d.e]+)(?: ([-\d.e]+))?\)")
LAYER = re.compile(r'\(layer "?([^")\s]+)"?\)')
REF = re.compile(r'\((?:property "Reference"|fp_text reference) "([^"]*)"')
UUID = re.compile(r'\((?:uuid|tstamp) "?[^)]*\)')


def default_store():
    return Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))


def default_cache():
    return Path(os.path.expanduser(os.environ.get("KAE_REACH_CACHE", "~/.cache/kaeres/reach")))


# --- fingerprints -----------------------------------------------------------------------------------------------

def place_fp(run_dir):
    """(hpwl, scorecard, crossings) after the place stage, or None."""
    p = Path(run_dir) / "adapter.log.gz"
    try:
        with gzip.open(p, "rt", errors="replace") as f:
            for line in f:
                i = line.find('{"seed"')
                if i < 0:
                    continue
                try:
                    j = json.loads(line[i:])
                except ValueError:
                    continue
                st = ((j.get("iterations") or [{}])[0].get("stages") or {}).get("place") or {}
                t = (st.get("hpwl"), st.get("scorecard"), st.get("crossings"))
                return None if t[0] is None else list(t)
    except (OSError, EOFError):
        return None
    return None


def board_hashes(text):
    """(placement hash, copper hash) of a .kicad_pcb text."""
    starts = [(m.start(), m.group(1)) for m in TOP.finditer(text)] + [(len(text), "")]
    place, copper = [], []
    for (s, head), (e, _) in zip(starts, starts[1:]):
        if head == "footprint":
            chunk = text[s:e]
            at, ly, ref = AT.search(chunk), LAYER.search(chunk), REF.search(chunk)
            place.append((ref.group(1) if ref else "", ly.group(1) if ly else "", at.groups() if at else ()))
        elif head in ("segment", "arc", "via"):
            copper.append(" ".join(UUID.sub("", text[s:e]).split()))
    h = lambda xs: hashlib.sha256(json.dumps(sorted(xs)).encode()).hexdigest()[:16]
    return h([list(map(str, p[:2])) + list(p[2]) for p in place]), h(copper)


def final_fp(run_dir, evaluator=None):
    """(opens, errors, track length, vias) from the run's DRC evaluation (the given evaluator, else the newest)."""
    best = None
    for p in sorted((Path(run_dir) / "evals").glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        s = d.get("score")
        if not isinstance(s, dict):
            continue
        if evaluator and d.get("evaluator") == evaluator:
            best = (d, s)
            break
        if best is None or (d.get("at") or "") > (best[0].get("at") or ""):
            best = (d, s)
    if best is None:
        return None
    s = best[1]
    return [s.get("unconnected"), s.get("errors"), s.get("track_length_mm"), s.get("vias")]


def fingerprint(run_dir, cache=None, evaluator=None):
    """dict(place, placement, copper, final) for one stored run, cached by path and output board mtime/size."""
    run_dir = Path(run_dir)
    out = run_dir / "output.kicad_pcb.gz"
    try:
        stt = out.stat()
        key_src = f"{run_dir}|{stt.st_mtime_ns}|{stt.st_size}|{evaluator}"
    except OSError:
        stt, key_src = None, f"{run_dir}|none|{evaluator}"
    cfile = None
    if cache:
        k = hashlib.sha1(key_src.encode()).hexdigest()
        cfile = Path(cache) / k[:2] / f"{k}.json"
        try:
            return json.loads(cfile.read_text())
        except (OSError, ValueError):
            pass
    fp = dict(place=place_fp(run_dir), placement=None, copper=None, final=final_fp(run_dir, evaluator))
    if stt is not None:
        try:
            with gzip.open(out, "rt", errors="replace") as f:
                fp["placement"], fp["copper"] = board_hashes(f.read())
        except (OSError, EOFError):
            pass
    if cfile:
        cfile.parent.mkdir(parents=True, exist_ok=True)
        tmp = cfile.with_suffix(".tmp")
        tmp.write_text(json.dumps(fp))
        tmp.replace(cfile)
    return fp


def stage(fa, fb):
    """First stage where two fingerprints of the same board and seed differ: 'place', 'route' or 'none'."""
    if fa.get("place") and fb.get("place"):
        if fa["place"] != fb["place"]:
            return "place"
    elif fa.get("placement") and fb.get("placement") and fa["placement"] != fb["placement"]:
        return "place"
    for k in ("placement", "copper", "final"):
        if fa.get(k) != fb.get(k):
            return "route"
    return "none"


def fill_unreached(per_board, unreached):
    """Per-board differences for the all-board estimate: unreached boards enter as zero differences."""
    out = dict(per_board)
    for b in unreached:
        out.setdefault(b, 0.0)
    return out


# --- the store --------------------------------------------------------------------------------------------------

def connect(store):
    return sqlite3.connect(f"file:{Path(store) / 'index.sqlite'}?mode=ro", uri=True)


def resolve_method(conn, name):
    rows = conn.execute("SELECT id, name FROM methods WHERE id LIKE ? OR name = ?", (name + "%", name)).fetchall()
    ids = sorted({r[0] for r in rows})
    if len(ids) != 1:
        raise SystemExit(f"method {name!r}: " + ("not found" if not ids else "ambiguous: " + ", ".join(i[:12] for i in ids)))
    return ids[0]


def runs_of(conn, mid, evaluator=None, boards=None, max_attempt=99):
    """board -> attempt -> row(path, cpu, final) for one method; final from the index's DRC evaluation."""
    q = ("SELECT r.board, r.attempt, r.path, r.cpu_s, e.evaluator, e.unconnected, e.errors, e.valid, e.json "
         "FROM runs r LEFT JOIN evals e ON e.board = r.board AND e.run = r.run AND e.evaluator = COALESCE(?, e.evaluator) "
         "WHERE r.method_id = ?")
    out = defaultdict(dict)
    for b, a, path, cpu, ev, u, er, va, js in conn.execute(q, (evaluator, mid)):
        if (boards is not None and b not in boards) or a is None or a >= max_attempt or u is None:
            continue
        try:
            s = json.loads(js)["score"]
        except (TypeError, ValueError, KeyError):
            continue
        row = dict(path=path, cpu=cpu or 0.0, valid=va, evaluator=ev,
                   final=[u, er, s.get("track_length_mm"), s.get("vias")])
        prev = out[b].get(a)
        if prev is None or (ev or "") > (prev["evaluator"] or ""):
            out[b][a] = row
    return out


def experiment(store, conn, name):
    ej = json.loads((Path(store) / "experiments" / name / "experiment.json").read_text())
    try:
        boards = set((Path(store) / "experiments" / name / "boards.txt").read_text().split())
    except OSError:
        boards = None
    return ej, boards


# --- compare ----------------------------------------------------------------------------------------------------

def compare_runs(ra, rb, fps=None):
    """Per (board, seed): stage, CPU-h of both arms and of the treatment. fps(row) gives a fingerprint, else final only."""
    cells = []
    for b, at in sorted(ra.items()):
        for s, a in sorted(at.items()):
            r = rb.get(b, {}).get(s)
            if r is None or not a.get("valid") or not r.get("valid"):
                continue
            if fps is not None:
                fa, fb = fps(a), fps(r)
                fa["final"], fb["final"] = a["final"], r["final"]       # the index's evaluation decides the final tuple
                st = stage(fa, fb)
            else:
                st = "none" if a["final"] == r["final"] else "diverged"
            cells.append(dict(board=b, seed=s, stage=st, cpu_a=a["cpu"] / 3600, cpu_b=r["cpu"] / 3600,
                              final_same=a["final"] == r["final"]))
    return cells


def summarize(cells):
    by_board = defaultdict(list)
    for c in cells:
        by_board[c["board"]].append(c)
    unreached = sorted(b for b, cs in by_board.items() if all(c["stage"] == "none" for c in cs))
    stages = Counter(c["stage"] for c in cells)
    pilot = Counter()
    for b, cs in by_board.items():
        cs = sorted(cs, key=lambda c: c["seed"])
        if len(cs) < 2:
            continue
        first = cs[0]["stage"] == "none"
        later = [c["stage"] == "none" for c in cs[1:]]
        pilot[first, "boards"] += 1
        pilot[first, "all_later"] += all(later)
        pilot[first, "later_pairs"] += len(later)
        pilot[first, "later_none"] += sum(later)
    none = [c for c in cells if c["stage"] == "none"]
    return dict(pairs=len(cells), stages=dict(stages), final_identical=sum(c["final_same"] for c in cells),
                boards=len(by_board), unreached_boards=unreached,
                cpu_both=sum(c["cpu_a"] + c["cpu_b"] for c in cells), cpu_treatment=sum(c["cpu_b"] for c in cells),
                cpu_both_unreached=sum(c["cpu_a"] + c["cpu_b"] for c in none), cpu_treatment_unreached=sum(c["cpu_b"] for c in none),
                pilot={("unreached" if k[0] else "reached") + "_" + k[1]: v for k, v in pilot.items()})


def pilot_text(p):
    out = []
    for k in ("unreached", "reached"):
        n = p.get(f"{k}_boards", 0)
        if n:
            out.append(f"pilot {k}: {n} boards with later seeds, all later unreached on {p.get(f'{k}_all_later', 0)} "
                       f"({p.get(f'{k}_all_later', 0) / n * 100:.0f}%), later pairs unreached {p.get(f'{k}_later_none', 0)}/{p.get(f'{k}_later_pairs', 0)}")
    return "; ".join(out) or "no board with later seeds"


def compare_experiment(store, conn, name, arms=None, final_only=False, cache=None):
    ej, boards = experiment(store, conn, name)
    mids = [m["id"] for m in ej.get("methods") or []]
    names = {m["id"]: m["name"] for m in ej.get("methods") or []}
    ev = (ej.get("evaluators") or {}).get("drc")
    natt = ej.get("attempts") or 99
    ra = runs_of(conn, mids[0], ev, boards, natt)
    fps = None if final_only else (lambda row: dict(fingerprint(row["path"], cache, row["evaluator"])))
    out = []
    for B in mids[1:]:
        if arms and not any(B.startswith(x) or names[B] == x for x in arms):
            continue
        cells = compare_runs(ra, runs_of(conn, B, ev, boards, natt), fps)
        out.append(dict(experiment=name, control=names[mids[0]], arm=names[B], method_id=B,
                        mode="final" if final_only else "fingerprint", cells=cells, **summarize(cells)))
    return out


def report_lines(rows):
    L = ["| experiment | arm | mode | pairs | place / route / none | final identical | boards unreached | "
         "CPU-h both | CPU-h both, unreached | CPU-h treatment, unreached | pilot seed |", "|---|---|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        s = r["stages"]
        L.append(f"| {r['experiment']} | {r['arm']} | {r['mode']} | {r['pairs']} | "
                 f"{s.get('place', 0)} / {s.get('route', s.get('diverged', 0))} / {s.get('none', 0)} | "
                 f"{r['final_identical']} | {len(r['unreached_boards'])} of {r['boards']} | {r['cpu_both']:.1f} | "
                 f"{r['cpu_both_unreached']:.1f} | {r['cpu_treatment_unreached']:.1f} | {pilot_text(r['pilot'])} |")
    return L


# --- precheck ---------------------------------------------------------------------------------------------------

def precheck(store, conn, arm, control, boards=None, pilot=0, seeds=3, cache=None, evaluator=None):
    """From the arm's pilot seed and the stored control at the same seed: which (board, seed) cells to run."""
    am, cm = resolve_method(conn, arm), resolve_method(conn, control)
    ra = runs_of(conn, cm, evaluator, boards)
    rb = runs_of(conn, am, evaluator, boards)
    stages, cpu_pilot = {}, {}
    for b in sorted(set(ra) & set(rb)):
        a, r = ra[b].get(pilot), rb[b].get(pilot)
        if a is None or r is None:
            continue
        fa, fb = fingerprint(a["path"], cache, a["evaluator"]), fingerprint(r["path"], cache, r["evaluator"])
        fa["final"], fb["final"] = a["final"], r["final"]
        stages[b] = stage(fa, fb)
        cpu_pilot[b] = r["cpu"] / 3600
    reached = sorted(b for b, s in stages.items() if s != "none")
    unreached = sorted(b for b, s in stages.items() if s == "none")
    missing = sorted((boards or set(ra) | set(rb)) - set(stages))
    later = [s for s in range(seeds) if s != pilot]
    return dict(arm=am, control=cm, pilot=pilot, seeds=seeds, stages=stages, reached=reached, unreached=unreached,
                no_pilot=missing, cells=[[b, s] for b in reached + missing for s in later],
                cpu_h_saved_estimate=sum(cpu_pilot[b] for b in unreached) * len(later),
                rule="an unreached board's cells are zero differences in the all-board estimate (fill_unreached)")


# --- CLI --------------------------------------------------------------------------------------------------------

def _boards_arg(v):
    if not v:
        return None
    if v.startswith("@"):
        return set(Path(v[1:]).read_text().split())
    return set(v.split(","))


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["experiment", "arm", "method_id", "board", "seed", "stage", "final_same", "cpu_h_control", "cpu_h_treatment"])
        for r in rows:
            for c in r["cells"]:
                w.writerow([r["experiment"], r["arm"], r["method_id"], c["board"], c["seed"], c["stage"], int(c["final_same"]),
                            round(c["cpu_a"], 4), round(c["cpu_b"], 4)])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", type=Path, default=default_store())
    ap.add_argument("--cache", type=Path, default=default_cache(), help="fingerprint cache, outside the store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--experiment", required=True)
    c.add_argument("--arm", action="append", help="method id prefix or name; default every arm")
    c.add_argument("--final-only", action="store_true", help="final tuple from the index only (no file reads)")
    c.add_argument("--out", type=Path)
    p = sub.add_parser("precheck")
    p.add_argument("--arm", required=True)
    p.add_argument("--control", required=True)
    p.add_argument("--boards", help="@FILE or a,b,c")
    p.add_argument("--pilot", type=int, default=0)
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--evaluator", help="DRC evaluator id (default: the newest per run)")
    p.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("retro")
    r.add_argument("--since", default="2026-11-01")
    r.add_argument("--fingerprint", nargs="*", default=[], help="experiments to fingerprint (others: final tuple only)")
    r.add_argument("--max-boards", type=int, default=1500)
    r.add_argument("--min-pairs", type=int, default=10)
    r.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    conn = connect(a.store)
    if a.cmd == "precheck":
        res = precheck(a.store, conn, a.arm, a.control, _boards_arg(a.boards), a.pilot, a.seeds, a.cache, a.evaluator)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "reach.json").write_text(json.dumps(res, indent=1) + "\n")
        (a.out / "cells.txt").write_text("".join(f"{b} {s}\n" for b, s in res["cells"]))
        print(f"pilot seed {res['pilot']}: {len(res['reached'])} boards reached, {len(res['unreached'])} unreached, "
              f"{len(res['no_pilot'])} without a pilot pair; {len(res['cells'])} cells to run; "
              f"about {res['cpu_h_saved_estimate']:.1f} CPU-h of treatment runs saved")
        return 0
    if a.cmd == "compare":
        rows = compare_experiment(a.store, conn, a.experiment, a.arm, a.final_only, a.cache)
    else:
        rows = []
        root = Path(a.store) / "experiments"
        for name in sorted(os.listdir(root)):
            if "smoke" in name and name not in a.fingerprint:
                continue
            try:
                ej, boards = experiment(a.store, conn, name)
            except (OSError, ValueError):
                continue
            if len(ej.get("methods") or []) < 2 or (ej.get("created") or "") < a.since or (boards and len(boards) > a.max_boards):
                continue
            rows += [x for x in compare_experiment(a.store, conn, name, final_only=name not in a.fingerprint, cache=a.cache)
                     if x["pairs"] >= a.min_pairs]
        tot = Counter()
        for x in rows:
            tot["pairs"] += x["pairs"]
            tot["ident"] += x["final_identical"]
            tot["cpu"] += x["cpu_both"]
            tot["cpu_none"] += x["cpu_both_unreached"]
            for k, v in x["pilot"].items():
                tot[k] += v
    L = ["# Reach", ""] + report_lines(rows)
    if a.cmd == "retro":
        L += ["", f"All arms: {tot['pairs']} pairs, final identical {tot['ident']} ({tot['ident'] / max(1, tot['pairs']) * 100:.0f}%); "
                  f"CPU-h both arms {tot['cpu']:.0f}, on unreached pairs {tot['cpu_none']:.0f}; {pilot_text(tot)}"]
    text = "\n".join(L) + "\n"
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "REACH.md").write_text(text)
        write_csv(a.out / "reach-cells.csv", rows)
        (a.out / "reach.json").write_text(json.dumps([{k: v for k, v in x.items() if k != "cells"} for x in rows], indent=1) + "\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
