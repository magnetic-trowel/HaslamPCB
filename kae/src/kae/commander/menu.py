# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The priced loop-back menu: which earlier decision to revisit when routing leaves opens.

    doc = build_menu([report, ...], board=board_summary(pcb), opts=None)

`reports`: kae run reports of ONE board (attempts, seeds): a route report (kae.route.cli
route --report, bridge.route), a joint report (kae.joint.loop: final.blocked), a results
store's restart-report.json (the kept attempt's own report: either of those) or a standalone
diagnosis (python -m kae.route.blocked --out). The `blocked` dict is found wherever it sits.

Each open connection (blocked.blocked + blocked.congestion) is keyed (net, pads) and weighted
by its persistence (share of the reports in which it is open; 1 with one report). Rules (the
CATALOGUE table, one small function each) turn the connections, the escape certificates
(blocked.packages) and the stop reasons into items: evidence, gain (persistence-weighted opens
the item could act on), price (fab class, assembly USD, plane loss, whether the benchmark's
scorer allows the change: bench/src/kaebench/score.py forbids rule, layer, outline and pad-net
edits), the knob (route and joint command-line pieces, or none) and score = gain / price
factor. Items with a knob the scorer allows are the "menu", ranked by score (ties: catalogue
order); the rest go under "ask" (a person, or a rule change the benchmark forbids). Opens no
item addresses are counted under "unactionable" with the reason. `more_effort` (a restart or
resume) is always present: the null item.

The output is a pure function of the inputs: same input, same bytes (json.dumps sort_keys).
"""
from __future__ import annotations

import gzip
import json
import math
import re

SCHEMA = "kae.loopback-menu/1"

# price factors (score = gain / product of the factors that apply); configurable via opts["price"]
PRICE = {"advanced": 2.0, "hdi": 4.0, "plane_loss": 1.5, "first_bottom_part": 1.5}
BIG_PADS = 20              # a "big" part: this many pads or more
PART_OPENS = 3.0           # persistence-weighted opens on one big part that make it the target
PART_PERSIST = 0.8         # or this part-level persistence (with >= 2 reports)
CONCENTRATED = 0.5         # congestion opens are "on one part" when one part carries this share
# Prior, not a measurement (to be replaced by the share of opens a resume or restart closed in the
# results store): the share of the opens more effort closes when the last stop was the clock, and
# when it was not.
EFFORT_PRIOR_TIME = 0.3
EFFORT_PRIOR_OTHER = 0.1
# JLCPCB standard PCBA, double-sided assembly: setup fee 51.12 vs 25.56 USD single-sided, stencil
# 16.42 vs 8.21 USD (https://jlcpcb.com/help/article/pcb-assembly-price): 25.56 + 8.21 = 33.77
FIRST_BOTTOM_USD = 34

DEFAULTS = dict(big_pads=BIG_PADS, part_opens=PART_OPENS, part_persist=PART_PERSIST, price=PRICE, task=None)


# ----------------------------------------------------------------------------- reading reports
def find_blocked(rep):
    """The `blocked` dict of a report wherever it sits, or None."""
    if not isinstance(rep, dict):
        return None
    if "congestion" in rep and "blocked" in rep and isinstance(rep.get("blocked"), list):
        return rep                                   # a standalone diagnosis
    b = rep.get("blocked")
    if isinstance(b, dict):
        return b
    fin = rep.get("final")
    if isinstance(fin, dict) and isinstance(fin.get("blocked"), dict):
        return fin["blocked"]
    return None


def _kind(rep):
    if isinstance(rep.get("final"), dict) and ("stop" in rep or "blocked_note" in rep["final"]):
        return "joint"
    if "repair" in rep or "router" in rep or "opts" in rep:
        return "route"
    return "blocked"


def _route_opts(rep):
    return rep.get("opts") or (rep.get("final") or {}).get("opts") or {}


def _stop(rep):
    """'time' when the report's last stop was the clock, else the stop reason or None."""
    rounds = (rep.get("repair") or {}).get("rounds") or []
    if rounds and rounds[-1].get("stopped"):
        s = str(rounds[-1]["stopped"])
        return "time" if s == "time" else s
    s = rep.get("stop")
    if isinstance(s, str):
        return "time" if s.startswith("time") else s
    return None


