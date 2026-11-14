# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""KiCad DRC with kicad-cli, the way kaebench scores (zones refilled, all severities, mm).

kicad-cli is found as in kaebench: KAE_KICAD_CLI (a command, possibly with a wrapper),
KAE_KICAD_WRAP + kicad-cli (e.g. "apptainer exec ~/kicad.sif"), or kicad-cli on PATH.
The board must have its project files (.kicad_pro, .kicad_dru) beside it, since KiCad takes
rule severities and custom rules from them.
"""
from kae import budget
import functools
import hashlib
import json
import re
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import stepcache

# Violation types that depend on the local library setup, not on the board (as kaebench).
ENV_DEPENDENT = ("lib_footprint_issues", "lib_footprint_mismatch")
# kicad-cli lists at most this many unconnected items; past it (or when the project ignores the
# check: unconnected_ignored) the count comes from pcbnew's connectivity after a zone fill, as
# kaebench's scorer counts (score._uncapped): on polarfire-som
# every repair round read 499 and last-mile rounds that joined 26-41 connections were discarded
DRC_UNCONNECTED_CAP = 499
UNCONNECTED_PY = ("import json, sys, pcbnew\n"
                  "b = pcbnew.LoadBoard(sys.argv[1]); zs = pcbnew.ZONES()\n"
                  "for i in range(b.GetAreaCount()): zs.append(pcbnew.Cast_to_ZONE(b.GetArea(i)))\n"
                  "len(zs) and pcbnew.ZONE_FILLER(b).Fill(zs)\n"
                  "b.BuildConnectivity()\n"
                  "print(json.dumps(dict(unconnected=b.GetConnectivity().GetUnconnectedCount(False))))\n")


class DrcError(RuntimeError):
    pass


@functools.lru_cache(maxsize=None)
def kicad_cli():
    v = os.environ.get("KAE_KICAD_CLI")
    if v:
        return tuple(shlex.split(v))
    w = os.environ.get("KAE_KICAD_WRAP")
    if w:
        return (*shlex.split(w), "kicad-cli")
    p = shutil.which("kicad-cli")
    if not p:
        raise DrcError("kicad-cli not found; set KAE_KICAD_CLI or KAE_KICAD_WRAP")
    return (p,)


def run(board, out_json, timeout=900, cache=True):
    """kicad-cli pcb drc on `board`; returns the parsed JSON report. `cache=False` runs KiCad even
    with the step cache on (a second run of the same board, to see which checks are noisy)."""
    board, out_json = Path(board).resolve(), Path(out_json).resolve()
    if out_json.exists():
        out_json.unlink()
    timeout = budget.wall_timeout(timeout)
    mb = board.stat().st_size / 1e6
    back, judged = {}, board
    if budget.work_mode():
        canonical_copper_order(board)
        judged, back = _judged_copy(board)
    try:
        rep = _run(judged, out_json, timeout, cache, mb)
        if budget.work_mode() and rep.get("unconnected_items"):
            canonical_unconnected(rep, _copper_items(judged, timeout))
        if len(rep.get("unconnected_items") or []) >= DRC_UNCONNECTED_CAP or unconnected_ignored(board):
            n = uncapped_unconnected(judged, timeout)
            if n is not None:
                rep["unconnected_count"] = n
    finally:
        if judged != board:
            shutil.rmtree(judged.parent, ignore_errors=True)
    _map_uuids(rep, back)
    if budget.work_mode():
        # the file holds the report as returned (content order, the board's UUIDs, the uncapped count):
        # callers that read it back (repair's reroute rounds) see what this call's caller saw, not
        # KiCad's raw report of the temporary copy, whose UUIDs name nothing on `board`
        tmp = out_json.with_name(out_json.name + ".tmp")
        tmp.write_text(json.dumps(rep, indent=2))
        os.replace(tmp, out_json)
    return rep


def _run(board, out_json, timeout, cache, mb):
    cmd = [*kicad_cli(), "pcb", "drc", "--format", "json", "--refill-zones", "--severity-all",
           "--units", "mm", "-o", str(out_json), str(board)]
    try:
        if cache and stepcache.enabled():   # KAE_STEP_CACHE: a board DRC'd before, with the same rules, replays its report
            r = stepcache.run("kicad-drc", cmd, inputs=stepcache.kicad_inputs(board), outputs={"report": out_json},
                              wd=board.parent, timeout=timeout, tool=stepcache.kicad_version(kicad_cli()),
                              cwd=board.parent)
        else:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=board.parent, errors="replace")
    except subprocess.TimeoutExpired:
        raise DrcError(f"DRC timed out after {timeout}s")
    finally:
        budget.charge("drc_mb", mb)
    if not out_json.exists():
        raise DrcError(f"DRC failed (rc={r.returncode}): {(r.stdout + r.stderr)[-600:]}")
    with open(out_json) as f:
        rep = json.load(f)
    if budget.work_mode():              # KiCad's report follows the file's order (UUIDs: see kicad_file.load)
        for k in ("violations", "unconnected_items", "schematic_parity"):
            if rep.get(k):
                rep[k].sort(key=_content_key)
    return rep


def unconnected_ignored(board):
    """True when the project beside `board` sets the unconnected_items check to "ignore": KiCad's
    DRC then lists no unconnected items at all, even with --severity-all, so its count says nothing
    about connectivity (as kaebench's boardfiles.unconnected_ignored; the scorer then counts with
    pcbnew, and so does run). gamaphy-freedom-rp2040 is one such board."""
    try:
        pro = json.loads(Path(board).with_suffix(".kicad_pro").read_text(encoding="utf-8"))
        return pro["board"]["design_settings"]["rule_severities"]["unconnected_items"] == "ignore"
    except (OSError, ValueError, KeyError, TypeError):
        return False


def canonical_copper_order(board, uuids=False):
    """Rewrite `board` with its top-level (segment), (arc) and (via) blocks in the order of their content.
    KiCad writes copper in UUID order, new on every import of a routed board, and its ratsnest breaks ties
    between equally near copper by load order: the same board then reports other unconnected items.
    With `uuids`, the copper's UUIDs are also derived from that content (KiCad's counts depend on them
    too: two copies of one board with other UUIDs judged 96 and 97 open), and the result is
    {new uuid: old uuid}."""
    lines = Path(board).read_text(errors="replace").split("\n")
    blocks, first, out, i = [], None, [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith(("\t(segment", "\t(arc", "\t(via")) and not ln.startswith("\t(via_"):
            j, depth = i, 0
            while True:
                depth += lines[j].count("(") - lines[j].count(")")
                if depth <= 0:
                    break
                j += 1
            blocks.append(lines[i:j + 1])
            if first is None:
                first = len(out)
            i = j + 1
            continue
        out.append(ln)
        i += 1
    if blocks:
        blocks.sort(key=lambda b: [x for x in b if "(uuid" not in x and "(tstamp" not in x])
        back = {}
        if uuids:
            for k, blk in enumerate(blocks):
                h = hashlib.sha1(("%d\n" % k + "\n".join(x for x in blk if "(uuid" not in x)).encode()).hexdigest()
                u = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
                for x in blk:
                    m = _UUID.search(x)
                    if m:
                        back[u] = m.group(1)
                blocks[k] = [_UUID.sub(f'(uuid "{u}")', x) for x in blk]
        out[first:first] = [x for b in blocks for x in b]
        Path(board).write_text("\n".join(out))
        return back
    return {}


_UUID = re.compile(r'\(uuid "?([0-9a-fA-F-]+)"?\)')


def _judged_copy(board):
    """A temporary copy of `board` (with its project files) in canonical copper order with content UUIDs,
    and {new uuid: old uuid} to read its report against `board`."""
    d = Path(tempfile.mkdtemp(prefix="drc-canon-", dir=board.parent))
    for f in board.parent.glob(board.stem + ".kicad_*"):
        if f.suffix in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".kicad_prl"):
            shutil.copy2(f, d / f.name)
    c = d / board.name
    return c, canonical_copper_order(c, uuids=True)


def _map_uuids(rep, back):
    for k in ("violations", "unconnected_items"):
        for v in rep.get(k) or []:
            for it in v.get("items") or []:
                if it.get("uuid") in back:
                    it["uuid"] = back[it["uuid"]]


def _copper_items(board, timeout):
    """pcbnew_io.copper_items of `board`, None when KiCad's Python cannot give them."""
    from kae.board.pcbnew_io import PcbnewError, copper_items
    try:
        return copper_items(board, timeout=timeout)["items"]
    except (PcbnewError, OSError, KeyError, TypeError):
        return None


