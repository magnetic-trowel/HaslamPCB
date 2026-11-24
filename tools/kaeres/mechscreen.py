#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mechanism screen: count, per board, how often a candidate change's situation occurs, from the
prepared route input alone (no routing), so an experiment's suite is chosen by measurement.

    mechscreen.py --screen thermal-ring --screen netrules --boards @ids.txt --out screen.jsonl
    mechscreen.py --list                       # the screens
    mechscreen.py --top screen.jsonl [--screen S] [-n 40]   # boards by count

Output: one JSON line per board and screen, {board, screen, count, examples, source, s, ...};
`count` is the number of places on the board where the change can act (0: the change cannot
act there, the pair would come out identical). A board that fails gives {board, screen, error}.

Input board, in order: the route task's input in the local task cache
($KAERES_TASK_CACHE, default /var/tmp/$USER/kaeres-task-cache, `<id>.*/route/input/`), else a
copy of the corpus board (`$KAE_BOARDS`, default ~/kae-boards/boards/<id>/, read-only). The
board's routing does not enter any screen here. KiCad is read once per board
(kae.board.pcbnew_io.export_dsn, without probes); `--info-cache DIR` keeps that export
(gzip JSON) so later screens of the same boards need no KiCad.

Screens are functions `screen(ctx) -> dict(count=, examples=[...], **extra)`, registered in
SCREENS. A screen that compares the tag's code with a candidate commit loads the candidate's
module from git (`variant_module`): the tool runs with the tag's kae on PYTHONPATH and never
imports a candidate into kae's own namespace."""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCREENS = {}


def screen(name, doc):
    def deco(fn):
        SCREENS[name] = (fn, doc)
        return fn
    return deco


# ----------------------------------------------------------------------------- inputs
def task_cache_root():
    return Path(os.environ.get("KAERES_TASK_CACHE") or
                Path("/var/tmp") / (os.environ.get("USER") or str(os.getuid())) / "kaeres-task-cache")


def corpus_root():
    return Path(os.environ.get("KAE_BOARDS") or Path.home() / "kae-boards" / "boards")


def find_input(bid):
    """(board folder, source): the newest cached route input of board `bid`, else its corpus folder."""
    root = task_cache_root()
    best = None
    if root.is_dir():
        for d in root.glob(f"{bid}.*"):
            if d.name.rsplit(".", 1)[0] != bid:
                continue
            pcb = d / "route" / "input" / "board.kicad_pcb"
            if pcb.is_file() and (best is None or pcb.stat().st_mtime > best[0]):
                best = (pcb.stat().st_mtime, pcb.parent)
    if best:
        return best[1], "task-cache:" + best[1].parents[1].name
    c = corpus_root() / bid
    if (c / "board.kicad_pcb").is_file():
        return c, "corpus"
    raise FileNotFoundError(f"{bid}: no cached route input and no corpus board")


class Ctx:
    """One board: its input folder (copied to a scratch folder: KiCad may write next to it),
    the KiCad export (`info`, lazy) and the .kicad_dru rules (`dru`, lazy)."""

    def __init__(self, bid, scratch, info_cache=None):
        self.bid = bid
        src, self.source = find_input(bid)
        self.dir = Path(scratch) / bid
        shutil.copytree(src, self.dir, ignore=shutil.ignore_patterns("drc.json", "*.kicad_prl"))
        pcbs = sorted(self.dir.glob("*.kicad_pcb"))
        self.pcb = self.dir / "board.kicad_pcb" if (self.dir / "board.kicad_pcb").exists() else pcbs[0]
        self.info_cache = Path(info_cache) if info_cache else None
        self._info = self._dru = None

    @property
    def info(self):
        if self._info is None:
            f = self.info_cache / f"{self.bid}.json.gz" if self.info_cache else None
            if f is not None and f.exists():
                self._info = json.loads(gzip.decompress(f.read_bytes()))
            else:
                from kae.board import pcbnew_io as P
                self._info = P.export_dsn(str(self.pcb), str(self.dir / "board.dsn"), probes=False)
                if not self._info or not self._info.get("pads"):
                    raise RuntimeError("KiCad export gave no pads")
                if f is not None:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    tmp = f.with_suffix(f".{os.getpid()}.tmp")
                    tmp.write_bytes(gzip.compress(json.dumps(self._info).encode()))
                    os.replace(tmp, f)
        return self._info

    @property
    def dru(self):
        """The board's custom rules ([] without a .kicad_dru)."""
        if self._dru is None:
            from kae.board.kicad_file import read_dru
            fs = sorted(self.dir.glob("*.kicad_dru"))
            self._dru = read_dru(fs[0]) if fs else []
        return self._dru


