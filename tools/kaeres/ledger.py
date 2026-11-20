#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-connection outcome ledger over the kaeres results store (report only).

One JSONL row per open connection of every run of an experiment, and one row per run, built
from what the store already holds: the DRC item list of the stored evaluation
(`evals/<evaluator>.drc.json.gz`) and the router's own diagnosis of the kept board
(`blocked` in `restart-report.json`, `final.blocked` in `restart-report-windows.json`, from
`kae.route.blocked`). Nothing is written into the store; scoring is not touched.

    ledger.py build  --experiment NAME [--methods ID,...] [--tags DIR] [--out DIR]
    ledger.py report DIR [--pair A,B]          writes DIR/LEDGER.md
    ledger.py reach  DIR --a A --b B           boards and connections whose outcome differs

The store is `$KAE_RESULTS`, else `~/kae-baselines`. Methods are given by id, id prefix or name.
"""
import argparse
import collections
import csv
import gzip
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# Disjoint cause classes, in report order. The first five are kae.route.blocked's causes.
CLASSES = ("inherited", "geometry", "rule", "kae_default", "fixed_copper", "pour_island", "congestion",
           "undiagnosed_cap", "no_diagnosis_stored")
CLASS_TEXT = {
    "inherited": "inherited (an end pad is open in the task's human board)",
    "geometry": "walled in (no path at zero clearance)",
    "rule": "rule-blocked (board rule)",
    "kae_default": "rule-blocked (kae default)",
    "fixed_copper": "input pre-routes in the way",
    "pour_island": "own copper: pour island",
    "congestion": "own copper (a path exists without our other copper)",
    "undiagnosed_cap": "not diagnosed (connection cap or deadline)",
    "no_diagnosis_stored": "no diagnosis stored for the kept board",
}
UNCLASSIFIED = ("undiagnosed_cap", "no_diagnosis_stored")
RAW_CAUSE = {"congestion": "congestion", "fixed copper": "fixed_copper", "rule": "rule",
             "kae default": "kae_default", "geometry": "geometry"}
BIG_BOARD = 1000        # pads; boards above it are reported apart
NEAR_MISS = (1, 5)      # opens on a near-miss run

GND = re.compile(r"(GND|VSS|EARTH|GROUND|^0V$|AGND|DGND|PGND)", re.I)
PWR = re.compile(r"(^\+|VCC|VDD|VBUS|VBAT|VIN\b|VOUT|PWR|POWER|\b\d+V\d*\b|^/?\d+V|3V3|5V0|1V8|1V2|VREF|VSYS|VPP|"
                 r"AVCC|VAA|VEE|^V[+-])", re.I)


def store_root():
    return Path(os.environ.get("KAE_RESULTS") or Path.home() / "kae-baselines")


# ---------------------------------------------------------------- parsing helpers

def net_role(net, zone_nets):
    """ground / power / signal by name; a non-ground net with a zone counts as power."""
    base = (net or "").rsplit("/", 1)[-1]
    if GND.search(base):
        return "ground"
    if PWR.search(base) or net in zone_nets:
        return "power"
    return "signal"


def parse_item(item):
    """One DRC end item -> kind (pad/track/via/zone/other), net, ref, pad, position."""
    d = item.get("description", "")
    head = d.split("[")[0].lower()
    if "pad" in head:
        kind = "pad"
    elif head.startswith(("track", "arc")):
        kind = "track"
    elif head.startswith("via"):
        kind = "via"
    elif "zone" in head:
        kind = "zone"
    else:
        kind = "other"
    m = re.search(r"\[(.*?)\]", d)
    ref = pad = None
    if kind == "pad":
        m2 = re.search(r"[Pp]ad (\S+) \[.*?\] of (\S+)", d)
        if m2:
            pad, ref = m2.group(1), m2.group(2)
    pos = item.get("pos")
    return dict(kind=kind, net=m.group(1) if m else "", ref=ref, pad=pad,
                pos=[pos.get("x"), pos.get("y")] if isinstance(pos, dict) else pos)


def norm_net(n):
    return (n or "").replace("{slash}", "/").strip()


def size_class(n):
    if n is None:
        return None
    return ">=16" if n >= 16 else "3-15" if n >= 3 else "2" if n == 2 else "1"


def board_class(pads):
    if pads is None:
        return None
    return "<=200" if pads <= 200 else "201-1000" if pads <= BIG_BOARD else ">1000"


def board_parts(path):
    """({ref: pad count}, nets with a zone) from a (gzipped) .kicad_pcb; empty when absent."""
    try:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", errors="replace") as f:
            t = f.read()
    except OSError:
        return {}, set()
    parts = {}
    for ch in re.split(r"\n\s*\(footprint ", t)[1:]:
        m = re.search(r'\(property "Reference" "([^"]*)"', ch) or re.search(r'\(fp_text reference "?([^"\s)]*)', ch)
        if not m:
            continue
        cut = re.search(r"\n\t\((segment|via|zone|gr_|arc|group|generated|embedded)", ch)
        body = ch[:cut.start()] if cut else ch
        parts[m.group(1)] = max(parts.get(m.group(1), 0), len(re.findall(r"\(pad ", body)))
    zone_nets = set()
    for ch in re.split(r"\n\s*\(zone", t)[1:]:
        m = re.search(r'\(net_name "([^"]*)"\)', ch[:3000]) or re.search(r'\(net "([^"]+)"\)', ch[:3000])
        if m and m.group(1):
            zone_nets.add(m.group(1))
    return parts, zone_nets


def read_json(p):
    try:
        if str(p).endswith(".gz"):
            with gzip.open(p, "rt") as f:
                return json.load(f)
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _dig(o, keys):
    for k in keys:
        o = o.get(k) if isinstance(o, dict) else None
    return o


def find_blocked(run_dir):
    """(blocked dict or None, where it was read) from the kept attempt's report."""
    for name, paths in (("restart-report.json", (("blocked",), ("final", "blocked"))),
                        ("restart-report-windows.json", (("final", "blocked"), ("blocked",)))):
        o = read_json(Path(run_dir) / name)
        if o is None:
            continue
        for ks in paths:
            v = _dig(o, ks)
            if isinstance(v, dict) and ("blocked" in v or "congestion" in v):
                return v, f"{name}:{'.'.join(ks)}"
        return None, f"{name}:none(mode={o.get('mode')})"
    return None, "no report"


