#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stress dial: derived copies of a board whose clearance and track-width rules are scaled.

A cheap board that every method routes says nothing. The same board under rules tightened by a
factor f may: the score is then the hardest level a method still routes clean. This prototype
writes the derived boards and measures how far the dial can go; the judge stays kicad-cli DRC under
the derived board's own rules (kaebench, unchanged).

    stress.py derive  SRC_DIR OUT_ROOT --factor 1.5 [--factor 2 ...]   # OUT_ROOT/<id>@c1.5/
    stress.py ceiling TASKS_DIR --out ceilings.json [--only id,...] [-j N]
    stress.py levels  ceilings.json                                     # the pilot's three levels per board
    stress.py report  RESULTS_RUN_DIR... --ceilings ceilings.json --out pilot.json

What `derive` scales (board.kicad_pro, read as JSON):
  net_settings.classes[*].clearance, .track_width      every net class
  board.design_settings.rules.min_clearance, .min_track_width
and, in board.kicad_dru, the min/opt/max values of `(constraint clearance ...)` and
`(constraint track_width ...)` when each value is a plain number with an optional unit.

Left alone: hole, edge, silk and mask clearances, annular width, via and drill sizes, diff-pair
gap and width, zone settings and the clearance overrides stored in the board file (zones, pads,
footprints), every other .kicad_dru constraint, and .kicad_dru values that are expressions. A
board without a board.kicad_pro, or whose project stores no net class clearance (KiCad's built-in
defaults apply), is refused: there is nothing to scale. Board minimums a project does not store
stay at KiCad's defaults (stress.json lists them as unscaled_defaults).

KiCad's DRC enforces a net class's clearance, but a net class's track width is only the width a
router should use: the enforced floor is the board minimum (`min_track_width`). Where that is 0,
the width half of the dial rests on the method honouring the class width; `report` gives each
output's narrowest track against the scaled class width so that this can be seen.

`ceiling` needs KiCad (through kaebench.tools); `derive`, `levels` and `report` are stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

STEM = "board"
CLASS_KEYS = ("clearance", "track_width")
RULE_KEYS = ("min_clearance", "min_track_width")
DRU_SCALED = ("clearance", "track_width")
# the scan grid: 0.1 steps to 2, then coarser (a board that survives 2x is limited by pad pitch, slowly)
GRID = (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0)
TOP_CAP = 3.0       # the pilot runs no level above this
NDIGITS = 6         # mm values are written to 1 nm


def tag(factor):
    """1.5 -> 'c1.5', 2.0 -> 'c2' (the id suffix after '@')."""
    return f"c{float(factor):g}"


def derived_id(base_id, factor):
    return f"{base_id}@{tag(factor)}"


def split_id(board_id):
    """'name@c1.5' -> ('name', 1.5); an id without a level -> (id, None)."""
    base, sep, t = board_id.rpartition("@c")
    if not sep:
        return board_id, None
    try:
        return base, float(t)
    except ValueError:
        return board_id, None


def _scaled(v, factor):
    return round(float(v) * factor, NDIGITS)


def scale_project(pro, factor):
    """A copy of a .kicad_pro dict with the clearance and track-width rules scaled.
    Returns (project, changes): changes lists (where, key, old, new) for every value touched."""
    out, changes = copy.deepcopy(pro), []
    rules = ((out.get("board") or {}).get("design_settings") or {}).get("rules")
    for key in RULE_KEYS:
        if isinstance(rules, dict) and isinstance(rules.get(key), (int, float)):
            new = _scaled(rules[key], factor)
            changes.append(("board", key, rules[key], new))
            rules[key] = new
    for nc in (out.get("net_settings") or {}).get("classes") or []:
        for key in CLASS_KEYS:
            if isinstance(nc.get(key), (int, float)):
                new = _scaled(nc[key], factor)
                changes.append((nc.get("name", "?"), key, nc[key], new))
                nc[key] = new
    return out, changes


_CONSTRAINT = re.compile(r"\(\s*constraint\s+([a-z_]+)((?:\s*\([^()]*\))*)\s*\)")
_BOUND = re.compile(r"\(\s*(min|opt|max)\s+([^()]*?)\s*\)")
_VALUE = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+))\s*(mm|mil|in|um)?$")