def canonical_unconnected(rep, items):
    """Name each unconnected item of `rep` (in place) by a choice of KiCad's that does not vary from run to run.

    kicad-cli's DRC of one and the same file names other items in a few unconnected pairs on every run: of
    the copper meeting at the anchor the ratsnest joins (two tracks sharing an end, a connector's front and
    back pads at one position) it names whichever its threads came to first (a 341-track board, five DRCs of
    one file: 1-9 of 182 pairs named otherwise each time, the count the same). The joint loop's congestion
    history and the repair loop's pad choice read those names and positions. Here each side of a pair is the
    item, among those of its net with an anchor at the pair's nearest anchors, first by description and
    position, and the pair's items are in that order too. `items`: pcbnew_io.copper_items of the board the
    report is of (None: the report is left as it is). A pair naming an item `items` does not hold as KiCad
    describes it (a zone, another KiCad) keeps KiCad's names."""
    if not items:
        return rep
    by_uuid = {it["uuid"]: it for it in items}
    at = {}
    for it in items:
        for a in it["anchors"]:
            at.setdefault((it["net"], tuple(a)), []).append(it)

    def rec(it):
        return dict(description=it["description"], pos=dict(x=it["pos"][0] / 1e6, y=it["pos"][1] / 1e6), uuid=it["uuid"])

    def first(cands):
        return min(cands, key=lambda c: (c["description"], tuple(c["pos"]), c["uuid"]))

    for u in rep.get("unconnected_items") or []:
        its = u.get("items") or []
        known = [by_uuid.get(i.get("uuid")) for i in its]
        if len(its) != 2 or any(k is None or k["description"] != i.get("description") for k, i in zip(known, its)):
            continue
        x, y = known
        _, ax, ay = min(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2, tuple(a), tuple(b)) for a in x["anchors"] for b in y["anchors"])
        cx, cy = first(at.get((x["net"], ax)) or [x]), first(at.get((y["net"], ay)) or [y])
        u["items"] = sorted((rec(cx), rec(cy)), key=lambda r: (r["description"], r["pos"]["x"], r["pos"]["y"], r["uuid"]))
    rep["unconnected_items"].sort(key=_content_key)
    return rep