def origin_blocked(run_dir):
    o = read_json(Path(run_dir) / "restart-report-origin.json")
    for ks in (("blocked",), ("final", "blocked")):
        v = _dig(o, ks)
        if isinstance(v, dict) and ("blocked" in v or "congestion" in v):
            return v
    return None


def cause_detail(rec):
    cz = rec.get("cause")
    if cz in ("rule", "kae default"):
        b = rec.get("binding") or {}
        return dict(constraint=b.get("constraint"), against=b.get("against"), where=b.get("where"))
    if cz == "fixed copper":
        return dict(fixed_nets=(rec.get("fixed_nets") or [])[:8])
    if cz == "geometry":
        return dict(walled_by=(rec.get("walled_by") or [])[:4])
    return {}


def human_opens(task_dir):
    """({net: opens}, {net: end pads}) of the task's human DRC, or (None, None)."""
    o = read_json(Path(task_dir) / "human-drc.json.gz")
    if o is None:
        return None, None
    nets, pads = collections.Counter(), collections.defaultdict(set)
    for u in o.get("unconnected_items", []):
        ends = [parse_item(i) for i in u.get("items", [])]
        if not ends:
            continue
        net = norm_net(ends[0]["net"])
        nets[net] += 1
        pads[net].update(f"{e['ref']}.{e['pad']}" for e in ends if e["ref"])
    return nets, pads


def load_buses(tags_dir):
    """{board: {net: (bus kind, swap class)}} from a board-tags `bus/buses.jsonl`."""
    out = collections.defaultdict(dict)
    if not tags_dir:
        return out
    p = Path(tags_dir) / "bus" / "buses.jsonl"
    with open(p) as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            swap = "/".join(s for s in (o.get("swap_a"), o.get("swap_b")) if s) or None
            for grp in o.get("nets") or []:
                for n in grp:
                    out[o.get("board")][norm_net(n)] = (o.get("kind"), swap)
    return out


# ---------------------------------------------------------------- build

def experiment_runs(root, experiment, methods=None, evaluator=None):
    exp = read_json(root / "experiments" / experiment / "experiment.json")
    if exp is None:
        sys.exit(f"no experiment {experiment!r} in the store")
    ev = evaluator or (exp.get("evaluators") or {}).get("drc")
    db = sqlite3.connect(f"file:{root / 'index.sqlite'}?mode=ro", uri=True)
    names = dict(db.execute("select id, name from methods").fetchall())
    exp_ids = [m["id"] for m in exp.get("methods", [])]
    if methods:
        want = []
        for m in methods:
            hit = [i for i in exp_ids if i.startswith(m) or names.get(i) == m]
            if len(hit) != 1:
                sys.exit(f"method {m!r} matches {len(hit)} methods of {experiment}")
            want.append(hit[0])
        exp_ids = want
    q = ("select r.board, r.run, r.method_id, r.attempt, r.task_id, r.status, e.unconnected "
         "from runs r left join evals e on e.board = r.board and e.run = r.run and e.evaluator = ? "
         f"where r.experiment = ? and r.method_id in ({','.join('?' * len(exp_ids))}) order by r.board, r.method_id")
    rows = db.execute(q, (ev, experiment, *exp_ids)).fetchall()
    meta = {}
    res = root / "experiments" / experiment / "results.csv"
    if res.exists():
        with open(res) as f:
            for r in csv.DictReader(f):
                try:
                    meta.setdefault(r["board"], (int(float(r["pads"])), int(float(r["layers"]))))
                except (KeyError, ValueError):
                    pass
    for b, layers in db.execute("select id, layers from boards"):
        meta.setdefault(b, (None, layers))
    return ev, names, rows, meta


