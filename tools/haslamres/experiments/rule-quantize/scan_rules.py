# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""rule-quantize: which usable boards have a .kicad_dru bound that haslam's or Freerouting's grids push a value past.

Usage: python3 scan_rules.py BOARDS_DIR USABILITY_JSONL OUT_JSON

KiCad judges in integer nm. On main, haslam rounds class widths up to 0.1 um (constraints.up) and via sizes up to
1 um (_via_size); Freerouting keeps half widths in whole 0.1 um units, so a routed width lands on a 0.2 um grid
(nearest). For every (constraint ...) with a max, or min = max, this reports whether the value haslam would pick
(opt, else min, clamped into [min, max]) leaves the interval after those roundings, and whether the interval
holds any point of the grid at all. It also reports net-class vias whose drill and diameter, each rounded up to 1 um
on its own (main's _via_size), leave a ring below the board's minimum annular width (0.4064/0.2032 mm with a
0.1016 mm ring becomes 0.407/0.204, ring 0.1015).
"""
import json, math, re, sys

U = {"mm": 1.0, "mil": 0.0254, "um": 1e-3, "in": 25.4, "nm": 1e-6}
GRIDS = {"track_width": 2e-4, "diff_pair_width": 2e-4, "via_diameter": 1e-3, "hole_size": 1e-3,
         "annular_width": 1e-3}


def mm(v, unit):
    return round(float(v) * U[unit or "mm"], 9)


def bodies(text):
    for m in re.finditer(r"\(constraint\s+([a-z_]+)", text):
        depth = 0
        for j in range(m.start(), len(text)):
            depth += (text[j] == "(") - (text[j] == ")")
            if depth == 0:
                yield m.group(1), text[m.end():j]
                break


def chain(ctype, v):
    """The value main ends with: haslam's up() then, for widths, Freerouting's nearest 0.2 um."""
    if ctype in ("via_diameter", "hole_size"):
        return math.ceil(v * 1000 - 1e-6) / 1000
    w = math.ceil(v / 1e-4 - 1e-6) * 1e-4
    if ctype in ("track_width", "diff_pair_width"):
        w = 2e-4 * math.floor(w / 2e-4 + 0.5 + 1e-9)
    return w


def annular(boards, bid):
    try:
        d = json.load(open(f"{boards}/{bid}/board.kicad_pro"))
    except (OSError, ValueError):
        return []
    r = (d.get("board", {}).get("design_settings", {}) or {}).get("rules", {}) or {}
    a, mD, md = (r.get(k) or 0.0 for k in ("min_via_annular_width", "min_via_diameter", "min_through_hole_diameter"))
    out = []
    for nc in (d.get("net_settings", {}) or {}).get("classes", []) or []:
        D, dr = nc.get("via_diameter"), nc.get("via_drill")
        if not (a and D and dr):
            continue
        dr = max(dr, md)
        D = max(D, mD, dr + 2 * a)
        D2, d2 = (math.ceil(v * 1000 - 1e-6) / 1000 for v in (D, dr))
        if (D2 - d2) / 2 < a - 5e-7:
            out.append(dict(ctype="annular_width", min=a, opt=None, max=None, main=round((D2 - d2) / 2, 6),
                            crosses=True, grid_point_inside=True, via=[D, dr], netclass=nc.get("name")))
    return out


def scan(boards, usable):
    out = []
    for bid in usable:
        try:
            t = open(f"{boards}/{bid}/board.kicad_dru", errors="replace").read()
        except OSError:
            t = ""
        t = "\n".join(x for x in t.splitlines() if not x.strip().startswith("#"))
        hits = []
        for ctype, body in bodies(t):
            v = {k: mm(x, u) for k, x, u in re.findall(r"\((min|opt|max)\s+(-?[0-9.]+)\s*(mm|mil|um|in|nm)?\)", body)}
            if "max" not in v or ctype not in GRIDS:
                continue
            lo, hi = v.get("min", 0.0), v["max"]
            want = min(max(v.get("opt", lo), lo), hi)
            got = chain(ctype, want)
            q = GRIDS[ctype]
            k = math.ceil(lo / q - 1e-6)
            fits = k * q <= hi + 1e-9
            if got > hi + 1e-9 or got < lo - 1e-9 or not fits:
                hits.append(dict(ctype=ctype, min=lo, opt=v.get("opt"), max=hi, main=round(got, 6),
                                 crosses=got > hi + 1e-9 or got < lo - 1e-9, grid_point_inside=fits))
        hits += annular(boards, bid)
        if hits:
            out.append(dict(id=bid, hits=hits))
    return out


if __name__ == "__main__":
    boards, use, dst = sys.argv[1:4]
    usable = [r["id"] for r in map(json.loads, open(use)) if r.get("usable_route_test")]
    res = scan(boards, usable)
    json.dump(dict(usable=len(usable), boards=res), open(dst, "w"), indent=1)
    for r in res:
        print(r["id"], [(h["ctype"], h["min"], h["max"], h["main"], h["grid_point_inside"]) for h in r["hits"]][:4])
    print(len(res), "boards of", len(usable))
