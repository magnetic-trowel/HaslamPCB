#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""net_layers: layer-set tables for kae's `net_layers` setting (kae.route.layer_assign), and how far
a routed board's layer use is from a reference's. Text parse of .kicad_pcb or .kicad_pcb.gz; no KiCad.

  net_layers.py extract ROUTED.kicad_pcb -o OUT [--roles] [--source TEXT]
      Per net, the copper layers of its segments and arcs, as a table. OUT is a .json file, or a
      directory: then <board stem>.json and <net-name fingerprint>.json are both written, and
      KAE_NET_LAYERS=OUT finds the table for the bare copy of the same board.
      --roles: every net gets the same set, the layers on which the board has any track
      (which layers carry signals at all), instead of its own layers.
  net_layers.py reach ROUTED.kicad_pcb REFERENCE.kicad_pcb [--json]
      Share of ROUTED's track length, and of its routed nets, on layers REFERENCE does not use for
      that net; per-layer shares of track length for both.

A table extracted from a human layout of the board under test is an oracle for diagnosis only
(what a perfect layer assignment can buy through the router): keep it out of the repository and
out of any delivered method.
"""
import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

_NUM = r"([-\d.eE+]+)"
_NET = r'\(net (?:(\d+)|"((?:[^"\\]|\\.)*)")\)'
SEG = re.compile(r"\((?:segment|arc)\s+\(start " + _NUM + " " + _NUM + r"\)\s+(?:\(mid [^)]*\)\s+)?\(end " + _NUM + " " + _NUM
                 + r"\)\s+\(width [^)]*\)\s+(?:\(locked [^)]*\)\s+)?\(layer \"([^\"]+)\"\)\s+(?:\(locked [^)]*\)\s+)?" + _NET)
NET_TABLE = re.compile(r'^\s*\(net (\d+) "((?:[^"\\]|\\.)*)"\)\s*$', re.M)
NET_REF = re.compile(r'\(net (?:\d+ )?"((?:[^"\\]|\\.)*)"\)')


def _unescape(s):
    return re.sub(r"\\(.)", r"\1", s)


def read(path):
    p = Path(path)
    return gzip.open(p, "rt", errors="replace").read() if p.suffix == ".gz" else p.read_text(errors="replace")


def stem(path):
    n = Path(path).name
    for suf in (".gz", ".kicad_pcb"):
        if n.endswith(suf):
            n = n[:-len(suf)]
    return n


def tracks(text):
    """{net name: {layer: track length in mm}} of a board's segments and arcs (an arc by its chord)."""
    by_no = {m.group(1): _unescape(m.group(2)) for m in NET_TABLE.finditer(text)}
    out = defaultdict(lambda: defaultdict(float))
    for m in SEG.finditer(text):
        x1, y1, x2, y2, layer, no, name = m.groups()
        net = _unescape(name) if name is not None else by_no.get(no, "")
        if net:
            out[net][layer] += math.hypot(float(x2) - float(x1), float(y2) - float(y1))
    return out


def net_names(text):
    return {_unescape(m.group(1)) for m in NET_REF.finditer(text)} - {""}


def fingerprint(names):
    """As kae.route.layer_assign.fingerprint: 16 hex digits of the SHA-1 of the sorted net names."""
    return hashlib.sha1("\n".join(sorted({n for n in names if n})).encode()).hexdigest()[:16]


def table(text, roles=False, source=""):
    t = tracks(text)
    used = sorted({l for lays in t.values() for l in lays})
    nets = {n: (used if roles else sorted(lays)) for n, lays in sorted(t.items())}
    return dict(version=1, source=source, kind="roles" if roles else "nets", nets=nets)


def reach(routed, reference):
    R, H = tracks(routed), tracks(reference)
    tot = off = 0.0
    nets = nets_off = 0
    for net, lays in R.items():
        if net not in H:
            continue
        nets += 1
        tot += sum(lays.values())
        off += sum(v for l, v in lays.items() if l not in H[net])
        nets_off += any(l not in H[net] for l in lays)

    def shares(d):
        by = defaultdict(float)
        for lays in d.values():
            for l, v in lays.items():
                by[l] += v
        s = sum(by.values()) or 1.0
        return {l: round(v / s, 4) for l, v in sorted(by.items())}
    return dict(nets_compared=nets, length_mm=round(tot, 2), off_length_share=round(off / tot, 4) if tot else None,
                off_net_share=round(nets_off / nets, 4) if nets else None, routed_layer_shares=shares(R),
                reference_layer_shares=shares(H),
                reference_layers_per_net=round(sum(len(v) for v in H.values()) / len(H), 3) if H else None)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("board")
    e.add_argument("-o", "--out", required=True)
    e.add_argument("--roles", action="store_true")
    e.add_argument("--source", default="")
    r = sub.add_parser("reach")
    r.add_argument("routed")
    r.add_argument("reference")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        text = read(a.board)
        doc = table(text, a.roles, a.source or f"extracted from {Path(a.board).name}")
        out = Path(a.out)
        if out.suffix == ".json":
            files = [out]
        else:
            out.mkdir(parents=True, exist_ok=True)
            files = [out / f"{stem(a.board)}.json", out / f"{fingerprint(net_names(text))}.json"]
        for f in files:
            f.write_text(json.dumps(doc, indent=1, sort_keys=True))
        print(f"{len(doc['nets'])} nets with tracks -> {', '.join(str(f) for f in files)}")
        return 0
    res = reach(read(a.routed), read(a.reference))
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"nets compared {res['nets_compared']}, track {res['length_mm']} mm; on layers the reference does not use "
              f"for that net: {res['off_length_share']} of length, {res['off_net_share']} of nets")
        print(f"layer shares routed    {res['routed_layer_shares']}")
        print(f"layer shares reference {res['reference_layer_shares']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