def _match(cands, endp):
    pick = next((r for r in cands if endp & set(r.get("pads") or [])), None)
    if pick is None and cands:
        pick = cands[0]
    if pick is not None:
        cands.remove(pick)
    return pick


def classify(row):
    """The disjoint cause class of one ledger row (also returned as `cause_class`)."""
    if row["inherited"] == "pad":
        return "inherited"
    cz = row.get("cause")
    if cz is None:
        return "undiagnosed_cap" if row["status"] == "undiagnosed" else "no_diagnosis_stored"
    cls = RAW_CAUSE.get(cz, cz)
    if cls == "congestion" and row.get("zone_involved"):
        return "pour_island"
    return cls


def congestion_shape(row):
    kinds, pads = row.get("island_kinds"), row.get("island_pads") or []
    if kinds is None:
        return "island not stored"
    if kinds == ["pad"] and len(pads) == 1:
        n = row.get("island_part_pads")
        return "bare pin of a part with >=16 pads" if n and n >= 16 else "bare pad of a smaller part"
    return "partly routed island"


def build_run(root, ev, board, run, mid, mname, attempt, task, status, unc, meta, buses, drc_cache=None):
    run_dir = root / "boards" / board / "runs" / run
    pads_b, layers = meta.get(board, (None, None))
    info = dict(board=board, method_id=mid, method=mname, run=run, attempt=attempt, task=task, status=status,
                opens=unc, evaluated=unc is not None, board_pads=pads_b, board_layers=layers,
                board_size=board_class(pads_b), drc_list=False, drc_items=None, blocked_source=None,
                has_blocked=False, records=0, undiagnosed=0, origin_blocked=False, human_opens=None,
                diagnosed=0, capped=0, not_attempted=0)
    if not unc:
        return info, []
    d = read_json(run_dir / "evals" / f"{ev}.drc.json.gz")
    drc_src = "drc"
    if d is None and drc_cache is not None:      # a DRC re-run by `fill-drc` (not a stored score)
        d = read_json(Path(drc_cache) / board / f"{run}.drc.json.gz")
        drc_src = "drc-cache"
    items = None if d is None else d.get("unconnected_items", [])
    B, where = find_blocked(run_dir)
    parts, zone_nets = board_parts(run_dir / "output.kicad_pcb.gz")
    hnets, hpads = human_opens(root / "boards" / board / "tasks" / str(task))
    recs = [] if B is None else list(B.get("blocked", [])) + list(B.get("congestion", []))
    Bo = origin_blocked(run_dir) if B is None else None
    info.update(drc_list=items is not None, drc_list_source=drc_src if items is not None else None, drc_items=None if items is None else len(items), blocked_source=where,
                has_blocked=B is not None, records=len(recs), undiagnosed=(B or {}).get("undiagnosed", 0),
                origin_blocked=Bo is not None, human_opens=None if hnets is None else sum(hnets.values()))
    by_net = collections.defaultdict(list)
    for r in recs:
        by_net[norm_net(r.get("net"))].append(r)
    by_net_o = collections.defaultdict(list)
    for r in ([] if Bo is None else list(Bo.get("blocked", [])) + list(Bo.get("congestion", []))):
        by_net_o[norm_net(r.get("net"))].append(r)
    undiag_left = info["undiagnosed"]
    bus = buses.get(board, {})

    def row(net, ends, source):
        net = norm_net(net)
        bk = bus.get(net)
        r = dict(board=board, method_id=mid, method=mname, run=run, attempt=attempt, net=net or None,
                 a=ends[0] if ends else None, b=ends[1] if len(ends) > 1 else None, source=source,
                 cause=None, cause_detail={}, cause_origin=None,
                 role=net_role(net, zone_nets) if net else None, zone_net=net in zone_nets,
                 bus=bk[0] if bk else None, swap_class=bk[1] if bk else None,
                 board_pads=pads_b, board_layers=layers, board_size=info["board_size"], run_opens=unc,
                 island_pads=None, island_kinds=None, island_part_pads=None)
        for k, e in (("a", r["a"]), ("b", r["b"])):
            n = parts.get(e["ref"]) if e and e.get("ref") else None
            r[f"{k}_part_pads"], r[f"{k}_size"] = n, size_class(n)
        return r

    def take(r, rec, field="cause"):
        if field == "cause":
            r["cause"], r["cause_detail"] = rec.get("cause"), cause_detail(rec)
        else:
            r["cause_origin"] = rec.get("cause")
        ip = rec.get("pads") or []
        r["island_pads"], r["island_kinds"] = ip, rec.get("kinds")
        sizes = [parts.get(p.split(".")[0]) for p in ip]
        r["island_part_pads"] = max([s for s in sizes if s], default=None)

    def finish(r, endp):
        zone_end = any(e and e["kind"] == "zone" for e in (r["a"], r["b"]))
        r["zone_involved"] = zone_end or any(k in ("fill", "zone") for k in (r["island_kinds"] or []))
        if hnets is None or not r["net"]:
            r["inherited"] = None
        elif endp & hpads.get(r["net"], set()):
            r["inherited"] = "pad"
        else:
            r["inherited"] = "net" if hnets.get(r["net"], 0) else False
        r["cause_class"] = classify(r)
        if r["cause_class"] == "congestion":
            r["cause_detail"] = dict(shape=congestion_shape(r))
        info[{"diagnosed": "diagnosed", "undiagnosed": "capped", "not_attempted": "not_attempted"}[r["status"]]] += 1
        return r

    out = []
    if items is not None:
        for u in items:
            ends = [parse_item(i) for i in u.get("items", [])][:2]
            net = ends[0]["net"] if ends else ""
            r = row(net, [dict(ref=e["ref"], pad=e["pad"], kind=e["kind"], pos=e["pos"]) for e in ends], drc_src)
            endp = {f"{e['ref']}.{e['pad']}" for e in ends if e["ref"]}
            pick = _match(by_net.get(norm_net(net), []), endp)
            if pick is not None:
                take(r, pick)
                r["status"] = "diagnosed"
            elif B is not None:
                r["status"] = "undiagnosed"
                undiag_left -= 1
            else:
                r["status"] = "not_attempted"
                po = _match(by_net_o.get(norm_net(net), []), endp)
                if po is not None:
                    take(r, po, "origin")
            out.append(finish(r, endp))
        info["records_unmatched"] = sum(len(v) for v in by_net.values())
        for _ in range(max(unc - len(items), 0)):     # the DRC list is cut (499 items): count the rest
            r = row(None, [], "count")
            r["status"] = "undiagnosed" if B is not None else "not_attempted"
            r["cause_detail"] = dict(note="DRC item list cut")
            out.append(finish(r, set()))
    else:
        for rec in recs:
            r = row(rec.get("net"), [], "blocked")
            take(r, rec)
            r["status"] = "diagnosed"
            out.append(finish(r, set(rec.get("pads") or [])))
        for _ in range(max(unc - len(recs), 0)):
            r = row(None, [], "count")
            r["status"] = "undiagnosed" if B is not None else "not_attempted"
            out.append(finish(r, set()))
    return info, out


