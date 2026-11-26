# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""pose-transplant-3 verdict (arm P, with pose-transplant-2's K, H, B, M): legality, held poses, gap shares (PLAN.md)."""
import csv, glob, gzip, json, math, os, random, sys, tempfile
from collections import defaultdict
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "kae" / "src")]   # this checkout's kae
from kae.board.kicad_file import load  # noqa: E402
from kae.place.pose_tiers import board_key  # noqa: E402

E = Path.home() / "haslam-baselines/experiments/pose-transplant-3"
E2 = Path.home() / "haslam-baselines/experiments/pose-transplant-2"
STORE = Path.home() / "haslam-baselines/boards"
K, H, B, M, P = "716e9b11e0f4", "71e60a91475d", "3434cb72a315", "0f4c8a49cfcb", "1a8de103ed23"
ARM = {B: "big", M: "mid", P: "small"}
import sys as _s
ONLY_SMOKE = len(_s.argv) > 1
PLACE_TYPES = None

rows = list(csv.DictReader(open(E2 / "results.csv"))) + ([] if ONLY_SMOKE else [r for r in csv.DictReader(open(E / "results.csv")) if r["method_id"] == P])
boards = [l.strip() for l in open(E / "boards.txt") if l.strip()]
if ONLY_SMOKE: boards = _s.argv[1:]
oracle = {}
for src in (E2 / "pose-oracle", Path.home() / ".cache/haslambench/pose-oracle/pose-transplant-3"):
    for f in src.glob("*.json"):
        d = json.loads(f.read_text())
        if "board" in d:
            o = oracle.setdefault(d["board"], dict(d, tiers={}))
            o["tiers"].update(d["tiers"])
owner = {}
opens = {}
for r in rows:
    owner[r["board"]] = r["repo"].rstrip("/").split("/")[-2].lower() if r["repo"] else r["board"]
    if r["method_id"] in (K, H, B, M, P):
        opens[(r["board"], r["method_id"], int(r["attempt"]))] = int(r["unconnected"]) if r["unconnected"] not in ("", None) else None

# legality and held poses, per arm run
leg = defaultdict(list)
moved_runs = []
for b in boards:
    o = oracle[b]
    base = o["input_placement_errors"]
    for mid in (K, B, M, P):
        for run in sorted(glob.glob(str(STORE / b / "runs" / f"*.{mid[:8]}.a[01]"))):
            rj = json.loads(Path(run, "run.json").read_text())
            if rj.get("experiment") not in ("pose-transplant-2", "pose-transplant-3", "control-w47") and mid != K:
                continue
            ev = json.loads(Path(run, "evals/7868e10b621b.json").read_text())["score"]
            pe = ev.get("placement_errors") or {}
            exc = {k: v - base.get(k, 0) for k, v in pe.items() if v > base.get(k, 0)}
            out = ev.get("outside") or 0
            held_bad = None
            if mid in ARM and ARM[mid] in o["tiers"]:
                held = o["tiers"][ARM[mid]]["held"]
                with tempfile.TemporaryDirectory() as td:
                    p = Path(td, "o.kicad_pcb")
                    p.write_bytes(gzip.open(Path(run, "output.kicad_pcb.gz")).read())
                    bd = load(str(p))
                fp = {f.uuid: f for f in bd.footprints}
                held_bad = 0
                for u, (x, y, rot, side) in held.items():
                    f = fp.get(u)
                    if f is None or abs(f.x - x) > 1e-3 or abs(f.y - y) > 1e-3 or abs(((f.rot - rot + 180) % 360) - 180) > 1e-3 or f.side != side:
                        held_bad += 1
                if held_bad:
                    moved_runs.append((b, ARM[mid], run[-2:], held_bad))
            leg[mid].append(dict(board=b, run=run[-2:], exc=exc, outside=out, held_bad=held_bad,
                                 legal=(not exc and not out and not held_bad)))

for mid, name in ((K, "K"), (B, "big"), (M, "mid"), (P, "P")):
    L = leg[mid]
    print(f"{name}: runs {len(L)}, legal {sum(x['legal'] for x in L)}, excess-error runs {sum(1 for x in L if x['exc'])}, "
          f"outside runs {sum(1 for x in L if x['outside'])}, held-moved runs {sum(1 for x in L if x['held_bad'])}")
    for x in L:
        if not x["legal"]:
            print("   illegal", x)
if ONLY_SMOKE:
    raise SystemExit
NAMES = ["K-H", "K-B", "K-M", "K-P", "g_B", "g_M", "g_P", "g_M+g_P"]
f = lambda n: math.log1p(n)
pairs = []
for b in boards:
    for s_ in (0, 1):
        v = [opens.get((b, m, s_)) for m in (K, H, B, M, P)]
        if None in v:
            print("missing", b, s_, v)
            continue
        k, h, bb, mm, pp = map(f, v)
        pairs.append((owner[b], b, s_, k - h, k - bb, k - mm, k - pp, v))


def stat(ps):
    m = [sum(p[i] for p in ps) / len(ps) for i in (3, 4, 5, 6)]
    kh = m[0]
    g = [x / kh if kh else float("nan") for x in m[1:]]
    return (*m, *g, g[1] + g[2])


def boot(ps):
    groups = defaultdict(list)
    for p in ps:
        groups[p[0]].append(p)
    keys = sorted(groups)
    rng = random.Random(0)
    bs = []
    for _ in range(5000):
        s = []
        for _ in keys:
            s.extend(groups[keys[rng.randrange(len(keys))]])
        bs.append(stat(s))
    est = stat(ps)
    print(f"pairs {len(ps)}, boards {len({p[1] for p in ps})}, owners {len(keys)}")
    for i, n in enumerate(NAMES):
        xs = sorted(x[i] for x in bs if not math.isnan(x[i]))
        print(f"{n}: {est[i]:+.3f} [{xs[int(0.025 * (len(xs) - 1))]:+.3f}, {xs[int(0.975 * (len(xs) - 1))]:+.3f}]")


boot(pairs)
print("opens sum K,H,B,M,P:", [sum(p[7][j] for p in pairs) for j in range(5)])
print("P better/same/worse than K:", sum(p[6] > 0 for p in pairs), sum(p[6] == 0 for p in pairs), sum(p[6] < 0 for p in pairs))
for j, n in enumerate("KHBMP"):
    print(n, "zero-open runs", sum(1 for p in pairs if p[7][j] == 0), "1-5 opens", sum(1 for p in pairs if 1 <= p[7][j] <= 5))
print("per board (seed0, seed1) opens K/H/B/M/P:")
for b in boards:
    print(" ", b[:50], [p[7] for p in pairs if p[1] == b])
bad = {(x["board"], int(x["run"][1])) for m in (P,) for x in leg[m] if not x["legal"]}
print("\nlegal P board-seeds only:")
boot([p for p in pairs if (p[1], p[2]) not in bad])
