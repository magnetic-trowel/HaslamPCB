# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0, design 2: spread of opens across placement seeds (ST and JL fresh first-wave attempts: placement
# re-drawn) versus routing seeds (BR fresh first-wave attempts: human placement fixed), per board class, from
# restarts.json of s2-merit213; and the cost of one fresh attempt. Read-only, stdlib.
# Usage: python open_variance.py [--write DIR] [--bus-pose bus-pose-ab]   (results store: $KAE_RESULTS)
import collections, csv, glob, gzip, hashlib, json, math, os, re, statistics as st, sys
BASE = os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
M = {"ST": "f596297c", "JL": "3634e663", "BR": "90a34137"}
R = {}
for r in csv.DictReader(open(BASE + "/experiments/s2-merit213/results.csv")):
    if r["attempt"] == "0":
        R[(r["board"], r["method_id"][:8])] = r
def opens(b, m):
    r = R.get((b, M[m]))
    try: return int(float(r["unconnected"])) if r and r["status"] == "ok" else None
    except ValueError: return None
boards = sorted({b for b, _ in R})
cls = {}
for b in boards:
    s, h = opens(b, "ST"), opens(b, "BR")
    cls[b] = "none" if s is None or h is None else "P22" if s > 0 and h == 0 else "P47-other" if s > h else "P10" if s < h else "both-open-equal" if s > 0 else "both-clean"
def band(b):
    p = float(R[(b, M["BR"])]["pads"]) if (b, M["BR"]) in R else float("nan")
    return "<=150" if p <= 150 else "150-400" if p <= 400 else "400-1000" if p <= 1000 else ">1000"
def first_wave(b, m):
    ds = glob.glob(f"{BASE}/boards/{b}/runs/*.{M[m]}.a0/restarts.json")
    if not ds: return []
    try: j = json.load(open(ds[0]))
    except Exception: return []
    al = [a for a in j.get("attempt_log", []) if isinstance(a.get("k"), int) and a.get("rank") and a.get("resumed_from") is None]
    if not al: return []
    b0 = min(a["budget"] for a in al)
    return [(a["rank"][2], a.get("cpu_s") or 0) for a in al if a["budget"] == b0 and a["rank"][0] == 0]
D = {m: {b: first_wave(b, m) for b in boards} for m in M}
def summ(m, sel, label):
    cv, sdl, cpu, n = [], [], [], 0
    for b in sel:
        w = D[m][b]
        o = [x[0] for x in w]
        if len(o) >= 3 and st.mean(o) > 0:
            n += 1
            cv.append(st.pstdev(o) / st.mean(o))
            sdl.append(st.stdev([math.log1p(x) for x in o]))
            cpu.append(st.median(x[1] for x in w) / 3600)
    if n >= 3:
        print(f"   {label:28s} {m}: boards {n:3d}  CV median {st.median(cv):.3f}  SD of log1p(opens) median {st.median(sdl):.3f} "
              f"mean {st.mean(sdl):.3f} rms {math.sqrt(st.mean(x * x for x in sdl)):.3f}  CPU-h per fresh attempt median {st.median(cpu):.3f} sum {sum(cpu):.1f}")
    return sdl
print("== all boards with >= 3 valid first-wave fresh attempts and non-zero mean opens")
for m in M: summ(m, boards, "all")
print("== by pad band")
for bd in ("<=150", "150-400", "400-1000", ">1000"):
    for m in M: summ(m, [b for b in boards if band(b) == bd], bd)
print("== by layers")
for L, f in (("2 layers", lambda x: x == "2"), ("4+ layers", lambda x: x != "2")):
    for m in M: summ(m, [b for b in boards if (b, M["BR"]) in R and f(R[(b, M["BR"])]["layers"])], L)
print("== by set (ST vs BR final opens)")
for c in ("P22", "P47-other", "P10", "both-open-equal", "both-clean"):
    for m in M: summ(m, [b for b in boards if cls[b] == c], c)
