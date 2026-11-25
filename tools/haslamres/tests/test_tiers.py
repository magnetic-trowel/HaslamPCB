# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamres.py's tier guard: the CPU estimate from board history and the sprint tier's limits (stdlib only)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import haslamres as K  # noqa: E402
from test_suites import make_index  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store whose index knows cheap (0.1 CPU-h per run), dear (2 CPU-h) and, by size only, new."""
    make_index(tmp_path / "index.sqlite", [("cheap", "A", 0, "e", 360, 0, True), ("dear", "A", 0, "e", 7200, 0, True)])
    c = sqlite3.connect(tmp_path / "index.sqlite")
    c.executemany("INSERT INTO boards VALUES(?,?,?,?,?,?)", [("cheap", 2, 10, 5, "", ""), ("dear", 4, 300, 90, "", ""),
                                                             ("new", 4, 310, 90, "", "")])
    c.commit()
    c.close()
    monkeypatch.setattr(K, "STORE", tmp_path)
    return tmp_path


def test_sprint_passes_a_small_campaign_and_prints_its_estimate(store, capsys):
    K.tier_guard("sprint", dict(cheap=8), "experiment x")
    assert "experiment x: estimated 0.8 CPU-h from board history (8 method-runs on 1 boards, 1 with history" in capsys.readouterr().out


def test_sprint_refuses_over_40_cpu_h_in_two_lines(store):
    with pytest.raises(SystemExit) as r:
        K.tier_guard("sprint", dict(cheap=401), "experiment x")
    msg = str(r.value).split("\n")
    assert len(msg) == 2 and "this is 40.1 CPU-h." in msg[0] and "boards are over" not in msg[0]
    assert msg[1].startswith("Do this: ") and "sprint-frontier.txt" in msg[1] and "--tier ladder" in msg[1]


def test_sprint_refuses_a_board_whose_history_is_over_half_a_cpu_hour(store):
    with pytest.raises(SystemExit, match=r"this is 2.1 CPU-h and 1 boards are over \(dear 2.0\)"):
        K.tier_guard("sprint", dict(cheap=1, dear=1), "experiment x")
    K.tier_guard("sprint", dict(cheap=1, dear=0), "submit x")   # nothing left to run on it
    K.tier_guard("sprint", dict(new=1), "experiment x")         # priced by its size (2 CPU-h), but it has no history to be over


def test_ladder_and_canary_lift_the_limits(store, capsys):
    for tier in ("ladder", "canary"):
        K.tier_guard(tier, dict(cheap=1000, dear=50), "experiment x")
    assert "estimated 200.0 CPU-h" in capsys.readouterr().out


def test_no_index_no_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(K, "STORE", tmp_path)
    K.tier_guard("sprint", dict(dear=100), "experiment x")
    assert "no CPU estimate" in capsys.readouterr().out


def _create(monkeypatch, store, **kw):
    monkeypatch.setattr(K, "exp_dir", lambda n: store / "experiments" / n)
    monkeypatch.setattr(K, "main_repo", lambda: str(store))
    monkeypatch.setattr(K, "git", lambda repo, *a: a[-1])
    monkeypatch.setattr(K, "on_remote", lambda repo, c: True)
    monkeypatch.setattr(K, "ensure_harness", lambda *a, **k: None)
    monkeypatch.setattr(K, "ensure_method_code", lambda m: None)
    monkeypatch.setattr(K, "harness_task_spec", lambda c: 11)
    monkeypatch.setattr(K, "kicad_version", lambda: "10.0.7")
    monkeypatch.setattr(K, "evaluators_for", lambda *a: {})
    monkeypatch.setattr(K, "CORPUS", store)
    (store / "manifest.jsonl").write_text("")
    recipe = lambda t: dict(runner=dict(type=t))  # noqa: E731
    meth = dict(m=dict(id="m" * 12, name="m", code={}, recipe=recipe("command")),
                human=dict(id="h" * 12, name="human", code={}, recipe=recipe("reference")))
    monkeypatch.setattr(K, "find_method", lambda k: meth[k])
    a = dict(name="x", method=["m", "human"], harness="h", haslam="h", boards="cheap,dear", attempts=2, description="",
             reuse_runs=False, env=None, tier="sprint")
    a.update(kw)
    K.cmd_exp_create(type("A", (), a))
    return json.loads((store / "experiments" / a["name"] / "experiment.json").read_text())


def test_exp_create_checks_the_tier_and_records_it(monkeypatch, store, capsys):
    with pytest.raises(SystemExit, match="refused: tier sprint allows 40 CPU-h in all and 0.5 CPU-h per method-run"):
        _create(monkeypatch, store)
    assert "estimated 4.2 CPU-h from board history (4 method-runs on 2 boards" in capsys.readouterr().out   # the human reference is not counted
    assert not (store / "experiments").exists()
    assert _create(monkeypatch, store, boards="cheap")["tier"] == "sprint"
    assert _create(monkeypatch, store, name="y", tier="ladder")["tier"] == "ladder"


def test_exp_submit_checks_what_is_left_to_run_and_can_change_the_tier(monkeypatch, store):
    e = _create(monkeypatch, store, tier="ladder")
    recipe = dict(runner=dict(type="command"), params={})
    monkeypatch.setattr(K, "find_method", lambda k: dict(id=k, name=k, recipe=recipe))
    monkeypatch.setattr(K, "corpus_rows", lambda: dict(cheap=dict(path="p"), dear=dict(path="p")))
    left = dict(cheap=[("m" * 12, 0)], dear=[("m" * 12, 0), ("m" * 12, 1)])
    monkeypatch.setattr(K, "missing", lambda e, bid: left[bid])
    monkeypatch.setattr(K, "prepare_failed", lambda e, bid: False)
    monkeypatch.setattr(K, "code_dir", lambda c: store / "code")
    exp = store / "experiments" / "x" / "experiment.json"
    exp.write_text(json.dumps({k: v for k, v in e.items() if k != "tier"}))   # an experiment from before the tiers
    a = dict(name="x", only=None, limit=None, redo=False, dry_run=True, tier=None)
    with pytest.raises(SystemExit, match=r"1 boards are over \(dear 2.0\)"):
        K.cmd_exp_submit(type("A", (), a))
    left["dear"] = []                                                        # its runs exist: only the cheap board is left
    K.cmd_exp_submit(type("A", (), a))
    left["dear"] = [("m" * 12, 1)]
    monkeypatch.setattr(K.subprocess, "run", lambda *a, **k: None)
    K.cmd_exp_submit(type("A", (), dict(a, tier="canary", dry_run=False)))
    assert json.loads(exp.read_text())["tier"] == "canary"
    K.cmd_exp_submit(type("A", (), dict(a, prio=5)))                         # the queue priority goes into each job
    jobs = [json.loads(ln) for f in sorted(exp.parent.glob("jobs-*.jsonl")) for ln in f.read_text().splitlines()]
    assert jobs and jobs[-1]["prio"] == 5


def test_exp_create_with_reuse_runs_counts_only_the_runs_to_make(monkeypatch, store, capsys):
    stored = [(None, dict(method_id="m" * 12, attempt=0)), (None, dict(method_id="other", attempt=1))]
    monkeypatch.setattr(K, "board_runs", lambda b: stored)
    monkeypatch.setattr(K, "board_dir", lambda b: store)
    (store / "experiments" / "x").mkdir(parents=True)                     # the folder with its PLAN.md is there already
    _create(monkeypatch, store, boards="cheap", reuse_runs=True)
    assert "(1 method-runs on 1 boards" in capsys.readouterr().out      # attempt 0 is stored; attempt 1 is to make


def _sprint(monkeypatch, store, plan=True, **kw):
    """cmd_sprint against a stored control of two methods, the store's writers recorded instead of run."""
    calls = {}
    tag = "t" * 40
    ctl = dict(br=dict(id="br", name="control bridge", recipe=dict(kind="route", params=dict(timeout_s="3600"), environment=dict(kicad_threads=2),
                                                                  runner=dict(template="cp numba-default-ttttttt numba; haslam route"))),
               st=dict(id="st", name="control staged", recipe=dict(kind="joint-fixed", params={}, environment=dict(kicad_threads=2),
                                                                  runner=dict(template="haslam joint"))))
    monkeypatch.setattr(K, "exp_dir", lambda n: store / "experiments" / n)
    monkeypatch.setattr(K, "load_exp", lambda n: dict(name=n, attempts=2, harness=dict(commit=tag), methods=[dict(id="br"), dict(id="st")]))
    monkeypatch.setattr(K, "find_method", lambda k: ctl[k])
    monkeypatch.setattr(K, "main_repo", lambda: "/repo")
    monkeypatch.setattr(K, "git", lambda repo, *a: tag if a[-1].startswith("TAG") else "c" * 40)
    monkeypatch.setattr(K, "cmd_method_add", lambda a: calls.setdefault("method", a) and "new")
    monkeypatch.setattr(K, "cmd_exp_create", lambda a: calls.setdefault("create", a))
    monkeypatch.setattr(K, "cmd_exp_submit", lambda a: calls.setdefault("submit", a))
    if plan:
        (store / "experiments" / "x").mkdir(parents=True, exist_ok=True)
        (store / "experiments" / "x" / "PLAN.md").write_text("plan\n")
    a = dict(name="x", base="bridge", commit="abc", set=None, control="control-w47", dry_run=False)
    a.update(kw)
    K.cmd_sprint(type("A", (), a))
    return calls


