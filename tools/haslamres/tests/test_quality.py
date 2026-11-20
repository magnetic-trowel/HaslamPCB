# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""quality.py on small synthetic result tables: endpoints, pairing, intervals and verdict words (stdlib only)."""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality as Q  # noqa: E402


def row(board, method, opens=0, owner=None, pads=100, length=100.0, vias=4, errors=None, xc=None, status="ok", valid=True,
        kind="route", phys="p1", drc="d1"):
    """A results.csv row as csv.DictReader gives it: every value a string."""
    failed = status != "ok"
    return dict(board=board, method=method, attempt="0", status=status, valid="" if failed else str(valid),
                unconnected="" if failed else str(opens), pads=str(pads), track_length_mm="" if failed else str(length),
                vias="" if failed else str(vias), errors_by_type=json.dumps(errors or {}), kind=kind,
                xc=str(opens == 0 and not failed) if xc is None else str(xc), run=f"{method}.a0",
                repo=f"https://github.com/{owner or 'own-' + board}/repo-{board}", evaluator_physics=phys, evaluator_drc=drc)


def arms(a_rows, b_rows):
    by = Q.by_method([Q.typed(r) for r in a_rows + b_rows])
    return by["A"], by["B"]


def test_typed_reads_csv_strings_and_owner_groups_repositories():
    r = Q.typed(row("b1", "A", opens=3, errors={"silk_overlap": 2}, owner="Acme"))
    assert r["unconnected"] == 3 and r["valid"] is True and r["xc"] is False and r["errors_by_type"] == {"silk_overlap": 2}
    assert r["owner"] == "github.com/acme" == Q.owner_of("https://github.com/ACME/other", "x")
    assert Q.owner_of("", "b9") == "board:b9"
    f = Q.typed(row("b2", "A", status="no_output"))
    assert f["unconnected"] is None and f["valid"] is None and not Q.scored(f) and not Q.closed(f)


def test_clopper_pearson_and_verdict_words():
    lo, hi = Q.clopper_pearson(0, 10)
    assert lo == 0.0 and abs(hi - 0.3085) < 1e-3
    lo, hi = Q.clopper_pearson(5, 10)
    assert abs(lo - 0.1871) < 1e-3 and abs(hi - 0.8129) < 1e-3
    assert Q.verdict(20, 0.8, 0.9, 1.0) == "better" and Q.verdict(20, 1.1, 1.2, 1.0) == "worse"
    assert Q.verdict(20, 0.9, 1.0, 1.0) == "undecided"          # the interval includes no change
    assert Q.verdict(20, 0.1, 0.4, 0.5, lower_better=False) == "worse"
    assert Q.verdict(9, 0.8, 0.9, 1.0) == "unknown"


def test_near_miss_counts_closures_both_ways():
    # 12 boards A leaves 1-5 open: B closes 10, leaves one as it was and fails on one. B leaves 1 near-miss A closed.
    a = [row(f"n{i}", "A", opens=1 + i % 5) for i in range(12)] + [row("m0", "A", opens=0), row("far", "A", opens=6)]
    b = ([row(f"n{i}", "B", opens=0) for i in range(10)] + [row("n10", "B", opens=1), row("n11", "B", status="no_output"),
         row("m0", "B", opens=2), row("far", "B", opens=0)])
    r = Q.near_miss(*arms(a, b))
    assert (r["near_a"], len(r["won"]), r["near_b"], len(r["lost"])) == (12, 10, 2, 1)
    assert (r["fewer"], r["same"], r["more"]) == (0, 1, 1)      # the failed run is neither closed nor fewer
    assert r["n"] == 13 and r["verdict"] == "better" and r["lo"] > 0.5 and r["p"] < 0.05
    back = Q.near_miss(*reversed(arms(a, b)))
    assert back["verdict"] == "worse" and len(back["won"]) == 1 and len(back["lost"]) == 10


def test_near_miss_is_unknown_on_few_boards_and_undecided_when_even():
    a = [row(f"n{i}", "A", opens=2) for i in range(4)]
    b = [row(f"n{i}", "B", opens=0) for i in range(4)]
    assert Q.near_miss(*arms(a, b))["verdict"] == "unknown"
    a = [row(f"n{i}", "A", opens=2 if i < 6 else 0) for i in range(12)]
    b = [row(f"n{i}", "B", opens=0 if i < 6 else 2) for i in range(12)]
    r = Q.near_miss(*arms(a, b))
    assert (len(r["won"]), len(r["lost"])) == (6, 6) and r["verdict"] == "undecided" and r["p"] == 1.0


