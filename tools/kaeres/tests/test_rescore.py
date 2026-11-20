# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""rescore.py on a synthetic store: pairing, near-miss counts both ways, board size from the task, pooling, outputs."""
import csv
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rescore as R  # noqa: E402


def make_store(tmp, opens, pads=None, footprints=None, created="2026-11-10", extra_exps=()):
    """opens[method][board] = list of (opens, track length) per attempt; method 'A' is the control."""
    pads, footprints = pads or {}, footprints or {}
    c = sqlite3.connect(tmp / "index.sqlite")
    c.executescript("""
      CREATE TABLE boards(id TEXT PRIMARY KEY, layers INT, footprints INT, nets INT, collection TEXT, license_tier TEXT);
      CREATE TABLE runs(board TEXT, run TEXT, method_id TEXT, method_name TEXT, attempt INT, task_id TEXT, status TEXT,
        runtime_s REAL, cpu_s REAL, max_rss_mb REAL, final_state TEXT, timed_out INT, experiment TEXT, path TEXT, PRIMARY KEY(board, run));
      CREATE TABLE evals(board TEXT, run TEXT, evaluator TEXT, clean INT, valid INT, completion REAL, unconnected INT,
        errors INT, errors_by_type TEXT, wl_ratio REAL, via_delta INT, physics_total REAL, physics_modules INT, json TEXT,
        PRIMARY KEY(board, run, evaluator));""")
    boards = sorted({b for m in opens.values() for b in m})
    for b in boards:
        c.execute("INSERT INTO boards VALUES(?,?,?,?,?,?)", (b, 2, footprints.get(b, 10), 5, "x", "t"))
        if b in pads:
            t = tmp / "boards" / b / "tasks" / "t1"
            t.mkdir(parents=True)
            (t / "task.json").write_text(json.dumps(dict(record=dict(tasks=dict(route=dict(input_stats=dict(pads=pads[b])))))))
    for m, per in opens.items():
        for b, atts in per.items():
            for a, (u, ln) in enumerate(atts):
                run = f"{m}.a{a}"
                c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (b, run, m, m, a, "t1", "ok", 1, 3600.0, 1, "", 0, "e", str(tmp / b / run)))
                c.execute("INSERT INTO evals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (b, run, "drc1", int(u == 0), 1, 1.0, u, 0, "{}", 1.0, 0, None, None,
                           json.dumps(dict(score=dict(track_length_mm=ln, vias=2)))))
    c.commit()
    for name, methods, cr in [("ab", list(opens), created)] + list(extra_exps):
        e = tmp / "experiments" / name
        e.mkdir(parents=True)
        (e / "experiment.json").write_text(json.dumps(dict(created=cr, attempts=3, evaluators=dict(drc="drc1"),
                                                           methods=[dict(id=m, name=f"arm {m}") for m in methods])))
        (e / "boards.txt").write_text("\n".join(boards))
    return tmp


OPENS = {
    "A": {"b1": [(2, 10.0), (0, 10.0), (0, 10.0)], "b2": [(3, 5.0), (3, 5.0), (0, 5.0)], "big1": [(10, 9.0), (20, 9.0), (30, 9.0)],
          "b3": [(0, 1.0), (0, 1.0), (0, 1.0)]},
    "B": {"b1": [(0, 11.0), (1, 10.0), (0, 10.0)], "b2": [(0, 5.0), (0, 6.0), (0, 5.0)], "big1": [(5, 9.0), (10, 9.0), (15, 9.0)],
          "b3": [(0, 1.0), (0, 1.0), (0, 1.0)]},
}


def run(tmp, **kw):
    store = make_store(tmp, OPENS, pads={"big1": 1500, "b1": 20}, footprints={"b2": 900}, **kw)
    conn = R.connect(store)
    sizes = R.Sizes(store, conn)
    return R.rows_of(R.load(store, conn, min_runs=1), sizes, min_pairs=1), sizes