def cmd_build(a):
    root = store_root()
    methods = [m for m in (a.methods or "").split(",") if m]
    ev, names, rows, meta = experiment_runs(root, a.experiment, methods, a.evaluator)
    buses = load_buses(a.tags)
    out = Path(a.out or f"ledger-{a.experiment}")
    out.mkdir(parents=True, exist_ok=True)
    n_rows = 0
    cache = Path(a.drc_cache) if a.drc_cache else out / "drc-cache"
    cache = cache if cache.is_dir() else None
    with open(out / "ledger.jsonl", "w") as fl, open(out / "runs.jsonl", "w") as fr:
        for board, run, mid, attempt, task, status, unc in rows:
            info, recs = build_run(root, ev, board, run, mid, names.get(mid, mid), attempt, task, status, unc, meta, buses, cache)
            fr.write(json.dumps(info) + "\n")
            for r in recs:
                fl.write(json.dumps(r) + "\n")
            n_rows += len(recs)
    (out / "ledger.json").write_text(json.dumps(dict(
        experiment=a.experiment, evaluator=ev, methods={m: names.get(m, m) for m in sorted({r[2] for r in rows})},
        tags=bool(a.tags), drc_cache=cache is not None, runs=len(rows), rows=n_rows), indent=1) + "\n")
    print(f"{out}: {len(rows)} runs, {n_rows} open connections")


# ---------------------------------------------------------------- report

def load(d):
    d = Path(d)
    with open(d / "ledger.jsonl") as f:
        rows = [json.loads(x) for x in f]
    with open(d / "runs.jsonl") as f:
        runs = [json.loads(x) for x in f]
    head = read_json(d / "ledger.json") or {}
    return head, runs, rows


