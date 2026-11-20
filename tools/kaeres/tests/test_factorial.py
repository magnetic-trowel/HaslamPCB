# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of tools/kaeres/factorial.py: design matrices, aliasing, mde, analysis on synthetic data."""
import csv
import itertools
import json
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factorial as F  # noqa: E402

FIVE = [F.parse_factor(s) for s in ("xing:on=place_w_xing=2", "chan:on=place_w_chan=3",
                                     "margin:on=place_margin=-1,place_margin_gate=4", "matrix:on=array_macros=1",
                                     "barrier:on=barrier_split=2")]


def seven():
    return [F.parse_factor(f"{c}:on=k{c}=1") for c in "abcdefg"]


@pytest.mark.parametrize("runs,k", [(8, 4), (8, 5), (8, 7), (16, 5), (16, 6), (16, 8), (16, 15), (32, 6), (32, 10)])
def test_regular_fractions_orthogonal(runs, k):
    rows, gens = F.regular_fraction(k, runs)
    assert len(rows) == runs and len(rows[0]) == k
    assert F.is_orthogonal(rows)
    assert len(set(map(tuple, rows))) == runs


def test_pb12_and_foldover_orthogonal():
    rows = F.plackett_burman12(11)
    assert len(rows) == 12 and F.is_orthogonal(rows)
    assert F.is_orthogonal(F.foldover(rows))


def test_2_7_4_every_main_effect_aliased_with_three_2fi():
    plan = F.make_plan(seven(), runs=8)
    assert plan["resolution"] == 3
    assert set(plan["main_effect_aliases"]) == set("ABCDEFG")
    assert all(len(v) == 3 for v in plan["main_effect_aliases"].values())


def test_foldover_is_resolution_iv():
    plan = F.make_plan(seven(), runs=8, fold=True)
    assert plan["runs"] == 16 and plan["resolution"] == 4
    assert plan["main_effect_aliases"] == {}
    assert all(len(g) == 3 for g in plan["two_factor_alias_groups"])


def test_resolution_computed():
    assert F.make_plan(seven()[:5], runs=16)["resolution"] == 5         # E = ABCD
    assert F.make_plan(seven()[:6], runs=16)["resolution"] == 4         # E = ABC, F = BCD
    assert F.make_plan(seven()[:3], runs=8)["resolution"] is None       # full factorial
    pb = F.make_plan(seven()[:5], kind="pb12")
    assert pb["resolution"] == 3 and 3 < pb["generalized_resolution"] < 4
    assert pb["partial_aliases"] and not pb["main_effect_aliases"]


def test_plan_arms_settings_and_flags():
    plan = F.make_plan(FIVE, runs=8)
    assert len(plan["arms"]) == 8
    on = [a for a in plan["arms"] if a["all_on"]]
    assert len(on) == 1 and "--set place_margin_gate=4" in on[0]["set_args"]
    assert plan["has_all_off"] is False            # D = AB, E = AC has no all-off row; it is flagged, not invented
    full = F.make_plan(FIVE[:3], runs=8)
    assert full["has_all_off"] and [a for a in full["arms"] if a["all_off"]][0]["set_args"] == ""


def test_with_all_off_keeps_aliasing():
    a, b = F.make_plan(FIVE, runs=8), F.make_plan(FIVE, runs=8, all_off=True)
    assert b["has_all_off"] and b["has_all_on"] is False and b["generators"] == {"D": "-AB", "E": "-AC"}
    assert a["resolution"] == b["resolution"]
    assert {k: sorted(v) for k, v in a["main_effect_aliases"].items()} == \
        {k: sorted(v) for k, v in b["main_effect_aliases"].items()}
    assert sorted(map(sorted, a["two_factor_alias_groups"])) == sorted(map(sorted, b["two_factor_alias_groups"]))
    c = F.make_plan(seven()[:5], runs=16, all_off=True)            # E = ABCD: even word, negated
    assert c["has_all_off"] and c["resolution"] == 5


