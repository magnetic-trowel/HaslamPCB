# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rigid array macros: LED matrices and series-resistor buses found in the netlist (J47).

A matrix of identical parts is a product of two net groups: every row net meets every column
net in exactly one part (gecko5education's 120 RGB LEDs, 12 x 10, about 165 of its 247 open
connections when the placer scatters them). The annealer's single-part moves have no incentive to keep
that lattice, so the row and column nets end up crossing everywhere. A rigid macro keeps it, and lets the
annealer move the array as one body.

Detection reads only the netlist and the footprints (never the human placement):

- `matrices`: footprints of one lib_id (at least MIN_MATRIX, movable). For a pair of pad numbers
  (a, b), part i has row net a(i) and column net b(i); the pair is a matrix when the (row, column)
  pairs are all different, both nets are signal nets, at least 2 rows and 2 columns exist and they
  fill at least MIN_FILL of rows x columns. Rows and columns are ordered by the lowest reference number on
  them, which designers usually number in matrix order; a rotation of the whole macro is the floorplan's.
- `buses`: at least MIN_BUS identical two-pin SMD parts (R, FB, ...) each joining the same two parts A
  and B by nets that touch no third part (series resistors between an FPGA and a memory): a straight
  line, ordered by the pad numbers at A, so a block fits between its ends.

`macros` turns each group into a kae.place.clusters.Macro with three layouts by the gap between cells
(GAPS_MM: routing room against compactness). `pin` then gives each macro a legal spot near the seed's
position and the parts are held there as fixed parts for the rest of the placement (pipeline's array pre-step,
like the edge connectors), so nothing downstream, annealer or legalizers, can break the lattice.
Radial arrays (LED rings) and daisy chains are not detected: the netlist of a chain cannot say what
shape the designer wants.

The array_macros setting is a mask (off by default until the A/Bs decide): 1 matrices, 2 buses, 3 both.

- Matrices of user-interface parts (key switches, buttons, touch and sensor pads: `is_ui_part`) are left
  alone: where a key or a touch pad sits is the enclosure's and the hand's requirement, which the netlist's
  reference order cannot know. array-macro-ab: such grids showed no gain (per-board 4-seed mean about +0.0 in
  log opens over 8 boards) and the keypad's lattice landed on its mounting holes.
- A bus is laid out the way designers lay one out: members side by side across their pad 1-2 axis (pitch =
  the short courtyard side + gap), each turned so its pad on end A faces A, the column ordered like A's pins
  and centred between its two ends (array-macro-ab built them end to end, at 2-3x the human pitch).
- A spot is legal only if every member is exactly clean against the board (kae.place.exact: fixed parts'
  courtyards and holes, fixed copper, rule areas) and its courtyard lies inside the outline deflated by the
  copper-to-edge clearance; the seed footprints of large movable parts (RESERVE_MM2) and of a bus's own end
  parts are kept free, so the block does not take the room they need. No spot: `no_legal_spot`, no macro.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

MIN_MATRIX = 16              # parts in a matrix: below it the tag's own threshold
MIN_FILL = 0.8               # share of rows x columns that must hold a part
MIN_BUS = 6                  # parts in a series-resistor bus
GAPS_MM = (0.5, 0.25, 1.0)   # the gaps between cells, first layout first
PASSIVE_REF = re.compile(r"^(R|FB|L|C)\d", re.I)
MATRIX, BUS = 1, 2           # array_macros mask bits
RESERVE_MM2 = 100.0          # movable parts at least this large keep their seed footprint free of macros
MAX_EXACT = 400              # candidate spots checked exactly per macro before no_legal_spot
# user-interface parts, by footprint library/name or value: key switches, buttons, touch and sensor pads
UI_WORDS = re.compile(r"(?<![a-z])key|touch|electrode|sensor_?pad|(?<![a-z])btn|button|switch|(?<![a-z])sw(?![a-z])|"
                      r"(?<![a-z])tact|(?<![a-z])mx|(?<![a-z])choc|kailh|gateron|pg1350|(?<![a-z])pad(?![a-z])|\d+(\.\d+)?mm_?pad|flex_?sensor",
                      re.I)
UI_REFS = {"SW", "S", "KEY", "KEYS", "BTN", "BUTTON", "TS"}