def _total_open(rep, blk):
    fin = (rep.get("repair") or {}).get("final") or rep.get("final") or {}
    u = fin.get("unconnected")
    if isinstance(u, (int, float)):
        return int(u)
    if blk:
        return len(blk.get("blocked") or []) + len(blk.get("congestion") or []) + int(blk.get("undiagnosed") or 0)
    return 0


def _ref(pad):
    return pad.rsplit(".", 1)[0] if "." in pad else pad


def drc_connections(drc):
    """Open connections of a kicad-cli DRC JSON: [{net, pads, cause: 'undiagnosed'}]."""
    out = []
    rx = re.compile(r"Pad (\S+) \[([^\]]*)\] of (\S+)")
    for it in (drc or {}).get("unconnected_items") or []:
        pads, net = [], None
        for x in it.get("items") or []:
            m = rx.search(x.get("description") or "")
            if m:
                pads.append(f"{m.group(3)}.{m.group(1)}")
                net = net or m.group(2)
        if net is not None:
            out.append(dict(net=net, pads=sorted(pads), kinds=["pad"], cause="undiagnosed"))
    return out


def _key(c):
    pads = c.get("pads") or []
    return (c.get("net") or "", tuple(sorted(pads))) if pads else (c.get("net") or "",)


def _label(c):
    return f"{c.get('net')}: {'-'.join(c.get('pads') or []) or 'copper'}"


# ----------------------------------------------------------------------------- context
class _Ctx:
    """What the rules read: the connections over all reports with their persistence."""

    def __init__(self, reports, board, opts, extra=None):
        self.o = dict(DEFAULTS, **(opts or {}))
        self.o["price"] = dict(PRICE, **((opts or {}).get("price") or {}))
        self.reports = reports
        self.board = board or {}
        self.N = len(reports)
        self.kinds = [_kind(r) for r in reports]
        self.blks = [find_blocked(r) for r in reports]
        self.ropts = [_route_opts(r) for r in reports]
        self.stops = [_stop(r) for r in reports]
        per = []
        for i, b in enumerate(self.blks):
            cs = list((b or {}).get("blocked") or []) + list((b or {}).get("congestion") or [])
            if not b and extra and i == len(reports) - 1:
                cs = list(extra)
            per.append(cs)
        seen, order = {}, []
        for i, cs in enumerate(per):
            for c in cs:
                k = _key(c)
                if k not in seen:
                    seen[k] = dict(rec=c, reports=set())
                    order.append(k)
                seen[k]["reports"].add(i)
        self.conns = []
        for k in order:
            s = seen[k]
            p = len(s["reports"]) / self.N
            c = dict(s["rec"])
            c["_key"] = k
            c["_w"] = p
            c["_refs"] = sorted({_ref(x) for x in c.get("pads") or []})
            c["_label"] = _label(c)
            self.conns.append(c)
        # part-level persistence: share of reports with an open on the part, mean opens there
        parts = {}
        for i, cs in enumerate(per):
            for c in cs:
                for r in {_ref(x) for x in c.get("pads") or []}:
                    parts.setdefault(r, [0] * self.N)[i] += 1
        self.parts = {r: dict(ref=r, persistence=round(sum(1 for v in vs if v) / self.N, 4),
                              mean_opens=round(sum(vs) / self.N, 4)) for r, vs in parts.items()}
        pk = {}
        for b in self.blks:
            for c in (b or {}).get("packages") or []:
                if isinstance(c, dict) and c.get("package"):
                    pk[c["package"]] = c         # the latest report's certificate of each package
        self.packages = [pk[k] for k in sorted(pk)]
        self.undiagnosed = [int((b or {}).get("undiagnosed") or 0) for b in self.blks]
        self.totals = [_total_open(r, b) for r, b in zip(reports, self.blks)]
        self.addressed = set()

    def pads_of(self, ref):
        """Pad count of a footprint: the board's, else a proxy from the pad names seen (the
        largest numeric pin, or 'many' for ball names like A12)."""
        p = (self.board.get("parts") or {}).get(ref)
        if p:
            return p.get("pads") or 0
        best = 0
        for c in self.conns:
            for x in c.get("pads") or []:
                if _ref(x) != ref:
                    continue
                pin = x.rsplit(".", 1)[-1]
                if pin.isdigit():
                    best = max(best, int(pin))
                elif re.fullmatch(r"[A-Z]{1,2}\d{1,2}", pin):
                    best = max(best, self.o["big_pads"])
        return best

    def any_opt(self, k, pred):
        return any(pred(o.get(k)) for o in self.ropts if o)