_variants = {}


def variant_module(commit, relpath, name):
    """Module `name` (e.g. 'kae.route.constraints_3eb6a72f') loaded from kae/src/`relpath` as it is at
    `commit` of this repository, inside the tag's package (relative imports resolve to the tag's
    modules). The source is read once per process."""
    key = (commit, relpath, name)
    if key not in _variants:
        src = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:kae/src/{relpath}"],
                             check=True, capture_output=True, text=True).stdout
        d = Path(tempfile.mkdtemp(prefix="mechscreen-"))
        f = d / Path(relpath).name
        f.write_text(src)
        spec = importlib.util.spec_from_file_location(name, f)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _variants[key] = mod
    return _variants[key]


def _pad_name(p):
    return f"{p.get('ref')}.{p.get('number')}"


# ----------------------------------------------------------------------------- screens
THERMAL_RING_COMMIT = os.environ.get("MECHSCREEN_THERMAL_RING", "3eb6a72f")


@screen("thermal-ring", "other nets' pads whose copper the tag's thermal-spoke corridors (kae.route.constraints."
                        "thermal_corridors, zero-clearance keepouts for the router) cover by at least 10 % of its "
                        "area, and gfix-thermal-ring 3eb6a72f's by less (its relief ring keeps out other nets' pads "
                        "within the zone clearance); pads of nets with two or more pads only. The neighbours of a "
                        "fine-pitch zone pin under a wide zone clearance (solar-small's DAC I2C pins 6 and 8; "
                        "barsy ah3's SPI pins beside U1.3 and U2.3, open in every control seed). Extra: "
                        "`freed_frac` the summed covered fraction those pads lose, `cover` pads with any covered "
                        "copper freed, `shut` pads whose every straight way out (a minimum-width lane along the "
                        "pad's axes crossing no other net's pad, as thermal_corridors' free_lanes) crosses a tag "
                        "corridor and not at the candidate, `differ` zone pads whose corridor changes at all, "
                        "`corridors` at the tag")
def screen_thermal_ring(ctx, frac=0.1):
    import math
    import shapely
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from kae.route import constraints as CN
    V = variant_module(THERMAL_RING_COMMIT, "kae/route/constraints.py",
                       f"kae.route.constraints_{THERMAL_RING_COMMIT[:8]}")
    info = ctx.info
    base, new = CN.thermal_corridors(info, None), V.thermal_corridors(info, None)
    old_k = {(p.get("uuid"), l): g for g, l, p in base}
    new_k = {(p.get("uuid"), l): g for g, l, p in new}
    differ = sum(1 for k in set(old_k) | set(new_k)
                 if (old_k.get(k) is None) != (new_k.get(k) is None)
                 or (old_k.get(k) is not None and old_k[k].symmetric_difference(new_k[k]).area > 1e-6))

    def by_net(cors):           # {(layer, zone net): union of its pads' corridors}
        d = {}
        for g, l, p in cors:
            d.setdefault((l, p.get("net")), []).append(g)
        return {k: unary_union(v) for k, v in d.items()}
    ub, un = by_net(base), by_net(new)
    npads = {}
    for p in info["pads"]:
        if p.get("net"):
            npads[p["net"]] = npads.get(p["net"], 0) + 1
    lane_w = max(info["settings"].get("min_track") or 0.0, 0.1)
    count = cover = shut = 0
    freed_frac, ex = 0.0, []
    for l in sorted({l for l, _ in ub}):
        items = [(q, CN._pad_shapes(q)[1].get(l)) for q in info["pads"] if q.get("net")]
        items = [(q, c) for q, c in items if c is not None and not c.is_empty and c.area > 0]
        tree = shapely.STRtree([c for _, c in items])
        cb = [(n, g) for (ll, n), g in ub.items() if ll == l]
        cn = [(n, g) for (ll, n), g in un.items() if ll == l]
        reach = unary_union([g for _, g in cb])
        for i in tree.query(reach, predicate="intersects"):
            q, c = items[int(i)]
            if npads.get(q["net"], 0) < 2:
                continue
            ob = unary_union([g for n, g in cb if n != q["net"]])
            onw = unary_union([g for n, g in cn if n != q["net"]])
            fb = ob.intersection(c).area / c.area if not ob.is_empty else 0.0
            fn = onw.intersection(c).area / c.area if not onw.is_empty else 0.0
            if fb <= 1e-6:
                continue
            if fn < fb - 1e-6:
                cover += 1
            if fb >= frac and fn < frac:
                count += 1
                freed_frac += fb - fn
                if len(ex) < 10:
                    ex.append(dict(pad=_pad_name(q), net=q["net"], layer=l, covered=round(fb, 3),
                                   covered_new=round(fn, 3)))
            cx, cy = q["pos"]
            x0, y0, x1, y1 = c.bounds
            far = max(x1 - cx, cx - x0, y1 - cy, cy - y0) + 1.0
            lanes = []
            for k in range(4):
                ang = math.radians((q.get("orient") or 0.0) + 90 * k)
                lane = LineString([(cx, cy), (cx + far * math.cos(ang), cy - far * math.sin(ang))]).buffer(
                    lane_w / 2, cap_style="flat")
                if any(o is not q and o["net"] != q["net"] and og.intersects(lane)
                       for o, og in (items[int(j)] for j in tree.query(lane))):
                    continue
                lanes.append(lane.difference(c))
            hit = lambda g, x: not g.is_empty and g.intersection(x).area > 1e-6
            if lanes and all(hit(ob, x) for x in lanes) and not all(hit(onw, x) for x in lanes):
                shut += 1
    return dict(count=count, examples=ex, freed_frac=round(freed_frac, 3), cover=cover, shut=shut,
                differ=differ, corridors=len(base), zones=len(info.get("zones") or []))