def is_ui_part(fp):
    """Whether footprint `fp` is a user-interface part (a key, button, touch or sensor pad): the fixed-part
    classifier's user class (kae.place.mech_rules, LEDs aside) or UI_WORDS / UI_REFS."""
    from .mech_rules import classify, ref_prefix
    lib_id = fp.lib_id or ""
    lib, _, name = lib_id.rpartition(":")
    pads = fp.pads or ()
    drilled = [p for p in pads if getattr(p, "drill", 0.0)]
    npth = sum(1 for p in pads if getattr(p, "kind", "") == "np_thru_hole")
    try:
        cls, why = classify(dict(ref=fp.ref, lib=lib, name=name, value=getattr(fp, "value", "") or "",
                                 pads=len(pads), pth=len(drilled) - npth, npth=npth, smd=len(pads) - len(drilled)))
    except Exception:       # noqa: BLE001 - the words below still apply
        cls, why = None, ""
    if cls == "user" and "LED" not in why:
        return True
    return bool(UI_WORDS.search(lib_id) or UI_WORDS.search(getattr(fp, "value", "") or "")
                or ref_prefix(fp.ref) in UI_REFS)


@dataclass
class ArrayGroup:
    kind: str           # "matrix" | "bus"
    cells: dict         # part id -> (row, col)
    rows: int
    cols: int
    pads: tuple = ()
    ends: tuple = ()    # bus: (uuid of end A, uuid of end B)
    toward: dict = None  # bus: member uuid -> (index of its pad on A's side, index of A's pad, of B's pad it meets)


def _num(s):
    m = re.search(r"\d+", str(s))
    return (int(m.group()) if m else 1 << 30, str(s))


def _is_power(net, kinds):
    return kinds.get(net) in ("ground", "power")


def _pad_net(fp):
    """{pad number: net} of a footprint's pads with a net; a number with several nets: none."""
    out = {}
    for p in fp.pads:
        if not p.net:
            continue
        if p.number in out and out[p.number] != p.net:
            out[p.number] = ""
        else:
            out[p.number] = p.net
    return {k: v for k, v in out.items() if v}


def matrices(fps, kinds, exclude=()):
    """[ArrayGroup kind matrix] over footprints `fps` (objects with uuid, ref, lib_id, pads)."""
    by_lib = defaultdict(list)
    for f in fps:
        if f.pads and f.uuid not in exclude:
            by_lib[f.lib_id].append(f)
    out, used = [], set(exclude)
    for lib, parts in sorted(by_lib.items(), key=lambda t: -len(t[1])):
        parts = [f for f in parts if f.uuid not in used]
        if len(parts) < MIN_MATRIX:
            continue
        pn = {f.uuid: _pad_net(f) for f in parts}
        numbers = sorted({k for d in pn.values() for k in d})
        best = None
        for a in numbers:
            for b in numbers:
                if a >= b:
                    continue
                rows, cols = {}, {}
                cells, ok, pairs = {}, True, set()
                for f in parts:
                    d = pn[f.uuid]
                    if a not in d or b not in d or _is_power(d[a], kinds) or _is_power(d[b], kinds):
                        ok = False
                        break
                    pair = (d[a], d[b])
                    if pair in pairs:
                        ok = False
                        break
                    pairs.add(pair)
                    rows.setdefault(d[a], []).append(f.ref)
                    cols.setdefault(d[b], []).append(f.ref)
                    cells[f.uuid] = pair
                if not ok or len(rows) < 2 or len(cols) < 2:
                    continue
                fill = len(parts) / (len(rows) * len(cols))
                if fill >= MIN_FILL and (best is None or (fill, -abs(len(rows) - len(cols))) > best[0]):
                    best = ((fill, -abs(len(rows) - len(cols))), rows, cols, cells, (a, b))
        if best is None:
            continue
        _, rows, cols, cells, pads = best
        order = lambda d: {n: i for i, n in enumerate(sorted(d, key=lambda n: min(_num(r) for r in d[n])))}
        rr, cc = order(rows), order(cols)
        grid = {u: (rr[r], cc[c]) for u, (r, c) in cells.items()}
        out.append(ArrayGroup("matrix", grid, len(rr), len(cc), pads))
        used |= set(grid)
    return out