def pct(n, d):
    return f"{n} ({100 * n / d:.0f}%)" if d else f"{n} (-)"


def table(head, body):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in body]
    return out + [""]


def label(head, mid):
    return f"{(head.get('methods') or {}).get(mid, mid)} ({mid[:8]})"


def resolve(head, runs, m):
    ids = sorted({r["method_id"] for r in runs})
    hit = [i for i in ids if i.startswith(m) or (head.get("methods") or {}).get(i) == m]
    if len(hit) != 1:
        sys.exit(f"method {m!r} matches {len(hit)} methods in this ledger")
    return hit[0]


SUBSETS = (("all", lambda r: True),
           (f"<={BIG_BOARD} pads", lambda r: r.get("board_pads") is not None and r["board_pads"] <= BIG_BOARD),
           (f"near-miss ({NEAR_MISS[0]}-{NEAR_MISS[1]} opens)", lambda r: NEAR_MISS[0] <= (r.get("run_opens") or 0) <= NEAR_MISS[1]))


def conn_key(r):
    ends = {f"{e['ref']}.{e['pad']}" for e in (r.get("a"), r.get("b")) if e and e.get("ref")}
    return ends | set(r.get("island_pads") or [])


def persistence(rows, runs, ma, mb):
    """Lines: open connections of A also open under B and the reverse, on boards both list completely."""
    def complete(run):      # every open is a row that names its net
        return run["evaluated"] and (not run["opens"] or (run["drc_items"] or 0) >= run["opens"]
                                     or run["records"] >= run["opens"])
    ok = {}
    for run in runs:
        ok.setdefault(run["board"], {})[run["method_id"]] = complete(run)
    boards = {b for b, v in ok.items() if v.get(ma) and v.get(mb)}
    by = collections.defaultdict(list)
    for r in rows:
        if r["board"] in boards and r["method_id"] in (ma, mb) and r["net"]:
            by[(r["method_id"], r["board"], r["net"])].append(conn_key(r))
    lines = []
    for x, y in ((ma, mb), (mb, ma)):
        n = conn = net = n_both = 0
        only_boards = set()
        open_y = {b2 for (m2, b2, _) in by if m2 == y}
        for (m, b, nt), keys in by.items():
            if m != x:
                continue
            other = by.get((y, b, nt), [])
            for k in keys:
                n += 1
                n_both += b in open_y
                if other:
                    net += 1
                    if any((k & o) or (not k and not o) for o in other):
                        conn += 1
            if b not in open_y:
                only_boards.add(b)
        lines.append(f"- {x[:8]} opens on the {len(boards)} boards both list completely: {n}, of which {n_both} on boards "
                     f"open under both; connection also open under {y[:8]} {pct(conn, n_both)} of those; net also open "
                     f"{pct(net, n_both)}; boards open only under {x[:8]}: {len(only_boards)} "
                     f"({n - n_both} opens).")
    return lines


def concentration(rows, key):
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[key(r)][r["board"]] += 1
    out = []
    for k, c in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        tot, acc, b50 = sum(c.values()), 0, None
        b80 = None
        for i, (_, n) in enumerate(c.most_common(), 1):
            acc += n
            if b50 is None and acc >= 0.5 * tot:
                b50 = i
            if b80 is None and acc >= 0.8 * tot:
                b80 = i
        out.append((k, tot, len(c), b50, b80, c.most_common(1)[0][1]))
    return out