def scale_dru(text, factor):
    """Scale the bounds of `(constraint clearance ...)` and `(constraint track_width ...)` in a
    .kicad_dru text. Returns (text, scaled, left_alone): scaled counts the values rewritten;
    left_alone lists the constraint kinds not touched (other kinds, or values that are not a plain
    number with an optional unit)."""
    scaled, left = 0, []

    def bound(m):
        nonlocal scaled
        v = _VALUE.match(m.group(2))
        scaled += 1
        return f"({m.group(1)} {_scaled(v.group(1), factor):g}{v.group(2) or ''})"

    def constraint(m):
        kind, body = m.group(1), m.group(2)
        bounds = _BOUND.findall(body)
        simple = bounds and all(_VALUE.match(v) for _, v in bounds) and not _BOUND.sub("", body).strip()
        if kind not in DRU_SCALED or not simple:
            left.append(kind)
            return m.group(0)
        return f"(constraint {kind}{_BOUND.sub(bound, body)})"

    return _CONSTRAINT.sub(constraint, text), scaled, left


def derive(src_dir, out_root, factor, base_id=None):
    """Write OUT_ROOT/<id>@c<factor>/ from a board folder (board.kicad_pcb, board.kicad_pro, optional
    board.kicad_dru and row.json): the board file unchanged, the rules scaled. Returns
    (folder, record); the record is also written as stress.json."""
    src = Path(src_dir)
    base_id = base_id or src.name
    pro_path = src / f"{STEM}.kicad_pro"
    if not (src / f"{STEM}.kicad_pcb").exists():
        raise SystemExit(f"{src}: no {STEM}.kicad_pcb")
    if not pro_path.exists():
        raise SystemExit(f"{src}: no {STEM}.kicad_pro, so KiCad's built-in rules apply and there is nothing to scale")
    if not factor > 0:
        raise SystemExit(f"factor must be positive, got {factor}")
    pro, changes = scale_project(json.loads(pro_path.read_text(encoding="utf-8")), factor)
    if not any(key == "clearance" for _, key, _, _ in changes):
        # e.g. a project file that is `{}`: every level would be the same board
        raise SystemExit(f"{src}: {STEM}.kicad_pro has no net class clearance, so KiCad's built-in rules apply "
                         "and there is nothing to scale")
    dst = Path(out_root) / derived_id(base_id, factor)
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / f"{STEM}.kicad_pcb", dst / f"{STEM}.kicad_pcb")
    (dst / f"{STEM}.kicad_pro").write_text(json.dumps(pro, indent=2) + "\n", encoding="utf-8")
    # board minimums the project does not store keep KiCad's defaults at every level
    unscaled = [k for k in RULE_KEYS if not any(w == "board" and key == k for w, key, _, _ in changes)]
    rec = dict(base=base_id, factor=factor, id=dst.name, project=[list(c) for c in changes], unscaled_defaults=unscaled)
    dru = src / f"{STEM}.kicad_dru"
    if dru.exists():
        text, n, left = scale_dru(dru.read_text(encoding="utf-8", errors="replace"), factor)
        (dst / f"{STEM}.kicad_dru").write_text(text, encoding="utf-8")
        rec["dru"] = dict(scaled=n, left_alone=sorted(set(left)))
    row = src / "row.json"
    if row.exists():  # kaebench prepare-dir reads repo, licence and tags from it
        meta = json.loads(row.read_text())
        meta.update(id=dst.name, stress=dict(base=base_id, factor=factor))
        (dst / "row.json").write_text(json.dumps(meta, indent=1) + "\n")
    (dst / "stress.json").write_text(json.dumps(rec, indent=1) + "\n")
    return dst, rec


# ---------------------------------------------------------------- ceiling and human level (KiCad)
def drc_at(board_dir, factor, work):
    """kicad-cli DRC (zones refilled) of the board in board_dir under its rules scaled by factor:
    the harness's own counts (kaebench.tools.summarize_drc)."""
    from kaebench import tools
    d, _ = derive(board_dir, work, factor, base_id="b")
    return tools.summarize_drc(tools.run_drc(d / f"{STEM}.kicad_pcb", d / "drc.json"))


def gained(drc, base):
    """Error types whose count is above the base level's: {type: extra}."""
    return {t: n - base["errors_by_type"].get(t, 0) for t, n in sorted(drc["errors_by_type"].items())
            if n > base["errors_by_type"].get(t, 0)}


def ceiling_of(scan):
    """The largest grid factor below the first one at which the bare input gains a DRC error.
    scan: [(factor, gained)] ascending, the first factor 1.0. Returns (ceiling, limit): limit is
    (factor, gained) of the first failing level, or None when the grid never fails."""
    top = scan[0][0]
    for f, g in scan:
        if g:
            return top, (f, g)
        top = f
    return top, None


def clean_level(is_clean, lo, hi, tol=0.01):
    """The largest factor in [lo, hi] at which is_clean holds, by bisection to tol; None when it
    does not hold at lo. Assumes clean stays clean at every smaller factor (minimum rules)."""
    if not is_clean(lo):
        return None
    if is_clean(hi):
        return hi
    while hi - lo > tol:
        mid = round((lo + hi) / 2, 4)
        lo, hi = (mid, hi) if is_clean(mid) else (lo, mid)
    return math.floor(lo * 100 + 1e-6) / 100


