# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""suites.py: board history and response from the index, and the four tier suites (stdlib only)."""
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import suites as S  # noqa: E402

SCHEMA = """
CREATE TABLE methods(id TEXT PRIMARY KEY, name TEXT, kind TEXT, runner TEXT, version TEXT, json TEXT);
CREATE TABLE boards(id TEXT PRIMARY KEY, layers INT, footprints INT, nets INT, collection TEXT, license_tier TEXT);
CREATE TABLE runs(board TEXT, run TEXT, method_id TEXT, method_name TEXT, attempt INT, task_id TEXT, status TEXT,
  runtime_s REAL, cpu_s REAL, max_rss_mb REAL, final_state TEXT, timed_out INT, experiment TEXT, path TEXT,
  PRIMARY KEY(board, run));
CREATE TABLE evals(board TEXT, run TEXT, evaluator TEXT, clean INT, valid INT, completion REAL, unconnected INT,
  errors INT, errors_by_type TEXT, wl_ratio REAL, via_delta INT, physics_total REAL, physics_modules INT, json TEXT,
  PRIMARY KEY(board, run, evaluator));
"""
METHODS = dict(A="joint-fixed", B="joint-fixed", R="route", H="route")


def make_index(path, runs):
    """runs: (board, method, attempt, experiment, cpu_s, unconnected or None, clean)."""
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    for m, kind in METHODS.items():
        c.execute("INSERT INTO methods VALUES(?,?,?,?,?,?)", (m, m, kind, "reference" if m == "H" else "command", None, "{}"))
    for b, m, att, exp, cpu, unc, clean in runs:
        run = f"{m}.{exp}.a{att}"
        c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (b, run, m, m, att, "t", "ok", 1.0, cpu, 0, None, 0, exp, ""))
        if unc is not None:
            c.execute("INSERT INTO evals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (b, run, "drc", int(clean), 1, 1.0, unc, 0, "{}", 1, 0, None, None, "{}"))
    c.commit()
    c.close()
    return path


def ab(board, exp, differ, cpu_s, attempts=2):
    """One two-arm experiment's runs of a board: arms A and B, opens differing or not."""
    return [(board, m, att, exp, cpu_s, (1 if differ and m == "B" else 0), not (differ and m == "B"))
            for att in range(attempts) for m in ("A", "B")]


def test_owner_is_the_repository_account():
    assert S.owner_of("https://github.com/Some-One/Repo") == "github.com/some-one"
    assert S.owner_of("https://github.com/some-one/other.git") == "github.com/some-one"
    assert S.owner_of("https://gitlab.com/group/sub/repo") == "gitlab.com/group"
    assert S.owner_of("https://codeberg.org/some-one/x") != S.owner_of("https://github.com/some-one/x")


def test_history_leaves_out_the_reference_sweeps_and_runs_without_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SWEEP_BOARDS", 2)
    runs = [("b1", "A", 0, "e1", 3600, 0, True), ("b1", "B", 0, "e1", 7200, 0, True), ("b1", "H", 0, "e1", 99999, 0, True),
            ("b1", "A", 1, "e1", 0, 0, True), ("b1", "R", 0, "", 99999, 0, True),
            *[(f"s{i}", "R", 0, "sweep", 99999, 0, True) for i in range(3)], ("b1", "R", 0, "sweep", 99999, 0, True)]
    c = S.open_index(make_index(tmp_path / "i.sqlite", runs))
    assert S.history(c) == {"b1": 1.5}


def test_estimator_uses_own_history_then_the_footprint_band():
    hist = {"small1": 0.1, "small2": 0.3, "big": 4.0}
    est = S.estimator(hist, dict(small1=10, small2=15, big=300, new_small=12, new_big=350, new_huge=5000))
    assert est("small1") == (0.1, True)
    assert est("new_small") == (0.2, False) and est("new_big") == (4.0, False)
    assert est("new_huge")[0] == sum(hist.values()) / 3   # no board in its band: the overall mean
    assert S.estimator({}, {})("x") == (0.0, False)


def test_response_counts_pairs_of_two_arm_experiments_only(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "AB_BOARDS", (2, 100))
    runs = []
    for exp, differ in (("e1", True), ("e2", False)):
        runs += ab("b1", exp, differ, 60) + ab("b2", exp, False, 60)
    runs += [(b, m, 0, "three", 60, i, False) for b in ("b1", "b2") for i, m in enumerate("ABR")]   # three arms: not an A/B
    runs += [("b1", "A", 0, "one", 60, 5, False), ("b1", "B", 0, "one", 60, 0, True)]              # one board: too small
    runs += [("b2", "A", 5, "e1", 60, 3, False)]                                                    # no partner: no pair
    c = S.open_index(make_index(tmp_path / "i.sqlite", runs))
    assert S.response(c) == {"b1": dict(pairs=4, resp=0.5, flip=0.5), "b2": dict(pairs=4, resp=0.0, flip=0.0)}
    assert S.placed(c) == {"b1", "b2"}


class Inp:
    """Inputs filled by hand: n boards i0.., each its own owner unless told otherwise."""

    def __init__(self, n):
        ids = [f"i{k}" for k in range(n)]
        self.hist = {b: 0.1 for b in ids}
        self.resp = {b: dict(pairs=4, resp=1.0, flip=0.0) for b in ids}
        self.placed, self.routable, self.human_clean = set(ids), set(ids), set(ids)
        self.footprints = {b: 50 for b in ids}
        self.layers = {b: 2 for b in ids}
        self.owner = {b: f"host/{b}" for b in ids}
        self.tag = {t: set(ids) for t in S.QUALITY_TAGS}
        self.merit, self.pads = [], {}


def test_frontier_ranks_by_response_per_cpu_hour_one_per_owner():
    inp = Inp(12)
    inp.hist.update(i0=0.4, i1=0.05, i2=0.2, i3=0.6, i11=0.05)   # i3 is over the sprint cap
    inp.resp["i4"]["resp"] = 0.25                                 # responds too rarely
    inp.owner["i2"] = inp.owner["i1"]                             # a second board of i1's owner
    inp.footprints["i5"] = 401
    inp.placed.discard("i6")                                      # never ran as a place task
    inp.layers.update(i0=4, i11=4)
    resp, rand = S.frontier(inp, 5, random.Random(1))
    # cheapest first, ties by id; the last place waits for a second board with 4 layers (a quarter, rounded up)
    assert resp == ["i1", "i11", "i10", "i0"] and len(rand) == 1
    assert rand[0] in {"i4", "i7", "i8", "i9"}                    # same cost and size range, any response
    inp.layers["i0"] = 2
    assert S.frontier(inp, 5, random.Random(1))[0] == ["i1", "i11", "i10", "i7"]   # no such board: the next best


def test_frontier_keeps_a_quarter_for_boards_with_four_layers():
    inp = Inp(40)
    for k in range(30, 40):
        inp.layers[f"i{k}"] = 4
        inp.hist[f"i{k}"] = 0.4          # the 4-layer boards rank last
    resp, rand = S.frontier(inp, 20, random.Random(1))
    assert len(resp) == 16 and len(rand) == 4
    assert sum(inp.layers[b] >= 4 for b in resp) == 5   # ceil(20 / 4)
    assert len({inp.owner[b] for b in resp + rand}) == 20


def test_round_robin_fills_cells_evenly_and_passes_on_a_short_cells_share():
    pool = ["a1", "a2", "a3", "a4", "b1"]
    owner = {b: b for b in pool}
    got = S.round_robin(pool, ["a", "b"], lambda b: {b[0]}, 4, set(), owner)
    assert got == ["a1", "b1", "a2", "a3"]
    owner["a2"] = "a1"
    assert S.round_robin(pool, ["a", "b"], lambda b: {b[0]}, 4, set(), owner) == ["a1", "b1", "a3", "a4"]


def test_build_suites_share_no_owner_and_are_deterministic():
    inp = Inp(400)
    for k in range(400):
        b = f"i{k}"
        inp.footprints[b] = 5 + k
        inp.layers[b] = 2 if k % 2 else 4
        if k % 3:
            inp.resp.pop(b)
    inp.footprints["i399"] = 900
    inp.merit, inp.pads = ["i0", "i1"], dict(i0=1200, i1=900)
    sizes = dict(frontier=20, quality=20, ladder=60)
    suites, n_random = S.build(inp, seed=7, sizes=sizes)
    assert S.build(inp, seed=7, sizes=sizes) == (suites, n_random)
    assert S.build(inp, seed=8, sizes=sizes)[0]["ladder"] != suites["ladder"]
    assert [len(suites[k]) for k in ("sprint-frontier", "sprint-quality", "ladder")] == [20, 20, 60] and n_random == 4
    three = suites["sprint-frontier"] + suites["sprint-quality"] + suites["ladder"]
    assert len({inp.owner[b] for b in three}) == len(three)
    lo, hi = S.QUALITY_FOOTPRINTS
    assert all(lo <= inp.footprints[b] <= hi and inp.layers[b] in (2, 4) for b in suites["sprint-quality"])
    assert {inp.layers[b] for b in suites["sprint-quality"]} == {2, 4}
    assert sum(inp.footprints[b] > 150 for b in suites["ladder"]) >= 15 and max(inp.footprints[b] for b in suites["ladder"]) <= 400
    assert suites["canary"] == ["i0", "i396", "i397", "i398", "i399"]   # merit over 1,000 pads; human-clean over 400 footprints
    assert "| `ladder` | 60 | 60 |" in S.summary(inp, suites, n_random)


def test_inputs_read_the_index_the_corpus_and_the_tag_folder(tmp_path):
    ids = [f"b{k}" for k in range(4)]
    make_index(tmp_path / "i.sqlite", [("b0", "A", 0, "e", 1800, 0, True)])
    corpus, tags = tmp_path / "corpus", tmp_path / "tags"
    (tags / "suites").mkdir(parents=True)
    (tags / "structural").mkdir()
    corpus.mkdir()
    (corpus / "manifest.jsonl").write_text("".join(json.dumps(dict(
        id=b, repo=f"https://github.com/Own{k % 2}/r{k}", footprints=10 * k, layers=2)) + "\n" for k, b in enumerate(ids)))
    (tags / "structural" / "usability.jsonl").write_text("".join(json.dumps(dict(
        id=b, usable_route_test=b != "b3", usable_with_reference=b in ("b1", "b3"))) + "\n" for b in ids + ["gone"]))
    for t in S.QUALITY_TAGS:
        (tags / "suites" / f"{t}.txt").write_text("b1\n")
    (tags / "suites" / "human_drc_errors.clean.txt").write_text("# comment\nb1\t# why\nb2\nb3\n")
    (tags / "structural" / "features.jsonl").write_text(json.dumps(dict(n_pads=7, id="b2")) + "\n" + json.dumps(dict(id="b1", n_pads=9)) + "\n")
    (tmp_path / "merit.txt").write_text("b2\nunknown\n")
    inp = S.Inputs(tmp_path / "i.sqlite", tags, corpus, tmp_path / "merit.txt")
    assert inp.hist == {"b0": 0.5} and inp.placed == {"b0"}
    assert inp.owner["b2"] == "github.com/own0" and inp.footprints["b3"] == 30
    assert inp.routable == {"b0", "b1", "b2"} and inp.human_clean == {"b1"}   # b2: no trusted reference; b3: not routable
    assert inp.merit == ["b2"] and inp.pads == {"b2": 7}
