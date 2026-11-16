# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Freerouting fallback ladder, run last (opts ladder_late; experimental, off by default).

The fork's no-fanout ladder (`autorouter.no_fanout_fallback_strategies`: re-route at cheaper or
dearer vias, continue after ripping other nets near open pins, drop a neck) runs inside every
Freerouting call when the pass loop stagnates. fr-ladder-ab (2026-11-16, seed-paired attempts) found
that it costs opens: it takes the attempt's time from the repair rounds and the last mile
(repair calls 79 -> 41 over the fired attempts; rk3328 50 -> 107 with the same Freerouting board),
and the board it picks by Freerouting's count gains nothing in KiCad's count.

With ladder_late the ladder is off in every Freerouting call of the attempt, and the attempt ends
with one ladder pass instead: after the repair rounds and the last mile, on the board they kept,
in a time box of at most ladder_share of the attempt (reserved from the repair rounds; never in an
attempt shorter than ladder_min_s), with the fork's `autorouter.fallback_only` (no pass loop
first: the board is already routed and repaired). Its board replaces the kept one only when
KiCad's DRC ranks it better with no more errors (repair's rule), so the judge is KiCad's count,
not Freerouting's.
"""
import shutil
from pathlib import Path

from kae.board import pcbnew_io
from kae.budget import now as clock_now

from . import drc, freerouting, specctra, translate

STRATEGIES = "vias-cheaper,vias-dearer,continue-ripped,no-neck"
CHECK_SHARE = 0.3       # of the ladder's time box: kept for the session import and one KiCad DRC
CHECK_MIN_S = 30.0


def window(opts, time_s):
    """Seconds reserved for the ladder pass in an attempt of `time_s` seconds (0: none)."""
    if not opts.get("ladder_late") or time_s < float(opts.get("ladder_min_s") or 150.0):
        return 0.0
    return float(opts.get("ladder_share") or 0.25) * time_s


def off_in_calls(opts):
    """Router settings that turn the in-call ladder off (every Freerouting call but the ladder pass)."""
    return {"autorouter.no_fanout_fallback_strategies": "none"} if opts.get("ladder_late") else {}


def run(input_path, output_path, wd, plan, info, opts, best, deadline, log=print):
    """One ladder pass on `output_path` (the board the repair rounds and last mile kept, whose KiCad
    summary is `best`), replacing it in place when KiCad ranks the result better. Returns a report;
    "_report" is the DRC report of the board kept when the ladder's board was kept."""
    from . import repair
    from .bridge import import_session, plane_policy, router_settings
    t0 = clock_now()
    rdir = Path(wd) / "ladder"
    if rdir.exists():
        shutil.rmtree(rdir)
    rdir.mkdir(parents=True)
    fixed = set(opts.get("fixed_uuids") or [])
    rec = dict(before=dict(errors=best["errors"], unconnected=best["unconnected"]), kept=False)

    def left():
        return deadline - clock_now()

    staged = drc.stage_board(output_path, input_path, rdir / "board")
    dsn_k = rdir / "kicad.dsn"
    pcbnew_io.export_dsn(staged, dsn_k, probes=False)
    tree = specctra.read(dsn_k)
    plan.plane_policy = plane_policy(opts, free_round_with_open=True)
    plan.plane_cost = opts.get("plane_cost")
    plan.outer_surcharge = opts.get("outer_surcharge")
    plan.pad_shapes = opts.get("pad_shapes") or "kicad"
    translate.apply(tree, plan, info)
    translate.permute(tree, repair.round_seed(opts.get("seed"), 97))
    dsn = rdir / "board.dsn"
    specctra.write(tree, dsn)
    translate.write_rules(plan, dsn)
    settings = router_settings(plan, opts, repair=True)
    settings["autorouter.fallback_only"] = "true"
    settings["autorouter.no_fanout_fallback_strategies"] = opts.get("ladder_strategies") or STRATEGIES
    check = max(CHECK_MIN_S, CHECK_SHARE * left())
    budget = max(15.0, left() - check)
    grace = opts.get("router_grace", freerouting.GRACE_S)
    run_ = freerouting.route(dsn, rdir / "board.ses", rdir, passes=opts.get("passes") or 0, settings=settings,
                             budget_s=budget, hard_s=max(budget, min(budget + grace, left() - 15)),
                             log_path=rdir / "freerouting.log")
    rec["router"] = dict(seconds=run_.seconds, state=run_.report.get("final_state"), killed=run_.timed_out,
                         **({"telemetry": run_.report["telemetry"]} if run_.report.get("telemetry") else {}))
    if run_.ses is None:
        rec["stopped"] = "no session"
        return _done(rec, t0, log)
    ses = specctra.read(run_.ses)
    translate.fix_session(ses, plan)
    ses_k = rdir / "board_kicad.ses"
    specctra.write(ses, ses_k)
    cand = rdir / "cand.kicad_pcb"
    imp = import_session(staged, ses_k, cand)
    if any(h["severity"] == "block" for h in imp["hazards"]):
        rec["stopped"] = "import put copper on the wrong nets"
        return _done(rec, t0, log)
    pcbnew_io.edit_routing(cand, cand, unlock_all=True, keep_locked=fixed)
    if left() < 10:
        rec["stopped"] = "time"
        return _done(rec, t0, log)
    try:
        rep = drc.run(drc.stage_board(cand, input_path, rdir / "drc"), rdir / "drc" / "drc.json",
                      timeout=max(10, left() - 5))
    except drc.DrcError as e:
        rec["stopped"] = f"drc: {e}"
        return _done(rec, t0, log)
    s_ = drc.summary(rep)
    rec["after"] = s_
    no_worse = s_["errors"] <= best["errors"] or repair.errors_no_worse(
        s_, best, repair.input_errors(input_path, wd, deadline))
    rec["kept"] = repair._key(s_) > repair._key(best) and no_worse
    if rec["kept"]:
        shutil.copy2(cand, output_path)
        rec["_report"] = rep
        rec["hazards"] = imp["hazards"]
    return _done(rec, t0, log)


def _done(rec, t0, log):
    rec["seconds"] = round(clock_now() - t0, 1)
    a = rec.get("after") or {}
    log(f"ladder: {rec['before']['unconnected']} -> {a.get('unconnected', '-')} unconnected, "
        f"{rec['before']['errors']} -> {a.get('errors', '-')} errors "
        f"({'kept' if rec['kept'] else 'discarded'}{', ' + rec['stopped'] if rec.get('stopped') else ''}, "
        f"{rec['seconds']} s)")
    return rec