def measure(task_dir, grid=GRID):
    """Ceiling of a prepared kaebench task's bare route input and the human layout's level."""
    task_dir = Path(task_dir)
    out = dict(id=task_dir.name)
    with tempfile.TemporaryDirectory(prefix="stress-") as tmp:
        bare, n = task_dir / "route" / "input", 0

        def at(d, f):
            nonlocal n
            n += 1
            return drc_at(d, f, Path(tmp) / f"s{n}")

        base = at(bare, grid[0])
        scan = [(grid[0], {})] + [(f, gained(at(bare, f), base)) for f in grid[1:]]
        out["bare_errors_at_1"] = base["errors_by_type"]
        out["bare_scan"] = [[f, g] for f, g in scan]
        out["ceiling"], limit = ceiling_of(scan)
        out["ceiling_limit"] = list(limit) if limit else None
        # monotone: once an error type is gained it stays gained at every larger factor
        seen, mono = set(), True
        for _, g in scan:
            mono &= seen <= set(g)
            seen |= set(g)
        out["bare_monotone"] = mono
        human, first_bad = task_dir / "reference", {}

        def clean(f):
            d = at(human, f)
            ok = d["errors"] == 0 and d["unconnected"] == 0
            if not ok:
                first_bad[f] = dict(d["errors_by_type"], **({"unconnected": d["unconnected"]} if d["unconnected"] else {}))
            return ok

        out["human_level"] = clean_level(clean, grid[0], grid[-1])
        out["human_limit"] = first_bad[min(first_bad)] if first_bad else None
        out["drc_runs"] = n
    return out


def pick_levels(ceiling, human_level, cap=TOP_CAP):
    """The pilot's three levels: 1.0, a middle and a top inside the ceiling. Top is the ceiling
    (at most cap). The middle is the human layout's level when that lies well inside (1.15 to
    0.9 x top): the human layout then proves the level routable; otherwise the geometric middle.
    None when the ceiling leaves no room for two tighter levels (below 1.2)."""
    top = min(ceiling, cap)
    if top < 1.2:
        return None
    if human_level and 1.15 <= human_level <= 0.9 * top:
        mid = math.floor(human_level * 20 + 1e-6) / 20
    else:
        mid = round(math.sqrt(top) * 20) / 20
    mid = min(max(mid, 1.1), round(top - 0.1, 2))
    return [1.0, mid, top]


# ---------------------------------------------------------------- report
_WIDTH = re.compile(r"\((?:segment|arc)\b[^()]*(?:\([^()]*\)[^()]*)*?\(width ([\d.]+)\)")


def narrowest_track(board):
    """Smallest track width (mm) in a .kicad_pcb, or None when it has no tracks."""
    try:
        widths = [float(w) for w in _WIDTH.findall(Path(board).read_text(encoding="utf-8", errors="replace"))]
    except OSError:
        return None
    return min(widths) if widths else None


def hardest_clean(levels):
    """levels: {factor: clean}. The largest factor up to which every tested level is clean (None
    when the lowest is not), and whether clean never comes back after a failure (monotone)."""
    fs = sorted(levels)
    best, failed, mono = None, False, True
    for f in fs:
        if levels[f] and not failed:
            best = f
        elif levels[f]:
            mono = False
        else:
            failed = True
    return best, mono


def _kae_work(log):
    """restart.py's last `KAE_WORK {json}` line in an attempt's adapter.log ({} when there is none)."""
    try:
        lines = [ln for ln in Path(log).read_text(errors="replace").splitlines() if ln.startswith("KAE_WORK ")]
        return json.loads(lines[-1][len("KAE_WORK "):]) if lines else {}
    except (OSError, ValueError):
        return {}


def collect(run_dirs):
    """Rows of every route attempt under kaebench results run folders."""
    rows = []
    for rd in map(Path, run_dirs):
        for aj in sorted(rd.glob("*/route/*/attempt-*/attempt.json")):
            a = json.loads(aj.read_text())
            s = a.get("score") or {}
            base, f = split_id(a["id"])
            if f is None:
                continue
            w = _kae_work(aj.parent / "adapter.log")
            rows.append(dict(board=base, factor=f, method=a["adapter"], status=a.get("status"), clean=bool(s.get("clean")),
                             valid=s.get("valid"), unconnected=s.get("unconnected"), start_unconnected=s.get("start_unconnected"),
                             completion=s.get("completion"), errors=s.get("errors"), errors_by_type=s.get("errors_by_type") or {},
                             runtime_s=a.get("runtime_s"), cpu_s=(a.get("method_usage") or {}).get("cpu_s"),
                             restarts=w.get("attempts"), timed_out=bool((a.get("adapter_meta") or {}).get("timed_out")), min_track_mm=narrowest_track(aj.parent / "score" / "board.kicad_pcb"),
                             run=rd.name))
    return rows


