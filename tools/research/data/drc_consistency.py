#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""drc_consistency.py CORPUS [--workdir W] [-j N] [--suite NAME=FILE ...] [-o OUT.jsonl]

Cheap consistency scan of a board corpus's stored DRC reports (boards/<id>/drc.json)
against the board files they claim to describe. No KiCad: the board is parsed as text.

Flags per board:
  missing_drc            no drc.json
  bad_drc                drc.json unreadable
  drc_older              drc.json mtime earlier than board.kicad_pcb, and the board is not
                         byte-identical to upstream (row pcb_sha256)
  drc_older_same_bytes   as above, but the board is upstream's file unchanged (a re-copy)
  source_mismatch        drc.json "source" does not name board.kicad_pcb
  enrich_copy_differs    the enrich work dir's DRC input (W/drc/<id>/board.kicad_pcb) differs
                         from the corpus board, so the report describes another file
  notes_mismatch         row.json notes' "unconnected=N" differs from drc.json's count
  stats_mismatch         row.json tracks/vias/zones differ from the board text
  zero_unconn_unrouted   0 unconnected items, yet some net on >= 2 footprints has no copper
  unconn_capped          exactly 499 unconnected items: kicad-cli's report may be truncated
  unconn_below_min       fewer unconnected items than the copper-less multi-footprint nets
                         need (sum of footprints-1; pads sharing a spot can lower it)