def test_rotation():
    boards = [f"b{i}" for i in range(10)]
    plan = F.make_plan(FIVE, runs=8, rotate=8, boards=boards, seeds=3)
    asg = plan["rotation"]["assignment"]
    assert len(asg) == 30
    assert asg[0]["arm"] == "r00" and [x for x in asg if x["board"] == "b3" and x["seed"] == 2][0]["arm"] == "r05"
    assert F.rotation_row(7, 3, 8) == 2
    with pytest.raises(ValueError):
        F.make_plan(FIVE, runs=8, rotate=5)


def test_parse_factor():
    f = F.parse_factor("margin:on=place_margin=-1,place_margin_gate=4:off=place_margin=0")
    assert f == {"name": "margin", "on": ["place_margin=-1", "place_margin_gate=4"], "off": ["place_margin=0"]}
    for bad in ("x", "x:on=", "x:up=a=1", "x:on=a"):
        with pytest.raises(ValueError):
            F.parse_factor(bad)


def test_mde_against_mde_out():
    # Rows of the design-6 stage-0 table (mde.out): s_int, s_dw, boards, runs per (board, seed) -> detectable %.
    cases = [(0.136, 0.355, 21, 8, 14.6), (0.136, 0.355, 10, 16, 17.8), (0.158, 0.093, 21, 8, 10.6),
             (0.158, 0.093, 10, 16, 15.4), (0.056, 0.132, 15, 8, 6.4), (0.142, 0.351, 15, 8, 17.7)]
    for s_int, s_dw, nb, R, want in cases:
        got = F.pct(F.mde(F.var_cells(s_int, s_dw, nb, 1, R)))
        assert abs(got - want) < 0.25, (s_int, s_dw, nb, R, got, want)


def test_mde_rotation_and_bonferroni():
    v = F.var_rotation(0.1, 0.3, 40, 120)
    assert v == pytest.approx(0.01 / 40 + 4 * 0.09 / 120)
    assert F.mde(v, tests=5) > F.mde(v)
    assert F.z_power() == pytest.approx(2.8016, abs=1e-3)


def test_holm():
    assert F.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def synth(plan, effects, n_boards=40, n_owners=20, seeds=2, sd_board=0.8, sd_seed=0.3, sd_noise=0.15, rng_seed=1,
          rotate=False):
    """Runs with board effects, a same-seed component shared by all arms of a cell, and planted log-scale effects."""
    rng = random.Random(rng_seed)
    runs = []
    owners = {}
    for i in range(n_boards):
        b = f"board{i:03d}"
        owners[b] = f"owner{i % n_owners}"
        base = 1.5 + rng.gauss(0, sd_board)
        lbase = 5 + rng.gauss(0, 0.5)
        inter = {f: rng.gauss(0, 0.03) for f in effects}         # small board x factor interaction
        for s in range(seeds):
            shared = rng.gauss(0, sd_seed)
            arms = plan["arms"]
            if rotate:
                arms = [arms[F.rotation_row(i, s, len(arms))]]
            for a in arms:
                y = base + shared + rng.gauss(0, sd_noise)
                ly = lbase + 0.5 * shared + rng.gauss(0, 0.02)
                for f, eff in effects.items():
                    y += a["levels"][f] * (eff + inter[f]) / 2
                    ly += a["levels"][f] * (eff / 4) / 2
                runs.append({"board": b, "seed": s, "arm": a["id"], "opens": math.expm1(max(y, 0.0)),
                             "clean": 0, "length": math.exp(ly), "vias": 20.0})
    return runs, owners


def test_planted_effects_recovered():
    plan = F.make_plan(FIVE, runs=8, fold=True)                  # resolution IV: main effects free of 2fi
    effects = {"xing": -0.3, "chan": 0.0, "margin": 0.25, "matrix": 0.0, "barrier": 0.0}
    runs, owners = synth(plan, effects)
    v = F.analyse(runs, plan, owners)
    op = {f: v["factors"][f]["opens"] for f in effects}
    assert op["xing"]["status"] == "better" and op["xing"]["estimate"] == pytest.approx(-0.3, abs=0.06)
    assert op["margin"]["status"] == "worse" and op["margin"]["estimate"] == pytest.approx(0.25, abs=0.06)
    for f in ("chan", "matrix", "barrier"):
        assert op[f]["status"] in ("bounded", "undecided"), op[f]
        assert op[f]["status"] != "better" and op[f]["status"] != "worse"
    assert op["xing"]["p_holm"] < 0.05
    assert v["interactions"] and all("opens" in e for e in v["interactions"].values())


