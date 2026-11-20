# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Conflict-set closure: the last mile's joint rip-up for boards left a few opens from clean.

After Freerouting, repair and the last mile, about 20-25 boards per method are left 1-5 opens
from clean, and kae.route.blocked calls most of those opens "congestion": a legal path exists
once our own copper of other nets is taken out. The path crosses few of our nets (median 2-3;
design 4, stage 0). The last mile's rip-up (lastmile._join) rips what one soft search crosses
and re-joins the ripped nets one at a time; the opens left are those that order fails on.

`run` differs from it in three ways:

1. The set is solved jointly. For an open connection c: the path with our other copper taken
   out (as blocked._one finds it), its conflict set K (our nets whose copper the path
   violates), shrunk greedily (a net of K is put back when a path still exists without it).
   K's copper near the path is ripped (a net's whole copper when it has at most
   `closure_whole_net_items` tracks and vias, else the run of tracks and vias between the
   junctions or pads on either side of each crossing). S = c plus every connection the rip
   opened is routed with everything else fixed, in every order (|S| <= 4) or in
   `closure_orders` seeded orders (shortest first, longest first, then shuffles); the first
   order that routes all of S wins. When every order fails on some connection x, x's own
   conflict set is added to K (at most `closure_max_nets` nets) and the solve is tried again,
   `closure_depth` levels at most.
2. All or nothing. The new copper stays only when every connection of S is routed, the
   missing connections of the nets touched went down, and no new item breaks a rule against
   the space; otherwise the space is put back exactly as it was. Input copper (`fixed`),
   locked or critical copper (`soft`) and zone fills are never ripped: a set that needs them
   is recorded as "needs fixed copper".
3. It reports: one record per open connection tried (net, pads, conflict nets before and
   after shrinking, |S|, orders tried, depth, seconds, outcome, the connection that failed
   most often). A failed exhaustive enumeration (|S| <= 4) is labelled "exhausted-orders":
   evidence of local infeasibility bounded by the grid and the windows, never proof.