def buses(fps, kinds, exclude=(), pin_fps=None):
    """[ArrayGroup kind bus (rows 1)]: series two-pin parts of one lib_id between the same two parts.
    Members come from `fps`; the parts at the two ends are looked up among `pin_fps` (default `fps`):
    pass every part of the board, so a bus whose far end is a fixed connector is still a bus."""
    pins = defaultdict(list)
    for f in (fps if pin_fps is None else pin_fps):
        for p in f.pads:
            if p.net:
                pins[p.net].append((f, p))
    groups = defaultdict(list)
    for f in fps:
        if f.uuid in exclude or not PASSIVE_REF.match(f.ref) or len(f.pads) != 2 or any(p.drill for p in f.pads):
            continue
        n1, n2 = f.pads[0].net, f.pads[1].net
        if not n1 or not n2 or n1 == n2 or _is_power(n1, kinds) or _is_power(n2, kinds):
            continue
        o1 = [(g, p) for g, p in pins[n1] if g.uuid != f.uuid]
        o2 = [(g, p) for g, p in pins[n2] if g.uuid != f.uuid]
        if len(o1) != 1 or len(o2) != 1:
            continue
        (g1, p1), (g2, p2) = o1[0], o2[0]
        if g1.uuid == g2.uuid:
            continue
        a, b, mine = (g1, p1), (g2, p2), 0          # mine: the member's pad on a's side
        if a[0].uuid > b[0].uuid:
            a, b, mine = b, a, 1
        at_a = next(k for k, q in enumerate(a[0].pads) if q is a[1])
        at_b = next(k for k, q in enumerate(b[0].pads) if q is b[1])
        groups[(f.lib_id, a[0].uuid, b[0].uuid)].append((f, a[1].number, (mine, at_a, at_b)))
    out = []
    for key, members in sorted(groups.items(), key=lambda t: -len(t[1])):
        if len(members) < MIN_BUS:
            continue
        members.sort(key=lambda t: _num(t[1]))
        out.append(ArrayGroup("bus", {f.uuid: (0, c) for c, (f, _, _) in enumerate(members)}, 1, len(members),
                              ends=(key[1], key[2]), toward={f.uuid: t for f, _, t in members}))
    return out


def _cell_rot(P, i, mine):
    """Rotation index of bus member i with its pad `mine` (on end A's side) at -x and the other at +x."""
    best, bk = None, 0
    p = P.parts[i]
    for k, r in enumerate(p.rots):
        if len(r.pins) < 2:
            continue
        v = r.pins[1 - mine] - r.pins[mine]
        n = float((v[0] ** 2 + v[1] ** 2) ** 0.5) or 1.0
        c = float(v[0]) / n
        if best is None or c > best + 1e-9:
            best, bk = c, k
    return bk


def bus_layouts(P, order, rot_of):
    """Layouts of a bus column: members `order` side by side along y (slot 0 at the top), each at rotation
    rot_of[i] (pad on A's side at -x), pitch = the cell's y extent + gap; anchor: the middle member."""
    from .clusters import _layout
    g = P.g
    ra = (len(order) - 1) // 2
    anchor = order[ra]
    h = max(P.parts[i].rots[rot_of[i]].g_own[3] - P.parts[i].rots[rot_of[i]].g_own[2] for i in order)
    out, seen = [], set()
    for gap in GAPS_MM:
        py = h + int(round(gap / g))
        if py in seen:
            continue
        seen.add(py)
        out.append(_layout(P, {i: (0, (s - ra) * py, rot_of[i]) for s, i in enumerate(order)}, 0.0))
    return anchor, out