def test_null_factor_with_noise_is_not_called():
    plan = F.make_plan(FIVE, runs=8)
    runs, owners = synth(plan, {f["name"]: 0.0 for f in FIVE}, n_boards=12, n_owners=12, sd_seed=0.6, sd_noise=0.5)
    v = F.analyse(runs, plan, owners)
    for f in FIVE:
        assert v["factors"][f["name"]]["opens"]["status"] in ("bounded", "undecided")
        if v["factors"][f["name"]]["opens"]["status"] == "undecided":
            assert v["factors"][f["name"]]["opens"]["boards_to_decide"] > 12


def test_unknown_under_ten_owners():
    plan = F.make_plan(FIVE, runs=8)
    runs, owners = synth(plan, {"xing": -0.5}, n_boards=30, n_owners=6)
    v = F.analyse(runs, plan, owners)
    assert v["factors"]["xing"]["opens"]["status"] == "unknown"


def test_length_only_on_closed_cells():
    plan = F.make_plan(FIVE, runs=8)
    runs, owners = synth(plan, {"xing": -0.3})
    for r in runs:
        r["opens"] = max(r["opens"], 1.0)
    runs[0]["opens"] = 0                                         # one closed run does not make a closed cell
    assert F.board_contrasts(runs, plan, "length", "xing") == {}
    for r in runs:
        r["opens"] = 0
    assert len(F.board_contrasts(runs, plan, "length", "xing")) == 40


def test_rotation_analysis_recovers_effect():
    plan = F.make_plan(FIVE, runs=8, rotate=8)
    runs, owners = synth(plan, {"xing": -0.4}, n_boards=120, n_owners=60, seeds=8, rotate=True)
    v = F.analyse(runs, plan, owners)
    e = v["factors"]["xing"]["opens"]
    assert e["boards"] == 120 and e["status"] == "better"


def test_reach_and_confseq_options():
    plan = F.make_plan(FIVE, runs=8, fold=True)
    runs, owners = synth(plan, {"xing": -0.3})
    reach = {"factors": {"xing": [f"board{i:03d}" for i in range(20)]}}
    v = F.analyse(runs, plan, owners, confseq=1.0, reach=reach)
    e = v["factors"]["xing"]["opens"]
    assert e["reached"]["boards"] == 20
    cs = e["confseq"]
    assert cs["interval"][0] <= e["estimate"] <= cs["interval"][1]
    assert cs["width_ratio_vs_fixed_n"] > 1
    assert "5x wider" in v["confseq_note"]


def test_confseq_coverage():
    rng = random.Random(0)
    miss = 0
    reps = 300
    for _ in range(reps):
        xs = [max(-1, min(1, rng.gauss(0.05, 0.3))) for _ in range(100)]
        mu = 0.05                     # clipping at +-1 moves the mean by < 1e-3 at sd 0.3
        if any(not (lo - 1e-3 <= mu <= hi + 1e-3) for lo, hi in F.eb_confseq(xs)):
            miss += 1
    assert miss / reps <= 0.05


def test_confseq_wider_than_fixed_n_at_60():
    rng = random.Random(1)
    w = []
    for _ in range(100):
        xs = [rng.gauss(0, 0.4) for _ in range(60)]
        lo, hi = F.eb_confseq(xs, lo=-2, hi=2)[-1]
        w.append((hi - lo) / 2)
    ratio = sorted(w)[50] / (1.96 * 0.4 / math.sqrt(60))
    assert 4 < ratio < 6                                         # confseq.out: 5.01


