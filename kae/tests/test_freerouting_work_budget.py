# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route.freerouting under counted budgets: a build with autorouter.max_work gets the budget as its
own work budget (a counted stop) and the optimizer a pass cap; a run is charged by the work units it
logs (only when the build takes the budget), its start-up and its optimizer passes; an older build keeps the pass cap."""
from pathlib import Path

import pytest

from kae import budget
from kae.route import freerouting as F

DSN = "(pcb t (network (net A (pins U1-1 U2-1)) (net B (pins U1-2 U2-2 U3-1))))\n"
LOG = "\n".join([
    "2026-11-11 19:00:00.000 INFO   [j] Auto-routing stage started on board 'h' with baseline score 1.00 for 3 unrouted items.",
    "2026-11-11 19:00:01.000 INFO   [j] Auto-routing pass #1: 9000 search steps and 12000 work units so far in the pass loop.",
    "2026-11-11 19:00:01.001 INFO   [j] Auto-routing pass #1 on board 'h' was completed in 1.00 seconds with score 5.0 (1 unrouted and 0 violations), using 1 CPU seconds and the job allocated 0.10 GB of memory so far.",
    "2026-11-11 19:00:02.000 INFO   [j] Auto-routing pass #2: 15000 search steps and 20000 work units so far in the pass loop.",
    "2026-11-11 19:00:02.001 INFO   [j] Auto-routing pass #2 on board 'h' was completed in 1.00 seconds with score 6.0 (1 unrouted and 0 violations), using 2 CPU seconds and the job allocated 0.20 GB of memory so far.",
])


@pytest.fixture
def fake(monkeypatch, tmp_path):
    calls = []

    def _route(dsn, ses, workdir, **kw):
        calls.append(kw)
        return F.Run(rc=0, ses=None, log=LOG, seconds=2.0, report={})
    monkeypatch.setattr(F, "_route", _route)
    d = tmp_path / "board.dsn"
    d.write_text(DSN)
    return calls, d


def test_work_mode_hands_freerouting_its_work_budget_and_charges_what_it_logged(fake, monkeypatch):
    calls, dsn = fake
    monkeypatch.setattr(F, "has_work_budget", lambda cmd=None: True)
    c = budget.set_mode("work", rates={"poll": 0.0})
    F.route(dsn, dsn.with_suffix(".ses"), dsn.parent, budget_s=100.0)
    s = calls[0]["settings"]
    r = c.rates
    g = F.work_scale(5)                                  # the board has 5 pins
    want = int((100.0 - r["fr_run"] - r["fr_dsn_kb"] * dsn.stat().st_size / 1e3) / (r["fr_work"] * g))
    assert s["autorouter.max_work"] == str(want)
    # a pass's weights in this board's search steps: FR_PASS_S per pin over the step's nominal seconds
    assert float(s["autorouter.work_pass_weight"]) == pytest.approx(F.FR_PASS_S / (r["fr_work"] * g), rel=1e-5)
    assert float(s["autorouter.work_unrouted_weight"]) == pytest.approx(F.FR_UNROUTED_S / (r["fr_work"] * g), rel=1e-5)
    assert s["optimizer.max_passes"] == str(F.FR_OPT_MAX_PASSES)
    assert calls[0]["passes"] == 0                       # no pass cap: the work budget binds
    assert c.units["fr_work"] == pytest.approx(20000 * g) and c.units["fr_run"] == 1 and "fr_pass_pin2" not in c.units
    budget.set_mode("time")


def test_an_older_build_keeps_the_pass_cap(fake, monkeypatch):
    calls, dsn = fake
    monkeypatch.setattr(F, "has_work_budget", lambda cmd=None: False)
    c = budget.set_mode("work", rates={"poll": 0.0})
    F.route(dsn, dsn.with_suffix(".ses"), dsn.parent, budget_s=100.0)
    assert "autorouter.max_work" not in calls[0]["settings"]
    assert calls[0]["passes"] >= 1
    # charged as an old build even if it logs work units (KAE_FR_WORK_BUDGET=0 on a new build must
    # leave every count as d137fd1 gives it)
    assert c.units["fr_pass_pin2"] > 0 and "fr_work" not in c.units
    budget.set_mode("time")


def test_time_mode_only_counts(fake, monkeypatch):
    calls, dsn = fake
    monkeypatch.setattr(F, "has_work_budget", lambda cmd=None: True)
    c = budget.set_mode("time")
    F.route(dsn, dsn.with_suffix(".ses"), dsn.parent, budget_s=100.0)
    assert "autorouter.max_work" not in (calls[0]["settings"] or {})
    assert c.units["fr_work"] == pytest.approx(20000 * F.work_scale(5))


def test_work_scale_grows_with_the_board():
    assert F.work_scale(F.FR_SCALE_REF_PINS) == pytest.approx(1.0)
    assert F.work_scale(148) < 0.25 < 2.0 < F.work_scale(821) < F.work_scale(1184)
    assert F.work_scale(1) == F.FR_SCALE_MIN and F.work_scale(10 ** 6) == F.FR_SCALE_MAX


def test_a_job_with_several_pass_loops_is_charged_for_all():
    # 9cf145d counted each pass loop (the fallbacks) from zero; abefc74 counts the job
    assert F.job_work(["100", "250", "40", "90"]) == 340
    assert F.job_work(["100", "250", "340"]) == 340
