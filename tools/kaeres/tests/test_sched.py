# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/kaeres/sched.py (--sched return): pure decisions from synthetic and recorded histories, and
restart.py end to end with a stand-in kicad-cli (no KiCad)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("sched_under_test", HERE / "sched.py")
sched = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sched)

CTX = dict(parallel=4, first_s=60.0, growth=2.0, has_final=True)


def opts(**kw):
    return sched.load_opts(json.dumps(kw) if kw else "")


def att(k, batch, opens, cpu=100.0, frm=None, illegal=0, new=0, budget=None):
    return dict(k=k, seed=k, batch=batch, budget=budget or 60 * 2 ** batch, cpu_s=cpu,
                rank=list(sched_rank(opens, new, illegal)), resumed_from=frm)


def sched_rank(opens, new=0, illegal=0):
    clean = illegal == 0 and new == 0 and opens == 0
    return (1 if illegal else 0, 0 if clean else 1, opens, new, illegal)


# --- options --------------------------------------------------------------------------------------

def test_defaults_are_the_replay_verdict_and_unknown_keys_are_refused(tmp_path):
    o = opts()
    assert (o["lanes_fresh"], o["lanes_resume"], o["depth_bonus"], o["adapt"]) == (1, 1, True, False)
    assert not (o["stop_near_miss"] or o["stop_futility"] or o["stop_capacity"])
    assert o["priors"]["resume"]["6-20"]["per_cpu_h"] == 24.0 and o["priors"]["fresh"][">100"]["per_cpu_h"] == 6.5
    with pytest.raises(ValueError):
        sched.load_opts('{"near_maxx": 3}')
    f = tmp_path / "o.json"
    f.write_text('{"near_max": 3}')
    assert sched.load_opts(str(f))["near_max"] == 3


def test_buckets():
    assert [sched.bucket(n) for n in (0, 1, 5, 6, 20, 21, 100, 101)] == \
        ["0", "1-5", "1-5", "6-20", "6-20", "21-100", "21-100", ">100"]


# --- probe and lanes ------------------------------------------------------------------------------

def test_probe_n():
    assert sched.plan([], 0, 1000, CTX, opts())["lanes"] == [None] * 4
    assert sched.plan([], 0, 1000, CTX, opts(fixed_placement=True))["lanes"] == [None] * 2
    assert sched.plan([], 0, 1000, CTX, opts(probe_n=3))["lanes"] == [None] * 3
    d = sched.plan([], 0, 1000, dict(CTX, parallel=2), opts(probe_n=3))
    assert d["lanes"] == [None] * 2 and d["budget"] == 60.0


def test_later_batches_default_to_one_resume_and_one_fresh_lane_with_depth_bonus():
    h = [att(0, 0, 9), att(1, 0, 7), att(2, 0, 8), att(3, 0, 12)]
    d = sched.plan(h, 1, 1000, CTX, opts())
    assert d["lanes"] == [1, None] and d["budget"] == 120.0
    assert d["plan_charge_s"] == 60.0 and d["depth_bonus"]           # 120 s x 2 lanes / 4
    assert sched.plan(h, 1, 1000, CTX, opts(depth_bonus=False))["plan_charge_s"] == 120.0
    # no ranked incumbent: the resume lane runs fresh
    h0 = [dict(a, rank=None) for a in h]
    assert sched.plan(h0, 1, 1000, CTX, opts())["lanes"] == [None, None]


def test_identical_seeds_cap_lanes_at_one_of_each_type():
    h = [att(0, 0, 9, cpu=100.0), att(1, 0, 9, cpu=101.0), att(2, 0, 11, cpu=50), att(3, 0, 12, cpu=70)]
    d = sched.plan(h, 1, 1000, CTX, opts(adapt=True))
    assert d["seeds_do_not_act"]["ks"] == [0, 1]
    assert d["resume"] <= 1 and d["fresh"] <= 1
    h2 = [att(0, 0, 9, cpu=100.0), att(1, 0, 9, cpu=110.0), att(2, 0, 11), att(3, 0, 12)]   # CPU differs > 2 %
    d2 = sched.plan(h2, 1, 1000, CTX, opts(adapt=True))
    assert "seeds_do_not_act" not in d2 and d2["resume"] + d2["fresh"] == 4