def test_big_board_opens_use_only_big_boards_and_log_differences():
    small = [row(f"s{i}", "A", opens=50) for i in range(20)], [row(f"s{i}", "B", opens=0) for i in range(20)]
    a = [row(f"g{i}", "A", opens=100 + i, pads=1500) for i in range(12)] + small[0]
    b = [row(f"g{i}", "B", opens=40 + i, pads=1500) for i in range(11)] + [row("g11", "B", pads=1500, status="no_output")] + small[1]
    r = Q.big_opens(*arms(a, b))
    assert r["n"] == 11 and r["unscored"] == 1 and r["opens_a"] == sum(range(100, 111)) and r["verdict"] == "better"
    assert r["hi"] < 0 and -1.0 < r["est"] < -0.7               # log(41 / 101) .. log(51 / 111)
    few = Q.big_opens(*arms(a[:9], b[:9]))
    assert few["n"] == 9 and few["est"] is None and few["verdict"] == "unknown"
    assert Q.big_opens(*arms(small[0], small[1]))["n"] == 0     # the small boards' opens never enter this endpoint


def test_one_owner_gives_no_interval():
    a = [row(f"g{i}", "A", opens=100, pads=2000, owner="one") for i in range(12)]
    b = [row(f"g{i}", "B", opens=10, pads=2000, owner="one") for i in range(12)]
    r = Q.big_opens(*arms(a, b))
    assert r["n"] == 12 and r["owners"] == 1 and r["verdict"] == "unknown" and r["est"] is None


def test_xc_is_paired_and_marks_placing_methods():
    a = [row(f"b{i}", "A", xc=True) for i in range(12)] + [row("u", "A", xc="")]
    b = [row(f"b{i}", "B", xc=i >= 8, kind="joint-fixed") for i in range(12)] + [row("u", "B", xc=True)]
    r = Q.xc_pair(*arms(a, b))
    assert r["n"] == 12 and (r["higher"], r["lower"]) == (0, 8) and r["verdict"] == "worse" and r["placing"]
    assert abs(r["share_b"] - 4 / 12) < 1e-9 and r["p"] < 0.05
    assert not Q.xc_pair(*arms(a, [dict(x, kind="route") for x in b]))["placing"]


def _quality_tables(n=12, ratio=0.9):
    a = [row(f"b{i}", "A", length=100.0 + i, vias=9, errors={"solder_mask_bridge": 1}) for i in range(n)]
    b = [row(f"b{i}", "B", length=(100.0 + i) * ratio, vias=4, errors={"solder_mask_bridge": 3, "silk_overlap": 1}) for i in range(n)]
    a += [row("open", "A", opens=2, length=10.0), row("pads", "A", length=0.0)]
    b += [row("open", "B", opens=0, length=1000.0), row("pads", "B", length=0.0)]
    return a, b


def test_quality_pairs_only_boards_both_finish():
    q = Q.quality(*arms(*_quality_tables()))
    r = {x["key"]: x for x in q["rows"]}
    assert q["n"] == 13                                         # "open" is finished by B only
    tl = r["track length"]
    assert tl["n"] == 12 and abs(tl["est"] - 0.9) < 1e-9 and tl["hi"] < 1 and tl["verdict"] == "better"   # no ratio without track
    assert abs(r["vias"]["est"] - 0.5) < 1e-9 and r["vias"]["n"] == 13
    mask = r["errors added: solder_mask_bridge"]
    assert abs(mask["est"] - 2 * 12 / 13) < 1e-9 and mask["verdict"] == "worse" and (mask["lower"], mask["same"], mask["higher"]) == (0, 1, 12)
    assert r["errors added: silk_edge_clearance"]["verdict"] == "undecided" and r["errors added: silk_edge_clearance"]["est"] == 0
    assert not any(k.startswith("physics") for k in r)          # no physics without a module reader


def test_quality_is_unknown_under_ten_boards():
    q = Q.quality(*arms(*_quality_tables(n=8)))
    r = {x["key"]: x for x in q["rows"]}
    assert r["track length"]["n"] == 8 and r["track length"]["est"] is None and r["track length"]["verdict"] == "unknown"
    assert r["errors added: solder_mask_bridge"]["verdict"] == "unknown"