def test_sprint_needs_a_plan(monkeypatch, store):
    with pytest.raises(SystemExit, match=r"no .*PLAN.md.*\nDo this: write it"):
        _sprint(monkeypatch, store, plan=False)


def test_sprint_registers_the_control_recipe_at_the_commit_and_reuses_the_stored_control(monkeypatch, store, capsys):
    c = _sprint(monkeypatch, store, set=["a.b=1", "c=2"])
    m, e, s = c["method"], c["create"], c["submit"]
    assert m.command == "cp numba-default-ccccccc numba; haslam route --set a.b=1 --set c=2" and m.kind == "route"
    assert m.code == ["haslam=/repo@" + "c" * 40] and m.harness == "t" * 40 and m.param == ["timeout_s=3600"]
    assert e.method == ["br", "new"] and e.reuse_runs and e.tier == "sprint" and e.attempts == 2
    assert e.harness == e.haslam == "t" * 40                      # prepared and evaluated as the control was
    suites = Path(K.__file__).resolve().parents[2] / "bench" / "suites"
    boards = (suites / "sprint-frontier.txt").read_text().split() + (suites / "sprint-quality.txt").read_text().split()
    assert e.boards.split(",") == boards
    assert s.prio == 5 and s.tier is None and not s.dry_run
    assert "haslamres exp report x && haslamres quality x --control 'control bridge'" in capsys.readouterr().out


def test_sprint_staged_takes_the_placing_control_and_refuses_the_control_itself(monkeypatch, store):
    c = _sprint(monkeypatch, store, base="staged", dry_run=True)
    assert c["method"].kind == "joint-fixed" and c["create"].method == ["st", "new"] and c["submit"].dry_run
    with pytest.raises(SystemExit, match="the arm is the control itself"):
        _sprint(monkeypatch, store, commit="TAG")
    assert _sprint(monkeypatch, store, commit="TAG", set=["k=v"])["method"].command.endswith("numba; haslam route --set k=v")
