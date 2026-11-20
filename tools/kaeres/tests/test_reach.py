# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""reach.py on a synthetic store: board hashes, fingerprints and their cache, stages, compare, precheck."""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reach as R  # noqa: E402


def pcb(r1=(10, 20, 0), track_end=(5, 5), uuid="u1"):
    return f"""(kicad_pcb
\t(version 20240108)
\t(footprint "lib:R"
\t\t(layer "F.Cu")
\t\t(uuid "{uuid}")
\t\t(at {r1[0]} {r1[1]} {r1[2]})
\t\t(property "Reference" "R1"
\t\t\t(at 0 -1 0)
\t\t\t(layer "F.SilkS")
\t\t)
\t)
\t(footprint "lib:C"
\t\t(layer "B.Cu")
\t\t(at 30 40)
\t\t(property "Reference" "C1"
\t\t\t(at 1 1 0)
\t\t)
\t)
\t(segment
\t\t(start 0 0)
\t\t(end {track_end[0]} {track_end[1]})
\t\t(width 0.2)
\t\t(layer "F.Cu")
\t\t(net "GND")
\t\t(uuid "{uuid}-s")
\t)
\t(via
\t\t(at 5 5)
\t\t(size 0.6)
\t\t(uuid "{uuid}-v")
\t)
)
"""


def test_board_hashes_ignore_uuids_and_see_moves():
    p0, c0 = R.board_hashes(pcb())
    assert (p0, c0) == R.board_hashes(pcb(uuid="other"))
    p1, c1 = R.board_hashes(pcb(r1=(11, 20, 0)))
    assert p1 != p0 and c1 == c0
    p2, c2 = R.board_hashes(pcb(track_end=(6, 5)))
    assert p2 == p0 and c2 != c0


def make_run(d, place=(100.0, 5.0, 7), board=None, final=(0, 0, 10.0, 2), ev="drc1"):
    d.mkdir(parents=True)
    with gzip.open(d / "adapter.log.gz", "wt") as f:
        f.write("[kae] start\n")
        if place:
            f.write("[kae] " + json.dumps(dict(seed=0, iterations=[dict(stages=dict(place=dict(hpwl=place[0], scorecard=place[1], crossings=place[2])))])) + "\n")
    with gzip.open(d / "output.kicad_pcb.gz", "wt") as f:
        f.write(board or pcb())
    (d / "evals").mkdir()
    (d / "evals" / f"{ev}.json").write_text(json.dumps(dict(evaluator=ev, at="2026-11-01", score=dict(
        unconnected=final[0], errors=final[1], track_length_mm=final[2], vias=final[3]))))
    (d / "evals" / "phys.json").write_text(json.dumps(dict(evaluator="phys", at="2026-11-02", physics={})))
    return d


def test_fingerprint_and_cache(tmp_path):
    d = make_run(tmp_path / "r")
    fp = R.fingerprint(d, tmp_path / "cache")
    assert fp["place"] == [100.0, 5.0, 7] and fp["final"] == [0, 0, 10.0, 2] and fp["placement"] and fp["copper"]
    assert len(list((tmp_path / "cache").rglob("*.json"))) == 1
    (d / "adapter.log.gz").unlink()                     # cached: the log is not read again
    assert R.fingerprint(d, tmp_path / "cache") == fp
    assert R.fingerprint(d)["place"] is None


def test_stage_order():
    base = dict(place=[1, 2, 3], placement="p", copper="c", final=[0, 0, 1, 1])
    assert R.stage(base, dict(base)) == "none"
    assert R.stage(base, dict(base, place=[1, 2, 4])) == "place"
    assert R.stage(base, dict(base, copper="d")) == "route"
    assert R.stage(base, dict(base, placement="q")) == "route"          # placed the same, moved later
    assert R.stage(dict(base, place=None), dict(base, place=None, placement="q")) == "place"
    assert R.stage(base, dict(base, final=[1, 0, 1, 1])) == "route"


def test_fill_unreached():
    assert R.fill_unreached({"a": 0.5}, ["a", "b"]) == {"a": 0.5, "b": 0.0}


