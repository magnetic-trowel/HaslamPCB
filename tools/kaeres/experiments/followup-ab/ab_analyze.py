# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Paired analysis of the followup-ab experiments (followup-ab.sh; decision criteria in its header).

Per method against the first (or --base), per board averaged over the attempts every arm finished:
cp1-style clean (attempt 0), any-clean (cpk), completion, legal, legal_strict, physics (kaeres physics
evaluation: valued total and its decap modules; for kae place runs also the placer's own scorecard and the
decap part of its last physics_trace stage), boards with placement shorts, ceiling hits and failed runs,
wall and CPU. Paired tests: kaebench.stats.paired (sign-flip, McNemar for binaries), clustered by repo.

  python3 ab_analyze.py EXP [--base NAME_SUBSTR] [--json OUT]
"""
import argparse
import collections
import functools
import gzip
import json
import sys
from pathlib import Path

WT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(WT / "tools/kaeres"))
sys.path.insert(0, str(WT / "bench/src"))
import kaeres as K  # noqa: E402
from kaebench import stats as ST  # noqa: E402

K.corpus_rows = functools.lru_cache(maxsize=None)(K.corpus_rows)

ap = argparse.ArgumentParser()
ap.add_argument("exp")
ap.add_argument("--base")
ap.add_argument("--json")
a = ap.parse_args()
e = K.load_exp(a.exp)
boards = (K.exp_dir(a.exp) / "boards.txt").read_text().split()
ms = e["methods"]
evs = e["evaluators"]


def last_json(run_dir):
    p = Path(run_dir) / "adapter.log.gz"
    if not p.exists():
        return {}
    try:
        lines = gzip.open(p, "rt", errors="replace").read().splitlines()
    except OSError:
        return {}
    for ln in reversed(lines):
        ln = ln.strip()
        if ln.startswith("{") and ln.endswith("}"):
            try:
                return json.loads(ln)
            except ValueError:
                continue
    return {}


def outcome(bid, m, att):
    kind = K._run_kind(dict(method_id=m["id"]))
    d, r = K.find_run(bid, m["id"], att, K.exp_task_id(e, bid, kind))
    if d is None:
        return None
    row = K.run_view(bid, d, r, evs)
    ed = K.evals_of(d)
    s = (ed.get(evs.get("drc")) or {}).get("score") or {}
    ph = ((ed.get(evs.get("physics")) or {}).get("physics")) or {}
    dec = [min(K.PHYSICS_U_CAP, max(0.0, float(v["u"]))) for k, v in (ph.get("modules") or {}).items()
           if v.get("kind") == "decap" and v.get("u") is not None]
    perr = s.get("placement_errors_strict") or s.get("placement_errors") or {}
    o = dict(status=r.get("status"), clean=bool(row.get("clean")), completion=row.get("completion"),
             legal=s.get("legal"), legal_strict=s.get("legal_strict"), physics=row.get("physics_valued_total"),
             physics_decap=round(sum(dec), 4) if dec else None,
             shorts=sum(int(v) for t, v in perr.items() if "short" in t),
             ceiling=bool((r.get("work") or {}).get("ceiling_hit") or "ceiling_hit" in json.dumps(r.get("adapter_meta") or {})),
             wall=row.get("runtime_s"), cpu=row.get("cpu_s"))
    if kind in K.PLACE_KINDS:
        rep = last_json(d)
        o["place_phys"] = (rep.get("scorecard") or {}).get("total_linear")
        tr = [t for t in rep.get("physics_trace") or [] if "by_kind" in t]
        o["place_decap"] = tr[-1]["by_kind"].get("decap", 0.0) if tr else None
        o["repair_physics"] = (rep.get("repair_physics") or {}).get("stats")
    if o["status"] != "ok":
        o["clean"] = False
    return o


data = {m["name"]: {b: [outcome(b, m, t) for t in range(e["attempts"])] for b in boards} for m in ms}
base = next((m["name"] for m in ms if a.base and a.base in m["name"]), ms[0]["name"])
repo = {b: (K.corpus_rows().get(b) or {}).get("repo") for b in boards}
# boards every arm finished every attempt (time-outs retried first): the only ones compared
complete = [b for b in boards if all(all(o is not None for o in data[m["name"]][b]) for m in ms)]


def per_board(name, key, agg="mean"):
    out = {}
    for b in complete:
        v = [o.get(key) for o in data[name][b]]
        if agg == "first":
            v = v[:1]
        v = [float(x) for x in v if x is not None]
        if v:
            out[b] = max(v) if agg == "any" else sum(v) / len(v)
    return out


def summary(name):
    runs = [o for b in complete for o in data[name][b]]
    rp = collections.Counter()
    for o in runs:
        rp.update(o.get("repair_physics") or {})

    def mean(k):
        v = [float(o[k]) for o in runs if o.get(k) is not None]
        return round(sum(v) / len(v), 4) if v else None
    return dict(runs=len(runs), status=dict(collections.Counter(o["status"] for o in runs)),
                ceiling_hits=sum(o["ceiling"] for o in runs),
                boards_with_shorts=sum(1 for b in complete if any(o["shorts"] for o in data[name][b])),
                **{k: mean(k) for k in ("clean", "completion", "legal", "legal_strict", "physics", "physics_decap",
                                        "place_phys", "place_decap", "wall", "cpu")},
                repair_physics=dict(rp) or None)


KEYS = [("clean", True, "first"), ("clean", True, "any"), ("completion", False, "mean"), ("legal", True, "mean"),
        ("legal_strict", True, "mean"), ("physics", False, "mean"), ("physics_decap", False, "mean"),
        ("place_phys", False, "mean"), ("place_decap", False, "mean"), ("shorts", False, "mean")]
res = dict(exp=a.exp, base=base, attempts=e["attempts"], boards=len(boards), complete=len(complete), methods={})
for m in ms:
    n = m["name"]
    r = dict(summary=summary(n))
    if n != base:
        for k, binary, agg in KEYS:
            A, B = per_board(base, k, agg), per_board(n, k, agg)
            common = sorted(set(A) & set(B))
            if not common:
                continue
            p = ST.paired({b: A[b] for b in common}, {b: B[b] for b in common},
                          binary=binary and agg != "mean", clusters=repo)
            r[f"{k}:{agg}"] = p
            if k in ("physics", "physics_decap", "place_phys", "place_decap"):
                rat = sorted(B[b] / A[b] for b in common if A[b] > 1e-9)
                r[f"{k}:ratio_median"] = round(rat[len(rat) // 2], 4) if rat else None
    res["methods"][n] = r

if a.json:
    Path(a.json).write_text(json.dumps(res, indent=1, default=str))


def fmt(p):
    s = f"{p['mean_a']}->{p['mean_b']} d={p['diff']:+} CI{p['ci']} p={p['p']} n={p['n']}"
    if "gained" in p:
        s += f" +{len(p['gained'])}/-{len(p['lost'])}"
    return s


print(f"== {a.exp}: {len(boards)} boards ({len(complete)} with every arm and attempt), k={e['attempts']}, base = {base}")
for n, r in res["methods"].items():
    s = r.pop("summary")
    print(f"-- {n}")
    print("   " + " ".join(f"{k}={v}" for k, v in s.items()))
    for k, v in r.items():
        print(f"   {k:28s} {fmt(v) if isinstance(v, dict) else v}")