def test_adapt_splits_lanes_by_rate():
    h = [att(0, 0, 30), att(1, 0, 31), att(2, 0, 32), att(3, 0, 33)]
    d = sched.plan(h, 1, 1e5, CTX, opts(adapt=True))
    assert (d["resume"], d["fresh"]) == (3, 1)               # priors 24 vs 6.5 per CPU-hour: 3.15 resume lanes
    # fresh attempts closed many opens, resume none: fresh gets every lane ...
    h += [att(4, 1, 30, cpu=3000, frm=0), att(5, 1, 10, cpu=300), att(6, 1, 12, cpu=300), att(7, 1, 11, cpu=300)]
    d = sched.plan(h, 2, 1e5, CTX, opts(adapt=True))
    assert d["rates_per_cpu_h"]["fresh"] > d["rates_per_cpu_h"]["resume"]
    assert (d["resume"], d["fresh"]) == (0, 4)
    # ... until resume has had no lane for explore_every - 1 batches: then it gets explore_min
    h += [att(8, 2, 5, cpu=300), att(9, 2, 6, cpu=300), att(10, 2, 7, cpu=300), att(11, 2, 8, cpu=300)]
    d = sched.plan(h, 3, 1e5, CTX, opts(adapt=True))
    assert (d["resume"], d["fresh"]) == (1, 3) and d["lanes"][0] == 8 and "explore resume" in d["why"]


def test_fresh_credit_is_against_the_incumbent_before_its_batch_and_never_negative():
    h = [att(0, 0, 10), att(1, 1, 14), att(2, 1, 6, frm=0)]
    rows = sched.ledger(h, 4, opts())
    assert rows[0]["fresh"]["closed"] == 0                    # batch 0: no incumbent
    assert rows[1]["fresh"]["closed"] == 0 and rows[1]["resume"]["closed"] == 4
    assert rows[1]["inc_before"] == 10 and rows[1]["inc_after"] == 6


# --- stop rules -----------------------------------------------------------------------------------

def _near_miss_history(last_closes):
    return [att(0, 0, 3), att(1, 0, 4), att(2, 1, 2 if last_closes else 3, frm=0), att(3, 1, 5)]


def test_near_miss_stop():
    on = opts(stop_near_miss=True)
    d = sched.plan(_near_miss_history(False), 2, 500, CTX, on)
    assert d["action"] == "stop" and d["reason"] == "near-miss" and d["opens"] == 3
    assert sched.plan(_near_miss_history(True), 2, 500, CTX, on)["action"] == "launch"    # last batch closed one
    assert sched.plan(_near_miss_history(False), 2, 500, dict(CTX, has_final=False), on)["action"] == "launch"
    assert sched.plan(_near_miss_history(False), 2, 500, CTX, opts())["action"] == "launch"   # off by default


def test_futility_stop():
    # 40 opens, three CPU-hours of resume and fresh work closed nothing, little plan time left
    h = [att(0, 0, 40, cpu=5400, budget=5400), att(1, 1, 40, cpu=5400, frm=0, budget=5400),
         att(2, 1, 41, cpu=5400, budget=5400)]
    on = opts(stop_futility=True)
    d = sched.plan(h, 2, 30, CTX, on)
    assert d["action"] == "stop" and d["reason"] == "futility" and d["expected_closed"] < 1.0
    assert "40 opens" in d["message"]
    assert sched.plan(h, 2, 30000, CTX, on)["action"] == "launch"      # plenty of time left
    assert sched.plan(h, 2, 30, CTX, opts())["action"] == "launch"


