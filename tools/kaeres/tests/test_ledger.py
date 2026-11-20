# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The connection ledger on a tiny synthetic results store."""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger as LG  # noqa: E402

EV = "ev0000000001"
MA, MB = "aaaaaaaa1111", "bbbbbbbb2222"     # route method (DRC list), staged-like method (blocked only)

PCB = """(kicad_pcb
\t(footprint "Package_QFP:LQFP-16"
\t\t(property "Reference" "U1")
""" + "".join(f'\t\t(pad "{i}" smd rect)\n' for i in range(1, 17)) + """\t)
\t(footprint "R_0402"
\t\t(property "Reference" "R1")
\t\t(pad "1" smd rect)
\t\t(pad "2" smd rect)
\t)
\t(zone (net 1) (net_name "GND"))
)
"""


def pad_item(pad, net, ref, x=1.0, y=2.0):
    return dict(description=f"Pad {pad} [{net}] of {ref} on F.Cu", pos=dict(x=x, y=y))


def wgz(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def wj(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "store"
    exp = root / "experiments" / "exp1"
    wj(exp / "experiment.json", dict(name="exp1", evaluators=dict(drc=EV),
                                     methods=[dict(id=MA, name="route-a"), dict(id=MB, name="staged-b")]))
    (exp / "results.csv").write_text("board,pads,layers\nb1,18,2\nb2,2000,4\n")
    runs = [("b1", "ra1", MA, 0, "t1", "ok", 3), ("b1", "rb1", MB, 0, "t1", "ok", 3),
            ("b2", "ra2", MA, 0, "t2", "ok", 0), ("b2", "rb2", MB, 0, "t2", "ok", 2)]
    db = sqlite3.connect(root / "index.sqlite")
    db.execute("create table methods(id TEXT PRIMARY KEY, name TEXT, kind TEXT, runner TEXT, version TEXT, json TEXT)")
    db.execute("create table boards(id TEXT PRIMARY KEY, layers INT, footprints INT, nets INT, collection TEXT, license_tier TEXT)")
    db.execute("create table runs(board TEXT, run TEXT, method_id TEXT, method_name TEXT, attempt INT, task_id TEXT, "
               "status TEXT, experiment TEXT, path TEXT)")
    db.execute("create table evals(board TEXT, run TEXT, evaluator TEXT, unconnected INT)")
    db.executemany("insert into methods(id, name) values (?, ?)", [(MA, "route-a"), (MB, "staged-b")])
    db.executemany("insert into boards(id, layers) values (?, ?)", [("b1", 2), ("b2", 4)])
    for b, r, m, att, t, st, unc in runs:
        db.execute("insert into runs values (?,?,?,?,?,?,?,?,?)", (b, r, m, "", att, t, st, "exp1", "/elsewhere"))
        db.execute("insert into evals values (?,?,?,?)", (b, r, EV, unc))
    db.commit()
    db.close()
    B = root / "boards"
    # b1, method A: DRC list of 3 opens + a `blocked` block diagnosing 2, 1 left undiagnosed by the cap
    ra = B / "b1" / "runs" / "ra1"
    wgz(ra / "evals" / f"{EV}.drc.json.gz", dict(unconnected_items=[
        dict(items=[pad_item("3", "/D0", "U1"), pad_item("1", "/D0", "R1")]),
        dict(items=[pad_item("4", "GND", "U1"), dict(description="Zone [GND] on F.Cu", pos=dict(x=0, y=0))]),
        dict(items=[pad_item("5", "/D1", "U1"), dict(description="Track [/D1] on B.Cu, length 2.0 mm", pos=dict(x=3, y=3))]),
    ]))
    wj(ra / "restart-report.json", dict(mode="fresh", blocked=dict(
        blocked=[dict(net="/D1", pads=["U1.5"], kinds=["pad"], cause="rule",
                      binding=dict(constraint="track_width", against="pad U1.6", where="board setup"))],
        congestion=[dict(net="GND", pads=["U1.4"], kinds=["pad", "fill"], cause="congestion")],
        undiagnosed=1)))
    wgz(ra / "output.kicad_pcb.gz", PCB)
    # b1, method B: no DRC list; restart-report-windows.json final.blocked covers 2 of 3 opens
    rb = B / "b1" / "runs" / "rb1"
    wj(rb / "restart-report-windows.json", dict(final=dict(blocked=dict(
        blocked=[dict(net="/D2", pads=["R1.2"], kinds=["pad"], cause="geometry", walled_by=["netless pad"])],
        congestion=[dict(net="/D0", pads=["U1.3"], kinds=["pad"], cause="congestion")], undiagnosed=1))))
    wgz(rb / "output.kicad_pcb.gz", PCB)
    # b2, method B: opens but no report at all
    (B / "b2" / "runs" / "rb2").mkdir(parents=True)
    (B / "b2" / "runs" / "ra2").mkdir(parents=True)
    # human DRC: /D2 R1.2 open in the human board
    wgz(B / "b1" / "tasks" / "t1" / "human-drc.json.gz", dict(unconnected_items=[
        dict(items=[pad_item("2", "/D2", "R1"), pad_item("9", "/D2", "U1")])]))
    tags = tmp_path / "tags"
    (tags / "bus").mkdir(parents=True)
    (tags / "bus" / "buses.jsonl").write_text(json.dumps(
        dict(board="b1", kind="parallel", swap_a="mcu_gpio", swap_b="", nets=[["/D0"], ["/D1"]])) + "\n")
    monkeypatch.setenv("KAE_RESULTS", str(root))
    return root, tags, tmp_path / "out"


def build(store, *extra):
    root, tags, out = store
    LG.main(["build", "--experiment", "exp1", "--tags", str(tags), "--out", str(out), *extra])
    rows = [json.loads(x) for x in (out / "ledger.jsonl").read_text().splitlines()]
    runs = [json.loads(x) for x in (out / "runs.jsonl").read_text().splitlines()]
    return out, rows, runs


def test_runs_one_row_each_with_sources(store):
    out, rows, runs = build(store)
    assert len(runs) == 4 and sum(r["opens"] for r in runs) == 8
    by = {r["run"]: r for r in runs}
    assert by["ra1"]["drc_list"] and by["ra1"]["has_blocked"] and by["ra1"]["blocked_source"] == "restart-report.json:blocked"
    assert not by["rb1"]["drc_list"] and by["rb1"]["blocked_source"] == "restart-report-windows.json:final.blocked"
    assert by["ra2"]["opens"] == 0 and by["rb2"]["blocked_source"] == "no report"
    assert by["ra1"]["board_pads"] == 18 and by["ra1"]["board_size"] == "<=200" and by["rb2"]["board_size"] == ">1000"
    # one ledger row per open
    assert len(rows) == 8
    assert (by["ra1"]["diagnosed"], by["ra1"]["capped"]) == (2, 1)
    assert by["rb2"]["not_attempted"] == 2


def test_drc_rows_match_diagnosis(store):
    _, rows, _ = build(store)
    a = {r["net"]: r for r in rows if r["run"] == "ra1"}
    d1 = a["/D1"]
    assert d1["source"] == "drc" and d1["cause_class"] == "rule"
    assert d1["cause_detail"]["constraint"] == "track_width"
    assert d1["a"] == dict(ref="U1", pad="5", kind="pad", pos=[1.0, 2.0]) and d1["b"]["kind"] == "track"
    assert d1["a_part_pads"] == 16 and d1["a_size"] == ">=16"
    assert d1["bus"] == "parallel" and d1["swap_class"] == "mcu_gpio"
    gnd = a["GND"]
    assert gnd["role"] == "ground" and gnd["zone_involved"] and gnd["cause_class"] == "pour_island"
    d0 = a["/D0"]
    assert d0["status"] == "undiagnosed" and d0["cause_class"] == "undiagnosed_cap"
    assert d0["b_size"] == "2" and d0["role"] == "signal"


def test_blocked_rows_inherited_and_count_rows(store):
    _, rows, _ = build(store)
    b = [r for r in rows if r["run"] == "rb1"]
    assert sorted(r["source"] for r in b) == ["blocked", "blocked", "count"]
    d2 = next(r for r in b if r["net"] == "/D2")
    assert d2["cause"] == "geometry" and d2["inherited"] == "pad" and d2["cause_class"] == "inherited"
    d0 = next(r for r in b if r["net"] == "/D0")
    assert d0["cause_class"] == "congestion" and d0["cause_detail"]["shape"] == "bare pin of a part with >=16 pads"
    assert d0["inherited"] is False
    cnt = next(r for r in b if r["source"] == "count")
    assert cnt["cause_class"] == "undiagnosed_cap" and cnt["net"] is None
    none = [r for r in rows if r["run"] == "rb2"]
    assert {r["cause_class"] for r in none} == {"no_diagnosis_stored"} and none[0]["inherited"] is None


def test_methods_filter_by_name_and_prefix(store):
    _, rows, runs = build(store, "--methods", "staged-b")
    assert {r["method_id"] for r in runs} == {MB}
    _, _, runs = build(store, "--methods", "aaaa")
    assert {r["method_id"] for r in runs} == {MA}
    with pytest.raises(SystemExit):
        build(store, "--methods", "nope")


def test_store_untouched(store):
    root = store[0]
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    build(store)
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


def test_report_and_reach(store, capsys):
    out, _, _ = build(store)
    LG.main(["report", str(out), "--pair", "route-a,staged-b"])
    md = (out / "LEDGER.md").read_text()
    for h in ("## Coverage", "## Taxonomy", "## Cause x net role", "## Persistence", "## Concentration", "## Unclassified share"):
        assert h in md
    assert "| route-a (aaaaaaaa) | 2 | 2 | 1 | 3 | 1 | 0 | 1 | 2 (67%) | 1 (33%) | 0 (0%) |" in md
    # staged-b names only 2 of its 3 opens on b1, so no board is listed completely by both
    assert "on the 0 boards both list completely" in md
    head, runs, rows = LG.load(out)
    for r in runs:
        if r["run"] == "rb1":
            r["records"] = 3        # pretend staged-b named every open
    lines = LG.persistence(rows, runs, MA, MB)
    # route-a's /D0 open (U1.3 - R1.1) is also open under staged-b (island U1.3)
    assert "connection also open under bbbbbbbb 1 (33%) of those" in lines[0]
    capsys.readouterr()
    LG.main(["reach", str(out), "--a", "route-a", "--b", "staged-b"])
    txt = capsys.readouterr().out
    assert "complete only under aaaaaaaa 1" in txt and "both open, different connections 1" in txt
    assert "| b1 | 3 | 3 | 2 | 1 | 18 |" in txt


def test_parse_item_kinds():
    assert LG.parse_item(dict(description="Via [GND] on F.Cu - B.Cu"))["kind"] == "via"
    assert LG.parse_item(dict(description="Zone [GND] on In1.Cu"))["kind"] == "zone"
    assert LG.parse_item(dict(description="PTH pad 1 [VCC] of J1"))["ref"] == "J1"
    assert LG.net_role("/VCC_3V3", set()) == "power" and LG.net_role("/SIG", {"/SIG"}) == "power"
