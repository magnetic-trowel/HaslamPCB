# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge's hot-loop stage: commutation cells laid and protected before Freerouting.

docs/research/routing/kae-hot-loops.md ranks four changes to the default router (bridge +
last mile + finish), each behind its own setting (constraints.DEFAULTS, project text variable
KAE_<NAME>, opts, env KAE_<NAME>), all off until the hotloop A/B:

| setting | option | what |
|---|---|---|
| hotloop_keepout | R5 | other nets' tracks and vias stay off the return-plane layer under each cell |
| hotloop_cells | R1 + R2 | the critical cell module (cells only), priced in watts, laid and locked first |
| hotloop_vias | R4 | return-via arrays at the cells' ground terminals, inside that stage |
| hotloop_pours | R3 | the cells' VIN and PGND hops also written as zones of their nets |

`stage` runs at the start of kae.route.bridge.route, on the task input, and writes a work board
(input + locked cell copper + `kae-crit:` keep-outs + `kae-hl:` pours) that the bridge then routes
as its input. Both zone kinds reach Freerouting, the repair rounds and the last mile as hard
obstacles for other nets (constraints.plan's crit_zones: a pin of the zone's net in the DSN, a
`shape` item of that net in critical_space.Space); the bridge drops the keep-outs from its
output (critical_write.edit drop_guards) and keeps the pours, which score v10+ allows as added
zones. `last_mile_crit_zones` gives the same obstacles to the restart portfolio's final last mile.

