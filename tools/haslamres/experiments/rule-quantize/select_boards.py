# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""rule-quantize guard boards: usable boards where the change alters what haslam writes without a binding rule.

Usage: python3 select_boards.py TAGS_DIR OUT_DIR

Q changes nothing in the DSN Freerouting gets on a board without a binding rule (its class width is rounded up to
the 0.2 um grid Freerouting kept anyway). It changes the widths haslam writes itself (critical router, last mile,
escapes, effective rules' opt): those were the class width rounded up to 0.1 um and are now the width in whole nm.
So the guard set is the usable boards with a net-class track or diff-pair width off the 0.1 um grid, plus BGA
boards whose minimum drill, via or annular ring is off it (escape's smallest legal via, which rounded to nearest).
One per repo_family, hard first (route_demand hard/extreme or pad_density very_dense/extreme), each group shuffled
by SEED. Writes guard.txt and guard.json (the reason per board).
"""
import json, random, sys

SEED = "rule-quantize-2026-11-15"
Q = 1e-4


def off(v):
    return isinstance(v, (int, float)) and v > 0 and abs(v / Q - round(v / Q)) > 1e-6


def tag(t, k):
    v = t.get(k, {})
    return v.get("value") if isinstance(v, dict) else v


def main(tags_dir, out_dir):
    use = {r["id"]: r for r in map(json.loads, open(f"{tags_dir}/usability.jsonl")) if r.get("usable_route_test")}
    tags = {r["id"]: r["tags"] for r in map(json.loads, open(f"{tags_dir}/tags.jsonl")) if r["id"] in use}
    why = {}
    for f in map(json.loads, open(f"{tags_dir}/features.jsonl")):
        bid = f.get("id")
        if bid not in use:
            continue
        r = []
        for nc in (f.get("netclasses_pro") or []) + (f.get("netclasses_legacy") or []):
            if isinstance(nc, dict):
                r += [f"{nc.get('name')}.{k}={nc[k]}" for k in ("track_width", "diff_pair_width", "trace_width")
                      if off(nc.get(k))]
        s = f.get("setup") or {}
        if tag(tags.get(bid, {}), "bga"):
            r += [f"setup.{k}={v}" for k, v in s.items() if any(x in k for x in ("drill", "via", "annul", "hole"))
                  and "micro" not in k and off(v)]
        if r:
            why[bid] = r
    rng = random.Random(SEED)
    fam = {}
    for bid in sorted(why):
        fam.setdefault(use[bid].get("repo_family") or bid, []).append(bid)

    def hard(bid):
        t = tags.get(bid, {})
        return tag(t, "route_demand") in ("hard", "extreme") or tag(t, "pad_density") in ("very_dense", "extreme")
    picks = []
    for k in sorted(fam):
        ids = fam[k]
        rng.shuffle(ids)
        ids.sort(key=lambda b: not hard(b))
        picks.append(ids[0])
    groups = [[b for b in picks if hard(b)], [b for b in picks if not hard(b)]]
    for g in groups:
        rng.shuffle(g)
    ordered = groups[0] + groups[1]
    open(f"{out_dir}/guard.txt", "w").write("\n".join(ordered) + "\n")
    json.dump({b: dict(hard=hard(b), why=why[b]) for b in ordered}, open(f"{out_dir}/guard.json", "w"), indent=1)
    print(len(why), "boards,", len(picks), "families,", len(groups[0]), "hard")


if __name__ == "__main__":
    main(*sys.argv[1:3])