def macros(P, used=(), log=None, kinds=MATRIX | BUS):
    """(Macros for P's arrays, report). `used`: part indices already in other macros; `kinds`: the
    array_macros mask (MATRIX, BUS). Each Macro carries `.array` = dict(kind, ends, toward) for pin()."""
    from .clusters import Macro, _layout
    from .problem import net_class_guess
    fps = [p.fp for p in P.parts if p.movable]
    all_fps = [p.fp for p in P.parts]
    kinds_of = {n.name: n.kind for n in P.nets}
    for n in {pd.net for p in P.parts for pd in p.fp.pads if pd.net}:
        kinds_of.setdefault(n, net_class_guess(n, 2, max(1, len(P.parts))))
    uuid_of = {p.fp.uuid: p.i for p in P.parts}
    index_used = {P.parts[i].fp.uuid for i in used}
    mats = matrices(fps, kinds_of, exclude=index_used)
    taken = index_used | {u for g in mats for u in g.cells}
    bs = buses(fps, kinds_of, exclude=taken, pin_fps=all_fps)
    out = []
    rep = dict(matrices=[], buses=[], skipped=[])
    g = P.g
    for grp in mats + bs:
        members = [uuid_of[u] for u in grp.cells]
        i0 = members[0]
        info = dict(ref=P.parts[i0].ref, parts=len(members), rows=grp.rows, cols=grp.cols, lib=P.parts[i0].fp.lib_id)
        if grp.kind == "matrix" and not kinds & MATRIX or grp.kind == "bus" and not kinds & BUS:
            rep["skipped"].append(dict(info, kind=grp.kind, why="kind off"))
            continue
        if grp.kind == "matrix" and is_ui_part(P.parts[i0].fp):
            rep["skipped"].append(dict(info, kind=grp.kind, why="user-interface parts"))
            continue
        cells = {uuid_of[u]: rc for u, rc in grp.cells.items()}
        if grp.kind == "bus":
            toward = {uuid_of[u]: t for u, t in grp.toward.items()}
            rot_of = {i: _cell_rot(P, i, toward[i][0]) for i in members}
            order = sorted(members, key=lambda i: cells[i][1])
            anchor, layouts = bus_layouts(P, order, rot_of)
            mac = Macro(members=order, anchor=anchor, layouts=layouts, structs=[])
            mac.array = dict(kind="bus", ends=tuple(uuid_of[u] for u in grp.ends), toward=toward, rot_of=rot_of)
        else:
            a, b, c, d = P.parts[i0].rots[0].g_own
            w, h = b - a, d - c
            r0 = (grp.rows - 1) // 2
            c0 = (grp.cols - 1) // 2
            anchor = min(members, key=lambda i: (abs(cells[i][0] - r0) + abs(cells[i][1] - c0), i))
            ra, ca = cells[anchor]
            layouts, seen = [], set()
            for gap in GAPS_MM:
                px, py = w + int(round(gap / g)), h + int(round(gap / g))
                if (px, py) in seen:
                    continue
                seen.add((px, py))
                off = {i: ((cells[i][1] - ca) * px, (cells[i][0] - ra) * py, 0) for i in members}
                layouts.append(_layout(P, off, 0.0))
            mac = Macro(members=members, anchor=anchor, layouts=layouts, structs=[])
            mac.array = dict(kind="matrix")
        out.append(mac)
        rep["matrices" if grp.kind == "matrix" else "buses"].append(info)
    if log and (out or rep["skipped"]):
        log(f"array macros: {len(rep['matrices'])} matrices, {len(rep['buses'])} buses "
            f"({sum(len(m.members) for m in out)} parts); skipped {len(rep['skipped'])}")
    return out, rep


def _bbox(P, lay, q):
    """Grid bounding box (x0, x1, y0, y1) of a layout turned q quarter turns, about the anchor."""
    xs0, xs1, ys0, ys1 = [], [], [], []
    for i, (dx, dy, k) in lay.offsets.items():
        for _ in range(q):
            dx, dy = dy, -dx
        k2 = P.parts[i].turn[k][q]
        a, b, c, d = P.parts[i].rots[k2].g_own
        xs0.append(dx + a); xs1.append(dx + b); ys0.append(dy + c); ys1.append(dy + d)
    return min(xs0), max(xs1), min(ys0), max(ys1)