def test_capacity_stop():
    h = [att(0, 0, 50), att(1, 0, 52), att(2, 1, 49, frm=0), att(3, 1, 51)]
    on = opts(stop_capacity=True)
    d = sched.plan(h, 2, 1e5, CTX, on)
    assert d["action"] == "stop" and d["reason"] == "capacity"
    assert d["message"] == "stopped: 49 opens stable across seeds and budgets; see the blocked report"
    assert d["fresh_best"] == [50, 51] and d["resume_best"] == 49
    h2 = [att(0, 0, 50), att(1, 0, 52), att(2, 1, 40, frm=0), att(3, 1, 51)]   # resume closed 20 %
    assert sched.plan(h2, 2, 1e5, CTX, on)["action"] == "launch"
    h3 = [att(0, 0, 50), att(1, 0, 52), att(2, 1, 49, frm=0), att(3, 1, 70)]   # fresh counts 40 % apart
    assert sched.plan(h3, 2, 1e5, CTX, on)["action"] == "launch"
    assert sched.plan(h, 2, 1e5, CTX, opts())["action"] == "launch"


def test_clean_is_always_a_stop():
    d = sched.plan([att(0, 0, 0)], 1, 1000, CTX, opts())
    assert d["action"] == "stop" and d["reason"] == "clean"


# --- determinism and replay -----------------------------------------------------------------------

