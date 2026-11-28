# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a design through the brief-to-board stages in order, and refuse a stage while an earlier gate is unmet.

    pipeline.py DESIGN_DIR status                 # every stage's gate and the next thing to do
    pipeline.py DESIGN_DIR build|board|preflight|size|layout|physics|warnings|review|fab [--seed N] [--time S]

Run from the repo root in the haslam venv with ~/.cache/haslambench/env.sh sourced (KICAD10_*_DIR set). DESIGN_DIR is
tools/research/llm-design/designs/<slug>. State and outputs: haslam-work/<slug>/pipeline/ (status.json per stage).

The stage table in docs/topics/workflow/brief-to-board.md is prose: an agent decides what "done" means, and in the
obd-solar run it skipped reading the rules, the DRC warnings, the physics, the seeds and the review (FRICTION.md
#39). Here each stage writes PASS/FAIL with its evidence, a stage runs only when every earlier gate passed and is
newer than the design's sources, and `fab` is the last stage, so fabrication files exist only for a board that
passed everything.

| stage | does | gate |
|---|---|---|
| build | haslamsynth jlc + build | exit 0 (0 unwaived errors, ERC, parity) |
| board | sch_to_board.py at the chosen outline (size stage's best, else board.json) | board written |
| preflight | preflight.py --probe | 0 FAIL (incl. board.fab: the fab profile) |
| size | size_search.py (resumable; may need several calls) | a passing outline exists |
| layout | layout.sh, HASLAM_EVAL=0, one seed per call | >= SEEDS seeds routed; best passes DRC (0/0) and width_check |
| physics | haslam.excite.evaluate + haslam.intent status on the best seed | evaluation complete, no hard term violated |
| warnings | DRC warnings of the best seed by type, plus tombstone_risk (tombstone_check.py) | every type listed in DESIGN_DIR/drc_warnings.json with a reason |
| review | an independent review | DESIGN_DIR/REVIEW.md newer than design.py and parts.py |
| fab | fab_outputs.py (no --allow-open) | fab-report gate pass; no blocking question open in report.md |
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
STAGES = ["build", "board", "preflight", "size", "layout", "physics", "warnings", "review", "fab"]
SEEDS = int(os.environ.get("HASLAM_PIPELINE_SEEDS", "3"))


class Ctx:
    def __init__(self, design_dir):
        self.dd = Path(design_dir).resolve()
        self.slug = self.dd.name
        self.out = self.dd / "out"
        self.work = REPO / "haslam-work" / self.slug / "pipeline"
        self.work.mkdir(parents=True, exist_ok=True)
        self.status_p = self.work / "status.json"
        self.status = json.loads(self.status_p.read_text()) if self.status_p.exists() else {}

    def save(self):
        self.status_p.write_text(json.dumps(self.status, indent=1))

    provisional = False

    def record(self, stage, ok, detail, **extra):
        self.status[stage] = {"ok": bool(ok), "detail": detail, "at": time.time(), **extra}
        if self.provisional:
            self.status[stage]["provisional"] = True
            detail = f"[provisional] {detail}"
        self.save()
        print(f"{stage}: {'PASS' if ok else 'FAIL'} {detail}")
        return 0 if ok else 1

    def sources_mtime(self):
        files = [self.dd / "design.py", self.dd / "parts.py", self.dd / "board.json"]
        files += list((self.dd / "footprints").rglob("*")) if (self.dd / "footprints").exists() else []
        return max(f.stat().st_mtime for f in files if f.exists())

    def gate_ok(self, stage):
        """Passed, newer than the sources, and not run past an unmet gate (--provisional)."""
        s = self.status.get(stage)
        return bool(s and s["ok"] and not s.get("provisional") and s["at"] >= self.sources_mtime())


def sh(cmd, log=None, env=None, cwd=None):
    with (open(log, "w") if log else open(os.devnull, "w")) as f:
        r = subprocess.run(cmd, stdout=f if log else subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           env=env or os.environ, cwd=cwd or REPO)
    return r.returncode, (Path(log).read_text() if log else r.stdout)


def kpy():
    return (os.environ.get("HASLAM_KICAD_WRAP", "") + " python3").split()


def outline(c):
    s = c.status.get("size", {})
    if s.get("ok") and s.get("best"):
        return s["best"]
    return json.loads((c.dd / "board.json").read_text())["outline"]


# ---------------------------------------------------------------------------------------------------- stages
def st_build(c, a):
    synth = REPO / "tools/research/llm-design/synth/.venv/bin/haslamsynth"
    rc, txt = sh([str(synth), "jlc", str(c.dd / "design.py")], c.work / "jlc.log")
    rc, txt = sh([str(synth), "build", str(c.dd / "design.py"), "-v"], c.work / "build.log")
    last = txt.strip().splitlines()[-1] if txt.strip() else ""
    return c.record("build", rc == 0, last)


def st_board(c, a):
    W, H = outline(c)
    rc, txt = sh(kpy() + [str(HERE / "sch_to_board.py"), str(c.out), str(c.dd / "board.json"), "--outline", str(W), str(H)],
                 c.work / "board.log")
    return c.record("board", rc == 0, f"{W} x {H} mm" if rc == 0 else txt[-300:], outline=[W, H])


def st_preflight(c, a):
    rc, txt = sh([sys.executable, str(HERE / "preflight.py"), str(c.out / f"{c.slug}.kicad_pcb"), "--probe"],
                 c.work / "preflight.log")
    fails = [ln for ln in txt.splitlines() if ln.startswith(("FAIL", "WARN"))]
    return c.record("preflight", rc == 0, txt.strip().splitlines()[-1] if txt.strip() else "", lines=fails)


def st_size(c, a):
    cmd = [sys.executable, str(HERE / "size_search.py"), str(c.out), str(c.dd / "board.json"), str(c.work / "size"),
           "--max-attempts", str(a.attempts)] + (["--time", str(a.time)] if a.time else [])
    rc, txt = sh(cmd, c.work / "size.log")
    st = json.loads((c.work / "size" / "state.json").read_text()) if (c.work / "size" / "state.json").exists() else {}
    done = st.get("attempts", [])
    finished = bool(done) and any(x["ok"] for x in done) and not done[-1]["ok"]
    not_size = bool(done) and done[-1].get("not_size")
    ok = bool(st.get("best"))
    why = (" (stopped: every connection routed but tracks too narrow; not a board-size problem, see width gate)"
           if not_size and not ok else "" if finished or ok else " (search not finished: run `size` again)")
    return c.record("size", ok, f"best {st.get('best')} after {len(done)} attempt(s){why}",
                    best=st.get("best"), finished=finished, not_size=not_size)


def _seed_runs(c):
    return sorted(p for p in (c.work / "layout").glob("s*") if (p / "eval").exists())


def _gates(run):
    sys.path.insert(0, str(HERE))
    from size_search import gates
    return gates(run)


def st_layout(c, a):
    if not c.gate_ok("board") or c.status["board"].get("outline") != list(outline(c)):
        return c.record("layout", False, "board stage is stale for the chosen outline: run `board` (and `preflight`) again")
    if not a.collect:                                   # --collect: only re-judge the seeds already routed
        seed = a.seed or (len(_seed_runs(c)) + 1)
        run = c.work / "layout" / f"s{seed}"
        env = dict(os.environ, HASLAM_EVAL="0", **({"HASLAM_TIME": str(a.time)} if a.time else {}))
        sh(["bash", str(HERE / "layout.sh"), str(c.out / f"{c.slug}.kicad_pcb"), str(run), str(seed)],
           c.work / f"layout-s{seed}.log", env=env)
    runs = _seed_runs(c)
    res = {r.name: {k: v[1] for k, v in _gates(r).items()} for r in runs}
    passing = [r for r in runs if all(ok for ok, _ in _gates(r).values())]
    best = passing[0] if passing else None
    ok = len(runs) >= SEEDS and best is not None
    return c.record("layout", ok, f"{len(runs)}/{SEEDS} seeds, {len(passing)} passing DRC and width"
                    + ("" if len(runs) >= SEEDS else f": run `layout` {SEEDS - len(runs)} more time(s)"),
                    seeds=res, best=str(best) if best else None)


def _best(c):
    """The best passing seed; provisionally (no passing seed) the first routed one."""
    best = c.status.get("layout", {}).get("best")
    if not best and c.provisional:
        runs = _seed_runs(c)
        best = str(runs[0]) if runs else None
    return best


def st_physics(c, a):
    best = _best(c)
    if not best:
        return c.record("physics", False, "no passing seed")
    run = Path(best)
    board = run / f"{c.slug}.kicad_pcb"
    intent = run / f"{c.slug}.haslam_intent.json"
    env = dict(os.environ, PYTHONPATH=str(REPO / "haslam/src"))
    py = str(REPO / "haslam/.venv/bin/python")
    # 0.125 mm cell windows: the default 0.0625 mm needed > 8.5 GB on obd-solar's spread U301 input loop (FRICTION #52)
    rc, _ = sh([py, "-u", "-W", "ignore", "-m", "haslam.excite.evaluate", str(board), "--intent", str(intent),
                "--cell-pitch", os.environ.get("HASLAM_CELL_PITCH", "0.125"), "-o", str(run / "eval/excite.json")],
               c.work / "excite.log", env=env)
    if rc != 0:
        # a negative code is a signal: -9 is SIGKILL, which on a container is usually the OOM killer (the obd-solar
        # evaluation was killed at 13 GB resident on a 15 GB host, FRICTION.md #52)
        why = f"killed by signal {-rc} (SIGKILL: check `dmesg` for the OOM killer)" if rc < 0 else f"exit {rc}"
        return c.record("physics", False, f"haslam.excite.evaluate {why}; see {c.work / 'excite.log'}")
    sh([py, "-u", "-W", "ignore", "-m", "haslam.intent", "status", str(run / "eval/excite.json"), "--intent",
        str(intent), "--detailed", "-o", str(run / "eval/status.json")], c.work / "status.log", env=env)
    sp = run / "eval/status.json"
    if not sp.exists():
        return c.record("physics", False, "no eval/status.json (see excite.log)")
    st = json.loads(sp.read_text())
    # haslam.intent status: tiers None when nothing could be scored (why_incomplete); not_computed lists copper the
    # solver could not compute (its terms are reported, not priced); tiers.hard counts hard violations
    tiers = st.get("tiers")
    complete = st.get("complete", tiers is not None and not st.get("not_computed"))
    hard = (tiers or {}).get("hard", 0)
    return c.record("physics", bool(complete) and not hard,
                    f"complete {bool(complete)}"
                    + (f", why_incomplete {st.get('why_incomplete') or st.get('not_computed')}" if not complete else "")
                    + (f", {hard:g} hard violation(s)" if hard else "")
                    + (f", limits {tiers['limit']:.4g} + costs {tiers['cost']:.4g} {st.get('currency', '')}" if tiers else ""))


def st_warnings(c, a):
    best = _best(c)
    if not best:
        return c.record("warnings", False, "no passing seed")
    d = json.loads((Path(best) / "eval/drc.json").read_text())
    ack_p = c.dd / "drc_warnings.json"
    ack = json.loads(ack_p.read_text()) if ack_p.exists() else {}
    ts = tombstones(Path(best), c.slug)
    if ts is None:
        return c.record("warnings", False, "tombstone check did not run (tombstone_check.py, KiCad's Python)")
    for w in ts["warnings"]:
        print(f"  tombstone_risk {w['ref']} ({w['size']}): {w['why']}")
    table = warning_table(d, ack, {"tombstone_risk": len(ts["warnings"])})
    for row in table:
        print(f"  {row['type']:24} {row['count']:4}  "
              + (f"acknowledged: {row['reason'][:110]}" if row["reason"] else "UNACKNOWLEDGED (needs a reason in "
                 "drc_warnings.json, or a fix)"))
    missing = [r["type"] for r in table if not r["reason"]]
    n = sum(r["count"] for r in table)
    return c.record("warnings", not missing,
                    f"{len(table)} warning types ({n} warnings); unacknowledged: "
                    + ", ".join(f"{r['type']} x{r['count']}" for r in table if not r["reason"]) if missing
                    else f"{len(table)} warning types ({n} warnings), each with a reason in drc_warnings.json",
                    types=table)


def tombstones(run, slug):
    """run/eval/tombstone.json (layout.sh writes it; run here when missing): small two-terminal parts with asymmetric
    pad copper (FRICTION.md #68). None when the check cannot run."""
    p = run / "eval" / "tombstone.json"
    if not p.exists():
        sh(kpy() + [str(HERE / "tombstone_check.py"), str(run / f"{slug}.kicad_pcb"), "--json", str(p)])
    return json.loads(p.read_text()) if p.exists() else None


def warning_table(drc, ack, extra=None):
    """Each DRC warning type of a report, plus `extra` {type: count} from the pipeline's own checks
    (tombstone_risk), with its count and the drc_warnings.json reason it matched ('' = none), most frequent first
    (FRICTION.md #38: a gate that counted errors only let 349 warnings through unread)."""
    counts = {t: n for t, n in (extra or {}).items() if n}
    for v in drc.get("violations", []):
        if v.get("severity") == "warning":
            counts[v["type"]] = counts.get(v["type"], 0) + 1
    return [dict(type=t, count=n, reason=str(ack.get(t, "")).strip())
            for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def st_review(c, a):
    rv = c.dd / "REVIEW.md"
    ok = rv.exists() and rv.stat().st_mtime >= max((c.dd / f).stat().st_mtime for f in ("design.py", "parts.py"))
    return c.record("review", ok, "REVIEW.md is current" if ok else
                    "write REVIEW.md: an independent review of design.py/parts.py (newer than both), following "
                    "docs/topics/workflow/design-review-checklist.md")


def st_fab(c, a):
    rep = (c.out / "report.md").read_text() if (c.out / "report.md").exists() else ""
    blocking = "BLOCKING" in rep and "not ready for fabrication" in rep.lower()
    best = Path(c.status["layout"]["best"])
    fab = c.work / "fab"
    if fab.exists():
        shutil.rmtree(fab)
    rc, txt = sh([sys.executable, str(HERE / "fab_outputs.py"), str(best / f"{c.slug}.kicad_pcb"), str(fab)],
                 c.work / "fab.log")
    ok = rc == 0 and (fab / "fab-report.json").exists() and not blocking
    return c.record("fab", ok, ("blocking questions open in report.md; " if blocking else "") + txt.strip()[-300:])


RUN = {"build": st_build, "board": st_board, "preflight": st_preflight, "size": st_size, "layout": st_layout,
       "physics": st_physics, "warnings": st_warnings, "review": st_review, "fab": st_fab}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("design_dir")
    ap.add_argument("stage", choices=["status"] + STAGES)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--time", type=int, default=0)
    ap.add_argument("--attempts", type=int, default=2, help="size stage: attempts per call")
    ap.add_argument("--collect", action="store_true", help="layout: judge the seeds already routed, route none")
    ap.add_argument("--provisional", action="store_true",
                    help="run past unmet gates to explore later stages; results are marked provisional, never count "
                         "as passed, and fab refuses to run on them")
    a = ap.parse_args(argv)
    c = Ctx(a.design_dir)
    if a.stage == "status":
        nxt = None
        for s in STAGES:
            st = c.status.get(s)
            ok = c.gate_ok(s)
            mark = "PASS" if ok else ("PROV" if st and st.get("provisional") else
                                      ("STALE" if st and st["ok"] else ("FAIL" if st else "----")))
            print(f"{mark:5} {s:9} {st['detail'] if st else ''}")
            if not ok and nxt is None:
                nxt = s
        print(f"next: {nxt}" if nxt else "all gates pass")
        return 0
    i = STAGES.index(a.stage)
    unmet = [s for s in STAGES[:i] if not c.gate_ok(s)]
    if unmet and (not a.provisional or a.stage == "fab"):
        print(f"refused: {a.stage} needs {', '.join(unmet)} to pass first (pipeline.py {c.dd} status)"
              + ("; fab never runs provisionally (use fab_outputs.py --allow-open for a review copy)"
                 if a.provisional and a.stage == "fab" else ""))
        return 2
    if unmet:
        c.provisional = True
        print(f"provisional: {a.stage} runs although {', '.join(unmet)} did not pass; its result will not count")
    return RUN[a.stage](c, a)


if __name__ == "__main__":
    sys.exit(main())
