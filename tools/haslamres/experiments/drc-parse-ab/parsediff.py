# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Old DRC item parsers (main) vs haslam.drc_items on real reports: count disagreements per call site."""
import gzip, json, glob, re, random, collections, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../haslam/src"))
from haslam import drc_items as D
lst = os.environ.get("FILES", "files.txt")
if not os.path.exists(lst):
    fs = glob.glob(os.path.expanduser("~/haslam-baselines/boards/*/runs/*/evals/*.drc.json.gz"))
    open(lst, "w").write("\n".join(fs))
fs = open(lst).read().split("\n"); random.seed(1); random.shuffle(fs); fs = fs[:int(sys.argv[1])]
# old parsers, verbatim from main
F_NET = re.compile(r"\[([^\]]*)\]"); F_REF = re.compile(r"\bof (\S+?)(?:\s+on\s|\s*$)")
def f_parse(d):
    low = d.lower()
    if low.startswith(("pad", "pth pad", "npth pad", "smd pad")): kind = "pad"
    elif low.startswith(("track", "arc")): kind = "track"
    elif low.startswith("via"): kind = "via"
    elif low.startswith(("zone", "teardrop")): kind = "zone"
    elif low.startswith("footprint"): kind = "footprint"
    else: kind = "other"
    nets = [m for m in F_NET.findall(d) if m and m != "<no net>"]
    m = F_REF.search(d)
    ref = m.group(1) if m and kind in ("pad", "footprint", "other") else ""
    if kind == "footprint" and not ref:
        p = d.split(); ref = p[1] if len(p) > 1 else ""
    return kind, ref, nets[0] if nets else ""
def n_parse(d):
    kind = D.item_kind(d); nets = D.item_nets(d)
    ref = (D.item_ref(d) or "") if kind in ("pad", "footprint", "other") else ""
    return kind, ref, nets[0] if nets else ""
L_OF = re.compile(r"\bof (\S+)"); L_FP = re.compile(r"^(?:Footprint|Courtyard of) (\S+)")
def l_ref(d):
    m = L_OF.search(d) or L_FP.search(d); return m.group(1) if m else None
BH_NET = re.compile(r"\[([^\]]+)\]"); BH_REF = re.compile(r"(?:\bof |^Footprint )(\S+)")
def bh_old(items):
    nets, refs = [], []
    for it in items or []:
        d = it.get("description") or ""
        for m in BH_NET.finditer(d):
            if m.group(1) not in nets and m.group(1) != "<no net>": nets.append(m.group(1))
        for m in BH_REF.finditer(d):
            if m.group(1) not in refs: refs.append(m.group(1))
    return refs + nets
def bh_new(items):
    nets, refs = [], []
    for it in items or []:
        d = it.get("description") or ""
        for n in D.item_nets(d):
            if n not in nets: nets.append(n)
        r = D.item_ref(d)
        if r and r not in refs: refs.append(r)
    return refs + nets
R_OF = re.compile(r"^(?:Footprint (\S+)$|.*\bpad\b.* of (\S+?)(?: on \S+)?$)", re.I)
def r_old(d):
    m = R_OF.match(d); return (m.group(1) or m.group(2)) if m else None
def r_new(d):
    return D.item_ref(d) if D.item_kind(d) in ("pad", "footprint") else None
def lm_old(rep):
    out = set()
    for u in rep.get("unconnected_items") or []:
        for it in u.get("items") or []:
            d = it.get("description") or ""
            if "[" in d and "]" in d: out.add(d[d.index("[") + 1:d.index("]")])
    return sorted(out)
def rp_old(d): return [m for m in F_NET.findall(d or "") if m and m != "<no net>"]
diff = collections.Counter(); seen = collections.Counter(); ex = collections.defaultdict(list)
import re as _re
def cat(d):
    if _re.search(r"\[[^\]]*\[|\][^ ]", d): return "bracket-net"
    if d.startswith("Footprint text of") or "| Footprint text of" in d: return "footprint-text"
    if _re.search(r"Footprint \S+ ", d): return "footprint-suffix"
    if _re.search(r" on \S+ \S+", d): return "layer-space"
    return "other"
cats = collections.Counter()
def note(site, a, b, d):
    seen[site] += 1
    if a != b:
        diff[site] += 1; c = cat(d); cats[(site, c)] += 1
        if c == "other" and len(ex[site]) < 8: ex[site].append((d[:110], a, b))
for f in fs:
    try: r = json.load(gzip.open(f))
    except Exception: continue
    seen["reports"] += 1
    for v in r.get("violations", []):
        its = v.get("items") or []
        note("board_hazards._objects", bh_old(its), bh_new(its), " | ".join(i.get("description", "") for i in its))
        for it in its:
            d = it.get("description") or ""
            note("feedback.parse_item", f_parse(d), n_parse(d), d)
            note("legalize/exact ref", l_ref(d), D.item_ref(d), d)
            note("repair._nets_of", rp_old(d), D.item_nets(d), d)
            if v.get("type") in ("courtyards_overlap", "shorting_items"):
                note("restart.overlaps ref", r_old(d), r_new(d), d)
    note("lastmile.open_nets", lm_old(r), D.open_nets(r), f)
print({k: (diff[k], seen[k]) for k in seen})
for k, n in sorted(cats.items()): print(k, n)
for k, xs in ex.items():
    print("==", k)
    for x in xs: print("  ", x)
