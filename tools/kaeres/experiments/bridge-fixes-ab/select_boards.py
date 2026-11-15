# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""bridge-fixes-ab board selection (PLAN.md), from the board corpus and the board-tag tables.

Usage: python3 select_boards.py BOARDS_DIR TAGS_DIR OUT_DIR

For every board with usable_route_test, reads the widths kae's bridge may give a routing class (net-class
track_width and diff_pair_width from the project or a KiCad 5 board, and a .kicad_dru track_width's opt or min)
and the .kicad_dru (constraint disallow ... track ...) rules. Writes:
  scan.json        per board: odd-unit widths, binding width rules (min = max on an odd-unit width), disallow rules
  mech-width.txt   boards with a binding odd-unit width rule (fix 1's errors)
  mech.txt         boards where a fix removes errors: a binding odd-unit width rule (fix 1), or a disallow-track
                   rule whose condition names nets or classes by layer, not geometry (fix 2); listed by hand below
  ordered.txt      boards where only fix 1 acts (odd-unit widths, no binding rule), one per repo_family, hard ones
                   first (route_demand hard/extreme or pad_density very_dense/extreme), each group shuffled by SEED
"""
import json, math, os, random, re, sys

SEED = "bridge-fixes-ab-2026-11-14"
UNIT = 1e-4      # mm: kae's DSN resolution; Freerouting keeps half widths in whole units of it
# Read by hand (PLAN.md): disallow-track rules whose condition is a net, class or layer test. The other boards with
# disallow-track rules (stab-rabbit serenity pilot/tacco, techmiguel stillpoint) condition on areas or courtyards only,
# which rules.disallowed reads as not matching: the fix does nothing there.
MECH = ["eevengers-thunderscope-thunderscope-rev5-3", "ewoudvv-ducktop2-12-keyboard-daughterboard",
        "ewoudvv-ducktop2-ducktop2-center", "ewoudvv-ducktop2-left-io", "ewoudvv-ducktop2-right-io",
        "opendrone-hw-openaio-whoop-openaio-whoop", "ripclap-rm520n-carrier-carrier"]


def units(w):
    return math.ceil(w / UNIT - 1e-6)


def mm(v):
    m = re.match(r"([0-9.]+)\s*(mm|mil|um|in)?", v)
    return float(m.group(1)) * {"mm": 1, "mil": 0.0254, "um": 1e-3, "in": 25.4}[m.group(2) or "mm"]


def constraints(text, ctype):
    """Bodies of (constraint CTYPE ...), parentheses balanced."""
    for m in re.finditer(r"\(constraint\s+" + ctype + r"\b", text):
        depth = 0
        for j in range(m.start(), len(text)):
            depth += (text[j] == "(") - (text[j] == ")")
            if depth == 0:
                yield text[m.end():j]
                break


def scan(boards, use, feat):
    out = []
    for bid, u in sorted(use.items()):
        if not u.get("usable_route_test"):
            continue
        f = feat.get(bid, {})
        odd = set()
        for nc in (f.get("netclasses_pro") or []) + (f.get("netclasses_legacy") or []):
            for k in ("track_width", "diff_pair_width", "trace_width"):
                w = nc.get(k) if isinstance(nc, dict) else None
                if isinstance(w, (int, float)) and w > 0 and units(w) % 2:
                    odd.add(("netclass", k, round(w, 6)))
        bind, disallow = [], []
        p = os.path.join(boards, bid, "board.kicad_dru")
        if os.path.exists(p):
            t = "\n".join(x for x in open(p, errors="replace").read().splitlines() if not x.strip().startswith("#"))
            for body in constraints(t, "track_width"):
                v = {k: mm(x) for k, x in re.findall(r"\((min|opt|max)\s+([0-9.]+\s*(?:mm|mil|um|in)?)\)", body)}
                w = v.get("opt", v.get("min"))
                if w and units(w) % 2:
                    odd.add(("dru", "track_width", round(w, 6)))
                    if "max" in v and (units(w) + 1) * UNIT > v["max"] + 1e-9:
                        bind.append(v)
            for body in constraints(t, "disallow"):
                if "track" in body.split():
                    disallow.append(body.split())
        if odd or bind or disallow:
            out.append(dict(id=bid, odd=sorted(odd), bind=bind, disallow=disallow, family=u.get("repo_family")))
    return out


def main(boards, tags_dir, out_dir):
    use = {d["id"]: d for d in map(json.loads, open(os.path.join(tags_dir, "usability.jsonl")))}
    feat = {d["id"]: d for d in map(json.loads, open(os.path.join(tags_dir, "features.jsonl")))}
    hard = set()
    for d in map(json.loads, open(os.path.join(tags_dir, "tags.jsonl"))):
        t = d["tags"]
        if (t.get("route_demand", {}).get("value") in ("hard", "extreme") or
                t.get("pad_density", {}).get("value") in ("very_dense", "extreme")):
            hard.add(d["id"])
    rows = scan(boards, use, feat)
    json.dump(rows, open(os.path.join(out_dir, "scan.json"), "w"), indent=1)
    mech_fam = {use[b]["repo_family"] for b in MECH}
    by_fam = {}
    for r in rows:
        if r["odd"] and not r["bind"] and r["id"] not in MECH and r["family"] not in mech_fam:
            by_fam.setdefault(r["family"], []).append(r["id"])
    rng = random.Random(SEED)
    pick = []
    for fam in sorted(by_fam):
        ids = sorted(by_fam[fam])
        hs = [b for b in ids if b in hard]
        pick.append(rng.choice(hs or ids))
    first = sorted(b for b in pick if b in hard)
    rest = sorted(b for b in pick if b not in hard)
    rng.shuffle(first)
    rng.shuffle(rest)
    open(os.path.join(out_dir, "ordered.txt"), "w").write("".join(b + "\n" for b in first + rest))
    open(os.path.join(out_dir, "mech.txt"), "w").write("".join(b + "\n" for b in MECH))
    open(os.path.join(out_dir, "mech-width.txt"), "w").write("".join(r["id"] + "\n" for r in rows if r["bind"]))
    print(f"scanned {len(rows)}; binding {sum(1 for r in rows if r['bind'])}; disallow {sum(1 for r in rows if r['disallow'])}; "
          f"odd-only families {len(pick)} ({len(first)} hard)")


if __name__ == "__main__":
    main(*sys.argv[1:4])