def test_cli_roundtrip(tmp_path):
    plan_p = tmp_path / "plan.json"
    assert F.main(["design", "--factor", "xing:on=place_w_xing=2", "--factor", "chan:on=place_w_chan=3",
                   "--factor", "margin:on=place_margin=-1", "-o", str(plan_p)]) == 0
    plan = json.loads(plan_p.read_text())
    runs, owners = synth(plan, {"xing": -0.3, "chan": 0.0, "margin": 0.0})
    csv_p = tmp_path / "runs.csv"
    with open(csv_p, "w", newline="") as fh:
        w = csv.DictWriter(fh, ["board", "owner", "seed", "arm", "opens", "clean", "length", "vias"])
        w.writeheader()
        for r in runs:
            w.writerow(dict(r, owner=owners[r["board"]]))
    out = tmp_path / "VERDICT.json"
    assert F.main(["analyse", "--plan", str(plan_p), "--csv", str(csv_p), "-o", str(out)]) == 0
    v = json.loads(out.read_text())
    assert v["factors"]["xing"]["opens"]["status"] == "better"
    statuses = {e["status"] for eps in v["factors"].values() for e in eps.values()}
    assert statuses <= {"better", "worse", "bounded", "undecided", "unknown"}
    assert F.main(["mde", "--s-int", "0.136", "--s-dw", "0.355", "--boards", "21", "--runs", "8",
                   "--cost-per-run", "0.2333"]) == 0


def test_read_store(tmp_path, monkeypatch):
    import sqlite3
    store = tmp_path / "store"
    (store / "experiments" / "fx").mkdir(parents=True)
    (store / "experiments" / "fx" / "experiment.json").write_text(json.dumps(
        {"methods": [{"id": "m0", "name": "kae fx r00 abc"}, {"id": "m1", "name": "kae fx r01 abc"}],
         "evaluators": {"drc": "drc1", "physics": "phy1"}}))
    for b, own in (("b1", "Alice"), ("b2", "bob")):
        (store / "boards" / b).mkdir(parents=True)
        (store / "boards" / b / "board.json").write_text(json.dumps({"repo": f"https://github.com/{own}/proj"}))
    c = sqlite3.connect(store / "index.sqlite")
    c.execute("create table runs(board, run, method_id, method_name, attempt, task_id, status, runtime_s, cpu_s, "
              "max_rss_mb, final_state, timed_out, experiment, path)")
    c.execute("create table evals(board, run, evaluator, clean, valid, completion, unconnected, errors, "
              "errors_by_type, wl_ratio, via_delta, physics_total, physics_modules, json)")
    for b in ("b1", "b2"):
        for m in ("m0", "m1"):
            run = f"{b}-{m}"
            c.execute("insert into runs(board, run, method_id, attempt, experiment) values (?,?,?,?,?)",
                      (b, run, m, 0, "fx"))
            c.execute("insert into evals(board, run, evaluator, clean, valid, unconnected, json) values (?,?,?,?,?,?,?)",
                      (b, run, "drc1", 1, 1, 0, json.dumps({"score": {"track_length_mm": 100.0, "vias": 3}})))
            mods = {"U1": {"kind": "decap", "value": 2.0, "open_hops": 0},
                    "U2": {"kind": "decap", "value": 8.0, "open_hops": 0},
                    "U3": {"kind": "decap", "value": 99.0, "open_hops": 1}}
            c.execute("insert into evals(board, run, evaluator, valid, json) values (?,?,?,?,?)",
                      (b, run, "phy1", 1, json.dumps({"physics": {"modules": mods}})))
    c.commit()
    plan = F.make_plan([F.parse_factor("fx:on=fx=1")])
    runs, owners = F.read_store("fx", plan, store=store)
    assert len(runs) == 4 and {r["arm"] for r in runs} == {"r00", "r01"}
    assert owners == {"b1": "alice", "b2": "bob"}
    r = runs[0]
    assert r["opens"] == 0 and r["length"] == 100.0 and r["vias"] == 3
    assert r["phys_decap"] == pytest.approx(4.0)                  # geometric mean, the open module left out
    runs2, _ = F.read_store("fx", plan, store=store, arm_map={"r00": "r01", "r01": "r00"})
    assert {(r["board"], r["arm"]) for r in runs2} == {(r["board"], r["arm"]) for r in runs}