Off by default (setting `closure`, constraints.DEFAULTS; project text variable KAE_CLOSURE or
env KAE_CLOSURE); lastmile.close calls it at its end on boards with 1..`closure_max_opens`
missing connections on the nets it was given. Lengths are mm.
"""
from __future__ import annotations

import itertools
import random

from shapely.geometry import box
from shapely.ops import unary_union

from kae.budget import charge
from kae.budget import now as clock_now

from . import lastmile as LM

OUTCOMES = ("closed", "no path without our copper", "needs fixed copper", "set too large",
            "joint solve failed", "time")
KNOBS = dict(closure_whole_net_items=40, closure_orders=24, closure_max_nets=6, closure_depth=2,
             closure_max_opens=5)
EPS = 1e-4


def settings(board_path=None, opts=None):
    """{"closure": bool, knob: value} from the project / opts / env (constraints.setting_env)."""
    from . import constraints as CN
    out = {"closure": bool(float(CN.setting_env("closure", board_path, opts) or 0))}
    for k, d in KNOBS.items():
        out[k] = int(float(CN.setting_env(k, board_path, opts) or d))
    return out


# ----------------------------------------------------------------------------- copper sets
def _foreign(sp, net):
    """Tracks and vias of other nets in the space."""
    return [it for it in sp.existing + sp.routed if it.kind in ("track", "via") and it.net and it.net != net]


def _rippable(it, fixed, soft):
    """Ours to rip: not input copper, not critical copper, not locked (unless this last mile laid it)."""
    if it.uuid in fixed or it.uuid in soft:
        return False
    return LM._own(it) or not it.locked


def _path(gr, sp, net, src, others, widths):
    """A route (not kept in the space) from `src` to `others`, or None."""
    x0, y0, x1, y1 = LM._bounds(src)
    wide = box(x0 - LM.WIDE, y0 - LM.WIDE, x1 + LM.WIDE, y1 + LM.WIDE)
    for win in [LM._window(src, others, m) for m in LM.MARGINS] + [wide]:
        got = LM._try(gr, sp, net, src, others, win, widths)
        if got:
            sp.remove(got[1])
            return got[0]
    return None


def _hits(sp, net, rt, pool):
    """{net: [items]} of `pool` (items currently out of the space) that route `rt` would violate."""
    ids = {id(it) for it in pool}
    LM._restore(sp, pool)
    out = {}
    try:
        seen = set()

        def note(vs):
            for it, _d, _nd in vs:
                if it == "edge" or id(it) not in ids or id(it) in seen:
                    continue
                seen.add(id(it))
                out.setdefault(it.net, []).append(it)
        for i, (l, a, b) in enumerate(rt.segs):
            note(sp.track_violations(net, l, rt.seg_w(i), a, b))
        for (x, y) in rt.vias:
            note(sp.via_violations(net, x, y))
    finally:
        sp.remove(pool)
    return out


def _ends(it):
    if it.kind == "track":
        c = list(it.geom.coords)
        return [(c[0], it.layers), (c[-1], it.layers)]
    return [((it.geom.x, it.geom.y), it.layers)]


def _run(sp, net, hit, whole_max, fixed, soft):
    """The copper of `net` to rip for crossings `hit`: all of it (at most whole_max tracks and
    vias, all rippable), else the connected run of each crossing up to the pads and junctions
    (points where a pad of the net lies or more than two items meet)."""
    mine = [it for it in sp.existing + sp.routed if it.net == net and it.kind in ("track", "via")]
    if len(mine) <= whole_max and all(_rippable(it, fixed, soft) for it in mine):
        return mine
    pads = [it for it in sp.pads if it.net == net]

    def at(pt, layers):
        from shapely.geometry import Point
        p = Point(pt)
        items = [it for it in mine if set(it.layers) & layers and it.geom.distance(p) <= (it.r if it.kind == "via" else 0) + EPS
                 and (it.kind == "via" or any(Point(e).distance(p) <= EPS for e, _ in _ends(it)))]
        on_pad = any(set(pd.layers) & layers and pd.geom.distance(p) <= EPS for pd in pads)
        return items, on_pad
    out, todo = {}, list(hit)
    while todo:
        it = todo.pop()
        if id(it) in out or not _rippable(it, fixed, soft):
            continue
        out[id(it)] = it
        for pt, layers in _ends(it):
            items, on_pad = at(pt, set(layers))
            if on_pad or len(items) > 2:
                continue
            todo += [o for o in items if id(o) not in out]
    return list(out.values())


# ----------------------------------------------------------------------------- connections
def _conns(sp, fp, net):
    """The relevant parts of `net` (largest first) when it has more than one, else []."""
    ps = [p for p in LM.parts(sp, fp, net) if LM._relevant(p)]
    return ps if len(ps) > 1 else []


def _gap(src_part, rest):
    sg = unary_union([n.copper for n in src_part])
    return min((n.copper.distance(sg) for p in rest for n in p), default=0.0)


def _join_plain(gr, sp, fp, net, tag):
    """Join `net`'s smallest relevant part to the rest without ripping anything: new items or None."""
    ps = _conns(sp, fp, net)
    if not ps:
        return []
    widths = LM.widths_of(sp, net)
    small, rest = ps[-1], ps[:-1]
    src = LM._anchors(small, max(widths) / 2 + 0.02)
    if not src:
        return None
    x0, y0, x1, y1 = LM._bounds(src)
    wide = box(x0 - LM.WIDE, y0 - LM.WIDE, x1 + LM.WIDE, y1 + LM.WIDE)
    for win in [LM._window(src, rest, m) for m in LM.MARGINS] + [wide]:
        got = LM._try(gr, sp, net, src, rest, win, widths)
        if got is not None:
            for it in got[1]:
                it.owner = ("lastmile", tag)
            return got[1]
    return None


def _orders(tasks, n_orders, lengths, seed=0):
    """Routing orders of `tasks` (a multiset of nets): every distinct order when there are at
    most 4, else shortest first, longest first, then seeded shuffles, `n_orders` in all."""
    if len(tasks) <= 4:
        seen, out = set(), []
        for o in itertools.permutations(tasks):
            if o not in seen:
                seen.add(o)
                out.append(list(o))
        return out, True
    by = sorted(tasks, key=lambda n: (lengths.get(n, 0.0), n))
    out = [by, list(reversed(by))]
    rnd = random.Random(seed)
    tries = 0
    while len(out) < n_orders and tries < 20 * n_orders:
        tries += 1
        o = list(by)
        rnd.shuffle(o)
        if o not in out:
            out.append(o)
    return out[:n_orders], False


def _legal(sp, items):
    """Whether every item in `items` keeps every rule against the space (itself aside)."""
    for it in items:
        if it.kind == "track":
            a, b = it.geom.coords[0], it.geom.coords[-1]
            if sp.track_violations(it.net, next(iter(it.layers)), it.width, a, b, ignore=[it], first=True):
                return False
        elif sp.via_violations(it.net, it.geom.x, it.geom.y, size=it.width, drill=it.drill, ignore=[it],
                               first=True, layers=list(it.layers)):
            return False
    return True