@screen("netrules", "pad pairs (different nets, shared copper layer, edge gap under the rule's clearance + 0.5 mm) "
                    "whose clearance a net-conditioned .kicad_dru rule (kae.board.dru_cond of gfix-place-netrules "
                    "5ee3486e) makes stricter than their net classes; extra: tight (gap already under the rule + "
                    "0.1 mm), net_pairs, rules (net-conditioned clearance rules dru_cond evaluates), unparsed")
def screen_netrules(ctx, margin=0.5):
    import shapely
    from kae.route import constraints as CN
    rules = ctx.dru
    if not rules:
        return dict(count=0, examples=[], rules=0, unparsed=0, tight=0, net_pairs=0)
    try:
        import kae.board.dru_cond as DC
    except ImportError:
        DC = variant_module(NETRULES_COMMIT, "kae/board/dru_cond.py", "kae.board.dru_cond")
    nr, unparsed = [], 0
    for n, r in enumerate(rules):
        vals = [c["min"] for c in r.get("constraints", []) if c.get("type") == "clearance"
                and isinstance(c.get("min"), (int, float))]
        if not vals:
            continue
        ast = DC.parse(r.get("condition") or "")
        if ast is None:
            unparsed += 1
            continue
        if not (DC.kinds(ast) & DC.NET_KINDS):
            continue
        lay = (r.get("layer") or "").strip()
        nr.append((n, ast, float(vals[0]), lay, r.get("name")))
    if not nr:
        return dict(count=0, examples=[], rules=0, unparsed=unparsed, tight=0, net_pairs=0)
    info = ctx.info
    ncls, nets = info.get("netclasses") or {}, info.get("nets") or {}
    nc_clr = lambda net: (ncls.get((nets.get(net) or {}).get("netclass") or "Default") or {}).get("clearance") or 0.0
    item = lambda p: DC.Item(net=p.get("net") or "", netclass=(nets.get(p.get("net")) or {}).get("netclass") or "Default",
                             ref=p.get("ref") or "", lib=p.get("lib") or "")
    reach = max(r[2] for r in nr) + margin
    rule_of = {}
    count, tight, net_pairs, ex = 0, 0, set(), []
    layers = sorted({l for p in info["pads"] for l in p.get("layers") or []})
    for l in layers:
        items = [(p, CN._pad_shapes(p)[1].get(l)) for p in info["pads"] if p.get("net")]
        items = [(p, g) for p, g in items if g is not None and not g.is_empty]
        if len(items) < 2:
            continue
        geoms = [g for _, g in items]
        tree = shapely.STRtree(geoms)
        ia, ib = tree.query(geoms, predicate="dwithin", distance=reach)
        for i, j in zip(ia.tolist(), ib.tolist()):
            if j <= i:
                continue
            (pa, ga), (pb, gb) = items[i], items[j]
            if pa["net"] == pb["net"]:
                continue
            key = (min(pa["net"], pb["net"]), max(pa["net"], pb["net"]), pa.get("ref"), pb.get("ref"), l)
            if key not in rule_of:
                hit = None
                for n, ast, mn, lay, name in nr:     # KiCad: the last matching rule wins
                    if lay and lay != l and not (lay == "outer" and l in ("F.Cu", "B.Cu")):
                        continue
                    if DC.pair_matches(ast, item(pa), item(pb)):
                        hit = (mn, name)
                rule_of[key] = hit
            hit = rule_of[key]
            if hit is None:
                continue
            base = max(nc_clr(pa["net"]), nc_clr(pb["net"]))
            d = ga.distance(gb)
            if hit[0] > base + 1e-6 and d < hit[0] + margin:
                count += 1
                net_pairs.add(key[:2])
                if d < hit[0] + 0.1:
                    tight += 1
                if len(ex) < 10:
                    ex.append(dict(a=_pad_name(pa), b=_pad_name(pb), nets=[pa["net"], pb["net"]], layer=l,
                                   gap=round(d, 4), rule=hit[1], min=hit[0], netclass=base))
    return dict(count=count, examples=ex, rules=len(nr), unparsed=unparsed, tight=tight, net_pairs=len(net_pairs))


