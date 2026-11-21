# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""pair_runs.py BOARDS.txt: paired per-board table of the TraceMaker trial: open connections and DRC errors above the task input's count per type (attempt 0), CPU, per arm; then pairwise counts. Results store: $KAE_RESULTS (default ~/kae-baselines)."""
import json, sys, pathlib, collections, statistics as st
import os
B = pathlib.Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines"))) / "boards"
ARMS = [("bridge", ("control-bridge-single-c2dd008-fr37b1a8b", "d3-bridge-c2dd008-fr37b1a8b-restarts")),
        ("fork", ("d3-fr-fork-37b1a8b-mp10",)), ("tm120", ("tracemaker-0-12-1-t120-d74877b",)), ("tm600", ("tracemaker-0-12-1-t600-d74877b",))]
def ev(r):
    p = r / "evals/7868e10b621b.json"
    return json.loads(p.read_text()).get("score") if p.exists() else None
boards = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
tot = collections.defaultdict(lambda: collections.Counter()); added_types = collections.defaultdict(collections.Counter)
rows = []
for b in boards:
    hb = None
    for r in sorted((B / b / "runs").glob("*")):
        c = (json.loads((r / "run.json").read_text()).get("job_steps") or {}).get("prepare", {}).get("cached")
        if c and pathlib.Path(c, "route/input/drc.json").exists():
            hb = collections.Counter(v.get("type") for v in json.loads(pathlib.Path(c, "route/input/drc.json").read_text()).get("violations") or [])
    if hb is None:
        print("no input drc for", b); hb = {}
    row = [b]
    for name, prefs in ARMS:
        xs = []
        for r in sorted((B / b / "runs").glob("*")):
            if r.name.rsplit(".", 2)[0] in prefs:
                s = ev(r); rj = json.loads((r / "run.json").read_text())
                if not s: continue
                add = {k: v - hb.get(k, 0) for k, v in (s.get("errors_by_type") or {}).items() if v > hb.get(k, 0)}
                cpu = (rj.get("method_usage") or {}).get("cpu_s") or 0
                xs.append(dict(open=s.get("unconnected"), add=sum(add.values()), types=add, clean=s.get("clean"), valid=s.get("valid"), cpu=cpu, vias=s.get("vias")))
        if not xs:
            row.append(None); continue
        x = xs[0]  # attempt 0 (cp1)
        row.append(xs)
        t = tot[name]; t["boards"] += 1; t["open"] += x["open"]; t["added"] += x["add"]; t["cpu_h"] += x["cpu"] / 3600
        t["clean"] += bool(x["open"] == 0 and x["add"] == 0); t["invalid"] += not x["valid"]
        for k, v in x["types"].items(): added_types[name][k] += v
    rows.append(row)
print("board | " + " | ".join(a for a, _ in ARMS) + "   (open/errors above the task input DRC per type, attempt 0; bridge: both seeds)")
for row in rows:
    cells = []
    for xs in row[1:]:
        cells.append("-" if not xs else " ".join(f"{x['open']}/{x['add']}" for x in xs))
    print(row[0][:42].ljust(42), " | ".join(c.ljust(12) for c in cells))
for name, _ in ARMS:
    print(name, dict(tot[name]), dict(added_types[name].most_common(8)))
# pairwise opens on boards both have
def a0(row, i): return row[i][0] if row[i] else None
idx = {a: i + 1 for i, (a, _) in enumerate(ARMS)}
for a, b in (("tm120", "bridge"), ("tm600", "bridge"), ("tm120", "fork"), ("tm600", "fork"), ("tm600", "tm120")):
    pr = [(a0(r, idx[a]), a0(r, idx[b])) for r in rows if a0(r, idx[a]) and a0(r, idx[b])]
    w = sum(x["open"] + x["add"] < y["open"] + y["add"] for x, y in pr); l = sum(x["open"] + x["add"] > y["open"] + y["add"] for x, y in pr)
    import math
    lr = [math.log((x["open"] + 1) / (y["open"] + 1)) for x, y in pr]
    print(f"{a} vs {b}: n={len(pr)} better {w} worse {l} tie {len(pr)-w-l}; opens {sum(x['open'] for x,_ in pr)} vs {sum(y['open'] for _,y in pr)}; "
          f"median log((open+1) ratio) {st.median(lr):+.2f} mean {st.mean(lr):+.2f}" if pr else f"{a} vs {b}: none")