# ----------------------------------------------------------------------------- items
# Knob keys the catalogue names, by the registry that reads them (kept static so the menu needs
# no router import; tests assert each is in its registry, so a rename breaks a test).
# bridge.DEFAULT_OPTS (joint: bridge.KEY), plus the escape keys escape.py reads from the same opts:
BRIDGE_KEYS = ("neckdown", "pad_shapes", "planes", "plane_cost", "rounds")
BRIDGE_OPT_KEYS = ("escape_via_in_pad", "escape_plane_layers")
# kae.route.constraints.DEFAULTS (joint: the key itself; route: --set; place: KAE_<KEY> text variable)
CONSTRAINT_KEYS = ("ignored_clearance_floor", "place_margin", "place_w_cong", "escape_band")


def _joint_key(k):
    """A route --set key as joint --set reads it: bridge.KEY for the bridge's options; the
    constraints' defaults (the diagnosis' overrides are those) as they are."""
    return "bridge." + k if k in BRIDGE_KEYS + BRIDGE_OPT_KEYS else k


def _set(kv, effect="full", route=True):
    k, _, v = kv.partition("=")
    return dict(kind="set", route=["--set", kv] if route else None, joint=["--set", f"{_joint_key(k)}={v}"],
                place=None, effect=effect)


def _none(note=None, joint=None):
    d = dict(kind="none", route=None, joint=joint, place=None, effect="none")
    if note:
        d["note"] = note
    return d


def _price(fab_class=None, fab_cost=None, usd=0, plane_loss=False, scorer="allowed"):
    return dict(fab_class=fab_class, fab_cost=fab_cost, assembly_usd=usd, plane_loss=plane_loss, scorer=scorer)


def _item(ctx, id_, decision, state, conns, knob, price, target=None, source="blocked", note=None, gain=None,
          extra=None):
    conns = list(conns)
    for c in conns:
        ctx.addressed.add(c["_key"])
    g = round(sum(c["_w"] for c in conns), 4) if gain is None else gain
    t = dict(parts=[], nets=[], rule=None, layer=None)
    t["nets"] = sorted({c.get("net") for c in conns if c.get("net")})
    t["parts"] = sorted({r for c in conns for r in c["_refs"]})
    t.update(target or {})
    ev = dict(source=source, opens=len(conns), persistent_opens=round(sum(c["_w"] for c in conns), 4),
              connections=[c["_label"] for c in conns][:20])
    if note:
        ev["note"] = note
    ev.update(extra or {})
    return dict(id=id_, decision=decision, expert_state=state, target=t, evidence=ev, gain=g, price=price, knob=knob)


def _override_kv(ov, b):
    """The `name=value` of a diagnosis' override ("KAE_X / --set x=" or "--set x=0.08")."""
    m = re.search(r"--set\s+([\w.]+)=(\S*)", ov or "")
    if not m:
        return None
    k, v = m.group(1), m.group(2)
    if not v:
        a = b.get("available")
        v = f"{math.floor(max(float(a), 0.0) * 1000) / 1000:g}" if isinstance(a, (int, float)) else "<value>"
    return f"{k}={v}"


def r_kae_default(ctx):
    groups = {}
    for c in ctx.conns:
        b = c.get("binding") or {}
        if c.get("cause") != "kae default" and b.get("source") != "kae":
            continue
        if b.get("constraint") == "pad_shape":
            continue
        kv = _override_kv(b.get("override"), b) or _override_kv(b.get("where"), b)
        if kv:
            groups.setdefault(kv, []).append(c)
    return [_item(ctx, "kae_default", "kae's own default limit", "S13->S9", cs, _set(kv), _price(),
                  target=dict(rule=kv.split("=")[0]), source="blocked.binding.override",
                  note="a kae default, not a board rule, binds; the diagnosis names its override")
            for kv, cs in sorted(groups.items())]


def _pad_named(s):
    return isinstance(s, str) and s.startswith("pad ")


