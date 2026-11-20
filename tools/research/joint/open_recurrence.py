# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Do the same nets (and parts) stay open across fresh placements of one board?

Stage 0 of design 2 (coupled placement and routing). On an experiment with several fresh placements per board
(default `bus-pose-ab`), for each board with at least `--min-placements` distinct placements: the share of open-net
incidences that come from nets open in at least half the placements, and the same per part, against a permutation
baseline that keeps each placement's open count but draws the open nets (parts) at random from the board's nets
(parts). Decision line: part-attached learning across fresh attempts has something to learn when the share is
>= 30 % and well above the baseline; otherwise pressure is carried only into revisions of the kept placement.

The stored evals hold only open counts, so the per-net lists come from a DRC per stored run:
  python open_recurrence.py drc  BOARD --exp bus-pose-ab --cache DIR   # one board; queue it (kicad-cli)
  python open_recurrence.py jobs --exp bus-pose-ab --cache DIR         # prints one `drc` command per board
  python open_recurrence.py analyse --exp bus-pose-ab --cache DIR [--min-placements 6] [--perm 200] [--seed 0]
Results store: $KAE_RESULTS (default ~/kae-baselines). KiCad: $KAE_KICAD_WRAP kicad-cli.
"""
import argparse, collections, glob, gzip, hashlib, json, os, random, re, shlex, subprocess, sys, tempfile

BASE = os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
ITEM = re.compile(r"\[([^\]]*)\] of (\S+)")
REF = re.compile(r'\(property\s+"Reference"\s+"([^"]*)"')
AT = re.compile(r"\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)")
NET = re.compile(r'\(net\s+\d+\s+"([^"]*)"\)')


def board_runs(exp, board):
    ej = json.load(open(f"{BASE}/experiments/{exp}/experiment.json"))
    return sorted(rd for m in ej["methods"] for rd in glob.glob(f"{BASE}/boards/{board}/runs/*.{m['id'][:8]}.a*"))


def pcb_facts(txt):
    """(pose hash, all net names, all footprint references) of a board file's text."""
    poses, refs = [], []
    for blk in re.split(r"\n\s*\(footprint\s", txt)[1:]:
        m, r = AT.search(blk), REF.search(blk)
        ref = r.group(1) if r else "?"
        refs.append(ref)
        if m:
            poses.append((ref, round(float(m.group(1)), 3), round(float(m.group(2)), 3), round(float(m.group(3) or 0), 2)))
    nets = {n for n in NET.findall(txt) if n}
    return hashlib.sha1(repr(sorted(poses)).encode()).hexdigest()[:12], sorted(nets), sorted(set(refs))


def opens_of(drc):
    """Open nets and parts touched by open connections in a kicad-cli DRC report."""
    nets, parts = set(), set()
    for u in drc.get("unconnected_items", []):
        for it in u.get("items", []):
            m = ITEM.search(it.get("description", ""))
            if m:
                nets.add(m.group(1))
                parts.add(m.group(2))
    return sorted(nets), sorted(parts)


def cmd_drc(a):
    os.makedirs(a.cache, exist_ok=True)
    wrap = shlex.split(os.environ.get("KAE_KICAD_WRAP", ""))
    out = {}
    for rd in board_runs(a.exp, a.board):
        pcb = rd + "/output.kicad_pcb.gz"
        if not os.path.exists(pcb):
            continue
        txt = gzip.open(pcb, "rt", errors="replace").read()
        pose, nets, refs = pcb_facts(txt)
        with tempfile.TemporaryDirectory(dir=a.tmp) as td:
            f = os.path.join(td, "b.kicad_pcb")
            open(f, "w").write(txt)
            rep = os.path.join(td, "drc.json")
            subprocess.run(wrap + ["kicad-cli", "pcb", "drc", "--format", "json", "--output", rep, f],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=a.timeout)
            try:
                on, op = opens_of(json.load(open(rep)))
            except (OSError, ValueError):
                continue
        out[os.path.basename(rd)] = dict(pose=pose, nets=nets, refs=refs, open_nets=on, open_parts=op)
    json.dump(out, open(os.path.join(a.cache, a.board + ".json"), "w"))


def cmd_jobs(a):
    me = os.path.abspath(__file__)
    for b in open(f"{BASE}/experiments/{a.exp}/boards.txt").read().split():
        print(f"python3 {me} drc {b} --exp {a.exp} --cache {a.cache}")


def recurrence(sets, perm, rng, universes):
    """Share of incidences from items open in >= half the placements; and its permutation-baseline mean.
    sets: list of open-item sets, one per placement; universes: the items each draw may pick from."""
    def share(ss):
        c = collections.Counter(x for s in ss for x in s)
        tot = sum(c.values())
        if not tot:
            return None, 0
        rec = sum(v for v in c.values() if v >= len(ss) / 2)
        return rec / tot, tot
    obs, tot = share(sets)
    if obs is None:
        return None, None, 0
    base = []
    for _ in range(perm):
        ss = [set(rng.sample(universes, min(len(s), len(universes)))) for s in sets]
        base.append(share(ss)[0])
    return obs, sum(base) / len(base), tot


def cmd_analyse(a):
    rng = random.Random(a.seed)
    rows = []
    for f in sorted(glob.glob(os.path.join(a.cache, "*.json"))):
        runs = json.load(open(f))
        byp = {}
        for name in sorted(runs):           # one run per distinct placement
            byp.setdefault(runs[name]["pose"], runs[name])
        if len(byp) < a.min_placements:
            continue
        pl = list(byp.values())
        row = dict(board=os.path.basename(f)[:-5], placements=len(pl))
        for kind, uni in (("net", "nets"), ("part", "refs")):
            u = sorted(set().union(*(p[uni] for p in pl)))
            o, b, t = recurrence([set(p[f"open_{kind}s"]) for p in pl], a.perm, rng, u)
            row.update({f"{kind}_share": o, f"{kind}_base": b, f"{kind}_incidences": t})
        rows.append(row)
    for kind in ("net", "part"):
        rs = [r for r in rows if r[f"{kind}_share"] is not None]
        w = sum(r[f"{kind}_incidences"] for r in rs)
        if not w:
            print(f"{kind}: no open incidences on {len(rows)} boards")
            continue
        obs = sum(r[f"{kind}_share"] * r[f"{kind}_incidences"] for r in rs) / w
        base = sum(r[f"{kind}_base"] * r[f"{kind}_incidences"] for r in rs) / w
        bs = []
        for _ in range(1000):               # board bootstrap of the pooled share
            s = [rs[rng.randrange(len(rs))] for _ in rs]
            ww = sum(r[f"{kind}_incidences"] for r in s)
            bs.append(sum(r[f"{kind}_share"] * r[f"{kind}_incidences"] for r in s) / ww if ww else 0)
        bs.sort()
        print(f"{kind}: recurrent share {obs:.3f} (board-bootstrap 95 % {bs[25]:.3f}-{bs[974]:.3f}), permutation "
              f"baseline {base:.3f}, {len(rs)} boards, {w} incidences; decision line >= 0.30 and well above baseline")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=("drc", "jobs", "analyse"))
    p.add_argument("board", nargs="?")
    p.add_argument("--exp", default="bus-pose-ab")
    p.add_argument("--cache", required=True)
    p.add_argument("--tmp", default=None)
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--min-placements", type=int, default=6)
    p.add_argument("--perm", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json")
    a = p.parse_args(argv)
    {"drc": cmd_drc, "jobs": cmd_jobs, "analyse": cmd_analyse}[a.mode](a)


if __name__ == "__main__":
    sys.exit(main())