def cmd_report(a):
    head, runs, rows = load(a.dir)
    mids = sorted({r["method_id"] for r in runs}, key=lambda m: label(head, m))
    L = [f"# Connection ledger: {head.get('experiment', '?')}", "",
         f"Report only, built by `tools/kaeres/ledger.py` from the stored DRC item lists (evaluator "
         f"{head.get('evaluator')}) and the routers' `blocked` diagnosis (`kae.route.blocked`). "
         f"{len(runs)} runs, {len(rows)} open connections. Cause classes are disjoint: an end pad open in the human "
         "board wins, then the diagnosed cause; own copper whose island holds a pour is `pour_island`.", ""]

    L += ["## Coverage", ""]
    body = []
    for m in mids:
        rs = [x for x in runs if x["method_id"] == m]
        wo = [x for x in rs if x["opens"]]
        rr = [x for x in rows if x["method_id"] == m]
        st = collections.Counter(x["status"] for x in rr)
        body.append([label(head, m), len(rs), sum(x["evaluated"] for x in rs), len(wo), sum(x["opens"] for x in wo),
                     sum(x["drc_list"] for x in wo), sum(1 for x in wo if x["drc_list"] and x["drc_items"] < x["opens"]),
                     sum(x["has_blocked"] for x in wo),
                     pct(st["diagnosed"], len(rr)), pct(st["undiagnosed"], len(rr)), pct(st["not_attempted"], len(rr))])
    L += table(["method", "runs", "evaluated", "runs with opens", "opens", "with DRC item list", "list cut", "with `blocked`",
                "opens diagnosed", "capped (cap or deadline)", "no diagnosis"], body)
    wh = collections.Counter((label(head, x["method_id"]), x["blocked_source"]) for x in runs if x["opens"])
    L += ["Where the diagnosis was read (runs with opens): " +
          "; ".join(f"{m} `{w}` {n}" for (m, w), n in sorted(wh.items())), ""]

    L += ["## Taxonomy (disjoint classes, share of opens)", ""]
    for m in mids:
        rr = [x for x in rows if x["method_id"] == m]
        if not rr:
            continue
        subs = [(n, [x for x in rr if f(x)]) for n, f in SUBSETS]
        L += [f"**{label(head, m)}**", ""]
        body = [[CLASS_TEXT[c]] + [pct(sum(1 for x in s if x["cause_class"] == c), len(s)) for _, s in subs]
                for c in CLASSES]
        diag = [[sum(1 for x in s if x["status"] == "diagnosed") for _, s in subs]]
        body.append(["**opens / diagnosed / boards**"] +
                     [f"{len(s)} / {d} / {len({x['board'] for x in s})}" for (_, s), d in zip(subs, diag[0])])
        L += table(["class"] + [n for n, _ in subs], body)
        dg = [x for x in rr if x["status"] == "diagnosed"]
        if dg:
            cz = collections.Counter(RAW_CAUSE.get(x["cause"], x["cause"]) for x in dg)
            L += ["Of diagnosed opens (`kae.route.blocked` cause, before the inherited rule): " +
                  "; ".join(f"{c} {pct(n, len(dg))}" for c, n in cz.most_common()), ""]

    L += ["## Cause x net role and cause x end size (diagnosed opens)", ""]
    for m in mids:
        dg = [x for x in rows if x["method_id"] == m and x["status"] == "diagnosed"]
        if not dg:
            continue
        L += [f"**{label(head, m)}** (n={len(dg)})", ""]
        cls = [c for c in CLASSES if any(x["cause_class"] == c for x in dg)]
        body = []
        for c in cls + ["(all)"]:
            s = [x for x in dg if c == "(all)" or x["cause_class"] == c]
            body.append([c, *(pct(sum(1 for x in s if x["role"] == r), len(s)) for r in ("signal", "power", "ground")),
                         pct(sum(1 for x in s if x.get("bus")), len(s)),
                         *(pct(sum(1 for x in s if size_class(x.get("island_part_pads")) == k), len(s))
                           for k in (">=16", "3-15", "2")),
                         pct(sum(1 for x in s if x["zone_involved"]), len(s))])
        L += table(["class", "signal", "power", "ground", "in a tagged bus", "island part >=16 pads", "3-15", "2-pad",
                    "zone involved"], body)
        cg = collections.Counter(x["cause_detail"].get("shape") for x in dg if x["cause_class"] == "congestion")
        if cg:
            L += ["Own-copper shape: " + "; ".join(f"{k} {pct(n, sum(cg.values()))}" for k, n in cg.most_common()), ""]

    drc = [x for x in rows if x["source"] in ("drc", "drc-cache")]
    if drc:
        L += ["## End sizes of pad-to-pad opens (DRC item lists)", ""]
        body = []
        for m in mids:
            pp = [x for x in drc if x["method_id"] == m and (x["a"] or {}).get("kind") == "pad"
                  and (x["b"] or {}).get("kind") == "pad"]
            if not pp:
                continue
            big = [sum(1 for k in ("a_size", "b_size") if x[k] == ">=16") for x in pp]
            body.append([label(head, m), len(pp), pct(big.count(2), len(pp)), pct(big.count(1), len(pp)),
                         pct(big.count(0), len(pp)), pct(sum(1 for x in pp if "2" in (x["a_size"], x["b_size"])), len(pp))])
        L += table(["method", "pad-to-pad opens", "both >=16", "one >=16", "neither", "a 2-pad part at an end"], body)

    if a.pair:
        ma, mb = (resolve(head, runs, m) for m in a.pair.split(","))
        L += [f"## Persistence: {label(head, ma)} vs {label(head, mb)}", ""]
        L += persistence(rows, runs, ma, mb) + ["", "A connection matches when the other method has an open on the same "
                                                "net sharing an end or island pad (net-only rows match any open on the net).", ""]

    L += ["## Concentration (boards holding 50 % and 80 % of each class)", ""]
    body = []
    for m in mids:
        rr = [x for x in rows if x["method_id"] == m]
        for k, tot, nb, b50, b80, top in concentration(rr, lambda x: x["cause_class"]):
            body.append([label(head, m), k, tot, nb, b50, b80, top])
    L += table(["method", "class", "opens", "boards", "boards for 50 %", "boards for 80 %", "largest board"], body)

    L += ["## Unclassified share (kill line: over 30 %)", ""]
    body = []
    for m in mids:
        rr = [x for x in rows if x["method_id"] == m]
        for n, f in SUBSETS:
            s = [x for x in rr if f(x)]
            u = sum(1 for x in s if x["cause_class"] in UNCLASSIFIED)
            body.append([label(head, m), n, len(s), pct(u, len(s)),
                         "over" if s and u > 0.3 * len(s) else "within" if s else "-"])
    L += table(["method", "subset", "opens", "unclassified", "30 % line"], body)
    out = Path(a.dir) / "LEDGER.md"
    out.write_text("\n".join(L))
    print(out)


