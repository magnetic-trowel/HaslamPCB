#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 0 (design 1): candidate mechanism suite for the layer-assignment oracle: boards with >= 4 copper layers, a
DRC-clean human layout (tag human_drc_errors.clean), opens left by the fork alone, history under 0.5 CPU-h, one per owner.
Usage: oracle_suite.py RESULTS_STORE TAGS_DIR CORPUS_MANIFEST [N] > boards.txt   (ranked by fork opens per CPU-hour)"""
import json, sqlite3, sys
from urllib.parse import urlparse
store, tags, manifest = sys.argv[1:4]; N = int(sys.argv[4]) if len(sys.argv) > 4 else 45
clean = {l.strip() for l in open(f"{tags}/suites/human_drc_errors.clean.txt") if l.strip() and not l.startswith("#")}
owner = {}
for l in open(manifest):
    r = json.loads(l); u = urlparse(r.get("repo") or ""); owner[r["id"]] = (u.netloc + "/" + (u.path.strip("/").split("/") or [""])[0]).lower()
c = sqlite3.connect(f"file:{store}/index.sqlite?mode=ro", uri=True)
q = c.execute("""select r.board, b.layers, b.footprints, e.unconnected, r.cpu_s from runs r join evals e on e.board=r.board and e.run=r.run
  join boards b on b.id=r.board where r.method_name='fr-fork master' and r.attempt=0 and b.layers>=4 and e.unconnected>0
  and r.cpu_s>0 and r.cpu_s<1800""").fetchall()
cand = sorted((x for x in q if x[0] in clean), key=lambda x: -min(x[3], 60) / max(x[4], 72.0))
seen, out = set(), []
for b, lay, fp, opens, cpu in cand:
    o = owner.get(b, b)
    if o in seen:
        continue
    seen.add(o); out.append((b, lay, fp, opens, cpu))
print(f"# {len(cand)} candidates, {len(out)} owners; first {N}: fork opens {sum(x[3] for x in out[:N])}, fork CPU-h {sum(x[4] for x in out[:N]) / 3600:.1f}, "
      f"median footprints {sorted(x[2] or 0 for x in out[:N])[min(N, len(out)) // 2]}, layers>4: {sum(1 for x in out[:N] if x[1] > 4)}", file=sys.stderr)
for x in out[:N]:
    print(x[0])