def _content_key(v):
    """A violation's order by what it says, not by the UUIDs of the items it names."""
    return (v.get("type") or "", v.get("severity") or "", sorted((i.get("description") or "", str(i.get("pos"))) for i in v.get("items") or []))


def uncapped_unconnected(board, timeout=900):
    """pcbnew's unconnected count of `board` after a zone fill (no cap), None when it cannot run."""
    from kae.board.pcbnew_io import PcbnewError, kicad_python
    try:
        r = subprocess.run([*kicad_python(), "-c", UNCONNECTED_PY, str(board)], capture_output=True, text=True,
                           timeout=budget.wall_timeout(timeout), cwd=Path(board).parent, errors="replace")
        return int(json.loads(r.stdout.strip().splitlines()[-1])["unconnected"])
    except (PcbnewError, OSError, subprocess.TimeoutExpired, ValueError, IndexError, KeyError):
        return None


def errors(report, ignore=ENV_DEPENDENT):
    """Error-level violations (as kaebench counts them), unconnected items aside."""
    return [v for v in report.get("violations", []) if v.get("severity") == "error" and v.get("type") not in ignore]


def summary(report):
    errs = errors(report)
    by = {}
    for v in errs:
        by[v["type"]] = by.get(v["type"], 0) + 1
    n = report.get("unconnected_count")
    return dict(errors=len(errs), unconnected=n if n is not None else len(report.get("unconnected_items", [])), by_type=by)


def excess(summary, base):
    """Error-level violations of `summary` beyond `base` ({type: count}, the board's own errors
    before routing), per type: what routing added. 0 for a board whose only errors it had already."""
    base = base or {}
    return sum(max(0, n - base.get(t, 0)) for t, n in (summary.get("by_type") or {}).items())


def promote_severities(staged_board, checks):
    """Set `checks` to 'error' in the staged board's .kicad_pro (a copy: stage_board), so KiCad's
    DRC reports what kae's fixed placement profile treats as errors. Returns the checks changed.
    Custom .kicad_dru rules with their own severity still apply (a designer's per-object waiver)."""
    pro = Path(staged_board).with_suffix(".kicad_pro")
    if not pro.exists():
        return []           # no project: KiCad's defaults, all of these are errors already
    try:
        d = json.loads(pro.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return []
    rs = d.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})
    changed = [c for c in checks if rs.get(c, "error") != "error"]
    if changed:
        for c in changed:
            rs[c] = "error"
        pro.write_text(json.dumps(d, indent=2))
    return changed


def stage_board(src_board, project_board, dest_dir):
    """Copy `src_board` into `dest_dir` as board.kicad_pcb with the project files of
    `project_board` (its .kicad_pro and .kicad_dru) beside it; returns the staged path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / "board.kicad_pcb"
    shutil.copy2(src_board, dst)
    for ext in (".kicad_pro", ".kicad_dru"):
        src = Path(project_board).with_suffix(ext)
        tgt = dest_dir / f"board{ext}"
        if src.exists():
            shutil.copy2(src, tgt)
        elif tgt.exists():
            tgt.unlink()
    return dst