def summarize(rows, ceilings=None):
    """Per board and method: the hardest clean level, monotonicity of clean and of completion."""
    ceilings = {c["id"].split("@")[0]: c for c in (ceilings or [])}
    out = {}
    for r in rows:
        out.setdefault((r["board"], r["method"]), {})[r["factor"]] = r
    table = []
    for (board, method), lv in sorted(out.items()):
        best, mono = hardest_clean({f: r["clean"] for f, r in lv.items()})
        comp = [lv[f]["completion"] for f in sorted(lv)]
        comp_mono = all(a is not None and b is not None and b <= a + 1e-9 for a, b in zip(comp, comp[1:]))
        c = ceilings.get(board) or {}
        table.append(dict(board=board, method=method, levels=sorted(lv), hardest_clean=best, clean_monotone=mono,
                          completion=comp, completion_monotone=comp_mono, ceiling=c.get("ceiling"),
                          human_level=c.get("human_level"),
                          cpu_s=[lv[f]["cpu_s"] for f in sorted(lv)],
                          unconnected=[lv[f]["unconnected"] for f in sorted(lv)],
                          errors=[lv[f]["errors"] for f in sorted(lv)]))
    return table


# ---------------------------------------------------------------- CLI
def _cmd_derive(a):
    for f in a.factor:
        dst, rec = derive(a.src, a.out, f, a.id)
        dru = f", dru {rec['dru']['scaled']} values (left alone: {', '.join(rec['dru']['left_alone']) or 'none'})" if "dru" in rec else ""
        print(f"{dst}: {len(rec['project'])} project values x{f:g}{dru}")
    return 0


def _cmd_ceiling(a):
    tasks = Path(a.tasks)
    ids = [x for x in (a.only or "").split(",") if x] or sorted(p.parent.name for p in tasks.glob("*/task.json"))
    grid = tuple(float(x) for x in a.grid.split(",")) if a.grid else GRID

    def one(i):
        try:
            r = measure(tasks / i, grid)
        except Exception as e:  # one board's KiCad failure must not lose the others
            r = dict(id=i, error=f"{type(e).__name__}: {e}"[:500])
        print(f"{i}: ceiling {r.get('ceiling')} human {r.get('human_level')} "
              f"limit {r.get('ceiling_limit')} {r.get('error', '')}", flush=True)
        return r

    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, ids))
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    return 1 if any("error" in r for r in res) else 0


def _cmd_levels(a):
    for c in json.loads(Path(a.ceilings).read_text()):
        if "error" in c:
            continue
        lv = pick_levels(c["ceiling"], c["human_level"], a.cap)
        print(c["id"].split("@")[0], c["ceiling"], c["human_level"], " ".join(f"{x:g}" for x in lv) if lv else "-")
    return 0


def _cmd_report(a):
    rows = collect(a.runs)
    ceilings = json.loads(Path(a.ceilings).read_text()) if a.ceilings else None
    table = summarize(rows, ceilings)
    if a.out:
        Path(a.out).write_text(json.dumps(dict(rows=rows, table=table), indent=1) + "\n")
    for t in table:
        print(f"{t['board'][:44]:44s} {t['method']:8s} levels {t['levels']} hardest clean {t['hardest_clean']} "
              f"mono {t['clean_monotone']}/{t['completion_monotone']} open {t['unconnected']} err {t['errors']} cpu {t['cpu_s']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("derive", help="write derived board folders with scaled rules")
    s.add_argument("src"), s.add_argument("out")
    s.add_argument("--factor", type=float, action="append", required=True)
    s.add_argument("--id", help="base id (default: the source folder's name)")
    s.set_defaults(fn=_cmd_derive)
    s = sub.add_parser("ceiling", help="ceiling of each prepared task's bare input, and the human layout's level")
    s.add_argument("tasks", help="kaebench tasks folder (WORKDIR/tasks)")
    s.add_argument("--out", required=True), s.add_argument("--only"), s.add_argument("--grid")
    s.add_argument("-j", "--jobs", type=int, default=1)
    s.set_defaults(fn=_cmd_ceiling)
    s = sub.add_parser("levels", help="the pilot's three levels per board")
    s.add_argument("ceilings"), s.add_argument("--cap", type=float, default=TOP_CAP)
    s.set_defaults(fn=_cmd_levels)
    s = sub.add_parser("report", help="hardest clean level per board and method")
    s.add_argument("runs", nargs="+"), s.add_argument("--ceilings"), s.add_argument("--out")
    s.set_defaults(fn=_cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