def _spot(P, mac, x0, y0, taken, step, qs=range(4), ok=None, max_exact=MAX_EXACT):
    """(dist, X, Y, layout, q) of the anchor: the spot nearest (x0, y0) (mm) where every member's board box
    is inside the outline, the array's bounding box is clear of fixed obstacles and of `taken` (side, grid
    box), and `ok(layout, q, X, Y)` (the exact check) passes; at most `max_exact` spots are checked
    exactly. None: no such spot."""
    import numpy as np
    first = P.parts[mac.anchor]
    side = 0 if first.s > 0 else 1
    tht = any(P.parts[i].tht for i in mac.members)
    Xc, Yc = (x0 - P.ox) / P.g, (y0 - P.oy) / P.g
    blocks = [ob.g for ob in P.obstacles if ob.side == side or tht] + [b for sd, b in taken if sd == side or tht]
    cands = []
    for lay in mac.layouts:
        for q in qs:
            x_a, x_b, y_a, y_b = _bbox(P, lay, q)
            Xs = np.arange(-x_a, P.ncx - x_b + 1, step)
            Ys = np.arange(-y_a, P.ncy - y_b + 1, step)
            if not len(Xs) or not len(Ys):
                continue
            free = np.ones((len(Xs), len(Ys)), bool)
            for (t0, t1, u0, u1) in blocks:
                free &= ~((Xs + x_a) < t1)[:, None] | ~(t0 < (Xs + x_b))[:, None] | ~((Ys + y_a) < u1)[None, :] | ~(u0 < (Ys + y_b))[None, :]
            dist = np.hypot((Xs - Xc)[:, None], (Ys - Yc)[None, :])
            key = np.where(free, dist, np.inf).ravel()
            n = 0
            for f in np.argsort(key, kind="stable"):
                if not np.isfinite(key[f]) or n >= max_exact:
                    break
                xi, yi = np.unravel_index(f, (len(Xs), len(Ys)))
                X, Y = int(Xs[xi]), int(Ys[yi])
                if all(P.outside_cells_all(*_at(P, i, lay, q, X, Y)) == 0 for i in lay.offsets):
                    cands.append((float(key[f]), len(cands), X, Y, lay, q))
                    n += 1
    cands.sort(key=lambda t: (t[0], t[1]))
    for d, _, X, Y, lay, q in cands[:max_exact]:
        if ok is None or ok(lay, q, X, Y):
            return d, X, Y, lay, q
    return None


def _at(P, i, lay, q, X, Y):
    dx, dy, k = lay.offsets[i]
    for _ in range(q):
        dx, dy = dy, -dx
    k2 = P.parts[i].turn[k][q]
    r = P.parts[i].rots[k2]
    return X + dx, Y + dy, r.g_boards or (r.g_board,)


class _Stop(Exception):
    pass


class _Exact:
    """Exact legality of macro members against what stays where it is: fixed parts, fixed copper, rule
    areas, the outline (kae.place.exact), with every movable part out of the way (they move later) and the
    members of macros already pinned in place. Courtyards must also lie inside the outline deflated by
    the copper-to-edge clearance."""

    def __init__(self, P, st):
        from .exact import ExactModel
        far = st.copy()
        for i in P.mov:
            far.X[i] = far.Y[i] = -(10 ** 7)
        self.P, self.st = P, far
        self.m = ExactModel(P, far)
        self.inner = P.outline.buffer(-max(0.0, P.edge_clearance))
        self.last = None          # the member that failed last: checked first next time
        self.why = {}             # finding type -> spots it rejected

    def member(self, i, X, Y, K):
        st, m = self.st, self.m
        saved = (st.X[i], st.Y[i], st.K[i])
        st.X[i], st.Y[i], st.K[i] = X, Y, K
        try:
            A = m._shapes(i, st.pose(i))
        finally:
            st.X[i], st.Y[i], st.K[i] = saved
        for cy in A["cy"].values():
            if cy is not None and not self.inner.contains(cy):
                return "courtyard_outside"

        def add(kind, idx, detail=""):
            raise _Stop(kind)
        try:
            m._env(i, A, add)
            for j in m.neighbours(A["env"], skip=i):
                m._pair(i, A, j, m.sh[j], add)
        except _Stop as e:
            return str(e)
        return None

    def ok(self, lay, q, X, Y):
        P = self.P
        order = list(lay.offsets)
        if self.last in lay.offsets:
            order.remove(self.last)
            order.insert(0, self.last)
        for i in order:
            x, y, gb = _at(P, i, lay, q, X, Y)
            k2 = _k(P, i, lay, q)
            why = self.member(i, x, y, k2)
            if why:
                self.last = i
                self.why[why] = self.why.get(why, 0) + 1
                return False
        return True

    def commit(self, i, X, Y, K):
        self.m.set_pose(i, X, Y, K)


def _k(P, i, lay, q):
    return P.parts[i].turn[lay.offsets[i][2]][q]


def _rot_q(v, q):
    x, y = v
    for _ in range(q):
        x, y = y, -x
    return x, y