def _drive(attempts, parallel, o, plan_s=100000.0):
    """Feed a recorded attempt list (summary.json attempt_log of the fixed schedule) batch by batch to
    the stateful scheduler, as restart.py would; the lanes it asks for are matched to recorded
    attempts of the same type (a replay: the board of a resumed attempt depends on what it resumed)."""
    s = sched.Return(o, parallel, 60.0, 2.0, True, log=lambda m: None)
    rec = {}
    for a in attempts:
        if isinstance(a["k"], int):
            rec.setdefault(a["k"] // parallel, []).append(a)
    done, k, used = [], 0, 0.0
    for b in sorted(rec):
        pool = list(rec[b])
        lanes = []
        while len(lanes) < parallel and (nx := s.lane(done, plan_s - used, not lanes, k)) is not None:
            want = "resume" if nx[1] is not None else "fresh"
            m = next((x for x in pool if (x.get("resumed_from") is not None) == (want == "resume")), None)
            if m is None:
                del s.kb[k]
                break
            pool.remove(m)
            lanes.append(dict(m, k=k, resumed_from=nx[1], budget=nx[0]))
            k += 1
        if not lanes:
            break
        used += s.charge(max(x["budget"] for x in lanes), len(lanes))
        done += lanes
    return s, done


RECORDED = [  # a 4-lane --resume 0.5 run: seeds act little, resume closes more
    dict(k=0, seed=0, budget=60, cpu_s=55.0, rank=[0, 1, 14, 2, 0], resumed_from=None),
    dict(k=1, seed=1, budget=60, cpu_s=58.0, rank=[0, 1, 15, 1, 0], resumed_from=None),
    dict(k=2, seed=2, budget=60, cpu_s=57.0, rank=[0, 1, 14, 3, 0], resumed_from=None),
    dict(k=3, seed=3, budget=60, cpu_s=60.0, rank=[0, 1, 16, 0, 0], resumed_from=None),
    dict(k=4, seed=4, budget=120, cpu_s=110.0, rank=[0, 1, 9, 2, 0], resumed_from=0),
    dict(k=5, seed=5, budget=120, cpu_s=115.0, rank=[0, 1, 10, 2, 0], resumed_from=0),
    dict(k=6, seed=6, budget=120, cpu_s=118.0, rank=[0, 1, 13, 2, 0], resumed_from=None),
    dict(k=7, seed=7, budget=120, cpu_s=117.0, rank=[0, 1, 14, 2, 0], resumed_from=None),
    dict(k=8, seed=8, budget=240, cpu_s=230.0, rank=[0, 1, 4, 2, 0], resumed_from=4),
    dict(k=9, seed=9, budget=240, cpu_s=235.0, rank=[0, 1, 6, 2, 0], resumed_from=4),
    dict(k=10, seed=10, budget=240, cpu_s=236.0, rank=[0, 1, 12, 2, 0], resumed_from=None),
    dict(k=11, seed=11, budget=240, cpu_s=239.0, rank=[0, 1, 13, 2, 0], resumed_from=None),
    dict(k="final", seed=999, budget=60, cpu_s=50.0, rank=[0, 1, 4, 2, 0], resumed_from=8),
]


def test_replay_of_a_recorded_attempt_list():
    s, done = _drive(RECORDED, 4, opts())
    acts = [(d["batch"], d["action"], d.get("resume"), d.get("fresh")) for d in s.decisions]
    assert acts == [(0, "launch", 0, 4), (1, "launch", 1, 1), (2, "launch", 1, 1)]
    assert [x["k"] for x in done] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert [d.get("plan_charged_s") for d in s.decisions] == [60.0, 60.0, 120.0]
    summ = s.summary(done, 1000.0)
    assert summ["policy"] == "return" and summ["stop"] is None and summ["plan_left_s"] == 1000.0
    json.dumps(summ)   # summary.json-ready


def test_same_history_gives_the_same_decisions():
    for o in (opts(), opts(adapt=True, stop_capacity=True, stop_futility=True, stop_near_miss=True)):
        a, _ = _drive(RECORDED, 4, o)
        b, _ = _drive(RECORDED, 4, o)
        assert json.dumps(a.decisions, sort_keys=True) == json.dumps(b.decisions, sort_keys=True)


def test_time_mode_keeps_the_fixed_schedule():
    lines = []
    assert sched.make("return", "", False, 4, 60.0, 2.0, "", lines.append) is None
    assert len(lines) == 1 and "KAE_BUDGET=work" in lines[0]


# --- restart.py end to end (stand-in kicad-cli) ---------------------------------------------------

FAKE_CLI = """#!/usr/bin/env python3
import json, re, sys
args = sys.argv[1:]
out = args[args.index("--output") + 1]
board = open(args[-1]).read()
m = re.search(r"OPEN=(\\d+)", board)
n = int(m.group(1)) if m else 0
json.dump(dict(violations=[], unconnected_items=[dict(items=[dict(description=f"Pad 1 [N{i}] of U1")])
                                                for i in range(n)]), open(out, "w"))
"""
# fresh attempts: 3 + seed % 3 opens; a resumed one removes one open of its board, down to 2
ATTEMPT = ("if [ \"$KAE_RESUME\" = 1 ]; then n=$(grep -o 'OPEN=[0-9]*' @BEST@ | cut -d= -f2); "
           "n=$(( n > 2 ? n - 1 : 2 )); else n=$(( 3 + @SEED@ % 3 )); fi; echo \"(kicad_pcb OPEN=$n)\" > @OUT@")


def _restart(tmp_path, restart_py, extra=(), time_s=400, parallel=2):
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "kicad-cli").write_text(FAKE_CLI.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    (bin_ / "kicad-cli").chmod(0o755)
    inp = tmp_path / "in" / "board.kicad_pcb"
    inp.parent.mkdir()
    inp.write_text("(kicad_pcb OPEN=9)\n")
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", KAE_KICAD_WRAP="", KAE_BUDGET="work")
    env.pop("KAE_STEP_CACHE", None)
    r = subprocess.run([sys.executable, str(restart_py), "--input", str(inp), "--output", str(tmp_path / "out.kicad_pcb"),
                        "--time", str(time_s), "--parallel", str(parallel), "--first-s", "25", *extra, "--", ATTEMPT],
                       cwd=work, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r, json.loads((work / "restarts" / "summary.json").read_text())


def _seq(summary):
    return [(d["k"], d["seed"], d["budget"], d["resumed_from"], d["rank"]) for d in summary["attempt_log"]]


def _lines(r):
    return [re.sub(r"^\[restart \d\d:\d\d:\d\d\] ", "", x) for x in r.stdout.splitlines() if not x.startswith("KAE_WORK")]


def test_default_schedule_is_the_same_without_the_module(tmp_path):
    """--sched '' never loads sched.py: a checkout without it runs the same attempts, with the same log."""
    bare = tmp_path / "bare"
    for rel in ("tools/kaeres/restart.py", "kae/src/kae/rank.py", "kae/src/kae/drc_items.py",
                "kae/src/kae/route/stepcache.py"):
        (bare / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, bare / rel)
    assert not (bare / "tools/kaeres/sched.py").exists()
    extra = ["--resume", "0.5"]
    r1, s1 = _restart(tmp_path / "with", HERE / "restart.py", extra)
    r2, s2 = _restart(tmp_path / "without", bare / "tools/kaeres/restart.py", extra)
    assert _seq(s1) == _seq(s2) and len(s1["attempt_log"]) >= 6
    assert any(d["resumed_from"] is not None for d in s1["attempt_log"])
    assert _lines(r1) == _lines(r2)
    assert "sched" not in s1


def test_sched_return_end_to_end(tmp_path):
    r, s = _restart(tmp_path / "a", HERE / "restart.py", ["--sched", "return"], parallel=4)
    sc = s["sched"]
    assert sc["policy"] == "return" and sc["opts"]["lanes_resume"] == 1
    launches = [d for d in sc["decisions"] if d["action"] == "launch"]
    assert launches[0]["why"] == "probe" and launches[0]["launched"] == 4
    assert all(d.get("launched", 0) <= 2 for d in launches[1:]) and len(launches) >= 3
    # depth bonus: 25 + 50/2 + 100/2 + 200/2 ... charged; more batches than the fixed 4-lane plan holds
    assert launches[1]["plan_charged_s"] == 25.0
    assert "sched return: batch 1 1 resume + 1 fresh at 50s" in r.stdout
    assert sc["plan_left_s"] >= 0


def test_sched_return_near_miss_gives_the_final_pass_the_plan_left(tmp_path):
    final = "sed 's/OPEN=[0-9]*/OPEN=0/' @BEST@ > @OUT@ && echo t=@TIME@ >> @OUT@"
    r, s = _restart(tmp_path / "a", HERE / "restart.py",
                    ["--sched", "return", "--sched-opts", '{"stop_near_miss": true}', "--final", final,
                     "--final-s", "20"], time_s=2000)
    sc = s["sched"]
    assert sc["stop"] == "near-miss", r.stdout
    fin = next(d for d in sc["decisions"] if d["action"] == "final")
    log = {d["k"]: d for d in s["attempt_log"]}
    assert log["final"]["budget"] == round(fin["final_s"]) > 20 and fin["final_s"] == fin["plan_left_s"]
    assert s["best_rank"][:3] == [0, 0, 0]


def test_sched_return_in_time_mode_is_the_fixed_schedule(tmp_path):
    """Without KAE_BUDGET=work the scheduler only says so; the attempts are those of the fixed schedule."""
    def run(p, extra):
        os.environ.pop("KAE_BUDGET", None)
        return _restart_time(p, extra)
    r1, s1 = run(tmp_path / "a", [])
    r2, s2 = run(tmp_path / "b", ["--sched", "return"])
    assert [d["k"] for d in s1["attempt_log"]][:2] == [d["k"] for d in s2["attempt_log"]][:2]
    assert s2["sched"] == dict(policy="return", active=False)
    assert "acts only in counted-work mode" in r2.stdout


def _restart_time(tmp_path, extra):
    tmp_path.mkdir(parents=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "kicad-cli").write_text(FAKE_CLI.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    (bin_ / "kicad-cli").chmod(0o755)
    inp = tmp_path / "in" / "board.kicad_pcb"
    inp.parent.mkdir()
    inp.write_text("(kicad_pcb OPEN=9)\n")
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", KAE_KICAD_WRAP="")
    env.pop("KAE_BUDGET", None)
    env.pop("KAE_STEP_CACHE", None)
    r = subprocess.run([sys.executable, str(HERE / "restart.py"), "--input", str(inp), "--output",
                        str(tmp_path / "out.kicad_pcb"), "--time", "200", "--parallel", "2", "--first-s", "25",
                        "--max-attempts", "2", *extra, "--", ATTEMPT],
                       cwd=work, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r, json.loads((work / "restarts" / "summary.json").read_text())