def r_neckdown(ctx):
    if ctx.any_opt("neckdown", lambda v: v is True):
        return []
    mins = [((r.get("plan") or {}).get("min_width")) for r in ctx.reports]
    mins = [m for m in mins if isinstance(m, (int, float))]
    wmin = min(mins) if mins else None
    cs = []
    for c in ctx.conns:
        b = c.get("binding") or {}
        if c.get("cause") == "rule" and b.get("source") == "board" and b.get("constraint") in ("track_width",
                                                                                               "clearance"):
            if _pad_named(b.get("against")) or "pad" in str(b.get("where") or ""):
                need = b.get("available") if b.get("constraint") == "track_width" else b.get("track")
                if wmin is None or need is None or need >= wmin - 1e-9:
                    cs.append(c)
                    continue
        if c.get("cause") == "congestion" and any(ctx.pads_of(r) >= ctx.o["big_pads"] for r in c["_refs"]):
            cs.append(c)
    if not cs:
        return []
    return [_item(ctx, "neckdown", "track width at pins", "S13->S2", cs, _set("neckdown=true"), _price(),
                  source="blocked.binding / congestion at big parts",
                  note="Freerouting's neck-down at pins, floored at the board's legal minimum width "
                       "(bridge._rules_settings): stays within the board's rules")]


def r_pad_shape(ctx):
    if ctx.any_opt("pad_shapes", lambda v: v == "outside"):
        return []
    cs = [c for c in ctx.conns if (c.get("binding") or {}).get("constraint") == "pad_shape"
          or "pad_shapes=outside" in str((c.get("binding") or {}).get("where") or "")]
    if not cs:
        return []
    return [_item(ctx, "pad_shape", "pin shapes in the DSN", "S13->S2", cs, _set("pad_shapes=outside"), _price(),
                  source="blocked.binding", note="pad copper beyond its DSN shape binds")]


def _relax(ctx, pred):
    """[(package certificate, relaxation)] whose relaxation removes the obstruction."""
    return [(p, r) for p in ctx.packages for r in p.get("relaxations") or [] if r.get("all") and pred(r)]


def _on_parts(ctx, refs):
    return [c for c in ctx.conns if set(c["_refs"]) & set(refs)]


def r_planes_allow(ctx):
    out = []
    rel = _relax(ctx, lambda r: str(r.get("rule", "")).startswith("signals on plane"))
    if rel:
        refs = sorted({p["package"] for p, _r in rel})
        cs = _on_parts(ctx, refs)
        k = _set("escape_plane_layers=true")
        k["route"] += ["--set", "planes=allow"]
        k["joint"] += ["--set", "bridge.planes=allow"]
        out.append(_item(ctx, "planes_allow", "signals on plane layers", "S13->S4", cs, k,
                         _price(plane_loss=True), target=dict(parts=refs), source="blocked.packages.relaxations",
                         gain=None if cs else round(sum(p.get("short") or 0 for p, _r in rel), 4),
                         note="the escape certificate finds no obstruction with signals on the plane layers"))
    strictish = ctx.any_opt("planes", lambda v: v in ("cost", "keep", "strict"))
    planes = any((r.get("plane_fill_shares") or (r.get("translate") or {}).get("plane_layers_costed"))
                 for r in ctx.reports)
    cong = [c for c in ctx.conns if c.get("cause") == "congestion"]
    if strictish and planes and cong and not rel:
        out.append(_item(ctx, "planes_allow", "signals on plane layers", "S13->S4", cong, _set("planes=allow"),
                         _price(plane_loss=True), source="congestion + opts.planes",
                         note="congestion with the inner plane layers costed or kept free of signals; "
                              "or lower plane_cost (bridge.DEFAULT_OPTS)"))
    return out


def r_via_in_pad(ctx):
    out = []
    for p, r in _relax(ctx, lambda r: str(r.get("rule", "")).startswith("vias in the balls")):
        cs = _on_parts(ctx, [p["package"]])
        out.append(_item(ctx, "via_in_pad", "via in pad for a ball grid", "S13->S6", cs,
                         _set("escape_via_in_pad=true", effect="plan_only"),
                         _price(fab_class=r.get("fab_class"), fab_cost=r.get("fab_cost")),
                         target=dict(parts=[p["package"]]), source="blocked.packages.relaxations",
                         gain=None if cs else float(p.get("short") or 0),
                         note="the escape plan is computed with via-in-pad but not laid (escape.py: the bridge "
                              "lays dog-bones); the knob changes the plan and its certificate only",
                         extra=dict(kicad=r.get("kicad"), short=p.get("short"), demand=p.get("demand"))))
    return out