def _bus_plan(P, mac, st):
    """(target x, y in mm, q, layouts, anchor) of a bus: the column centred between its ends' pins, turned
    so the members' A-side pads face end A, ordered along the column like the pins of its denser end."""
    import numpy as np
    info = mac.array
    ia, ib = info["ends"]
    tw = info["toward"]
    pa, pb = st.pins_xy(ia), st.pins_xy(ib)
    a_xy = {i: pa[tw[i][1]] for i in mac.members}
    b_xy = {i: pb[tw[i][2]] for i in mac.members}
    ca = np.mean([a_xy[i] for i in mac.members], axis=0)
    cb = np.mean([b_xy[i] for i in mac.members], axis=0)
    u = ca - cb
    n = float(np.hypot(*u))
    # the layout's A side is -x: the quarter turn that points it most nearly at A
    q = max(range(4), key=lambda q: (float(np.dot(_rot_q((-1.0, 0.0), q), u)) / (n or 1.0), -q)) if n > 1e-9 else 0
    w = np.array(_rot_q((0.0, 1.0), q))        # where the column's slot order runs on the board
    # the column follows the pin order of its denser end (an IC rather than a connector): where the two
    # ends' orders disagree the wires cross at the end with the more room
    spread = lambda xy: float(np.ptp([np.dot(xy[i], w) for i in mac.members]))
    near, far = (a_xy, b_xy) if spread(a_xy) <= spread(b_xy) else (b_xy, a_xy)
    order = sorted(mac.members, key=lambda i: (float(np.dot(near[i], w)), float(np.dot(far[i], w)), i))
    anchor, layouts = bus_layouts(P, order, info["rot_of"])
    x, y = (ca + cb) / 2
    return float(x), float(y), q, layouts, anchor


def _reserved(P, st, macs):
    """[(side, grid rect)] of the seed footprints the macros must keep free: movable parts of at least
    RESERVE_MM2 and the movable end parts of buses (not members of a macro)."""
    members = {i for m in macs for i in m.members}
    want = {i for i in P.mov if P.parts[i].area >= RESERVE_MM2}
    for m in macs:
        if getattr(m, "array", {}).get("kind") == "bus":
            want |= {i for i in m.array["ends"] if P.parts[i].movable}
    return [(sd, r) for i in sorted(want - members) for sd, r, _ in st.grid_rects(i)]


def pin(P, macs, st, step_mm=1.0, exact=True):
    """({uuid: (x, y, rot, side)} of every member of the macros that fit, largest macro first, the refs of
    macros with no legal spot, report). Positions come from the seed `st`: a matrix near its anchor's seed
    position, a bus between its two ends (_bus_plan)."""
    g = P.g
    step = max(1, int(round(step_mm / g)))
    poses, failed, taken = {}, [], list(_reserved(P, st, macs))
    chk = _Exact(P, st) if exact else None
    rep = dict(reserved=len(taken), spots=[])
    for mac in sorted(macs, key=lambda m: -len(m.members)):
        if getattr(mac, "array", {}).get("kind") == "bus":
            x0, y0, q, layouts, anchor = _bus_plan(P, mac, st)
            mac.layouts, mac.anchor, qs = layouts, anchor, (q,)
        else:
            x0, y0 = (float(v) for v in st.xy(mac.anchor))
            qs = range(4)
        if chk is not None:
            chk.why = {}
        spot = _spot(P, mac, x0, y0, taken, step, qs=qs, ok=chk.ok if chk is not None else None)
        if spot is None:
            failed.append(P.parts[mac.anchor].ref)
            rep["spots"].append(dict(ref=P.parts[mac.anchor].ref, spot=None, rejected=dict(chk.why) if chk else {}))
            continue
        d, X, Y, lay, q = spot
        x_a, x_b, y_a, y_b = _bbox(P, lay, q)
        taken.append((0 if P.parts[mac.anchor].s > 0 else 1, (X + x_a, X + x_b, Y + y_a, Y + y_b)))
        rep["spots"].append(dict(ref=P.parts[mac.anchor].ref, dist_mm=round(d * g, 2), q=q,
                                 rejected=dict(chk.why) if chk else {}))
        for i in lay.offsets:
            dx, dy, k = lay.offsets[i]
            dx, dy = _rot_q((dx, dy), q)
            k2 = P.parts[i].turn[k][q]
            p = P.parts[i]
            if chk is not None:
                chk.commit(i, X + dx, Y + dy, k2)
            poses[p.uuid] = (round(P.ox + (X + dx) * g, 6), round(P.oy + (Y + dy) * g, 6), float(p.rots[k2].rot), p.side)
    return poses, failed, rep