def test_near_miss_both_ways_and_identical(tmp_path):
    rows, _ = run(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["pairs"] == 12
    # b1: a0 B closes (2 -> 0); a1 A closes (B 1, A 0). b2: a0, a1 B closes.
    assert (r["nm_b"], r["nm_a"]) == (3, 1)
    assert r["nearA"] == 3
    # board level: b1 nets to 0, b2 to B
    assert (r["bb"], r["ba"]) == (1, 0)
    # identical: b1 a2, b2 a2, b3 x3 (b2 a1 differs in length only)
    assert r["ident"] == 5
    assert math.isclose(r["cpu_all"], 24.0) and math.isclose(r["cpu_ident"], 10.0)


def test_board_size_from_task_pads_then_footprints(tmp_path):
    rows, sizes = run(tmp_path)
    r = rows[0]
    # big1 has 1500 task pads; b2 has no task but 900 footprints; b1 has 20 task pads (small); b3 neither.
    assert set(r["big"]) == {"big1", "b2"} and set(r["mid"]) == {"b1", "b3"}
    want = sum(math.log1p(b) - math.log1p(a) for a, b in ((10, 5), (20, 10), (30, 15))) / 3
    assert math.isclose(r["big"]["big1"], want) and want < 0
    assert sizes.source["task pads"] >= 2 and sizes.source["footprints"] >= 2


def test_signp_exact():
    assert R.signp(0, 0) == 1.0
    assert math.isclose(R.signp(5, 0), 2 / 32)
    assert math.isclose(R.signp(1, 3), R.signp(3, 1))
    assert math.isclose(R.signp(2, 2), 1.0)


def test_pool_fixed_effect_and_q():
    def row(vals, nb=0, na=0):
        return dict(nm_b=nb, nm_a=na, bb=0, ba=0, nearA=0, pairs=1, ident=0, big={}, mid={f"x{i}": v for i, v in enumerate(vals)})
    p = R.pool([row([0.1, 0.2, 0.3], 4, 0), row([0.0, 0.1, 0.2, 0.3, 0.4], 0, 1)])
    m1, s1, _ = R.mean_se({i: v for i, v in enumerate([0.1, 0.2, 0.3])})
    m2, s2, _ = R.mean_se({i: v for i, v in enumerate([0.0, 0.1, 0.2, 0.3, 0.4])})
    w1, w2 = 1 / s1 ** 2, 1 / s2 ** 2
    m = (w1 * m1 + w2 * m2) / (w1 + w2)
    assert math.isclose(p["mid"]["mean"], m) and math.isclose(p["mid"]["se"], (w1 + w2) ** -0.5)
    assert math.isclose(p["mid"]["Q"], w1 * (m1 - m) ** 2 + w2 * (m2 - m) ** 2) and p["mid"]["df"] == 1
    assert p["big"] is None and (p["nm_b"], p["nm_a"]) == (4, 1) and math.isclose(p["p_pair"], R.signp(4, 1))


def test_pick_exact_id_substring_and_ambiguous():
    rows = [dict(exp="e", arm="kae x", method_id="aaaa1111"), dict(exp="e", arm="kae x neck", method_id="bbbb2222")]
    assert R.pick(rows, "e", "kae x")["method_id"] == "aaaa1111"
    assert R.pick(rows, "e", "bbbb")["arm"] == "kae x neck"
    assert R.pick(rows, "e", "neck")["arm"] == "kae x neck"
    assert isinstance(R.pick(rows, "e", "kae"), list) and R.pick(rows, "f", "kae x") is None


def test_filters_old_and_smoke_experiments(tmp_path):
    rows, _ = run(tmp_path, created="2026-10-01", extra_exps=[("ab-smoke", ["A", "B"], "2026-11-10")])
    assert rows == []


def test_cli_writes_markdown_and_csv(tmp_path):
    (tmp_path / "s").mkdir()
    store = make_store(tmp_path / "s", OPENS, pads={"big1": 1500})
    (tmp_path / "pool.tsv").write_text("ab\tarm B\nab\tnothing  # missing\n")
    assert R.main(["--store", str(store), "--pool", str(tmp_path / "pool.tsv"), "--out", str(tmp_path / "o")]) == 0
    md = (tmp_path / "o" / "RESCORE.md").read_text()
    assert "| ab | arm B | 12 |" in md and "named arms" in md and "ab\tnothing: no arm" in md
    rows = list(csv.DictReader(open(tmp_path / "o" / "rescore.csv")))
    assert len(rows) == 1 and rows[0]["b_closes"] == "3" and rows[0]["a_closes"] == "1"