The keep-out (R5) covers the return plane and every pour or plane of a loop net (input rail, ground,
switch node) under the cell's hull on any other layer, and on the parts' own layer the bridge between
the cell's own pads of that net (so the IC's fan-out stays free), for every cell whose loop terminals are found
(routed, partly routed or failed alike): a pour the loop needs, cut by another net, was the largest
cause in the board diagnosis (~24 of 37.6 nH: hdmi2rgb, nekoink, gecko5, bq25306). On the bq25306 charger, foreign tracks on the return layer under the loop
were 82 % of arm A's L gap (5.04 -> 2.19 nH, R 13.1 -> 5.3 mOhm; diagnosis what-if E1). Region:
the convex hull of the cell's loop terminals and laid copper, grown by hotloop_keepout_mm,
clipped to the ground plane's own zone on that layer (critical_recheck.guard_zones). Margin
(MARGIN_WHY): a return current at height h under a conductor spreads as J(x) ~ h / (x^2 + h^2),
so a band m wide beside it holds (2/pi) atan(m / h) of it; 1 mm keeps 94 % (h = 0.1 mm, 4-layer
L2) to 86 % (h = 0.2 mm) of the edge conductors' return off any cut, and the loop's interior,
where most of its return flows, is covered by the hull itself. On a 1.6 mm 2-layer board 1 mm
holds only about 40 % of an edge conductor's spread; the hull is still the part that matters
there (the bq25306 what-if removed tracks inside it). The keep-out is a zone of the plane's net,
so that net (ground) is never blocked. Every pin of the cell's own parts (IC and capacitors) on
another net has an escape corridor ready (`escapes`): a straight strip about the pad's width, room
for a via beside the pad, out of the keep-out along the exit that costs least, its length plus
ESCAPE_CUT_COST times its length under the loop (between the loop terminals, where the return
flows). A corridor is a hole any net could use, so it is opened only for a pin the repair rounds
leave open (`escape_round`: the corridors cut out, the last mile again): walling in the cell's own
part is a flaw, not a trade-off (bq25306: U1's /STB and /PMID stayed open), while opening every
corridor up front let U1's signal nets back under the loop (bq25306 K: 1.37 -> 3.22 nH).

Cells first (R1 + R2, R4). critical.Session with kinds ("cell",), no rails, no joins, priced in
watts (opts cell_price "W": loss.loop + loss.loop_ac at the cell's I, f_sw, D, so trim_tol, the
return vias and pad entries weigh R as well as L), return-via arrays with hotloop_vias
(critical_modules._via_array). The copper is written locked (Freerouting's fixed wiring).

Pours (R3). Each VIN or PGND hop of a laid cell (never the switch node): the hop's path widened to
the narrower terminal's extent across it, plus both terminal pads, minus every other net's pad
grown by an escape gap (a track of that net still leaves it), inside the board outline less the
edge clearance and outside rule areas; one KiCad zone per piece that touches a terminal, solid
pad connection, a priority above every zone on the layer and distinct from every other pour.

Hazards (the shared schema): a cell the stage could not lay (`hotloop_cell_unrouted`), a cell
with no ground plane to keep clear (`hotloop_no_return_plane`), and, after routing, an open
connection whose direct path crosses a keep-out (`hotloop_keepout_blocks_route`, the one design
trade-off here: keep the loop's return plane or give the net that room).
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from kae.budget import now as clock_now

from . import constraints as CN

HL_PREFIX = "kae-hl:"          # pours this stage writes (kept in the output)
GUARD_PREFIX = "kae-crit:"     # keep-outs (critical_write.GUARD_PREFIX; dropped from the output)
MARGIN_WHY = ("a return at height h spreads as h / (x^2 + h^2): a 1 mm band holds 94 % (h 0.1 mm) "
              "to 86 % (h 0.2 mm) of an edge conductor's return; the hull covers the loop's interior")
SETTINGS = ("hotloop_keepout", "hotloop_keepout_mm", "hotloop_cells", "hotloop_vias", "hotloop_pours",
            "hotloop_budget_s", "hotloop_keepout_pours", "hotloop_lift", "hotloop_keepout_loopvias")


def _log(msg):
    print(f"[kae.hotloop {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def settings(board_path=None, opts=None):
    """The stage's settings: project text variable KAE_<NAME>, opts, env KAE_<NAME>, default.
    hotloop_vias and hotloop_pours live inside the cell stage, so either turns hotloop_cells on."""
    g = {k: CN.setting_env(k, board_path, opts) for k in SETTINGS}
    out = dict(keepout=bool(float(g["hotloop_keepout"] or 0)), keepout_mm=float(g["hotloop_keepout_mm"]),
               cells=bool(float(g["hotloop_cells"] or 0)), vias=bool(float(g["hotloop_vias"] or 0)),
               pours=bool(float(g["hotloop_pours"] or 0)), budget_s=float(g["hotloop_budget_s"]))
    out["keepout_pours"] = bool(float(g["hotloop_keepout_pours"] or 0))
    out["keepout_loopvias"] = bool(float(g["hotloop_keepout_loopvias"] or 0))
    out["lift"] = g["hotloop_lift"] if g["hotloop_lift"] in LIFT_LEVELS else "plane"
    out["cells"] = out["cells"] or out["vias"] or out["pours"]
    return out


def active(st):
    return bool(st and (st["keepout"] or st["cells"]))


def _intent(board_path, opts):
    """The board's operating facts (setting `operating`: a JSON path), or None."""
    path = CN.setting("operating", board_path, opts) if board_path else (opts or {}).get("operating")
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return None


def _session(board_path, info, st, opts, log):
    from .critical import Session, intent_opts
    from kae.board import pinfacts as PF
    from kae.board.kicad_file import load
    intent = _intent(board_path, opts)
    board = load(Path(board_path))
    _seed_roles(board_path, board)
    # the schematic's pin facts the intent was compiled with (operating facts `pins`), applied as
    # kae.excite.evaluate does: without them an imported board's regulator pins carry no names and the
    # brief finds no cell (govish, powerboost)
    PF.apply(board, (intent or {}).get("pins"))
    copts = dict(kinds=("cell",), rails="none", complete_mm=0.0, island_mm=0.0, thermal_spokes=False,
                 place_allocs=False, guards=(), cell_price="W", cell_via_array=bool(st["vias"]), cell_widest_fit=True,
                 intent=intent, **intent_opts(intent))
    return Session(board_path, info=info, opts=copts, log=log, board=board)


def _seed_roles(board_path, board, also=None):
    """constraints._roles' per-content brief cache for `board_path` (and `also`, the work board, whose
    routing does not change the netlist) from the board already loaded: on hdmi2rgb each extra load of
    the board (silk outlines) cost ~40 s, and the stage, its Space's plan and the bridge's plan on the
    work board each paid one. The brief is built as _roles builds it (no pin facts), so the plan is N's."""
    import hashlib
    try:
        from kae.circuit.brief import build
        key = hashlib.sha1(Path(board_path).read_bytes()).hexdigest()
        if key not in CN._ROLES:
            CN._ROLES[key] = (build(board),)
        if also is not None:
            CN._ROLES[hashlib.sha1(Path(also).read_bytes()).hexdigest()] = CN._ROLES[key]
    except Exception:   # noqa: BLE001 - _roles builds its own
        pass


def _plan_cells(s):
    """The board's cells with their loop terminals, not routed (keep-out only)."""
    from .critical_modules import modules_from_brief
    mods = modules_from_brief(s.brief, ("cell",))
    for m in mods:
        T = [s.ctx.term(mem) for mem in m.spec.get("loop") or []]
        if len(T) < 3 or any(t is None for t in T):
            m.status = "skipped"
            m.notes.append("loop terminals not found")
            continue
        m.spec["_T"] = T
        m.status = "planned"
    return mods


def _region(s, m, margin):
    """The cell's hull (loop terminals and its laid copper) grown by `margin`, or None."""
    from shapely.ops import unary_union
    geoms = [t.geom for t in m.spec.get("_T") or []]
    geoms += [it.geom.buffer(it.r) for it in s.space.routed if it.owner and it.owner[0] == m.id]
    if not geoms:
        return None
    return unary_union(geoms).convex_hull.buffer(margin)


def keepout_plan(s, mods, margin, log=_log):
    """Per cell with a return plane: {cell, net, layer, h, region, escapes} (`escapes`: the corridor of
    every pin of the cell's parts, opened only when that pin is left open: zones_for), rows, hazards."""
    from kae import hazards as H
    from shapely.ops import unary_union
    plan, rows, hz = [], [], []
    for m in mods:
        if not m.spec.get("_T"):         # loop terminals not found: nothing to place a keep-out by
            continue
        region = _region(s, m, margin)
        if region is None or region.is_empty:
            continue
        T = m.spec["_T"]
        c = region.centroid
        h, pl, pn = s.ctx.plane(s.ctx.side_layer(T[0].fp), c.x, c.y, gnd=True)
        refs = sorted({getattr(s.ctx.fp.get(t.fp), "ref", "") for t in T} - {""})
        if pl is None:
            hz.append(H.make(
                "hotloop_no_return_plane", "info", "electrical",
                f"{m.id}: no ground zone on another layer under the hot loop, so there is no return plane to "
                f"keep other nets off; its return runs in the copper as routed.",
                objects=[m.id] + refs, evidence=dict(cell=m.id),
                fix="A ground pour on the layer next to the cell (the cell's return plane) would let the loop "
                    "close vertically (TI SNVA803: 2 mm2 < 0.5 nH)."))
            rows.append(dict(cell=m.id, layer=None, area_mm2=0.0))
        loop = unary_union([t.geom for t in T]).convex_hull
        # the return plane, and every pour or plane of a loop net (input rail, ground, switch node) the loop
        # itself needs on any layer under the hull: other nets' copper that cuts any of them breaks the loop
        # (diagnosis: hdmi2rgb U10 GND pour islanded by a SYSPWR ring, nekoink U2 SW pour split, gecko5 U13
        # +5V pour cut by a GND track; ~24 of the 37.6 nH gap)
        nets = {t.net for t in T if t.net} | {n for n in (m.spec.get("sw"), m.spec.get("rail")) if n}
        pours_on = getattr(s, "hotloop_pours_on", True)
        loopvias = getattr(s, "hotloop_loopvias_on", False)
        layers = ({(pn, pl)} if pl is not None else set()) | {(n, l) for n in (nets if pours_on else ()) for l, g in s.space.zones_of(n) if g.intersects(region)}
        side = s.ctx.side_layer(T[0].fp)
        for net, layer in sorted(layers):
            reg = region
            if layer == side:
                # on the parts' own layer a hull-wide keep-out walls in the IC's fan-out (bq25306: 17 opens
                # after the first route, a GND and an SW pour on F.Cu): there it covers only the bridge the
                # loop needs, the hull of the loop's own pads of that net (cap pad to IC pins; hdmi2rgb: the hull
                # of all the cell's GND pads, output caps included, left SYSPWR and +3V3 open)
                # the loop's own terminals of that net (input cap pad, IC pins); for a net with no two
                # terminals (the switch node) the IC's pins of it and the nearest other pad of it (inductor)
                pads = [t.geom_on(layer) for t in T if t.net == net and layer in t.layers]
                if len(pads) < 2:
                    own = [it for u in m.parts for it in s.space.pads_by_fp.get(u, [])
                           if it.net == net and layer in it.layers]
                    if len(own) < 2:
                        continue
                    a = min(own, key=lambda it: it.geom.distance(loop))
                    b = min((it for it in own if it.fp != a.fp), key=lambda it: it.geom.distance(a.geom),
                            default=None)
                    if b is None:
                        continue
                    pads = [a.geom, b.geom]
                reg = unary_union(pads).convex_hull
                # never over another loop net's own hop: the strip between its terminals stays free for it
                # (govish K: the GND bridge lay across the VBUS hop C1 -> U1, which then went round it:
                # 2.31 nH / 12.6 mOhm against 1.80 / 3.9 without the pour keep-outs)
                hops = []
                for k_ in range(len(T)):
                    ta, tb = T[k_], T[(k_ + 1) % len(T)]
                    if ta.fp != tb.fp and ta.net == tb.net and ta.net != net and layer in ta.layers:
                        hops.append(unary_union([ta.geom_on(layer), tb.geom_on(layer)]).convex_hull
                                    .buffer(s.space.max_need))
                if hops:
                    reg = reg.difference(unary_union(hops))
                if reg.is_empty or reg.area < 0.5:
                    continue
            esc = escapes(s, m, reg, loop, net)
            holes = loop_via_holes(s, T, nets, net) if loopvias else []
            plan.append(dict(cell=m.id, net=net, layer=layer, h=h, region=reg, escapes=esc, holes=holes,
                             plane=(net, layer) == (pn, pl), conn=_connection(s.info, net, layer), loop=loop))
            rows.append(dict(cell=m.id, layer=layer, net=net, h_mm=round(h, 3) if pl is not None else None,
                             region_mm2=round(reg.area, 2),
                             pins=len(esc), plane=(net, layer) == (pn, pl)))
    return plan, rows, hz


def loop_via_holes(s, T, nets, net):
    """With hotloop_keepout_loopvias: room for the loop's own vias in a keep-out of `net`. A keep-out is a zone of
    one net and a via crosses every layer, so without it a keep-out of the ground plane bans the input rail's vias
    under the cell and a keep-out of the rail's pour bans the ground vias: the cap's and the IC's vias into their
    planes then sit outside the hull, on long thin surface stubs (hotloop-ab K: none of the loop nets' vias within
    1 mm of the hull on arvsom, the sstv boost or gecko5 U13, where N had 2-7 per cell; arvsom U4's rail hop
    6.0 -> 15.2 mm). Each loop terminal of another loop net gets four via sites, one touching the middle of each
    side of its pad's box, each a hole of the via's radius plus the clearance: room for one via there, no corridor
    another net could run a track through. [Polygon]"""
    from shapely.geometry import Point
    out = []
    for t in T:
        if not t.net or t.net == net or t.net not in nets:
            continue
        try:
            d = s.space.via_size(t.net)[0]
        except Exception:  # noqa: BLE001 - no rule for the net: the board's default via
            d = 0.6
        try:
            c = s.space._generic_need(t.net, "via", t.layers[0]) or 0.2
        except Exception:  # noqa: BLE001 - no rule: a common class clearance
            c = 0.2
        x0, y0, x1, y1 = t.geom.bounds
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, d / 2
        for x, y in ((x0 - r, cy), (x1 + r, cy), (cx, y0 - r), (cx, y1 + r)):
            out.append(Point(x, y).buffer(r + c + 0.02))
    return out


def _connection(info, net, layer):
    """The pad connection of `net`'s zone on `layer` (export info): {connect, thermal_gap, spoke_width},
    so a keep-out over a plane joins pads as that plane does (nekoink: solid guards over U1's thermal-pad
    vias hid their starved spokes from the repair rounds, three starved_thermal errors once dropped)."""
    zs = [z for z in (info or {}).get("zones") or [] if z.get("net") == net and layer in (z.get("layers") or [])
          and not z.get("rule_area") and not (z.get("name") or "").startswith(GUARD_PREFIX)]
    if not zs:
        return {}
    z = max(zs, key=lambda z: int(z.get("priority") or 0))
    conn = z.get("pad_connection") or "thermal"
    out = dict(connect=conn if conn in ("solid", "thermal", "none", "thru_hole_only") else "thermal")
    if z.get("thermal_gap"):
        out["thermal_gap"] = float(z["thermal_gap"])
    if z.get("spoke_width"):
        out["spoke_width"] = float(z["spoke_width"])
    return out


def loop_guard(board, region, net, layer, name, min_area=0.5, conn=None):
    """A keep-out of `net` on `layer` over `region`: inside the net's own zones there, outside every
    other net's zone that fills before them (priority at least theirs), one priority above every zone
    on the layer (critical_recheck.guard_zones, which also clears lower-priority zones of other nets:
    a VBUS pour drawn over a GND pour would leave the VBUS keep-out empty)."""
    from shapely.geometry import Polygon as _Poly
    from .critical_recheck import _hole_free
    own = [z for z in board.zones if z.net == net and layer in z.layers and z.outline is not None
           and not (z.name or "").startswith(GUARD_PREFIX)]
    if not own or region is None or region.is_empty:
        return []
    from shapely.ops import unary_union
    g = region.intersection(unary_union([z.outline for z in own]))
    p_own = max(int(z.priority or 0) for z in own)
    other = [z.outline for z in board.zones if z.net and z.net != net and layer in z.layers and z.outline is not None
             and int(z.priority or 0) >= p_own and not (z.name or "").startswith(GUARD_PREFIX)]
    if other:
        g = g.difference(unary_union(other).buffer(0.05))
    prio = 1 + max([int(z.priority or 0) for z in board.zones if layer in z.layers] or [0])
    out = []
    for part in getattr(g, "geoms", [g]):
        if isinstance(part, _Poly) and part.area > min_area:
            for piece in _hole_free(part):
                if piece.area > min_area:
                    out.append((net, layer, [list(piece.exterior.coords)], name, prio, 0.0, conn or {}))
    return out


def zones_for(board, plan, open_pads=()):
    """The keep-out zones of `plan` with the escape corridors of the pads named in `open_pads`
    ("REF.NUMBER") and each entry's own `cuts` (lift corridors) cut out; entries marked `lifted` give
    none. [(net, layer, rings, name, priority, 0, connection)], merged per net and layer."""
    from shapely.geometry import Polygon as _Poly
    from shapely.ops import unary_union
    from .critical_recheck import _hole_free
    want = set(open_pads or ())
    groups = {}
    for e in plan:
        if e.get("lifted"):
            continue
        cor = ([x["geom"] for x in e["escapes"] if x["pad"] in want] + list(e.get("cuts") or [])
               + list(e.get("holes") or []))
        cut = e["region"].difference(unary_union(cor)) if cor else e["region"]
        for z in loop_guard(board, cut, e["net"], e["layer"], f"{GUARD_PREFIX}hotloop:{e['cell']}:{e['net']}",
                            conn=e.get("conn")):
            g = groups.setdefault((z[0], z[1]), dict(polys=[], prio=z[4], name=z[3], conn=z[6]))
            g["polys"].append(_Poly(z[2][0]))
            g["prio"] = max(g["prio"], z[4])
    out = []
    for (net, layer), g in groups.items():
        u = unary_union(g["polys"])
        for part in getattr(u, "geoms", [u]):
            if isinstance(part, _Poly) and part.area > 0.5:
                for piece in _hole_free(part):
                    if piece.area > 0.5:
                        out.append((net, layer, [list(piece.exterior.coords)], g["name"], g["prio"], 0.0, g["conn"]))
    return out


_PAD_OF = re.compile(r"Pad (\S+) \[[^\]]*\] of (\S+)")


def open_cell_pads(drc_report, plan):
    """The pads of the cells' parts ("REF.NUMBER") named by an open connection of a DRC report: the pins
    the keep-out walls in, whose corridors the escape round opens."""
    have = {x["pad"]: x["net"] for e in plan for x in e["escapes"]}
    out, nets = set(), set()
    for v in (drc_report or {}).get("unconnected_items") or []:
        for it in v.get("items") or []:
            d = it.get("description") or ""
            mm = _PAD_OF.search(d)
            if mm and f"{mm.group(2)}.{mm.group(1)}" in have:
                out.add(f"{mm.group(2)}.{mm.group(1)}")
            nets.update(_NET_IN.findall(d))
    # an open connection of a net whose pads the keep-outs cover (a track or via end, not the pad, may be
    # what DRC names: hdmi2rgb's SYSPWR, the cell's own rail): those pads' corridors too
    out |= {p for p, n in have.items() if n in nets}
    return out


def keepout_zones(s, mods, margin, log=_log):
    """The keep-outs as first routed (no corridor open): (zones, rows, hazards); the plan is kept on
    the session (s.hotloop_plan) for the escape round."""
    plan, rows, hz = keepout_plan(s, mods, margin, log=log)
    s.hotloop_plan = plan
    zones = zones_for(s.board, plan)
    return zones, rows, hz


def _open_pairs(rep):
    """[(net, LineString)] of the open connections of a DRC report (item positions)."""
    from shapely.geometry import LineString
    out = []
    for v in (rep or {}).get("unconnected_items") or []:
        its = v.get("items") or []
        pos = [it.get("pos") or {} for it in its]
        pos = [(p["x"], p["y"]) for p in pos if "x" in p]
        if len(pos) < 2:
            continue
        nets = [n for it in its for n in _NET_IN.findall(it.get("description") or "")]
        seg = LineString(pos[:2]) if pos[0] != pos[1] else LineString([pos[0], (pos[0][0] + 1e-3, pos[0][1])])
        out.append((nets[0] if nets else "", seg))
    return out


LIFT_LEVELS = ("corridors", "pours", "crossing", "plane")
CROSS_HALF_MM = 0.45     # half width of a crossing corridor: a track and its clearances on both sides


def escape_round(input_path, output_path, wd, plan, info, opts, hl, final_rep, deadline, log=_log):
    """After the repair rounds and the last mile: the keep-outs must never cost a connection the
    default makes. While an open connection's direct path crosses a keep-out (or names a pad it
    covers), the keep-outs it meets are lifted step by step, only there, with the last mile again
    after each step:
      corridors  the escape corridors of the covered pads of the open nets;
      pours      the loop-net pour keep-outs (all but the return plane) of the cells it crosses;
      crossing   a corridor through the return-plane keep-out along the open connection, priced by its
                 length under the loop (between the loop terminals, the cap-to-IC strip): the array
                 vias in its way are removed;
      plane      the return-plane keep-out of that cell, its copper unlocked for the last mile.
    Every lift is a hotloop_keepout_lifted hazard (info); a crossing or plane lift a foreign net needs
    under the loop is the design trade-off (hotloop_keepout_blocks_route, a decision naming the
    setting). Returns (DRC report, summary, plan, opened pads) or None when nothing crossed."""
    from shapely.ops import unary_union
    from . import constraints, critical_write as W, drc, repair
    from kae.board import pcbnew_io
    from kae import hazards as H
    ko = hl.get("_ko") or {}
    kplan = [dict(e) for e in ko.get("plan") or []]
    if not kplan:
        return None
    rep = final_rep
    wd = Path(wd)
    wd.mkdir(parents=True, exist_ok=True)
    base = None
    rounds, lifts, pads = [], [], set()
    cell_cu = set(ko.get("cell_uuids") or ())
    unlocked = False
    p2 = plan
    tmp = wd / "noguard.kicad_pcb"

    def implicated(rep):
        pairs = _open_pairs(rep)
        hit = []
        for net, seg in pairs:
            es = [e for e in kplan if not e.get("lifted") and e["net"] != net and seg.intersects(e["region"])]
            if es:
                hit.append((net, seg, es))
        return hit, open_cell_pads(rep, kplan)

    allowed = LIFT_LEVELS[:LIFT_LEVELS.index(settings(input_path, opts)["lift"]) + 1]
    for level in allowed:
        hit, opads = implicated(rep)
        if not hit and not (level == "corridors" and opads):
            break
        if deadline - clock_now() < 30:
            break
        nets = sorted({n for n, _s, _e in hit})
        if level == "corridors":
            new = opads | {x["pad"] for _n, _s, es in hit for e in es for x in e["escapes"] if x["net"] in nets}
            if not new - pads:
                continue
            pads |= new
            did = sorted(new)
        elif level == "pours":
            cells = {e["cell"] for _n, _s, es in hit for e in es}
            did = sorted({f"{e['cell']}:{e['net']}@{e['layer']}" for e in kplan
                          if e["cell"] in cells and not e.get("plane") and not e.get("lifted")})
            for e in kplan:
                if e["cell"] in cells and not e.get("plane"):
                    e["lifted"] = True
            if not did:
                continue
        elif level == "crossing":
            did = []
            for net, seg, es in hit:
                for e in es:
                    if not e.get("plane"):
                        continue
                    cor = seg.buffer(CROSS_HALF_MM, cap_style=2)
                    e.setdefault("cuts", []).append(cor)
                    cut = round(seg.intersection(e["loop"]).length, 2)
                    did.append(dict(net=net, cell=e["cell"], layer=e["layer"], under_loop_mm=cut))
            # array vias where those corridors run: the foreign path needs their sites
            cors = unary_union([c for e in kplan for c in e.get("cuts") or []]) if did else None
            gone = [a for a in ko.get("array") or [] if cors is not None and cors.distance(a["pt"]) < a["r"]]
            if gone:
                W.edit(output_path, output_path, remove=[u for a in gone for u in a["uuids"]])
                ko["array"] = [a for a in ko.get("array") or [] if a not in gone]
            if not did:
                continue
        else:
            did = sorted({e["cell"] for _n, _s, es in hit for e in es if e.get("plane")})
            for e in kplan:
                if e["cell"] in did:
                    e["lifted"] = True
            if not did:
                continue
            # the cell's array vias go too: past its ampacity count they are an L refinement, and round a
            # QFN they hold the fan-out (bq25306 H: /REGN and /STAT stayed open with the plane lifted)
            gone = [a for a in ko.get("array") or [] if a.get("cell") in did]
            if gone:
                W.edit(output_path, output_path, remove=[u for a in gone for u in a["uuids"]])
                ko["array"] = [a for a in ko.get("array") or [] if a not in gone]
        lifts.append(dict(level=level, nets=nets, what=did))
        log(f"hotloop: lift {level} for {', '.join(nets) or 'cell pins'}: {did if level != 'crossing' else len(did)}")
        zones = zones_for(ko["board"], kplan, pads)
        core = set(ko.get("core_uuids") or ())
        unlock = sorted(cell_cu - core) if level == "plane" and cell_cu - core and not unlocked else None
        unlocked = unlocked or bool(unlock)
        W.edit(output_path, tmp, drop_guards=True, unlock=unlock)
        W.append_items(tmp, output_path, zones=zones)
        opts["crit_zones"] = [z for z in pcbnew_io.zone_fills(output_path)["zones"] if hard_zone(z.get("name"))]
        p2 = constraints.plan(info, input_path, opts)
        for k in ("plane_policy", "plane_cost", "strict_planes", "outer_surcharge", "pad_shapes"):
            if hasattr(plan, k):
                setattr(p2, k, getattr(plan, k))
        best = drc.summary(rep)
        if base is None:
            base = repair.input_errors(input_path, wd, deadline) if best["errors"] else {}
        fixed = set(opts.get("fixed_uuids") or ()) - ((cell_cu - core) if unlocked else set())
        rep = repair._last_mile(input_path, output_path, wd, p2, info, opts, deadline, rounds, best, rep,
                                fixed, log, base=base) or rep
    if not lifts:
        return None
    left_open = drc.summary(rep)["unconnected"] if rep else 0
    if left_open and deadline - clock_now() > 60 and any(lf["level"] in ("crossing", "plane") for lf in lifts):
        # the last mile alone cannot undo what the locked cell copper blocked during Freerouting's repair
        # rounds (bq25306 and hdmi2rgb H): Freerouting repair rounds on the lifted board, the lifted cells'
        # copper but the core loop ripable, inside the escape round's own time
        import shutil
        rwd = wd / "repair"
        rwd.mkdir(parents=True, exist_ok=True)
        if (wd.parent / "kicad.dsn").exists():
            shutil.copy2(wd.parent / "kicad.dsn", rwd / "kicad.dsn")
        core = set(ko.get("core_uuids") or ())
        o2 = dict(opts, fixed_uuids=sorted(set(opts.get("fixed_uuids") or ()) - (cell_cu - core)))
        log(f"hotloop: Freerouting repair after the lifts ({left_open} open, {deadline - clock_now():.0f} s)")
        rr = repair.loop(input_path, output_path, rwd, p2, info, o2, deadline=deadline, log=log)
        got = rr.pop("_report", None)
        if got is not None:
            rep = got
        lifts.append(dict(level="repair", nets=[], what=[dict(before=left_open, after=drc.summary(rep)["unconnected"])]))
    for lf in lifts:
        hl.setdefault("hazards", []).append(H.make(
            "hotloop_keepout_lifted", "info", "electrical",
            f"Hot-loop keep-outs lifted ({lf['level']}) for {', '.join(lf['nets']) or 'the cells own pins'} so the "
            f"last mile could reach them: {str(lf['what'])[:160]}",
            objects=list(lf["nets"])[:8], evidence=dict(level=lf["level"], what=lf["what"])))
        trade = [d for d in lf["what"] if isinstance(d, dict) and d.get("under_loop_mm", 0) > 0] \
            if lf["level"] == "crossing" else ([] if lf["level"] != "plane" else lf["what"])
        if trade:
            hl["hazards"].append(H.make(
                "hotloop_keepout_blocks_route", "warn", "electrical",
                f"{', '.join(lf['nets'][:6])} needed a way through the return plane under the hot loop "
                f"({lf['level']}); that cut costs the loop part of what the keep-out saves.",
                objects=list(lf["nets"])[:8], evidence=dict(level=lf["level"], what=trade),
                fix=("A design trade-off: accept the cut, or forbid it (KAE_HOTLOOP_LIFT=pours keeps the return plane "
                     "whole and leaves the net open) and give the net another way (move a part, another layer)."),
                decision=dict(options=["let the net cut the return plane", "keep the plane whole"],
                              setting="hotloop_lift")))
    hl["guards"] = [dict(net=g[0], layer=g[1], ring=g[2][0], name=g[3]) for g in zones_for(ko["board"], kplan, pads)]
    hl["keepout_lifted"] = [f"{x['level']}:{len(x['what'])}" for x in lifts]
    ko["plan"] = kplan
    return rep, drc.summary(rep), p2, sorted(pads)


ESCAPE_DIRS = 16          # exit directions tried per pad
ESCAPE_CUT_COST = 10.0    # a corridor mm under the loop (between its terminals, where the return flows) costs
                          # this many mm outside it: a slot there lengthens the return around it, a slot beside
                          # the loop only narrows the plane (bq25306 E1: tracks under the loop were 82 % of the gap)


def escapes(s, m, region, loop, plane_net):
    """Escape corridors for every pad of the cell's parts on a net other than the plane's: the pad
    grown by the clearance and a straight corridor about the pad's width (at least a track, or a via,
    with its clearance on both sides, so a via can drop in it beside the pad) from the pad to
    just outside the keep-out `region`, in the direction of least cost: its length, plus
    ESCAPE_CUT_COST x its length inside `loop` (the hull of the loop terminals). [{pad, net, geom,
    length_mm, cut_mm}]"""
    from shapely.geometry import LineString, Point
    sp = s.space
    out = []
    reach = math.sqrt(region.area) * 2 + 2.0
    bnd = region.boundary
    # every pad the keep-out covers (the cell's own parts' and any neighbour's): a corridor costs nothing
    # until the repair rounds leave that pad open
    for it in sp.pads:
        u = it.fp
        if True:
            if it.kind != "pad" or not it.net or it.net == plane_net or it.pos is None:
                continue
            if not it.geom.intersects(region):
                continue
            D, _d = sp.via_size(it.net)
            mn, opt, _mx = sp.width_limits(it.net, sp.cu[-1])
            clr = sp.max_need
            pw = min(it.geom.bounds[2] - it.geom.bounds[0], it.geom.bounds[3] - it.geom.bounds[1])
            half = max(pw / 2.0, opt / 2.0 + clr, D / 2.0 + clr)     # a track, or a via, fits in it
            x, y = it.pos
            fp = s.ctx.fp.get(u)
            many = len(sp.pads_by_fp.get(u, [])) > 3
            best = None
            for k in range(ESCAPE_DIRS):
                th = 2 * math.pi * k / ESCAPE_DIRS
                ray = LineString([(x, y), (x + reach * math.cos(th), y + reach * math.sin(th))])
                hit = ray.intersection(bnd)
                if hit.is_empty:
                    continue
                # the farthest boundary crossing along the ray (a ray along an edge meets it as a segment;
                # a region cut into pieces has several crossings: hdmi2rgb, "max() of an empty sequence")
                ds = [math.dist((x, y), c) for g in getattr(hit, "geoms", [hit]) for c in g.coords]
                if not ds:
                    continue
                d = max(ds) + 0.2
                seg = LineString([(x, y), (x + d * math.cos(th), y + d * math.sin(th))])
                inside = seg.intersection(loop).length
                cost = d + ESCAPE_CUT_COST * inside
                if many and fp is not None and (x - fp.x) * math.cos(th) + (y - fp.y) * math.sin(th) < 0:
                    cost += 2.0 * d      # an IC pin fans out away from its body, not under it
                if best is None or cost < best[0]:
                    best = (cost, seg, d, inside)
            if best is None:
                continue
            geom = it.geom.buffer(clr).union(best[1].buffer(half, cap_style=2))
            out.append(dict(pad=f"{it.owner[0]}.{it.owner[1]}", net=it.net, geom=geom,
                            length_mm=round(best[2], 2), cut_mm=round(best[3], 2)))
    return out


def _escape_clear(s, net, layer, pad):
    """How far copper of `net` keeps from another net's `pad` so one track of the pad's net still
    leaves it between them (critical_modules._escape_gap with a zero-width edge)."""
    from .critical_modules import _escape_gap
    try:
        return _escape_gap(s.ctx, net, 0.0, pad, layer)
    except Exception:   # noqa: BLE001 - an unknown pair: the space's largest requirement
        return 2 * s.space.max_need + 0.3


def pour_zones(s, mods, prio0, log=_log):
    """The hot-loop pours (R3): [(net, layer, rings, name, priority, min_thickness)], rows."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
    from .critical_modules import extent_across, route_pts
    sp = s.space
    out, rows = [], []
    prio = prio0
    edge = float(getattr(sp.plan, "edge_clearance", 0.0) or 0.0)
    inner = sp.outline.buffer(-edge) if sp.outline is not None else None
    rule = {}
    for z in sp.info.get("zones") or []:
        if z.get("rule_area"):
            g = unary_union([p for p in (Polygon(r) for r in z.get("rings") or [] if len(r) >= 3) if p.is_valid])
            for l in z.get("layers") or []:
                rule.setdefault(l, []).append(g)
    for m in mods:
        if m.kind != "cell" or m.status not in ("routed", "partial"):
            continue
        T = m.spec.get("_T") or []
        sw = m.spec.get("sw")
        n = len(T)
        for k in range(n):
            ta, tb = T[k], T[(k + 1) % n]
            if ta.fp == tb.fp or ta.net != tb.net or not ta.net or ta.net == sw:
                continue
            net = ta.net
            rt = m.hops.get(f"hop{k}")
            if rt is not None and rt.segs:
                layer = rt.segs[0][0]
                pts = [(ta.x, ta.y)] + route_pts(rt, start=(ta.x, ta.y)) + [(tb.x, tb.y)]
            else:
                layer = s.ctx.side_layer(ta.fp)
                pts = [(ta.x, ta.y), (tb.x, tb.y)]
            if layer not in ta.layers or layer not in tb.layers:
                continue
            ga, gb = ta.geom_on(layer), tb.geom_on(layer)
            ux, uy = tb.x - ta.x, tb.y - ta.y
            d = math.hypot(ux, uy) or 1.0
            a = min(extent_across(ga, ux / d, uy / d), extent_across(gb, ux / d, uy / d))
            w = max(a, rt.width if rt is not None else 0.0)
            path = LineString(pts) if len(pts) > 1 and LineString(pts).length > 1e-6 else None
            body = unary_union([ga, gb] + ([path.buffer(w / 2, cap_style=2, join_style=2)] if path else []))
            if body.is_empty:
                continue
            body = body.intersection(unary_union([ga, gb]).convex_hull.buffer(w / 2)) if path else body
            foes = [it.geom.buffer(_escape_clear(s, net, layer, it)) for it in sp.items[layer]
                    if it.kind in ("pad", "pad_nopin") and it.net != net]
            foes += [it.geom.buffer(it.r + sp.max_need) for it in sp.items[layer]
                     if it.kind in ("track", "via") and it.net != net]
            if foes:
                body = body.difference(unary_union(foes))
            if inner is not None:
                body = body.intersection(inner)
            if rule.get(layer):
                body = body.difference(unary_union(rule[layer]))
            pieces = [p for p in getattr(body, "geoms", [body]) if isinstance(p, Polygon) and p.area > 0.05
                      and (p.intersects(ga) or p.intersects(gb))]
            from .critical_recheck import _hole_free
            mn = max(0.1, sp.width_limits(net, layer)[0] or 0.0)
            area = 0.0
            for p in pieces:
                for q in _hole_free(p.buffer(0)):
                    if q.area <= 0.05:
                        continue
                    prio += 1
                    out.append((net, layer, [list(q.exterior.coords)], f"{HL_PREFIX}{m.id}:{net}", prio, mn))
                    area += q.area
            rows.append(dict(cell=m.id, hop=k, net=net, layer=layer, area_mm2=round(area, 2), width_mm=round(w, 3)))
    return out, rows


def _zone_prio(info, layers):
    return max([int(z.get("priority") or 0) for z in info.get("zones") or []
                if set(z.get("layers") or []) & set(layers)] or [0])


def _array_items(s, mods):
    """The return-via array's vias (critical_modules._via_array) with their stubs: [{pt, r, uuids}], so the
    escape round can take out a site a foreign net's path needs."""
    from shapely.geometry import Point
    out = []
    for m in mods:
        for (x, y, _w) in m.spec.get("_array_vias") or []:
            v = next((it for it in s.space.routed if it.kind == "via" and it.owner and it.owner[0] == m.id
                      and math.dist((it.geom.x, it.geom.y), (x, y)) < 1e-6), None)
            if v is None or not v.uuid:
                continue
            stubs = [it.uuid for it in s.space.routed if it.kind == "track" and it.owner == v.owner and it.uuid
                     and min(math.dist(it.geom.coords[0], (x, y)), math.dist(it.geom.coords[-1], (x, y))) < 1e-6]
            out.append(dict(pt=Point(x, y), r=v.r + CROSS_HALF_MM, uuids=[v.uuid] + stubs, cell=m.id))
    return out


def cell_hazards(mods):
    from kae import hazards as H
    out = []
    for m in mods:
        # a ground hop left to the plane on purpose (route_cell: "returns through the plane") is no gap
        left = [f for f in m.flags if f.get("flag") == "ipc_floor_unroutable"]
        if m.kind != "cell" or not (left or m.status in ("failed", "error", "skipped")):
            continue
        out.append(H.make(
            "hotloop_cell_unrouted", "warn", "electrical",
            f"{m.id}: the hot-loop stage could not lay {len(left) or 'any'} of its loop hops ({m.status}); the "
            f"general router joins them at the class width, so this loop's L and R stay as Freerouting leaves them.",
            objects=[m.id] + sorted({f.get("net") for f in left if f.get("net")}),
            evidence=dict(status=m.status, hops=[f.get("hop") for f in left], notes="; ".join(m.notes[:3])[:200]),
            fix="Room beside the loop terminals (move the input capacitor next to VIN/PGND, clear neighbours), "
                "or accept the routed loop."))
    return out


def stage(input_path, info, workdir, opts=None, log=_log, time_s=None):
    """The hot-loop stage on a task input. Returns None when every option is off, else a report
    with `board` (the work board the bridge routes; None when nothing was added), `guards` (the
    keep-out polygons), `cells` (per-cell physics), `hazards`, `seconds`."""
    st = settings(input_path, opts)
    if not active(st):
        return None
    t0 = clock_now()
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    rep = dict(settings=st, board=None, guards=[], cells=[], hazards=[])
    try:
        s = _session(input_path, info, st, opts, log)
        if st["cells"]:
            budget = st["budget_s"] if time_s is None else min(st["budget_s"], 0.15 * time_s)
            s.route(budget_s=budget)
            mods = [m for m in s.modules if m.kind == "cell"]
            rep["hazards"] += s.hazards() + cell_hazards(mods)
        else:
            mods = _plan_cells(s)
            s.modules = mods
        for m in mods:
            ph = dict(m.physics or {})
            rep["cells"].append(dict(id=m.id, status=m.status, items=len(m.copper),
                                     L_nH=ph.get("value"), R_mohm=ph.get("R_mohm"), W_loop=ph.get("W_loop"),
                                     W_loop_ac=ph.get("W_loop_ac"), notes=m.notes[:4]))
        zones = []
        if st["keepout"]:
            s.hotloop_pours_on = st["keepout_pours"]
            s.hotloop_loopvias_on = st["keepout_loopvias"]
            guards, rows, hz = keepout_zones(s, mods, st["keepout_mm"], log=log)
            rep["_ko"] = dict(plan=s.hotloop_plan, board=s.board)
            rep["keepout"] = dict(margin_mm=st["keepout_mm"], margin_basis=MARGIN_WHY, cells=rows,
                                  zones=len(guards))
            rep["hazards"] += hz
            rep["guards"] = [dict(net=g[0], layer=g[1], ring=g[2][0], name=g[3]) for g in guards]
            zones += guards
        if st["pours"]:
            layers = sorted({l for m in mods for t in (m.spec.get("_T") or []) for l in t.layers})
            prio0 = max([_zone_prio(s.info, layers)] + [z[4] for z in zones])
            pours, prow = pour_zones(s, mods, prio0, log=log)
            rep["pours"] = prow
            zones += pours
        tracks, vias = s.copper()
        rep.update(tracks=len(tracks), vias=len(vias), zones=len(zones))
        if rep.get("_ko") is not None:
            rep["_ko"]["cell_uuids"] = sorted({t.uuid for t in tracks} | {v.uuid for v in vias})
            rep["_ko"]["array"] = _array_items(s, mods)
            # the core loop: the cell's hop tracks (cap to IC), kept locked through every lift
            rep["_ko"]["core_uuids"] = sorted(it.uuid for it in s.space.routed if it.kind == "track" and it.uuid
                                              and it.owner and str(it.owner[1]).startswith("hop"))
        if tracks or vias or zones:
            dst = wd / "hotloop.kicad_pcb"
            s.write(dst, guards=zones)
            rep["board"] = str(dst)
            _seed_roles(input_path, None, also=dst)
        log(f"hotloop: {len(mods)} cell(s), {len(tracks)} tracks, {len(vias)} vias, {len(zones)} zones "
            f"({clock_now() - t0:.1f}s)")
    except Exception as e:  # noqa: BLE001 - the bridge still routes the input
        import traceback
        traceback.print_exc()
        from kae import hazards as H
        rep["error"] = f"{type(e).__name__}: {e}"
        rep["board"] = None
        rep["hazards"].append(H.make("hotloop_stage_failed", "warn", "data",
                                     f"The hot-loop stage failed and was skipped: {rep['error']}"[:300],
                                     objects=["hotloop"], fix="Report the board; it is routed without it."))
    rep["seconds"] = round(clock_now() - t0, 2)
    return rep


def hard_zone(name):
    """Whether a zone (by name) is a hard obstacle for other nets in the bridge: kae.route.critical's
    guards and keep-outs (kae-crit:) and this stage's pours (kae-hl:)."""
    return (name or "").startswith((GUARD_PREFIX, HL_PREFIX))


_NET_IN = re.compile(r"\[([^\]]*)\]")


def blocked_by_keepout(drc_report, guards, gnd=(), max_n=8):
    """After routing: the open connections whose direct path crosses a keep-out, as hazards
    (`hotloop_keepout_blocks_route`, the design trade-off). `guards`: stage()["guards"]."""
    from kae import hazards as H
    from shapely.geometry import LineString, Polygon
    if not guards or not drc_report:
        return []
    polys = [(Polygon(g["ring"]), g) for g in guards if len(g.get("ring") or []) >= 3]
    hit = {}
    for v in drc_report.get("unconnected_items") or []:
        its = v.get("items") or []
        if len(its) < 2:
            continue
        pa, pb = its[0].get("pos") or {}, its[1].get("pos") or {}
        if "x" not in pa or "x" not in pb:
            continue
        nets = [n for it in its for n in _NET_IN.findall(it.get("description") or "")]
        net = nets[0] if nets else ""
        if net in gnd:
            continue
        seg = LineString([(pa["x"], pa["y"]), (pb["x"], pb["y"])])
        for p, g in polys:
            if seg.intersects(p):
                e = hit.setdefault(net, dict(cells=set(), layers=set(), n=0))
                e["cells"].add(g["name"].split("hotloop:")[-1].split("+")[0].rsplit(":", 1)[0])
                e["layers"].add(g["layer"])
                e["n"] += 1
                break
    out = []
    for net, e in sorted(hit.items())[:max_n]:
        cells = sorted(e["cells"])
        out.append(H.make(
            "hotloop_keepout_blocks_route", "warn", "electrical",
            f"Net {net} is left open ({e['n']} connection(s)) and its direct path crosses the return-plane keep-out "
            f"under {', '.join(cells)} on {', '.join(sorted(e['layers']))}: keeping the hot loop's return plane "
            f"whole may cost this connection.",
            objects=[net] + cells,
            evidence=dict(open=e["n"], cells=cells, layers=sorted(e["layers"]),
                          basis="the open pair's straight segment crosses the keep-out polygon"),
            fix=("A design trade-off: keep the keep-out and give the net another way (move a part, another layer), "
                 "or let it cross under the cell (KAE_HOTLOOP_KEEPOUT=0, or a smaller KAE_HOTLOOP_KEEPOUT_MM), which "
                 "cuts the loop's return plane (bq25306: 2.19 -> 5.04 nH)."),
            decision=dict(options=["keep the keep-out", "let the net cross the return plane"],
                          setting="hotloop_keepout")))
    return out


def last_mile_crit_zones(input_path, board_path, info, workdir, opts=None, log=_log, drc_report=None):
    """The hard zones a last mile on `board_path` (routed from `input_path`) must respect: the
    board's own kae-hl: pours (fills) and, with hotloop_keepout, the keep-outs recomputed from the
    cells' terminals and the board's locked copper. [] when the stage is off."""
    st = settings(input_path, opts)
    if not active(st):
        return []
    from kae.board import pcbnew_io
    from . import critical_write as W
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    zones = []
    try:
        filled = board_path
        if st["keepout"]:
            s = _session(input_path, info, dict(st, vias=False), opts, log)
            s.hotloop_pours_on = st["keepout_pours"]          # as the stage laid them (was: always with pours)
            s.hotloop_loopvias_on = st["keepout_loopvias"]
            plan, _rows, _hz = keepout_plan(s, _plan_cells(s), st["keepout_mm"], log=log)
            guards = zones_for(s.board, plan, open_cell_pads(drc_report, plan))
            if guards:
                filled = wd / "keepout.kicad_pcb"
                W.append_items(board_path, filled, zones=guards)
        if filled != board_path or st["pours"]:
            # the routed board's own pours come along (their fill with the routing as it is)
            zones = [z for z in pcbnew_io.zone_fills(filled)["zones"] if hard_zone(z.get("name"))]
    except Exception as e:  # noqa: BLE001 - the last mile still runs, without them
        log(f"hotloop: last-mile keep-outs: {type(e).__name__}: {e}")
        return []
    return zones