# ---------------------------------------------------------------- reach

def same_conn(r, o):
    """Same net, and a shared end or island pad (or neither row names a pad)."""
    kr, ko = conn_key(r), conn_key(o)
    return o["net"] == r["net"] and bool((kr & ko) or not (kr or ko))


def only_under(x, y):
    """Rows of x that name a net and have no matching open in y."""
    return sum(1 for r in x if r["net"] and not any(same_conn(r, o) for o in y))


def cmd_reach(a):
    head, runs, rows = load(a.dir)
    ma, mb = resolve(head, runs, a.a), resolve(head, runs, a.b)
    opens = {(r["board"], r["method_id"]): r for r in runs if r["method_id"] in (ma, mb)}
    conns = collections.defaultdict(list)
    for r in rows:
        if r["method_id"] in (ma, mb):
            conns[(r["board"], r["method_id"])].append(r)
    body, tally = [], collections.Counter()
    for b in sorted({k[0] for k in opens}):
        ra, rb = opens.get((b, ma)), opens.get((b, mb))
        if not ra or not rb or not ra["evaluated"] or not rb["evaluated"]:
            tally["not both evaluated"] += 1
            continue
        ca, cb = conns[(b, ma)], conns[(b, mb)]
        oa, ob = only_under(ca, cb), only_under(cb, ca)
        if ra["opens"] == rb["opens"] == 0:
            tally["both complete"] += 1
            continue
        if (ra["opens"] == 0) != (rb["opens"] == 0):
            tally[f"complete only under {(ma if not ra['opens'] else mb)[:8]}"] += 1
        elif oa or ob or ra["opens"] != rb["opens"]:
            tally["both open, different connections"] += 1
        else:
            tally["both open, same connections"] += 1
            continue
        body.append([b, ra["opens"], rb["opens"], oa, ob, ra["board_pads"]])
    L = [f"# Reach: {label(head, ma)} vs {label(head, mb)}", "",
         "; ".join(f"{k} {n}" for k, n in sorted(tally.items())), "",
         "Connection counts use only rows that name a net; runs without a DRC item list or `blocked` record "
         "name none, so their only-under counts are lower bounds.", ""]
    L += table(["board", f"opens {ma[:8]}", f"opens {mb[:8]}", f"only under {ma[:8]}", f"only under {mb[:8]}", "pads"], body)
    print("\n".join(L))


# ---------------------------------------------------------------- fill-drc

def cmd_fill_drc(a):
    """Write (and with --submit, queue) kaeq jobs that re-run the DRC of runs with opens and no stored item list."""
    root = store_root()
    methods = [m for m in (a.methods or "").split(",") if m]
    ev, names, rows, meta = experiment_runs(root, a.experiment, methods, a.evaluator)
    out = Path(a.out or f"ledger-{a.experiment}").resolve()
    cache = out / "drc-cache"
    corpus = Path(a.corpus or os.environ.get("KAE_CORPUS") or Path.home() / "kae-boards")
    only = set(a.only.split(",")) if a.only else None
    venv = os.environ.get("VIRTUAL_ENV")
    if not venv:
        sys.exit("activate the bench venv first (its activate script sets the KiCad wrapper)")
    jobs = []
    for board, run, mid, attempt, task, status, unc in rows:
        rd = root / "boards" / board / "runs" / run
        if not unc or (only is not None and board not in only) or not (rd / "output.kicad_pcb.gz").exists():
            continue
        if (rd / "evals" / f"{ev}.drc.json.gz").exists() and not a.include_stored:
            continue
        if (cache / board / f"{run}.drc.json.gz").exists():
            continue
        pads = meta.get(board, (None, None))[0] or 0
        cmd = (f"bash -c 'source {venv}/bin/activate && python3 tools/kaeres/ledger.py fill-drc-job "
               f"--run-dir {rd} --project-dir {corpus / 'boards' / board} --cache {cache / board}'")
        jobs.append(dict(cmd=cmd, name=f"ledger-drc:{board}:{run}", cpus=1, mem=f"{2 + pads / 1000:.1f}G",
                         timeout=f"{int(900 + 2 * pads)}s", prio=a.prio))
        if a.limit and len(jobs) >= a.limit:
            break
    out.mkdir(parents=True, exist_ok=True)
    f = out / "fill-drc-jobs.jsonl"
    f.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    repo = Path(__file__).resolve().parents[2]
    sub = ["kaeq", "submit", "--jobs", str(f), "--owner", f"ledger-drc-{a.experiment}", "--class", "batch",
           "--cwd", str(repo)]
    print(f"{len(jobs)} DRC jobs -> {f}; cache {cache} (never the store)\n" + " ".join(sub))
    if jobs and a.submit:
        import subprocess
        subprocess.run(sub, check=True)