print("== P47 (P22 + other) restricted to <= 400 pads: the sprint-sized placement-fixable suite")
sel = [b for b in boards if cls[b] in ("P22", "P47-other") and band(b) in ("<=150", "150-400")]
print("   boards", len(sel))
for m in M: summ(m, sel, "P47 <= 400 pads")
sel2 = [b for b in boards if cls[b] in ("P22", "P47-other", "P10") and band(b) in ("<=150", "150-400")]
for m in ("JL",):
    sd = summ(m, sel2, "P47+P10 <= 400 pads")
    if sd:
        rms = math.sqrt(st.mean(x * x for x in sd))
        for n, s in ((len(sel2), 1), (len(sel2), 3), (len(sel2), 5)):
            mde = 2.8 * rms * math.sqrt(2) / math.sqrt(n * s)
            print(f"   paired A/B, {n} boards x {s} seeds, independent placements per arm: MDE on mean dlog1p(opens) {mde:.3f} "
                  f"= {100 * (1 - math.exp(-mde)):.0f} % fewer (1+opens); sd of one board-seed difference {rms * math.sqrt(2):.3f}")
# first-wave cost of one fresh JL attempt on those boards
c = [st.median(x[1] for x in D["JL"][b]) / 3600 for b in sel2 if D["JL"][b]]
if c: print(f"   one fresh JL attempt on them: median {st.median(c):.3f} CPU-h, sum over {len(c)} boards {sum(c):.1f} CPU-h; max {max(c):.2f}")
if "--write" in sys.argv:
    open(os.path.join(sys.argv[sys.argv.index("--write") + 1], "place-fixable-le400.txt"), "w").write("\n".join(sel2) + "\n")


# Duplicate-placement decomposition (default experiment bus-pose-ab): runs of one board whose footprint poses are
# identical differ only by routing, so their spread of opens is routing noise; the spread across distinct
# placements is placement + routing.
REF = re.compile(r'\(property\s+"Reference"\s+"([^"]*)"')


def pose_key(pcb_gz):
    """Hash of every footprint's reference, position and rotation (rounded to 1 um / 0.01 deg)."""
    txt = gzip.open(pcb_gz, "rt", errors="replace").read()
    poses = []
    for blk in re.split(r"\n\s*\(footprint\s", txt)[1:]:
        m = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)', blk)
        r = REF.search(blk)
        if m:
            poses.append((r.group(1) if r else "?", round(float(m.group(1)), 3), round(float(m.group(2)), 3),
                          round(float(m.group(3) or 0), 2)))
    return hashlib.sha1(repr(sorted(poses)).encode()).hexdigest()[:12]


def run_opens(rd):
    for e in glob.glob(rd + "/evals/*.json"):
        try:
            sc = json.load(open(e)).get("score", {})
        except Exception:
            continue
        if "unconnected" in sc and sc.get("valid", True):
            return int(sc["unconnected"])
    return None


def decompose(exp):
    ej = json.load(open(f"{BASE}/experiments/{exp}/experiment.json"))
    mids = [m["id"][:8] for m in ej["methods"]]
    within, across, ngroups = [], [], collections.Counter()
    for b in open(f"{BASE}/experiments/{exp}/boards.txt").read().split():
        runs = [rd for m in mids for rd in glob.glob(f"{BASE}/boards/{b}/runs/*.{m}.a*")]
        g = collections.defaultdict(list)
        for rd in runs:
            o, pcb = run_opens(rd), rd + "/output.kicad_pcb.gz"
            if o is not None and os.path.exists(pcb):
                g[pose_key(pcb)].append(math.log1p(o))
        ngroups[sum(1 for v in g.values() if len(v) > 1)] += 1
        for v in g.values():
            if len(v) > 1:
                within.append(st.variance(v))
        means = [st.mean(v) for v in g.values()]
        if len(means) > 1:
            across.append(st.variance([x for v in g.values() for x in v]))
    print(f"== duplicate-placement decomposition on {exp}: boards by number of repeated-pose groups {dict(ngroups)}")
    if within:
        print(f"   routing noise (identical poses): mean var log1p(opens) {st.mean(within):.3f} over {len(within)} groups")
    if across:
        print(f"   placement + routing (all runs of a board): mean var log1p(opens) {st.mean(across):.3f} over {len(across)} boards")


if "--bus-pose" in sys.argv:
    decompose(sys.argv[sys.argv.index("--bus-pose") + 1])