# ----------------------------------------------------------------------------- one connection
def _conflict(gr, sp, net, src, others, widths, fixed, soft, outside=()):
    """(outcome or None, K {net: [hit items]}) for one connection: the path with our other
    copper (of nets not in `outside`) taken out, and whose copper it crosses."""
    foreign = [it for it in _foreign(sp, net) if it.net not in outside]
    ours = [it for it in foreign if _rippable(it, fixed, soft)]
    theirs = [it for it in foreign if not _rippable(it, fixed, soft)]
    sp.remove(ours)
    try:
        rt = _path(gr, sp, net, src, others, widths)
        if rt is None:
            if theirs:
                sp.remove(theirs)
                try:
                    rt2 = _path(gr, sp, net, src, others, widths)
                finally:
                    LM._restore(sp, theirs)
                if rt2 is not None:
                    return "needs fixed copper", {}
            return "no path without our copper", {}
        return None, (_hits(sp, net, rt, ours), ours)
    finally:
        LM._restore(sp, ours)


def _shrink(gr, sp, net, src, others, widths, K):
    """K with each net put back whose copper a path does not need (greedy, fewest crossings first)."""
    keep = dict(K)
    for k in sorted(K, key=lambda n: (len(K[n]), n)):
        if len(keep) <= 1:
            break
        out = [it for n, its in keep.items() if n != k for it in its]
        sp.remove(out)
        try:
            ok = _path(gr, sp, net, src, others, widths) is not None
        finally:
            LM._restore(sp, out)
        if ok:
            del keep[k]
    return keep


def _solve(gr, sp, fp, nets, cfg, deadline, tag):
    """Route every connection of `nets` (their parts as they are now) in some order: (new items,
    orders tried, exhaustive, {net: failures}) - new items None when no order routed all."""
    tasks, lengths = [], {}
    for n in sorted(nets):
        ps = _conns(sp, fp, n)
        tasks += [n] * max(0, len(ps) - 1)
        if ps:
            lengths[n] = _gap(ps[-1], ps[:-1])
    if not tasks:
        return [], 0, True, {}
    orders, exhaustive = _orders(tasks, cfg["closure_orders"], lengths)
    fails, tried = {}, 0
    for o in orders:
        if clock_now() >= deadline:
            return None, tried, False, fails
        tried += 1
        charge("closure_order")
        added, ok = [], True
        for n in o:
            new = _join_plain(gr, sp, fp, n, tag)
            if new is None:
                fails[n] = fails.get(n, 0) + 1
                ok = False
                break
            added += new
        if ok and not any(_conns(sp, fp, n) for n in nets):
            return added, tried, exhaustive, fails
        if ok:     # every task routed but a net still in pieces (a join that joined less): not all of S
            fails.update({n: fails.get(n, 0) + 1 for n in nets if _conns(sp, fp, n)})
        sp.remove(added)
    return None, tried, exhaustive and tried == len(orders), fails