"""
import argparse
import collections
import filecmp
import hashlib
import json
import multiprocessing
import re
import sys
from pathlib import Path

TOK = re.compile(rb'\((pad|footprint|module|segment|arc|via|zone)[\s)]'
                 rb'|\(net\s+(?:(\d+)\s*(?:"((?:[^"\\]|\\.)*)")?|"((?:[^"\\]|\\.)*)")')
NOTE_UNCONN = re.compile(r"DRC as saved[^:]*: unconnected=(\d+)")


def parse_board(text):
    """Footprints with pads on each net, and copper items on each net, from the board text.

    Nets are keyed by name (or number). Pads are counted per footprint, not one by one:
    pads of one footprint on one net (mounting-hole rings, castellated + SMD pins) usually
    overlap or join inside the footprint, which a text scan cannot see. An arc counts as
    copper only when a (net ...) follows it: zone and footprint outlines hold (arc ...) too.
    """
    names = {}  # number -> name, from the board's net table (pre-KiCad-10 files)
    pads = collections.defaultdict(set)  # net -> footprint indices
    fp = 0
    copper = collections.Counter()
    counts = collections.Counter()
    owner = None  # the item a following (net ...) belongs to
    for m in TOK.finditer(text):
        kind, num, nname, sname = m.groups()
        if kind:
            if kind in (b"footprint", b"module"):
                fp += 1
            elif kind != b"arc":
                counts[kind] += 1
            owner = kind
            continue
        if owner is None:  # top-level net table
            if num is not None and nname is not None:
                names[num] = nname
            continue
        key = sname if sname is not None else nname if nname is not None else names.get(num, num)
        if key not in (b"", b"0"):
            if owner == b"pad":
                pads[key].add(fp)
            elif owner in (b"segment", b"arc", b"via", b"zone"):
                copper[key] += 1
        if owner == b"arc":
            counts[b"arc"] += 1
        if owner in (b"pad", b"arc"):
            owner = None  # one net each; later (net ...) tokens are not theirs
    return {n: len(f) for n, f in pads.items()}, copper, counts


def scan(args):
    d, workdir = args
    bid = d.name
    out = {"id": bid, "flags": []}
    pcb = d / "board.kicad_pcb"
    if not pcb.exists():
        out["flags"].append("missing_board")
        return out
    text = pcb.read_bytes()
    pads, copper, counts = parse_board(text)
    multi = {n: k for n, k in pads.items() if k >= 2}
    bare = {n: k for n, k in multi.items() if not copper.get(n)}
    out.update(multi_fp_nets=len(multi), bare_nets=len(bare), min_unconn=sum(k - 1 for k in bare.values()),
               segments=counts[b"segment"], arcs=counts[b"arc"], vias=counts[b"via"], zones=counts[b"zone"])
    row = {}
    if (d / "row.json").exists():
        row = json.loads((d / "row.json").read_text())
        st = (out["segments"] + out["arcs"], out["vias"])
        if (row.get("tracks"), row.get("vias")) != st:
            out["flags"].append("stats_mismatch")
            out["row_stats"] = [row.get("tracks"), row.get("vias"), row.get("zones")]
    rep = d / "drc.json"
    if not rep.exists():
        out["flags"].append("missing_drc")
        return out
    try:
        r = json.loads(rep.read_text())
    except ValueError:
        out["flags"].append("bad_drc")
        return out
    n = len(r.get("unconnected_items", []))
    out.update(unconnected=n, drc_date=r.get("date"), kicad_version=r.get("kicad_version"))
    if rep.stat().st_mtime < pcb.stat().st_mtime:
        same = hashlib.sha256(text).hexdigest() == row.get("pcb_sha256")
        out["flags"].append("drc_older_same_bytes" if same else "drc_older")
    if Path(str(r.get("source", ""))).name != "board.kicad_pcb":
        out["flags"].append("source_mismatch")
    if workdir:
        src = Path(workdir) / "drc" / bid / "board.kicad_pcb"
        if src.exists() and not filecmp.cmp(src, pcb, shallow=False):
            out["flags"].append("enrich_copy_differs")
    m = NOTE_UNCONN.search(row.get("notes", ""))
    if m and int(m.group(1)) != n:
        out["flags"].append("notes_mismatch")
        out["notes_unconn"] = int(m.group(1))
    if n == 499:
        out["flags"].append("unconn_capped")
    elif n == 0 and bare:
        out["flags"].append("zero_unconn_unrouted")
    elif n < out["min_unconn"]:
        out["flags"].append("unconn_below_min")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--workdir", type=Path, help="enrich work dir holding drc/<id>/board.kicad_pcb")
    ap.add_argument("-j", type=int, default=16)
    ap.add_argument("--suite", action="append", default=[], metavar="NAME=FILE",
                    help="id list (one per line, # comments; or a dir of <id>.* files) to count flags in")
    ap.add_argument("-o", type=Path, help="write one JSON row per board")
    a = ap.parse_args()
    dirs = sorted(p for p in (a.corpus / "boards").iterdir() if p.is_dir())
    with multiprocessing.Pool(min(a.j, 16)) as pool:
        res = pool.map(scan, [(d, a.workdir) for d in dirs], chunksize=8)
    if a.o:
        with open(a.o, "w") as f:
            for r in res:
                f.write(json.dumps(r) + "\n")
    tally = collections.Counter(fl for r in res for fl in r["flags"])
    print(f"boards {len(res)}, flagged {sum(bool(r['flags']) for r in res)}")
    for k, v in tally.most_common():
        print(f"  {k:22} {v}")
    by_id = {r["id"]: r for r in res}
    for spec in a.suite:
        name, path = spec.split("=", 1)
        p = Path(path)
        ids = ({q.name.split(".")[0] for q in p.iterdir()} if p.is_dir() else
               {ln.split()[0] for ln in p.read_text().splitlines() if ln.strip() and not ln.startswith("#")})
        hit = [i for i in sorted(ids) if by_id.get(i, {}).get("flags")]
        t = collections.Counter(fl for i in hit for fl in by_id[i]["flags"])
        print(f"suite {name}: {len(ids)} ids, {sum(i in by_id for i in ids)} in corpus, {len(hit)} flagged "
              + " ".join(f"{k}:{v}" for k, v in t.most_common()))


if __name__ == "__main__":
    sys.exit(main())
