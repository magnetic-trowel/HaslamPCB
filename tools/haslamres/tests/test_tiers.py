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
    if "control_code" in kw:
        ctl["br"]["code"] = kw.pop("control_code")
    monkeypatch.setattr(K, "exp_dir", lambda n: store / "experiments" / n)
    monkeypatch.setattr(K, "load_exp", lambda n: dict(name=n, attempts=2, harness=dict(commit=tag), methods=[dict(id="br"), dict(id="st")]))
    monkeypatch.setattr(K, "find_method", lambda k: ctl[k])
    monkeypatch.setattr(K, "main_repo", lambda: "/repo")
    monkeypatch.setattr(K, "git", lambda repo, *a: tag if a[-1].startswith("TAG") else "c" * 40)
    monkeypatch.setattr(K, "cmd_method_add", kw.pop("method_add", lambda a: calls.setdefault("method", a) and "new"))
    monkeypatch.setattr(K, "cmd_exp_create", lambda a: calls.setdefault("create", a))
    monkeypatch.setattr(K, "cmd_exp_submit", lambda a: calls.setdefault("submit", a))
    if plan:
        (store / "experiments" / "x").mkdir(parents=True, exist_ok=True)
        (store / "experiments" / "x" / "PLAN.md").write_text("plan\n")
    runs = kw.pop("runs", None)
    if runs is not None:   # board -> [(method id, attempt, cpu_s)] stored; default: the control ran everywhere
        monkeypatch.setattr(K, "board_dir", lambda b: store)
        monkeypatch.setattr(K, "board_runs", lambda b: [(None, dict(method_id=m, attempt=k, work=dict(cpu_s=cpu)))
                                                        for m, k, cpu in runs.get(b, [])])
    else:
        monkeypatch.setattr(K, "board_dir", lambda b: store)
        monkeypatch.setattr(K, "board_runs", lambda b: [(None, dict(method_id=m, attempt=k, work=dict(cpu_s=360)))
                                                        for m in ("br", "st") for k in (0, 1)])
    a = dict(name="x", base="bridge", commit="abc", set=None, control="control-w47", dry_run=False, arm=None, suite=None,
             attempts=None, skip_over_cap=False, allow_over_cap=None, smoke=None)
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


def test_sprint_names_the_arm_code_as_the_control_template_does(monkeypatch, store):
    """A control stored before the rename of PR #163 (control-w47) runs {py:kae}: its arm's code is named kae."""
    old = dict(kae=dict(commit="t" * 40), harness=dict(commit="t" * 40))
    assert _sprint(monkeypatch, store, set=["k=v"], control_code=old)["method"].code == ["kae=/repo@" + "c" * 40]
    assert _sprint(monkeypatch, store, set=["k=v"])["method"].code == ["haslam=/repo@" + "c" * 40]


def test_sprint_params_and_note_go_on_every_arm(monkeypatch, store):
    c = _sprint(monkeypatch, store, set=["k=v"], param=["parallel=8"], note="router on wall clock")
    m = c["method"]
    assert m.param == ["timeout_s=3600", "parallel=8"] and m.description.endswith("; router on wall clock")
    with pytest.raises(SystemExit, match="--param: give K=V"):
        _sprint(monkeypatch, store, set=["k=v"], param=["parallel"])


def test_sprint_tier_ladder_runs_the_same_arms_as_a_ladder_experiment(monkeypatch, store):
    e = _sprint(monkeypatch, store, set=["k=4"], tier="ladder")["create"]
    assert e.tier == "ladder" and e.description.startswith("ladder on ") and e.reuse_runs


def test_sprint_staged_takes_the_placing_control_and_refuses_the_control_itself(monkeypatch, store):
    c = _sprint(monkeypatch, store, base="staged", dry_run=True)
    assert c["method"].kind == "joint-fixed" and c["create"].method == ["st", "new"] and c["submit"].dry_run
    with pytest.raises(SystemExit, match="the arm is the control itself"):
        _sprint(monkeypatch, store, commit="TAG")
    assert _sprint(monkeypatch, store, commit="TAG", set=["k=v"])["method"].command.endswith("numba; haslam route --set k=v")


