# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does haslam's reader name nets, layers and pads as pcbnew does on old boards?

    python names_audit.py pick CORPUS N_OLD N_CONTROL [extra_ids.txt] > ids.txt
    $HASLAM_KICAD_WRAP python3 names_audit.py pcbnew CORPUS ids.txt > pcbnew.jsonl
    python names_audit.py haslam CORPUS ids.txt > haslam.jsonl          # PYTHONPATH picks the haslam
    python names_audit.py compare pcbnew.jsonl haslam.jsonl

Per board, both sides list (canonical layer names, positions in mm rounded to 1 um):
  nets      every net name (pcbnew: GetNetsByName; haslam: Board.nets)
  pads      [ref, x, y, number, net, attribute]
  tracks    [layer, net, start, end] for segments and arcs
  vias      [x, y, net, layers]
  zones     [net, layers] (footprint zones too; rule areas left out)
  sides     [ref, F|B]
`compare` prints, per category, the boards and items that differ (multisets; positions match
within 2 um, pcbnew's display layer names map to the file names).
pcbnew reads with PCB_IO_MGR.Load (KICAD_SEXP), haslam's writers' reader.
"""
import collections
import json
import random
import sys
from pathlib import Path

ATTR = {0: "thru_hole", 1: "smd", 2: "connect", 3: "np_thru_hole"}


def r3(v):
    return round(v, 3)


def pick(corpus, n_old, n_ctl, extra=None):
    rows = [json.loads(ln) for ln in open(Path(corpus) / "manifest.jsonl")]
    rng = random.Random(11)
    ok = [r for r in rows if (r.get("footprints") or 0) <= 600 and (r.get("tracks") or 0) >= 1]
    old = sorted(r["id"] for r in ok if (r.get("kicad_file_version") or 0) < 20211014)
    ctl = sorted(r["id"] for r in ok if r.get("kicad_file_version") == 20211014)
    ids = [x.strip() for x in open(extra) if x.strip()] if extra else []
    ids += rng.sample(old, min(n_old, len(old))) + rng.sample(ctl, min(n_ctl, len(ctl)))
    return list(dict.fromkeys(ids))


def board_path(corpus, bid):
    return Path(corpus) / "boards" / bid / "board.kicad_pcb"


def pcbnew_view(path):
    import pcbnew
    b = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, str(path))
    mm = pcbnew.ToMM
    name = b.GetStandardLayerName
    pads, sides = [], []
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        sides.append([ref, "B" if fp.GetLayer() == pcbnew.B_Cu else "F"])
        for p in fp.Pads():
            q = p.GetPosition()
            pads.append([ref, r3(mm(q.x)), r3(mm(q.y)), p.GetNumber(), p.GetNetname(),
                         ATTR.get(int(p.GetAttribute()), str(p.GetAttribute()))])
    tracks, vias = [], []
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            q = t.GetPosition()
            cu = [name(ly) for ly in t.GetLayerSet().CuStack()]
            vias.append([r3(mm(q.x)), r3(mm(q.y)), t.GetNetname(), cu])
        else:
            s, e = t.GetStart(), t.GetEnd()
            tracks.append([name(t.GetLayer()), t.GetNetname(), [r3(mm(s.x)), r3(mm(s.y))],
                           [r3(mm(e.x)), r3(mm(e.y))]])
    zones = []
    for z in list(b.Zones()) + [z for fp in b.GetFootprints() for z in fp.Zones()]:
        if z.GetIsRuleArea():
            continue
        zones.append([z.GetNetname(), sorted(name(ly) for ly in z.GetLayerSet().Seq())])
    nets = sorted(str(n) for n in b.GetNetsByName().keys() if str(n))
    return dict(nets=nets, pads=pads, tracks=tracks, vias=vias, zones=zones, sides=sides)


def haslam_view(path):
    from haslam.board import kicad_file
    b = kicad_file.load(str(path))
    pads = [[f.ref, r3(p.x), r3(p.y), p.number, p.net, p.kind] for f in b.footprints for p in f.pads]
    sides = [[f.ref, f.side] for f in b.footprints]
    tracks = [[t.layer, t.net, [r3(t.start[0]), r3(t.start[1])], [r3(t.end[0]), r3(t.end[1])]] for t in b.tracks]
    vias = [[r3(v.x), r3(v.y), v.net, list(v.layers)] for v in b.vias]
    zones = [[z.net, sorted(z.layers)] for z in b.zones]
    return dict(nets=sorted(n for n in b.nets if n), pads=pads, tracks=tracks, vias=vias, zones=zones,
                sides=sides)


def run(fn, corpus, ids_file):
    out = sys.stdout
    if fn is pcbnew_view:       # pcbnew prints to stdout; keep the JSON stream clean
        import os
        out = os.fdopen(os.dup(1), "w")
        os.dup2(2, 1)
    for bid in [x.strip() for x in open(ids_file) if x.strip()]:
        p = board_path(corpus, bid)
        try:
            row = dict(id=bid, **fn(p))
        except Exception as e:  # noqa: BLE001
            row = dict(id=bid, error=f"{type(e).__name__}: {e}")
        out.write(json.dumps(row) + "\n")
        out.flush()


# pcbnew's GetStandardLayerName gives KiCad 10's display names for some non-copper layers
DISPLAY = {"F.Silkscreen": "F.SilkS", "B.Silkscreen": "B.SilkS", "F.Adhesive": "F.Adhes", "B.Adhesive": "B.Adhes",
           "F.Courtyard": "F.CrtYd", "B.Courtyard": "B.CrtYd", "User.Drawings": "Dwgs.User",
           "User.Comments": "Cmts.User", "User.Eco1": "Eco1.User", "User.Eco2": "Eco2.User"}
TOL = 0.002   # mm: haslam's float positions and pcbnew's nm round to different sides of 1 um


def _split(x):
    """An item as (its non-numeric parts, its numbers), layer display names normalized."""
    sig, nums = [], []

    def walk(v):
        if isinstance(v, list):
            for e in v:
                walk(e)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            nums.append(float(v))
        else:
            sig.append(DISPLAY.get(v, v))
    walk(x)
    return json.dumps(sig), nums


def _unmatched(a, b):
    """Items of a and of b left over after pairing equal signatures with numbers within TOL."""
    pool = collections.defaultdict(list)
    for x in b:
        s, n = _split(x)
        pool[s].append((n, x))
    only_a = []
    for x in a:
        s, n = _split(x)
        cand = pool.get(s, [])
        i = next((i for i, (m, _) in enumerate(cand)
                  if len(m) == len(n) and all(abs(p - q) <= TOL for p, q in zip(m, n))), None)
        if i is None:
            only_a.append(x)
        else:
            cand.pop(i)
    return only_a, [x for c in pool.values() for _, x in c]


def compare(pfile, kfile):
    P = {r["id"]: r for r in map(json.loads, open(pfile))}
    K = {r["id"]: r for r in map(json.loads, open(kfile))}
    cats = ("nets", "pads", "tracks", "vias", "zones", "sides")
    tot = collections.Counter()
    boards = collections.Counter()
    errors = 0
    for bid in P:
        p, k = P[bid], K.get(bid)
        if "error" in p or k is None or "error" in k:
            errors += 1
            print("ERROR", bid, (p.get("error") or (k or {}).get("error") or "missing")[:200])
            continue
        for c in cats:
            only_p, only_k = _unmatched(p[c], k[c])
            n = len(only_p) + len(only_k)
            if n:
                tot[c] += n
                boards[c] += 1
                print(f"{c:6s} {bid[:60]:60s} pcbnew-only {len(only_p)} haslam-only {len(only_k)}"
                      f"  e.g. {json.dumps(only_p[:1])} vs {json.dumps(only_k[:1])}")
    print(f"\n{len(P)} boards, {errors} errors")
    for c in cats:
        print(f"  {c:6s} mismatched items {tot[c]:6d} on {boards[c]:3d} boards")


def main(argv):
    if argv[0] == "pick":
        print("\n".join(pick(argv[1], int(argv[2]), int(argv[3]), argv[4] if len(argv) > 4 else None)))
    elif argv[0] == "pcbnew":
        run(pcbnew_view, argv[1], argv[2])
    elif argv[0] == "haslam":
        run(haslam_view, argv[1], argv[2])
    elif argv[0] == "compare":
        compare(argv[1], argv[2])


if __name__ == "__main__":
    main(sys.argv[1:])