def _kicad_rule(b):
    c, v = b.get("constraint"), b.get("available")
    if not isinstance(v, (int, float)):
        return None
    v = f"{math.floor(max(v, 0.0) * 1000) / 1000:g}"
    if c in ("track_width", "clearance", "hole_clearance", "edge_clearance"):
        return f".kicad_dru: (rule \"kae relax\" (constraint {c} (min {v}mm))) or {b.get('where')}"
    return f"{b.get('where')}: {c} to {v} mm"


def r_rule_relax(ctx):
    out = []
    groups = {}
    for c in ctx.conns:
        b = c.get("binding") or {}
        if c.get("cause") == "rule" and b.get("source", "board") == "board":
            groups.setdefault((b.get("constraint") or "?", b.get("where") or "?"), []).append(c)
    for (con, where), cs in sorted(groups.items()):
        b = min((c["binding"] for c in cs), key=lambda b: b.get("available") if isinstance(b.get("available"), (
            int, float)) else 1e9)
        out.append(_item(ctx, "rule_relax", "a board rule", "S13->S1", cs, _none("kae never relaxes a rule"),
                         _price(fab_class=b.get("fab_class"), fab_cost=b.get("fab_cost"), scorer="forbidden"),
                         target=dict(rule=con, layer=b.get("layer")), source="blocked.binding",
                         note=f"{con} from {where}", extra=dict(value=b.get("available"), required=b.get("required"),
                                                                kicad=_kicad_rule(b))))
    for p, r in _relax(ctx, lambda r: r.get("rule") in ("track width", "clearance", "via diameter")
                       or str(r.get("rule", "")).startswith("ball-to-track")):
        cs = _on_parts(ctx, [p["package"]])
        out.append(_item(ctx, "rule_relax", "a board rule", "S13->S1", cs, _none("kae never relaxes a rule"),
                         _price(fab_class=r.get("fab_class"), fab_cost=r.get("fab_cost"), scorer="forbidden"),
                         target=dict(parts=[p["package"]], rule=r.get("rule")), source="blocked.packages.relaxations",
                         gain=None if cs else float(p.get("short") or 0),
                         extra=dict(value=r.get("value"), kicad=r.get("kicad"), short=p.get("short"))))
    return out


def r_release_fixed(ctx):
    cs = [c for c in ctx.conns if c.get("cause") == "fixed copper"]
    if not cs:
        return []
    nets = sorted({n for c in cs for n in c.get("fixed_nets") or []})
    joint = ["--no-modules"] if "joint" in ctx.kinds else None
    return [_item(ctx, "release_fixed_copper", "keep the input's pre-routes", "S13->S3", cs,
                  _none("no route knob: the input's own copper is fixed", joint=joint), _price(),
                  source="blocked.fixed_nets", extra=dict(fixed_nets=nets),
                  note="when the fixed copper is copper kae's module stage laid (joint), --no-modules runs "
                       "without it; the input's pre-routes are released only by editing the input")]


def _part_targets(ctx):
    """Big parts carrying the congestion / geometry opens: [(ref, conns)]."""
    by = {}
    for c in ctx.conns:
        if c.get("cause") in ("congestion", "geometry", "undiagnosed"):
            for r in c["_refs"]:
                by.setdefault(r, []).append(c)
    out = []
    for r in sorted(by):
        w = sum(c["_w"] for c in by[r])
        big = ctx.pads_of(r) >= ctx.o["big_pads"]
        pers = ctx.N >= 2 and ctx.parts.get(r, {}).get("persistence", 0) >= ctx.o["part_persist"]
        if (big and w >= ctx.o["part_opens"]) or pers:
            out.append((r, by[r]))
    return out


def _placement_scorer(ctx):
    return "forbidden" if ctx.o.get("task") == "route" else "allowed"


def _edit_knob():
    return dict(kind="edit_input", route=None, joint=None, place=None, effect="full",
                note="edit the pose in the input, then hold it: kae place --fix REF, or lock the footprint for joint; "
                     "no per-part rotate/move setting exists")