def test_control_costs_come_from_the_control_method_own_runs_only(monkeypatch, store):
    runs = {"cheap": [(None, dict(method_id="ctl", attempt=0, work=dict(cpu_s=3600))),
                      (None, dict(method_id="ctl", attempt=1, work=dict(cpu_s=1800))),
                      (None, dict(method_id="ctl", attempt=0, work=dict(cpu_s=99999), repro_of="x")),   # a reproduction
                      (None, dict(method_id="restart", attempt=0, work=dict(cpu_s=50000)))]}            # another recipe
    monkeypatch.setattr(K, "board_dir", lambda b: store if b in runs else store / "none")
    monkeypatch.setattr(K, "board_runs", lambda b: runs.get(b, []))
    assert K.control_costs("ctl", ["cheap", "new"]) == {"cheap": 0.75}


def test_guard_prices_from_the_control_and_falls_back_to_history(store, capsys):
    # dear's history (2 CPU-h, mixed restart runs) is over the limit; its control runs cost 0.2: it passes
    rec = K.tier_guard("sprint", dict(cheap=1, dear=1, new=1), "experiment x", costs=dict(dear=0.2))
    out = capsys.readouterr().out
    assert "1 from the control's own runs, 1 from board history, the others by size" in out
    assert rec["over"] == {} and rec["cpu_h"] == round(0.1 + 0.2 + 2.0, 1)
    with pytest.raises(SystemExit, match=r"1 boards are over \(cheap 0.9\)"):   # the control's cost wins over history
        K.tier_guard("sprint", dict(cheap=1), "experiment x", costs=dict(cheap=0.9))


def test_guard_names_allow_over_cap_and_lifts_the_board_limit_with_a_reason(store, capsys):
    with pytest.raises(SystemExit) as r:
        K.tier_guard("sprint", dict(dear=1), "experiment x")
    assert '--allow-over-cap "REASON"' in str(r.value) and "--skip-over-cap" in str(r.value)
    rec = K.tier_guard("sprint", dict(dear=1), "experiment x", over_cap="the coupling boards are the question")
    assert rec["over"] == {"dear": 2.0} and "lifted for 1 boards (dear 2.00): the coupling boards" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="allows 40 CPU-h in all"):          # the total limit stays
        K.tier_guard("sprint", dict(dear=30), "experiment x", over_cap="needed")


def test_guard_total_limit_is_per_treatment_arm(store):
    K.tier_guard("sprint", dict(cheap=700), "experiment x", arms=2)             # 70 CPU-h, two arms
    with pytest.raises(SystemExit, match=r"allows 80 CPU-h in all \(40 per treatment arm, 2 arms\)"):
        K.tier_guard("sprint", dict(cheap=801), "experiment x", arms=2)


def test_exp_create_records_the_suite_cost_source_and_over_cap_reason(monkeypatch, store):
    monkeypatch.setattr(K, "control_costs", lambda mid, boards: {"dear": 0.3} if mid == "ctl" else {})
    e = _create(monkeypatch, store, boards="cheap,dear", cost_from="ctl", suite="mech/x", arms=2,
                record=dict(control_fill=["cheap"]))
    assert (e["suite"], e["cost_from"], e["arms"], e["control_fill"]) == ("mech/x", "ctl", 2, ["cheap"])
    e = _create(monkeypatch, store, name="y", allow_over_cap="needs them")
    assert e["over_cap"] == {"reason": "needs them", "boards": {"dear": 2.0}}


def test_sprint_takes_one_suite_by_name(monkeypatch, store):
    e = _sprint(monkeypatch, store, suite="mech/bga")["create"]
    assert e.suite == "mech/bga" and e.boards.split(",") == K.suite_boards(K.SUITES_DIR / "mech" / "bga.txt")
    assert _sprint(monkeypatch, store, suite="sprint-quality.txt")["create"].suite == "sprint-quality.txt"
    for bad in ("nosuch", "../README.md"):
        with pytest.raises(SystemExit, match="no suite"):
            _sprint(monkeypatch, store, suite=bad)