def cmd_fill_drc_job(a):
    """One run: the output board beside the corpus board's project files, kicad-cli DRC, gzipped into the cache."""
    import resource
    import shutil
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "src"))
    from kaebench import tools
    lim = 40 * (1 << 30)        # a runaway KiCad DRC once took 100 GB
    resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    rd, cache = Path(a.run_dir), Path(a.cache)
    ws = Path(tempfile.mkdtemp(prefix="ledger-drc-", dir=os.environ.get("KAEQ_SCRATCH") or "/var/tmp"))
    try:
        with gzip.open(rd / "output.kicad_pcb.gz", "rb") as fi, open(ws / "board.kicad_pcb", "wb") as fo:
            shutil.copyfileobj(fi, fo)
        for ext in ("kicad_pro", "kicad_dru"):
            src = Path(a.project_dir) / f"board.{ext}"
            if src.exists():
                shutil.copy2(src, ws / f"board.{ext}")
        binds = [b for b in os.environ.get("APPTAINER_BIND", "").split(",") if b]
        os.environ["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws)]))
        rep = tools.run_drc(ws / "board.kicad_pcb", ws / "drc.json")
        cache.mkdir(parents=True, exist_ok=True)
        tmp = cache / f".{rd.name}.tmp"
        with gzip.open(tmp, "wt") as f:
            json.dump(dict(unconnected_items=rep.get("unconnected_items", []), source="ledger fill-drc",
                           run=rd.name, project=sorted(p.name for p in ws.glob("board.kicad_*"))), f)
        os.replace(tmp, cache / f"{rd.name}.drc.json.gz")
        print(f"{rd.name}: {len(rep.get('unconnected_items', []))} unconnected items")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write ledger.jsonl and runs.jsonl for an experiment")
    b.add_argument("--experiment", required=True)
    b.add_argument("--methods", help="comma-separated method ids, id prefixes or names (default: all)")
    b.add_argument("--evaluator", help="DRC evaluator id (default: the experiment's)")
    b.add_argument("--tags", help="board-tags directory holding bus/buses.jsonl (bus membership, swap class)")
    b.add_argument("--out", help="output directory (default ./ledger-<experiment>)")
    b.add_argument("--drc-cache", help="DRC re-runs from fill-drc (default <out>/drc-cache when present)")
    r = sub.add_parser("report", help="write DIR/LEDGER.md")
    r.add_argument("dir")
    r.add_argument("--pair", help="A,B: persistence of open connections between two methods")
    c = sub.add_parser("reach", help="boards and connections whose outcome differs between two methods")
    c.add_argument("dir")
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    f = sub.add_parser("fill-drc", help="kaeq jobs re-running the DRC of runs without a stored item list (cache under --out)")
    f.add_argument("--experiment", required=True)
    f.add_argument("--methods")
    f.add_argument("--evaluator")
    f.add_argument("--out")
    f.add_argument("--corpus", help="board corpus (default $KAE_CORPUS, else ~/kae-boards)")
    f.add_argument("--only", help="comma-separated board ids")
    f.add_argument("--limit", type=int)
    f.add_argument("--prio", type=int, default=5)
    f.add_argument("--include-stored", action="store_true", help="also runs with a stored list (to check the re-run)")
    f.add_argument("--submit", action="store_true", help="queue the jobs (default: only write and print them)")
    j = sub.add_parser("fill-drc-job", help="one run's DRC re-run (what each queued job runs)")
    j.add_argument("--run-dir", required=True)
    j.add_argument("--project-dir", required=True)
    j.add_argument("--cache", required=True)
    a = p.parse_args(argv)
    {"build": cmd_build, "report": cmd_report, "reach": cmd_reach, "fill-drc": cmd_fill_drc,
     "fill-drc-job": cmd_fill_drc_job}[a.cmd](a)


if __name__ == "__main__":
    main()