def rotation_hpwl(board, ref):
    """{0, 90, 180, 270: HPWL mm} of the part's nets, its pads rotated about its own centre."""
    p = (board.get("parts") or {}).get(ref)
    if not p:
        return None
    nets = board.get("nets") or {}
    cx, cy = p["x"], p["y"]
    out = {}
    for deg in (0, 90, 180, 270):
        a = math.radians(deg)
        ca, sa = round(math.cos(a)), round(math.sin(a))
        tot = 0.0
        mine = {}
        for net, x, y in p.get("pad_xy") or []:
            if not net:
                continue
            dx, dy = x - cx, y - cy
            mine.setdefault(net, []).append((cx + dx * ca + dy * sa, cy - dx * sa + dy * ca))
        for net, pts in sorted(mine.items()):
            others = [(x, y) for r, x, y in nets.get(net) or [] if r != ref]
            if not others:
                continue
            xs = [q[0] for q in pts + others]
            ys = [q[1] for q in pts + others]
            tot += (max(xs) - min(xs)) + (max(ys) - min(ys))
        out[str(deg)] = round(tot, 3)
    return out


def r_rotate_move(ctx):
    out = []
    sc = _placement_scorer(ctx)
    for ref, cs in _part_targets(ctx):
        extra = dict(pads=ctx.pads_of(ref), part_persistence=ctx.parts.get(ref, {}).get("persistence"))
        rh = rotation_hpwl(ctx.board, ref) if ctx.board else None
        if rh:
            best = min(sorted(rh), key=lambda k: (rh[k], int(k)))
            extra = dict(extra, rotation_hpwl=rh, best_rotation=int(best))
            if rh[best] < rh["0"] - 1e-6:
                out.append(_item(ctx, "rotate_part", "orientation of a big part", "S13->S8", cs, _edit_knob(),
                                 _price(scorer=sc), target=dict(parts=[ref]), source="blocked + board",
                                 note=f"rotating {ref} by {best} deg shortens its nets' HPWL "
                                      f"{rh['0']:.1f} -> {rh[best]:.1f} mm", extra=extra))
        out.append(_item(ctx, "move_part", "position of a big part", "S13->S8", cs, _edit_knob(), _price(scorer=sc),
                         target=dict(parts=[ref]), source="blocked.congestion", extra=extra,
                         note="the opens concentrate on this part (or recur on it across attempts)"))
    return out


def r_flip(ctx):
    b = ctx.board
    if not b or (b.get("copper_layers") or 0) < 2:
        return []
    sides = {p.get("side") for p in (b.get("parts") or {}).values()}
    if len(sides) != 1:
        return []
    out = []
    side = next(iter(sides))
    smd_other = any(p.get("smd") and p.get("side") != side for p in (b.get("parts") or {}).values())
    for ref, cs in _part_targets(ctx):
        if ctx.pads_of(ref) < ctx.o["big_pads"]:
            continue
        out.append(_item(ctx, "flip_part", "board side of a big part", "S13->S8", cs,
                         _none("the placer keeps every part's side (kae/src/kae/place/problem.py)"),
                         _price(usd=0 if smd_other else FIRST_BOTTOM_USD, scorer=_placement_scorer(ctx)),
                         target=dict(parts=[ref]), source="blocked + board",
                         note="every part is on one side: the other side is free room"))
    return out


def r_placement_room(ctx):
    cong = [c for c in ctx.conns if c.get("cause") == "congestion"]
    if len(cong) < 2:
        return []
    w = sum(c["_w"] for c in cong)
    share = {}
    for c in cong:
        for r in c["_refs"]:
            share[r] = share.get(r, 0.0) + c["_w"]
    if share and max(share.values()) / w >= CONCENTRATED:
        return []
    joint = ["--set", "place_margin=-1"] + (["--set", "escape_band=1"] if ctx.packages else [])
    knob = dict(kind="set", route=None, joint=joint, place=None, effect="full",
                note="placement keys (kae.route.constraints.DEFAULTS): joint --set; in kae place only as board "
                     "text variables (KAE_PLACE_MARGIN, KAE_ESCAPE_BAND); place_w_cong is the other lever")
    return [_item(ctx, "placement_room", "routing room between parts", "S13->S8", cong, knob,
                  _price(scorer=_placement_scorer(ctx)), source="blocked.congestion",
                  note="congestion spread over the board, not on one part")]


