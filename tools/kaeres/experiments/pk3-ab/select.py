# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""pk3-ab boards: python3 select.py MERIT_BOARDS.txt N > boards.txt (seed 2611).
usable_route_test, route_demand hard or extreme, not a merit board, Freerouting fork master leaving at least 10
opens in fr-baseline (restarts likely leave opens: the mechanism needs an open kept board), one per repo_family."""
import csv
import json
import os
import random
import sys

S = os.environ.get("KAE_BOARD_TAGS", "/var/tmp/" + os.environ.get("USER", "") + "/board-tags") + "/structural"
U = {json.loads(l)["id"]: json.loads(l) for l in open(f"{S}/usability.jsonl")}
T = {}
for l in open(f"{S}/tags.jsonl"):
    r = json.loads(l)
    T[r["id"]] = {k: v.get("value") for k, v in r["tags"].items()}
FB = {r["board"]: r for r in csv.DictReader(open(os.path.expanduser("~/kae-baselines/experiments/fr-baseline/results.csv")))
      if r["method"] == "fr-fork master"}
merit = set(open(sys.argv[1]).read().split())
pool = sorted(b for b, u in U.items() if u.get("usable_route_test") and b not in merit
              and T.get(b, {}).get("route_demand") in ("hard", "extreme")
              and b in FB and FB[b]["unconnected"] and int(FB[b]["unconnected"]) >= 10)
rng = random.Random(2611)
rng.shuffle(pool)
fam, out = set(), []
for b in pool:
    f = U[b].get("repo_family")
    if f in fam:
        continue
    fam.add(f)
    out.append(b)
    if len(out) >= int(sys.argv[2]):
        break
print(f"pool {len(pool)}", file=sys.stderr)
print("\n".join(out))