def test_sprint_runs_the_control_where_it_is_not_stored(monkeypatch, store, capsys):
    boards = K.suite_boards(K.SUITES_DIR / "sprint-quality.txt")
    runs = {b: [("br", 0, 360), ("br", 1, 360)] for b in boards[2:]}
    runs[boards[1]] = [("br", 0, 360)]                                     # seed 1 missing
    c = _sprint(monkeypatch, store, suite="sprint-quality", runs=runs)
    e = c["create"]
    assert e.record["control_fill"] == boards[:2] and e.method[0] == "br" and e.cost_from == "br"
    assert "2 of 80 boards have no stored run of 'control bridge'" in capsys.readouterr().out
    fill = [json.loads(ln) for ln in (store / "experiments" / "control-w47" / "control-fill.jsonl").read_text().splitlines()]
    assert fill[-1]["boards"] == boards[:2] and fill[-1]["experiment"] == "x"
    assert _sprint(monkeypatch, store, suite="sprint-quality", runs=runs, attempts=1)["create"].record["control_fill"] == boards[:1]


def test_sprint_with_two_arms_is_one_campaign(monkeypatch, store):
    added = []
    c = _sprint(monkeypatch, store, set=["c=2"], arm=["t07:place_phys_hinge=0.7", "t10:place_phys_hinge=1.0,b=3"],
                method_add=lambda a: added.append(a) or f"id{len(added)}")
    assert [a.command.split("haslam route")[1] for a in added] == [" --set c=2 --set place_phys_hinge=0.7",
                                                                 " --set c=2 --set place_phys_hinge=1.0 --set b=3"]
    assert added[0].name.startswith("x-t07 bridge ccccccc") and added[1].name.startswith("x-t10 bridge")
    e = c["create"]
    assert e.method == ["br", "id1", "id2"] and e.arms == 2 and e.record["arm_methods"] == {"t07": "id1", "t10": "id2"}
    for bad in (["noset"], ["a:k"], ["a:k=1", "a:k=2"]):
        with pytest.raises(SystemExit, match="--arm"):
            _sprint(monkeypatch, store, arm=bad)


def test_sprint_skips_boards_over_the_cap_or_records_why_they_stay(monkeypatch, store, capsys):
    boards = K.suite_boards(K.SUITES_DIR / "sprint-quality.txt")
    runs = {b: [("br", 0, 360), ("br", 1, 360)] for b in boards}
    runs[boards[0]] = [("br", 0, 3600), ("br", 1, 3600)]                   # 1 CPU-h per run
    e = _sprint(monkeypatch, store, suite="sprint-quality", runs=runs, skip_over_cap=True)["create"]
    assert boards[0] not in e.boards.split(",") and e.record["skipped_over_cap"] == {boards[0]: 1.0}
    e = _sprint(monkeypatch, store, suite="sprint-quality", runs=runs, allow_over_cap="needed")["create"]
    assert boards[0] in e.boards.split(",") and e.allow_over_cap == "needed"
    with pytest.raises(SystemExit, match="needs the reason"):
        _sprint(monkeypatch, store, suite="sprint-quality", runs=runs, allow_over_cap=" ")


def test_sprint_smoke_submits_two_cheap_boards_one_of_them_a_control_fill(monkeypatch, store, capsys):
    boards = K.suite_boards(K.SUITES_DIR / "sprint-quality.txt")
    runs = {b: [("br", 0, 100 + i), ("br", 1, 100 + i)] for i, b in enumerate(boards[1:])}
    s = _sprint(monkeypatch, store, suite="sprint-quality", runs=runs, smoke=2)["submit"]
    assert s.only == f"{boards[0]},{boards[1]}" and s.prio == 5
    assert f"the rest: haslamres exp submit x --prio 5" in capsys.readouterr().out