def r_add_layers(ctx):
    out = []
    for p, r in _relax(ctx, lambda r: "more signal layers" in str(r.get("rule", ""))):
        cs = _on_parts(ctx, [p["package"]])
        out.append(_item(ctx, "add_layers", "layer count", "S13->S0", cs, _none("the stackup is the input's"),
                         _price(scorer="forbidden"), target=dict(parts=[p["package"]], rule=r.get("rule")),
                         source="blocked.packages.relaxations", gain=None if cs else float(p.get("short") or 0),
                         extra=dict(kicad=r.get("kicad"))))
    return out


def r_grow_outline(ctx):
    cs = [c for c in ctx.conns if c.get("cause") == "geometry" and
          any(("edge" in s or "outline" in s) for s in (c.get("walled_by") or []) if isinstance(s, str))]
    if not cs:
        return []
    return [_item(ctx, "grow_outline", "board outline", "S13->S0", cs, _none("the outline is the input's"),
                  _price(scorer="forbidden"), source="blocked.walled_by",
                  note="no path even with every clearance at zero, walled in at the board edge")]


def r_pin_swap(ctx):
    return [dict(id="pin_swap", decision="pin assignment", expert_state="S13->S7",
                 target=dict(parts=[], nets=[], rule=None, layer=None),
                 evidence=dict(source="none", opens=0, persistent_opens=0, connections=[],
                               note="no proxy exists yet; a pin swap changes pad nets, which the scorer forbids"),
                 gain=None, price=_price(scorer="forbidden"), knob=_none("no pin-swap support")) ]


def r_more_effort(ctx):
    timed = any(s == "time" for s in ctx.stops)
    f = EFFORT_PRIOR_TIME if timed else EFFORT_PRIOR_OTHER
    total = sum(c["_w"] for c in ctx.conns) or (sum(ctx.totals) / max(ctx.N, 1))
    knob = _set("rounds=auto")
    knob["note"] = "or resume / restart from the best board (a new seed)"
    it = _item(ctx, "more_effort", "more search (restart or resume)", "S13->S13", [], knob, _price(),
               source="stop reason", gain=round(total * f, 4),
               note=f"null item: prior {f} of all opens (to be replaced by measurement); last stops: "
                    f"{[s for s in ctx.stops]}")
    it["evidence"]["opens"] = len(ctx.conns)
    return [it]


# the catalogue, in tie-break order; more_effort last
CATALOGUE = (
    ("kae_default", r_kae_default),
    ("neckdown", r_neckdown),
    ("pad_shape", r_pad_shape),
    ("planes_allow", r_planes_allow),
    ("via_in_pad", r_via_in_pad),
    ("rule_relax", r_rule_relax),
    ("release_fixed_copper", r_release_fixed),
    ("rotate_move", r_rotate_move),
    ("flip_part", r_flip),
    ("placement_room", r_placement_room),
    ("add_layers", r_add_layers),
    ("grow_outline", r_grow_outline),
    ("pin_swap", r_pin_swap),
    ("more_effort", r_more_effort),
)


def _factor(ctx, it):
    pr, P = it["price"], ctx.o["price"]
    f = 1.0
    if pr.get("fab_class") in ("advanced", "hdi"):
        f *= P[pr["fab_class"]]
    if pr.get("plane_loss"):
        f *= P["plane_loss"]
    if pr.get("assembly_usd"):
        f *= P["first_bottom_part"]
    return f