def test_physics_pairs_modules_by_id_and_kind():
    a, b = _quality_tables()
    a += [row(f"u{i}", "A", opens=3) for i in range(12)]        # scored by both, finished by neither
    b += [row(f"u{i}", "B", opens=3) for i in range(12)]

    def modules(r):
        m = dict(decap=dict(kind="decap", value=10.0, open_hops=0), loop=dict(kind="cell", value=4.0, open_hops=0),
                 xtal=dict(kind="crystal", value=5.0, open_hops=0), only_a=dict(kind="chain", value=1.0, open_hops=0))
        if r["method"] == "B":
            m = dict(decap=dict(kind="decap", value=8.0, open_hops=0), loop=dict(kind="cell", value=6.0, open_hops=0),
                     xtal=dict(kind="crystal", value=1.0, open_hops=1), new=dict(kind="chain", value=1.0, open_hops=0))
        if r["board"].startswith("u"):                          # hot loops only on the boards neither finishes
            return dict(loop=m["loop"])
        return dict(m, loop=dict(kind="cell", value=None, open_hops=0))
    q = Q.quality(*arms(a, b), modules=modules)
    r = {x["key"]: x for x in q["rows"]}
    d = r["physics: decap"]
    assert d["n"] == 13 and d["items"] == 13 and abs(d["est"] - 0.8) < 1e-9 and d["verdict"] == "better"
    assert r["physics: hot-loop cell"]["n"] == 0 and r["physics: hot-loop cell"]["verdict"] == "unknown"
    assert r["physics: crystal"]["n"] == 0                      # an open hop in one arm: no pair
    assert r["physics: chain"]["n"] == 0                        # different module ids never pair
    loop = r["physics, unfinished boards too: hot-loop cell"]
    assert loop["n"] == 12 and abs(loop["est"] - 1.5) < 1e-9 and loop["verdict"] == "worse"
    assert r["physics, unfinished boards too: decap"]["n"] == 14    # plus the board only B finishes


def test_physics_of_two_evaluators_is_not_paired():
    a, b = _quality_tables()
    b = [dict(x, evaluator_physics="p2", evaluator_drc="d2") for x in b]
    q = Q.quality(*arms(a, b), modules=lambda r: dict(decap=dict(kind="decap", value=1.0 if r["method"] == "A" else 9.0, open_hops=0)))
    phys = [x for x in q["rows"] if x["key"].startswith("physics")]
    assert q["foreign_physics"] == q["n"] == q["foreign_drc"] == 13
    assert len(phys) == 1 and phys[0]["n"] == 0 and phys[0]["verdict"] == "unknown"


def test_reach_counts_identical_outcomes():
    a = [row("same", "A", errors={"clearance": 1}), row("copper", "A", length=5.0), row("opens", "A", opens=1),
         row("errs", "A"), row("fail", "A")]
    b = [row("same", "B", errors={"clearance": 1}), row("copper", "B", length=6.0), row("opens", "B", opens=2),
         row("errs", "B", errors={"clearance": 1}), row("fail", "B", status="no_output")]
    assert Q.reach(*arms(a, b)) == dict(n=4, unscored=1, same=2, same_copper=1)


def test_report_keeps_the_endpoints_apart_and_states_unknown(tmp_path):
    a, b = _quality_tables()
    a += [row(f"g{i}", "A", opens=100, pads=1500) for i in range(3)]
    b += [row(f"g{i}", "B", opens=10, pads=1500) for i in range(3)]
    human = [row(f"b{i}", "human", length=200.0, vias=9, drc="d0", phys="p0") for i in range(12)]
    src = tmp_path / "results.csv"
    with open(src, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(a[0]))
        w.writeheader()
        w.writerows(a + b + human)
    rows = Q.load_rows(src)
    text = Q.report(rows, "A", ["B"], modules=lambda r: None, title="synthetic")
    assert "### 1a. Near-miss closure" in text and "### 1b. Big-board opens" in text and "## 3. Reach" in text
    big = next(line for line in text.splitlines() if line.startswith("| B | 3 (3) |"))
    assert "300 → 30" in big and big.count("unknown") == 2      # the raw sums, no estimate and no verdict from 3 boards
    assert "| track length | better (n 12) |" in text and "| big-board opens | unknown (n 3) |" in text
    assert "### B vs human" in text and "### A vs human" in text and "better‡ (n 12)" in text
    assert "| physics: every kind | unknown (n 0) | unknown (n 0) |" in text
    assert "## 5." not in Q.report(rows, "A", ["B"], human=None)
    assert Q.pick("b", ["A", "B", "human"]) == "B"