def close_one(gr, sp, fp, net, small, rest, cfg, fixed, soft, deadline, tag, log=print):
    """Try conflict-set closure for one open connection (`small` part of `net` to `rest`).
    Returns (record, new items, ripped items); the space is unchanged unless outcome is "closed"."""
    t0 = clock_now()
    widths = LM.widths_of(sp, net)
    rec = dict(net=net, pads=sorted(f"{it.owner[0]}.{it.owner[1]}" for it in (n.item for n in small if n.kind == "pad")
                                    if isinstance(it.owner, tuple) and len(it.owner) >= 2),
               conflict=[], shrunk=[], s=0, orders=0, depth=0, outcome=None)

    def done(outcome, **kw):
        rec.update(outcome=outcome, seconds=round(clock_now() - t0, 3), **kw)
        return rec, [], []
    src = LM._anchors(small, max(widths) / 2 + 0.02)
    if not src:
        return done("no path without our copper", reason="no anchors")
    why, got = _conflict(gr, sp, net, src, rest, widths, fixed, soft)
    if why:
        return done(why)
    K, _pool = got
    rec["conflict"] = sorted(K)
    if not K:
        # grid artefact: the path crosses none of our nets; a plain join may still find it
        new = _join_plain(gr, sp, fp, net, tag)
        if new and _legal(sp, new):
            rec.update(outcome="closed", seconds=round(clock_now() - t0, 3), reason="no conflict net")
            return rec, new, []
        if new:
            sp.remove(new)
        return done("joint solve failed", reason="no conflict net (grid artefact)")
    K = _shrink(gr, sp, net, src, rest, widths, K)
    rec["shrunk"] = sorted(K)
    if len(K) > cfg["closure_max_nets"]:
        return done("set too large")
    nets_k = set(K)
    hits = {n: list(v) for n, v in K.items()}
    touched = {net} | nets_k
    before = {n: LM._open_count(sp, fp, n) for n in touched}
    ripped, fails_all = [], {}
    depth = 0
    while True:
        rip = []
        for k in sorted(nets_k):
            rip += [it for it in _run(sp, k, hits[k], cfg["closure_whole_net_items"], fixed, soft)
                    if not any(it is r for r in ripped)]
        sp.remove(rip)
        ripped += rip
        S = {net} | nets_k
        rec["s"] = sum(max(0, len(_conns(sp, fp, n)) - 1) for n in S)
        new, tried, exhaustive, fails = _solve(gr, sp, fp, S, cfg, deadline, tag)
        rec["orders"] += tried
        for n, c in fails.items():
            fails_all[n] = fails_all.get(n, 0) + c
        if new is not None:
            after = {n: LM._open_count(sp, fp, n) for n in before}
            if sum(after.values()) < sum(before.values()) and _legal(sp, new):
                rec.update(outcome="closed", depth=depth, seconds=round(clock_now() - t0, 3),
                           open_before=sum(before.values()), open_after=sum(after.values()))
                return rec, new, ripped
            sp.remove(new)
            fails_all["(no gain)"] = fails_all.get("(no gain)", 0) + 1
        if clock_now() >= deadline:
            LM._restore(sp, ripped)
            return done("time", depth=depth, failed_most=_most(fails_all))
        if depth >= cfg["closure_depth"] or not fails:
            break
        # extend once per level: the most-failing connection's own conflict set outside S
        x = _most(fails)
        ps = _conns(sp, fp, x)
        if not ps:
            break
        wx = LM.widths_of(sp, x)
        sx = LM._anchors(ps[-1], max(wx) / 2 + 0.02)
        if not sx:
            break
        why, got = _conflict(gr, sp, x, sx, ps[:-1], wx, fixed, soft, outside=S)
        if why or not got[0]:
            break
        extra = {n: v for n, v in got[0].items() if n not in S}
        if not extra or len(nets_k | set(extra)) > cfg["closure_max_nets"]:
            break
        for n, v in extra.items():
            hits[n] = v
            before.setdefault(n, LM._open_count(sp, fp, n))
        nets_k |= set(extra)
        depth += 1
        rec["depth"] = depth
    LM._restore(sp, ripped)
    rec["shrunk"] = sorted(nets_k)
    return done("joint solve failed", depth=depth, failed_most=_most(fails_all),
                label="exhausted-orders" if exhaustive else None)


def _most(fails):
    return max(sorted(fails), key=lambda n: fails[n]) if fails else None


# ----------------------------------------------------------------------------- driver
def run(sp, gr, fp, nets, cfg, fixed=(), soft=(), deadline=None, log=print):
    """Conflict-set closure on the open connections of `nets` in the space (lastmile.close's,
    after its joins). Returns {records: [...], added: [items], ripped: [items], skipped}: the
    space holds the closed sets' copper; ripped items are out of it."""
    fixed, soft = set(fixed), set(soft)
    total = sum(LM._open_count(sp, fp, n) for n in nets)
    out = dict(records=[], added=[], ripped=[], open_before=total)
    if not total or total > cfg["closure_max_opens"]:
        out["skipped"] = f"{total} open (closure runs on 1..{cfg['closure_max_opens']})"
        return out
    deadline = float("inf") if deadline is None else deadline
    k = 0
    tried = set()
    for net in list(nets):
        while clock_now() < deadline:
            ps = _conns(sp, fp, net)
            if not ps:
                break
            key = (net, frozenset(id(n.item) for n in ps[-1]))
            if key in tried:
                break
            tried.add(key)
            k += 1
            rec, new, ripped = close_one(gr, sp, fp, net, ps[-1], ps[:-1], cfg, fixed, soft, deadline,
                                         f"closure{k}", log=log)
            out["records"].append(rec)
            log(f"closure {net} {rec['pads']}: {rec['outcome']} (K {rec['conflict']} -> {rec['shrunk']}, "
                f"|S| {rec['s']}, {rec['orders']} orders, depth {rec['depth']}, {rec.get('seconds')} s)")
            if rec["outcome"] != "closed":
                break
            out["added"] += new
            out["ripped"] += ripped
        if clock_now() >= deadline:
            if not out["records"] or out["records"][-1]["net"] != net:
                out["records"].append(dict(net=net, outcome="time", seconds=0.0))
            break
    out["open_after"] = sum(LM._open_count(sp, fp, n) for n in nets)
    return out
