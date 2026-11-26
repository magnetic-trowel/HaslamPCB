# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ground-side-repair-ab: the PLAN's endpoints on board-seed pairs (owner bootstrap, quality.py's estimators)."""
import csv, json, math, statistics, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # the repository checkout
sys.path.insert(0, str(ROOT / "tools/haslamres"))
sys.path.insert(0, str(ROOT / "bench/src"))
import quality as Q  # noqa: E402
import return_board  # noqa: E402

E = Path.home() / "haslam-baselines/experiments/ground-side-repair-ab"
STORE = Path.home() / "haslam-baselines/boards"
ARMS = {"04aa874ecd06": "off", "bc785b931238": "gs2", "8140424ba3a7": "gs2r"}
LOSERS = set(json.load(open(Path.home() / "haslam-baselines/experiments/ground-side-ladder/repair_ab_boards.json"))["losers"])
rows = [Q.typed(r) for r in csv.DictReader(open(E / "results.csv")) if r["method_id"] in ARMS]
R = {(r["board"], r["attempt"], ARMS[r["method_id"]]): r for r in rows}
keys = sorted({(b, k) for b, k, _ in R})
cov = {}
for (b, k, a), r in R.items():
    try:
        cov[(b, k, a)] = return_board.measure_cached(STORE / b / "runs" / r["run"] / "output.kicad_pcb.gz").get("cov_opp")
    except Exception as e:  # noqa: BLE001
        print("cov failed", b, k, a, e, file=sys.stderr)
out = {}
print(f"board-seeds {len(keys)}; boards {len({b for b, _ in keys})}")
for sub, sel in (("all", lambda b: True), ("losers", lambda b: b in LOSERS), ("winners", lambda b: b not in LOSERS)):
    ks = [x for x in keys if sel(x[0]) and all((x[0], x[1], a) in R for a in ARMS.values())]
    print(f"\n## {sub}: {len(ks)} board-seeds")
    for a in ("off", "gs2", "gs2r"):
        xs = [R[(b, k, a)] for b, k in ks]
        print(f"  {a}: xc {sum(bool(r['xc']) for r in xs)}/{len(xs)}, opens {sum(int(r['unconnected'] or 0) for r in xs)}, "
              f"zero-open {sum(int(r['unconnected'] or 0) == 0 for r in xs)}, 1-5 opens {sum(1 <= int(r['unconnected'] or 0) <= 5 for r in xs)}, "
              f"CPU h {sum(float(r['cpu_s'] or 0) for r in xs) / 3600:.1f}")
    for a in ("gs2", "gs2r"):
        gained = sum(bool(R[(b, k, a)]["xc"]) and not R[(b, k, "off")]["xc"] for b, k in ks)
        lost = sum(not R[(b, k, a)]["xc"] and bool(R[(b, k, "off")]["xc"]) for b, k in ks)
        xc = Q.diff_row([(R[(b, k, a)]["owner"], f"{b}#{k}", float(bool(R[(b, k, a)]["xc"])) - float(bool(R[(b, k, "off")]["xc"])))
                         for b, k in ks], lower_better=False)
        fin = [(b, k) for b, k in ks if int(R[(b, k, a)]["unconnected"] or 0) == 0 and int(R[(b, k, "off")]["unconnected"] or 0) == 0
               and cov.get((b, k, a)) is not None and cov.get((b, k, "off")) is not None]
        cv = Q.diff_row([(R[(b, k, a)]["owner"], f"{b}#{k}", cov[(b, k, a)] - cov[(b, k, "off")]) for b, k in fin], lower_better=False)
        lo = [math.log1p(int(R[(b, k, a)]["unconnected"] or 0)) - math.log1p(int(R[(b, k, "off")]["unconnected"] or 0)) for b, k in ks]
        vias = [(1 + int(R[(b, k, a)]["vias"] or 0)) / (1 + int(R[(b, k, "off")]["vias"] or 0)) for b, k in fin]
        print(f"  {a} vs off: xc +{gained}/-{lost} (net {gained - lost}), xc diff {xc['est']} [{xc['lo']}, {xc['hi']}] {xc['verdict']}; "
              f"cov_opp ({len(fin)} finished by both) {cv['est'] and round(cv['est'], 4)} [{cv['lo']}, {cv['hi']}] {cv['verdict']}; "
              f"log1p opens mean {statistics.mean(lo):+.3f}; vias median ratio {statistics.median(vias) if vias else None}")
        out[(sub, a)] = dict(gained=gained, lost=lost, xc=xc, cov=cv)
# per board
print("\n## per board (seed 0 | seed 1): opens off/gs2/gs2r, xc, cov_opp")
for b in sorted({b for b, _ in keys}):
    cells = []
    for k in (0, 1):
        if all((b, k, a) in R for a in ARMS.values()):
            cells.append(" ".join(f"{a}:{R[(b, k, a)]['unconnected']}{'c' if R[(b, k, a)]['xc'] else ''}"
                                  f"/{(cov.get((b, k, a)) or float('nan')):.2f}" for a in ("off", "gs2", "gs2r")))
    print(f"  {'L' if b in LOSERS else 'W'} {b[:40]:40s} " + " | ".join(cells))