NETRULES_COMMIT = os.environ.get("MECHSCREEN_NETRULES", "5ee3486e")


# ----------------------------------------------------------------------------- driver
def read_ids(spec):
    out = []
    for s in spec:
        if s.startswith("@"):
            out += [ln.split()[0] for ln in Path(s[1:]).read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        else:
            out += [x for x in s.split(",") if x]
    return list(dict.fromkeys(out))


def run(ids, screens, out, info_cache=None, scratch=None):
    done = set()
    if Path(out).exists():                    # resume: boards already screened are skipped
        for ln in Path(out).read_text().splitlines():
            try:
                r = json.loads(ln)
                done.add((r["board"], r["screen"]))
            except (ValueError, KeyError):
                pass
    with open(out, "a") as fo:
        for bid in ids:
            todo = [s for s in screens if (bid, s) not in done]
            if not todo:
                continue
            with tempfile.TemporaryDirectory(prefix="mechscreen-", dir=scratch) as tmp:
                try:
                    ctx = Ctx(bid, tmp, info_cache)
                except Exception as e:  # noqa: BLE001 - one board's failure is its record
                    for s in todo:
                        fo.write(json.dumps(dict(board=bid, screen=s, error=f"{type(e).__name__}: {e}")) + "\n")
                    fo.flush()
                    continue
                for s in todo:
                    t0 = time.monotonic()
                    try:
                        r = dict(board=bid, screen=s, **SCREENS[s][0](ctx))
                    except Exception as e:  # noqa: BLE001
                        r = dict(board=bid, screen=s, error=f"{type(e).__name__}: {e}",
                                 trace=traceback.format_exc(limit=3)[-600:])
                    r.update(source=ctx.source, s=round(time.monotonic() - t0, 2))
                    fo.write(json.dumps(r) + "\n")
                    fo.flush()
                    print(f"{bid} {s} {r.get('count', r.get('error'))} {r['s']}s", flush=True)


def top(files, screen_name=None, n=40):
    rows = []
    for f in files:
        for ln in Path(f).read_text().splitlines():
            r = json.loads(ln)
            if screen_name is None or r["screen"] == screen_name:
                rows.append(r)
    for s in sorted({r["screen"] for r in rows}):
        rs = [r for r in rows if r["screen"] == s]
        ok = [r for r in rs if "count" in r]
        pos = sorted([r for r in ok if r["count"] > 0], key=lambda r: -r["count"])
        tot = sum(r["count"] for r in pos)
        top10 = sum(r["count"] for r in pos[:max(1, len(ok) // 10)])
        print(f"{s}: {len(rs)} boards, {len(rs) - len(ok)} errors, {len(pos)} with count > 0, total {tot}, "
              f"top tenth of boards hold {top10 / tot:.0%}" if tot else f"{s}: {len(rs)} boards, none > 0")
        for r in pos[:n]:
            extra = {k: v for k, v in r.items() if k not in ("board", "screen", "count", "examples", "source", "s")}
            print(f"  {r['count']:6d}  {r['board']}  {json.dumps(extra)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screen", action="append", choices=sorted(SCREENS))
    ap.add_argument("--boards", action="append", help="ids, comma lists or @file (repeatable)")
    ap.add_argument("--out", help="JSONL to append to (boards already in it are skipped)")
    ap.add_argument("--info-cache", help="folder for the KiCad export per board (reused by later screens)")
    ap.add_argument("--scratch", help="folder for the per-board copy (default: the system temp)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--top", nargs="+", metavar="JSONL")
    ap.add_argument("-n", type=int, default=40)
    a = ap.parse_args(argv)
    if a.list:
        for k, (_, doc) in sorted(SCREENS.items()):
            print(f"{k}: {doc}")
        return 0
    if a.top:
        top(a.top, (a.screen or [None])[0], a.n)
        return 0
    if not (a.screen and a.boards and a.out):
        ap.error("--screen, --boards and --out are needed")
    run(read_ids(a.boards), a.screen, a.out, a.info_cache, a.scratch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
