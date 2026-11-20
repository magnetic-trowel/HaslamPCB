# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Part-attached whitespace demand ("halo"): one channel from routing back to placement.

A producer says how much extra clear gap each part needs around its pads; the consumer
re-places the whole board from its current poses, keeps every part near where it is, and
opens the requested gaps; then the board is routed again from bare placement.

    p = load_pressure("pressure.json")          # or fallback_pressure(board_path, unconnected)
    rep = replace_with_halos("start.kicad_pcb", p, "out.kicad_pcb", seed=1, time_s=60)

Pressure file (schema 1):

    {"schema": 1, "source": "...", "parts": {ref: mm}, "pairs": [[refA, refB, mm], ...]}

`parts[ref]`: the extra clear gap (mm) part `ref` needs around it; `pairs`: the extra gap
between two named parts. The placer's occupancy model is per part (two parts' grown
rectangles may not overlap), so a pair's gap is split in halves onto its two parts, and a
part's halo holds against every other part, related or not (see NOTES-d2-halo.md).

The re-place is the window re-placement (kae.joint.replace.replace_window) with the window
the whole board and its subset every unlocked part: the parts start at their current poses
(the annealer's displacement term pulls them back to those poses), each part's halo is a
per-part occupancy growth (Problem.bump, the same per-part addition the window loop uses for
parts an unrouted connection names), and the halos are wishes: when the result is not grid
legal, replace_window drops them with the routing margin before the greedy legalizer, as it
does in the window loop. Locked parts (and Edge.Cuts footprints) stay fixed, as in the loop
started from a placed board (KaeStages.layout_from).

Command line (one round = pressure, re-place, strip routing, modules, bridge route, KiCad DRC,
the loop's ranked judge, keep the better of start and result; --rounds N repeats from the
kept board while time is left):

    python -m kae.joint.halo --start BOARD --input TASK_BOARD -o OUT --time T --seed S \\
        [--pressure FILE] [--rounds N] [--report FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import sys
import time
from pathlib import Path

from kae.budget import now as clock_now

SCHEMA = 1
MAX_PITCHES = 4          # the fallback producer's cap: at most this many routing pitches per part
# displacement weight of a revision. The annealer's own 0.05 is for a fresh placement: its hot
# start reshuffled the test fixture (median move 14 mm of a 72 mm diagonal); 1.0 kept the median
# move at 0.4 mm and still opened a 1 mm halo. A setting (--w-disp), not a tuned optimum.
W_DISP = 1.0


class PressureError(ValueError):
    """A pressure file that does not follow the schema."""


def _mm(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) < 0:
        raise PressureError(f"{what}: expected a finite number of mm >= 0, got {v!r}")
    return float(v)


def validate_pressure(d):
    """The pressure dict, checked and normalised (floats, pairs as [a, b, mm] with a != b).
    Raises PressureError."""
    if not isinstance(d, dict):
        raise PressureError("pressure must be a JSON object")
    if d.get("schema") != SCHEMA:
        raise PressureError(f"schema must be {SCHEMA}, got {d.get('schema')!r}")
    parts = d.get("parts", {})
    if not isinstance(parts, dict):
        raise PressureError("parts must be an object {ref: mm}")
    out_parts = {}
    for ref, mm in parts.items():
        if not isinstance(ref, str) or not ref:
            raise PressureError(f"parts: bad reference {ref!r}")
        out_parts[ref] = _mm(mm, f"parts[{ref}]")
    pairs = d.get("pairs", [])
    if not isinstance(pairs, list):
        raise PressureError("pairs must be a list of [refA, refB, mm]")
    out_pairs = []
    for k, pr in enumerate(pairs):
        if not isinstance(pr, (list, tuple)) or len(pr) != 3:
            raise PressureError(f"pairs[{k}]: expected [refA, refB, mm], got {pr!r}")
        a, b, mm = pr
        if not isinstance(a, str) or not isinstance(b, str) or not a or not b or a == b:
            raise PressureError(f"pairs[{k}]: two different references expected, got {a!r}, {b!r}")
        out_pairs.append([a, b, _mm(mm, f"pairs[{k}]")])
    source = d.get("source", "")
    if not isinstance(source, str):
        raise PressureError("source must be a string")
    return {"schema": SCHEMA, "source": source, "parts": out_parts, "pairs": out_pairs}


def load_pressure(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as e:
        raise PressureError(f"{path}: not JSON ({e})") from e
    return validate_pressure(d)


def part_halos(pressure):
    """{ref: mm} per part: its own halo plus half of each pair gap it is in (the occupancy model
    is per part; two halves keep the pair apart by the pair's gap)."""
    out = dict(pressure.get("parts") or {})
    for a, b, mm in pressure.get("pairs") or []:
        for r in (a, b):
            out[r] = out.get(r, 0.0) + mm / 2.0
    return {r: v for r, v in out.items() if v > 0}


def summary(pressure):
    h = part_halos(pressure)
    return dict(source=pressure.get("source", ""), parts_with_halo=len(h), total_mm=round(sum(h.values()), 3),
                max_mm=round(max(h.values()), 3) if h else 0.0, pairs=len(pressure.get("pairs") or []))


# ------------------------------------------------------------------ fallback producer
def routing_pitch(board):
    """(mm, why): one routing pitch of the board's default net class, track width + clearance
    (the board minimum clearance and minimum track as floors, KiCad's own rule order)."""
    r = board.rules
    if r is None:
        raise ValueError("board has no rules: no routing pitch")
    nc = (r.netclasses or {}).get("Default")
    width = max(float(nc.track_width or 0.0) if nc else 0.0, float(r.track_min or 0.0))
    clr = max(float(nc.clearance or 0.0) if nc else 0.0, float(r.clearance or 0.0))
    if width <= 0 or clr <= 0:
        raise ValueError(f"board rules give no routing pitch (track {width}, clearance {clr})")
    return width + clr, f"Default net class: track {width:g} mm + clearance {clr:g} mm"


def open_refs(unconnected):
    """[refs of one open connection] per KiCad DRC unconnected item, as the joint loop reads
    them (kae.joint.feedback.parse_item: pads name their footprint)."""
    from .feedback import parse_item
    out = []
    for u in unconnected or []:
        refs = sorted({it["ref"] for it in (parse_item(x) for x in (u.get("items") or [])) if it["ref"]})
        if refs:
            out.append(refs)
    return out


def fallback_pressure(board_path, unconnected, max_pitches=MAX_PITCHES):
    """A pressure from KiCad's unconnected list alone: each part at an end of an open
    connection gets one routing pitch (routing_pitch) per open connection on it, at most
    `max_pitches` pitches. `board_path`: a path or a loaded kae Board."""
    if isinstance(board_path, (str, Path)):
        from kae.board.kicad_file import load
        board = load(board_path)
    else:
        board = board_path
    pitch, why = routing_pitch(board)
    count = {}
    for refs in open_refs(unconnected):
        for r in refs:
            count[r] = count.get(r, 0) + 1
    parts = {r: round(min(n, max_pitches) * pitch, 6) for r, n in sorted(count.items())}
    return {"schema": SCHEMA, "source": f"fallback: one pitch per open connection, cap {max_pitches} ({why})",
            "parts": parts, "pairs": []}


def producer_pressure(board_path, drc_report, log=None):
    """The cutflow producer when it is importable (kae.place.cutflow.pressure(board_path,
    drc_report) -> pressure dict), else the fallback."""
    log = log or (lambda *a, **k: None)
    try:
        from kae.place import cutflow  # noqa: F401 - another branch
        fn = getattr(cutflow, "pressure", None)
    except ImportError:
        fn = None
    if fn is not None:
        try:
            return validate_pressure(fn(str(board_path), drc_report))
        except Exception as e:  # noqa: BLE001 - the fallback still gives a pressure
            log(f"cutflow pressure failed ({type(e).__name__}: {e}); fallback")
    return fallback_pressure(board_path, (drc_report or {}).get("unconnected_items") or [])


# ------------------------------------------------------------------ consumer
def _outline_rect(board):
    polys = [p for p in board.outline if p is not None]
    if polys:
        xs = [p.bounds for p in polys]
        return (min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs))
    xs = [fp.x for fp in board.footprints] or [0.0]
    ys = [fp.y for fp in board.footprints] or [0.0]
    return (min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + 10)


def displacement(board, poses, rect=None):
    """Moves of every unlocked part: median and max (mm) and max as a share of the board diagonal."""
    x0, y0, x1, y1 = rect or _outline_rect(board)
    diag = max(1e-9, math.hypot(x1 - x0, y1 - y0))
    d = [math.dist((fp.x, fp.y), poses[fp.uuid][:2]) if fp.uuid in poses else 0.0
         for fp in board.footprints if not fp.locked and not fp.edge_cuts]
    if not d:
        return dict(parts=0, moved=0, median_mm=0.0, max_mm=0.0, max_share_diag=0.0, median_share_diag=0.0)
    med, mx = statistics.median(d), max(d)
    return dict(parts=len(d), moved=sum(1 for v in d if v > 1e-4), median_mm=round(med, 4), max_mm=round(mx, 4),
                median_share_diag=round(med / diag, 5), max_share_diag=round(mx / diag, 5), diag_mm=round(diag, 2))


def replace_with_halos(start_board, pressure, out_board, seed=0, time_s=60.0, brief=None, margin=0.0,
                       w_disp=W_DISP, physics=False, locked_refs=(), moves_per_part=6000, board_path=None,
                       opts=None, log=None):
    """Re-place every unlocked part of `start_board` (a path) from its poses with per-part
    halos (see the module docstring) and write `out_board` (the start's routing kept as is;
    the caller strips it). Returns a report dict: halos asked and applied, legal, relaxed,
    displacement, seconds. An illegal or failed re-place writes the start board unchanged
    (`legal` False). `locked_refs`: more parts that stay fixed. `margin`: the uniform routing
    margin under the halos (default 0: only the asked gaps)."""
    from kae.board.kicad_file import load
    from kae.place.writer import write

    from .feedback import Window
    from .replace import replace_window, window_board

    t0 = clock_now()
    log = log or (lambda *a, **k: None)
    board = load(start_board)
    if locked_refs:
        keep = {fp.uuid for fp in board.footprints if fp.ref not in set(locked_refs)}
        board = window_board(board, keep)
    halos = part_halos(validate_pressure(pressure))
    movable = tuple(sorted(fp.uuid for fp in board.footprints if not fp.locked and not fp.edge_cuts))
    rect = _outline_rect(board)
    # a hair outside the outline: the board limits (not the window) bound the parts
    win = Window(rect=(rect[0] - 1.0, rect[1] - 1.0, rect[2] + 1.0, rect[3] + 1.0), parts=movable,
                 refs=tuple(fp.ref for fp in board.footprints if fp.uuid in set(movable)))
    unknown = sorted(set(halos) - {fp.ref for fp in board.footprints})
    rep = dict(seed=seed, halos_asked=len(halos), halo_total_mm=round(sum(halos.values()), 3),
               unknown_refs=unknown[:20], movable=len(movable))
    if not set(halos) & set(win.refs):
        # nothing asked of a part that may move: the start stands (no re-place, no drift)
        shutil.copy2(start_board, out_board)
        rep.update(halos_applied=0, relaxed=False, legal=True, rejected="no pressure on a movable part", poses=0,
                   displacement=displacement(board, {}, rect), seconds=round(clock_now() - t0, 2))
        return rep
    res = replace_window(board, win, brief or {"nets": {}, "structures": []}, history=None, seed=seed,
                         time_s=time_s, physics=physics, cong_mult=1.0, bump_mm=0.0, bump_refs=halos,
                         margin=margin, moves_per_part=moves_per_part, board_path=board_path, opts=opts,
                         log=log, w_disp=w_disp)
    r = res.report
    rep.update(halos_applied=len(r.get("bumped") or []), relaxed=bool(r.get("relaxed")),
               legal=bool(r.get("legal_grid")) and not r.get("exact") and not r.get("rejected"),
               rejected=r.get("rejected") or r.get("skipped"), anneal=r.get("anneal"),
               cost_before=r.get("cost_before"), cost_after=r.get("cost_after"))
    poses = dict(res.poses)
    if poses:
        write(str(start_board), str(out_board), poses, mode=(opts or {}).get("writer", "auto"), log=None)
    else:
        shutil.copy2(start_board, out_board)
    rep["poses"] = len(poses)
    rep["displacement"] = displacement(board, poses, rect)
    rep["seconds"] = round(clock_now() - t0, 2)
    return rep


# ------------------------------------------------------------------ rounds (command line)
def _log(msg):
    print(f"[kae.joint.halo {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def strip_routing(src, dst):
    """dst = src without tracks, arcs and vias (route from bare placement)."""
    from kae.route import critical_write as W
    W.edit(src, dst, remove=[r["uuid"] for r in W.routing(src)])
    return dst


def _card_dict(card):
    return dict(unconnected=card.unconnected, errors=card.errors, placement_errors=card.placement_errors,
                physics_checked=card.checked.get("physics", True))


def run(a, log=_log):
    from .scorecard import accept
    from .stages import KaeStages, _project

    t0 = clock_now()
    deadline = t0 + float(a.time)
    out = Path(a.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    wd = Path(a.workdir or (str(out) + ".halo")).resolve()
    wd.mkdir(parents=True, exist_ok=True)
    inp = Path(a.input).resolve()
    opts = dict(no_physics=bool(a.no_physics))
    rep = dict(start=str(a.start), input=str(inp), seed=a.seed, time_s=a.time, rounds=[])
    # the start board, judged as the loop judges an iteration
    S0 = KaeStages(inp, wd / "start", opts=opts, log=log)
    lay0 = S0.layout_from(a.start)
    t = clock_now()
    best_card, best_fb = S0.evaluate(lay0, 0)
    eval_s = clock_now() - t
    best_path = Path(lay0.board)
    rep["start_card"] = _card_dict(best_card)
    log(f"start: {best_card.unconnected} unconnected, {best_card.errors} errors ({eval_s:.0f}s)")
    for k in range(max(1, int(a.rounds))):
        left = deadline - clock_now()
        if left < 2.5 * eval_s + 60.0:
            rep["stop"] = f"time ({left:.0f}s left)"
            break
        if best_card.unconnected == 0 and best_card.errors == 0:
            rep["stop"] = "clean"
            break
        row = dict(round=k + 1, opens_before=best_card.unconnected, errors_before=best_card.errors, seconds={})
        rep["rounds"].append(row)
        S = KaeStages(inp, wd / f"round{k + 1:02d}", opts=opts, log=log)
        try:
            ts = clock_now()
            if a.pressure:
                pressure = load_pressure(a.pressure)
            else:
                pressure = producer_pressure(best_path, best_fb.get("drc"), log=log)
            row["pressure"] = summary(pressure)
            row["seconds"]["pressure"] = round(clock_now() - ts, 2)
            if not part_halos(pressure):
                row["outcome"] = "no pressure"
                break
            ts = clock_now()
            board = S._load(best_path)
            brief = S._ensure_brief(board) if not a.no_physics else None
            placed = S.wd / "halo_placed.kicad_pcb"
            place_s = min(float(a.place_time), max(10.0, 0.2 * (deadline - clock_now())))
            prep = replace_with_halos(best_path, pressure, placed, seed=a.seed + 7919 * k, time_s=place_s,
                                      brief=brief, margin=a.margin, w_disp=a.w_disp, physics=not a.no_physics,
                                      board_path=str(inp), opts=opts, log=log)
            row["replace"] = prep
            row["legal"] = prep["legal"]
            row["displacement"] = prep["displacement"]
            row["seconds"]["replace"] = round(clock_now() - ts, 2)
            if not prep["legal"] or not prep["poses"]:
                row["outcome"] = "re-place not legal" if not prep["legal"] else "no part moved"
                row["kept"] = False
                continue
            _project(inp, placed)
            bare = strip_routing(placed, S.wd / "halo_bare.kicad_pcb")
            _project(inp, bare)
            lay = S.layout_from(bare)
            ts = clock_now()
            if not a.no_modules:
                lay = S.modules(lay, 0)
            row["seconds"]["modules"] = round(clock_now() - ts, 2)
            ts = clock_now()
            route_s = max(30.0, deadline - clock_now() - 1.5 * eval_s - 15.0)
            lay = S.route(lay, 0, seed=a.seed + 7919 * k, time_s=route_s)
            row["seconds"]["route"] = round(clock_now() - ts, 2)
            ts = clock_now()
            card, fb = S.evaluate(lay, 0)
            row["seconds"]["evaluate"] = round(clock_now() - ts, 2)
            row["after"] = _card_dict(card)
            row["opens_after"] = card.unconnected
            keep, why = accept(best_card, card)
            row["kept"], row["why"] = bool(keep), why
            log(f"round {k + 1}: opens {best_card.unconnected} -> {card.unconnected}, "
                f"{'kept' if keep else 'not kept'} ({why})")
            if keep:
                kept = S.wd / "kept.kicad_pcb"
                S.finish(lay, kept)
                _project(inp, kept)
                best_path, best_card, best_fb = kept, card, fb
        except Exception as e:  # noqa: BLE001 - one failed round must not lose the incumbent
            import traceback
            log(f"round {k + 1} failed: {type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}")
            row["outcome"] = f"error: {type(e).__name__}: {e}"
            row["kept"] = False
    shutil.copy2(best_path, out)
    _project(inp, out)
    rep["final_card"] = _card_dict(best_card)
    rep["kept_rounds"] = sum(1 for r in rep["rounds"] if r.get("kept"))
    rep["seconds"] = round(clock_now() - t0, 1)
    return rep


def main(argv=None):
    from kae.budget import start_run
    ap = argparse.ArgumentParser(prog="python -m kae.joint.halo", description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", required=True, help="placed (possibly routed) board to revise")
    ap.add_argument("--input", required=True, help="the original task board (rules and project files)")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--time", type=float, default=900.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pressure", default=None, help="pressure JSON (schema 1); default: cutflow, else fallback")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--place-time", type=float, default=60.0, help="re-place seconds per round (at most)")
    ap.add_argument("--margin", type=float, default=0.0, help="uniform routing margin under the halos (mm)")
    ap.add_argument("--w-disp", type=float, default=W_DISP, help=f"displacement weight (default {W_DISP})")
    ap.add_argument("--no-modules", action="store_true")
    ap.add_argument("--no-physics", action="store_true")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--report", default=None, help="JSON report file (also the last line of stdout)")
    a = ap.parse_args(argv)
    start_run(float(a.time))
    rep = run(a)
    text = json.dumps(rep, default=str)
    if a.report:
        Path(a.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if Path(a.output).exists() else 2


if __name__ == "__main__":
    sys.exit(main())