def build_menu(reports, board=None, opts=None, drc=None):
    """The loop-back menu of `reports` (see the module docstring). Pure."""
    reports = [r for r in reports if isinstance(r, dict)]
    if not reports:
        raise ValueError("at least one report")
    ctx = _Ctx(reports, board, opts, extra=drc_connections(drc) if drc else None)
    items = []
    for order, (_name, rule) in enumerate(CATALOGUE):
        for it in rule(ctx):
            it["_order"] = order
            items.append(it)
    for it in items:
        g = it["gain"]
        if it["price"]["scorer"] == "forbidden" or g is None:
            it["score"] = 0.0
        else:
            it["score"] = round(g / _factor(ctx, it), 4)
    menu = [it for it in items if it["knob"]["kind"] != "none" and it["price"]["scorer"] == "allowed"]
    ask = [it for it in items if it not in menu]
    for lst in (menu, ask):
        lst.sort(key=lambda it: (-it["score"], it["_order"]))
        for i, it in enumerate(lst, 1):
            it["rank"] = i
            del it["_order"]
    top = (opts or {}).get("top")
    if top:
        menu = menu[:int(top)]
    by_cause = {}
    for c in ctx.conns:
        by_cause[c.get("cause") or "?"] = by_cause.get(c.get("cause") or "?", 0) + 1
    un = [c for c in ctx.conns if c["_key"] not in ctx.addressed]
    why = {}
    for c in un:
        k = c.get("cause") or "?"
        why[k] = why.get(k, 0) + 1
    und = max(ctx.undiagnosed) if ctx.undiagnosed else 0
    if und:
        why["undiagnosed"] = why.get("undiagnosed", 0) + und
    return {"schema": SCHEMA, "board": (board or {}).get("name") or _board_name(reports),
            "n_reports": ctx.N, "kinds": ctx.kinds,
            "opens": {"total": max(ctx.totals) if ctx.totals else 0, "connections": len(ctx.conns),
                      "by_cause": dict(sorted(by_cause.items())), "undiagnosed": und,
                      "per_report": ctx.totals},
            "persistence": {"n_reports": ctx.N,
                            "connections": [dict(net=c.get("net"), pads=c.get("pads") or [], cause=c.get("cause"),
                                                 persistence=round(c["_w"], 4)) for c in ctx.conns],
                            "parts": [ctx.parts[r] for r in sorted(ctx.parts, key=lambda r: (
                                -ctx.parts[r]["persistence"], -ctx.parts[r]["mean_opens"], r))]},
            "menu": menu, "ask": ask,
            "unactionable": {"opens": len(un) + und, "why": dict(sorted(why.items())),
                             "connections": [c["_label"] for c in un][:50]}}


def _board_name(reports):
    for r in reports:
        s = r.get("input") or r.get("board")
        if isinstance(s, str):
            return s.replace("\\", "/").rsplit("/", 1)[-1]
    return None


# ----------------------------------------------------------------------------- the board file
def board_summary(path):
    """What the rules read from a board file (repo's own reader, no pcbnew): parts (pads, side,
    smd, centre, pad positions with nets), nets (pad positions), copper layer count."""
    from kae.board.kicad_file import load
    p = str(path)
    if p.endswith(".gz"):
        import os
        import tempfile
        with gzip.open(p, "rb") as f:
            data = f.read()
        fd, tmp = tempfile.mkstemp(suffix=".kicad_pcb")
        try:
            with os.fdopen(fd, "wb") as g:
                g.write(data)
            b = load(tmp, rules=False)
        finally:
            os.unlink(tmp)
    else:
        b = load(p, rules=False)
    parts, nets = {}, {}
    for fp in b.footprints:
        pads = [pd for pd in fp.pads if pd.kind != "np_thru_hole"]
        parts[fp.ref] = dict(pads=len(pads), side=fp.side, smd="smd" in (fp.attrs or []), x=fp.x, y=fp.y,
                             pad_xy=[(pd.net, pd.x, pd.y) for pd in pads])
        for pd in pads:
            if pd.net:
                nets.setdefault(pd.net, []).append((fp.ref, pd.x, pd.y))
    cu = [l for l in (b.layers or {}) if l.endswith(".Cu")]
    return dict(name=p.replace("\\", "/").rsplit("/", 1)[-1], parts=parts, nets=nets, copper_layers=len(cu))


def _read_json(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt") as f:
        return json.load(f)


def dumps(doc):
    return json.dumps(doc, indent=1, sort_keys=True, default=str)


def main(argv=None):
    """python -m kae.commander.menu REPORT [REPORT ...] [--board PCB] [--drc JSON] [--out FILE] [--top N]"""
    import argparse
    ap = argparse.ArgumentParser(prog="kae.commander.menu", description=__doc__.split("\n")[0])
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--board")
    ap.add_argument("--drc")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int)
    ap.add_argument("--task", choices=("route", "joint", "place"),
                    help="the task the scorer judges: 'route' forbids placement changes")
    a = ap.parse_args(argv)
    reps = [_read_json(p) for p in a.reports]
    board = board_summary(a.board) if a.board else None
    drc = _read_json(a.drc) if a.drc else None
    doc = build_menu(reps, board=board, opts=dict(top=a.top, task=a.task), drc=drc)
    s = dumps(doc)
    if a.out:
        with open(a.out, "w") as f:
            f.write(s + "\n")
    print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