def make_store(tmp):
    """Control A, arm B on boards b1 (never reached), b2 (placement differs at seed 0 only), b3 (copper differs)."""
    c = sqlite3.connect(tmp / "index.sqlite")
    c.executescript("""
      CREATE TABLE methods(id TEXT PRIMARY KEY, name TEXT, kind TEXT, runner TEXT, version TEXT, json TEXT);
      CREATE TABLE runs(board TEXT, run TEXT, method_id TEXT, method_name TEXT, attempt INT, task_id TEXT, status TEXT,
        runtime_s REAL, cpu_s REAL, max_rss_mb REAL, final_state TEXT, timed_out INT, experiment TEXT, path TEXT, PRIMARY KEY(board, run));
      CREATE TABLE evals(board TEXT, run TEXT, evaluator TEXT, clean INT, valid INT, completion REAL, unconnected INT,
        errors INT, errors_by_type TEXT, wl_ratio REAL, via_delta INT, physics_total REAL, physics_modules INT, json TEXT,
        PRIMARY KEY(board, run, evaluator));""")
    for m, name in (("aaaa1111", "ctl"), ("bbbb2222", "arm")):
        c.execute("INSERT INTO methods VALUES(?,?,?,?,?,?)", (m, name, "route", "command", "", "{}"))
    spec = {  # (method, board, seed) -> run kwargs
        ("aaaa1111", "b1", 0): {}, ("bbbb2222", "b1", 0): {}, ("aaaa1111", "b1", 1): {}, ("bbbb2222", "b1", 1): {},
        ("aaaa1111", "b2", 0): {}, ("bbbb2222", "b2", 0): dict(place=(99.0, 5.0, 7), final=(3, 0, 11.0, 2)),
        ("aaaa1111", "b2", 1): {}, ("bbbb2222", "b2", 1): {},
        ("aaaa1111", "b3", 0): {}, ("bbbb2222", "b3", 0): dict(board=pcb(track_end=(6, 5))),
    }
    for (m, b, s), kw in spec.items():
        run = f"{m}.a{s}"
        d = make_run(tmp / "boards" / b / "runs" / run, **kw)
        fin = kw.get("final", (0, 0, 10.0, 2))
        c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (b, run, m, m, s, "t", "ok", 1, 7200.0, 1, "", 0, "e", str(d)))
        c.execute("INSERT INTO evals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (b, run, "drc1", 1, 1, 1.0, fin[0], fin[1], "{}", 1, 0, None, None,
                                                                             json.dumps(dict(score=dict(track_length_mm=fin[2], vias=fin[3])))))
    c.commit()
    e = tmp / "experiments" / "ab"
    e.mkdir(parents=True)
    (e / "experiment.json").write_text(json.dumps(dict(created="2026-11-10", attempts=2, evaluators=dict(drc="drc1"),
                                                       methods=[dict(id="aaaa1111", name="ctl"), dict(id="bbbb2222", name="arm")])))
    (e / "boards.txt").write_text("b1\nb2\nb3\n")
    return tmp


def test_compare_stages_unreached_cpu_and_pilot(tmp_path):
    store = make_store(tmp_path)
    conn = R.connect(store)
    r, = R.compare_experiment(store, conn, "ab", cache=tmp_path / "cache")
    assert r["pairs"] == 5 and r["stages"] == {"none": 3, "place": 1, "route": 1}
    assert r["unreached_boards"] == ["b1"] and r["final_identical"] == 4
    assert abs(r["cpu_both"] - 20.0) < 1e-9 and abs(r["cpu_both_unreached"] - 12.0) < 1e-9 and abs(r["cpu_treatment_unreached"] - 6.0) < 1e-9
    assert r["pilot"] == {"unreached_boards": 1, "unreached_all_later": 1, "unreached_later_pairs": 1, "unreached_later_none": 1,
                          "reached_boards": 1, "reached_all_later": 1, "reached_later_pairs": 1, "reached_later_none": 1}
    f, = R.compare_experiment(store, conn, "ab", final_only=True)
    assert f["stages"] == {"none": 4, "diverged": 1}            # the copper change on b3 is invisible to the final tuple


def test_precheck_and_cli(tmp_path):
    (tmp_path / "s").mkdir()
    store = make_store(tmp_path / "s")
    conn = R.connect(store)
    res = R.precheck(store, conn, "arm", "aaaa", boards={"b1", "b2", "b3", "b4"}, seeds=3, cache=tmp_path / "c")
    assert res["unreached"] == ["b1"] and res["reached"] == ["b2", "b3"] and res["no_pilot"] == ["b4"]
    assert res["cells"] == [[b, s] for b in ("b2", "b3", "b4") for s in (1, 2)]
    assert abs(res["cpu_h_saved_estimate"] - 4.0) < 1e-9
    out = tmp_path / "o"
    assert R.main(["--store", str(store), "--cache", str(tmp_path / "c"), "precheck", "--arm", "bbbb", "--control", "ctl",
                   "--out", str(out)]) == 0
    assert json.loads((out / "reach.json").read_text())["unreached"] == ["b1"]
    assert (out / "cells.txt").read_text().splitlines()[0] == "b2 1"
    assert R.main(["--store", str(store), "--cache", str(tmp_path / "c"), "retro", "--min-pairs", "1", "--fingerprint", "ab", "--out", str(out)]) == 0
    assert "| ab | arm | fingerprint | 5 | 1 / 1 / 3 |" in (out / "REACH.md").read_text()
