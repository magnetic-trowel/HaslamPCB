# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/commander/commander.py with a fake COMMAND whose opens depend on the --set flags it got."""
import importlib.util
import json
import shlex
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kae_commander", HERE.parent / "commander.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
TOP = HERE.parent / "choosers/top_item.py"

FAKE = r'''
import json, sys
out, rep, seed, kind = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
sets = [sys.argv[i + 1] for i in range(5, len(sys.argv) - 1) if sys.argv[i] == "--set"]
opens = 10 + seed % 2
for s in sets:
    opens += {"planes=strict": 5, "neckdown=true": -4, "bridge.neckdown=true": -4, "rounds=auto": -3,
              "bridge.rounds=auto": -3, "neckdown=clean": -100}.get(s, 0)
opens = max(opens, 0)
open(out, "w").write(f"board {opens} {' '.join(sets)}\n")
fin = {"unconnected": opens, "errors": 0}
json.dump({"final": fin} if kind == "joint" else {"repair": {"final": fin}}, open(rep, "w"))
'''


def item(id_, kv, effect="full", kind="set", scorer="allowed", rank=1):
    k, _, v = kv.partition("=")
    return dict(id=id_, rank=rank, score=1.0, price=dict(scorer=scorer),
                knob=dict(kind=kind, effect=effect, route=["--set", kv] if kv else None,
                          joint=["--set", (k if k == "planes" else "bridge." + k) + "=" + v] if kv else None))


MENU = [item("forbidden", "neckdown=true", scorer="forbidden"), item("rotate_part", "", kind="edit_input"),
        item("via_in_pad", "neckdown=true", effect="plan_only"), item("planes_strict", "planes=strict"),
        item("neckdown", "neckdown=true"), item("more_effort", "rounds=auto")]


@pytest.fixture
def board(tmp_path, monkeypatch):
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE)
    inp = tmp_path / "in.kicad_pcb"
    inp.write_text("input\n")
    monkeypatch.setattr(C, "build_menu", lambda reports, kind: {"menu": [dict(i) for i in MENU]})
    return tmp_path, fake, inp


def go(board, commander, k=4, kind="route", extra=(), seed=0):
    tmp, fake, inp = board
    out, log = tmp / "out.kicad_pcb", tmp / f"log-{commander}"
    argv = ["--input", str(inp), "--output", str(out), "--time", "40", "--seed", str(seed), "--invocations", str(k),
            "--commander", commander, "--kind", kind, "--log", str(log), *extra, "--",
            shlex.quote(sys.executable), shlex.quote(str(fake)), "@OUT@", "@REPORT@", "@SEED@", kind, "@SET@"]
    code = C.main(argv)
    rows = [json.loads(ln) for ln in (log / "decisions.jsonl").read_text().splitlines()]
    return code, rows, json.loads((log / "summary.json").read_text()), out


def test_null_varies_seed_only(board):
    code, rows, s, out = go(board, "null", k=3)
    assert code == 0 and [r["seed"] for r in rows] == [0, 1, 2]
    assert all(r["knobs"] == [] for r in rows) and s["best_invocation"] == 0
    assert out.read_text().startswith("board 10")


def test_rules_drops_a_worse_knob_and_keeps_a_better_one(board):
    code, rows, s, out = go(board, "rules", k=4)
    assert [r["knobs"] for r in rows] == [[], ["planes=strict"], ["neckdown=true"], ["neckdown=true", "rounds=auto"]]
    assert [r["choice"] for r in rows] == [None, "planes_strict", "neckdown", "more_effort"]
    assert [r["opens"] for r in rows] == [10, 16, 6, 4]
    assert s["best_invocation"] == 3 and out.read_text().startswith("board 4")
    assert rows[1]["menu_top5"][0]["id"] == "forbidden"


def test_stops_when_clean(board, monkeypatch):
    monkeypatch.setattr(C, "build_menu", lambda r, k: {"menu": [item("x", "neckdown=clean")]})
    _code, rows, s, _out = go(board, "rules", k=5)
    assert len(rows) == 2 and s["stop"] == "clean" and rows[-1]["opens"] == 0


def test_external_top_item_reimplements_rules(board):
    _c, rules, _s, _o = go(board, "rules", k=4)
    _c, ext, _s, _o = go(board, "external", k=4, extra=["--chooser-cmd", f"{sys.executable} {TOP}"])
    assert [r["knobs"] for r in ext] == [r["knobs"] for r in rules]
    assert [r["opens"] for r in ext] == [r["opens"] for r in rules]


@pytest.mark.parametrize("answer,why", [("not json", "not JSON"), ('{"choose": "nope", "set": []}', "unknown item"),
                                        ('{"choose": "neckdown", "set": ["neckdwn=true"]}', "unknown route key")])
def test_external_invalid_answers_are_null(board, tmp_path, answer, why):
    ch = tmp_path / "ch.py"
    ch.write_text(f"import sys; sys.stdin.read(); print({answer!r})")
    _c, rows, _s, _o = go(board, "external", k=2, extra=["--chooser-cmd", f"{sys.executable} {ch}"])
    assert rows[1]["valid"] is False and why in rows[1]["reason"] and rows[1]["knobs"] == []


def test_external_timeout_is_null(board, tmp_path):
    ch = tmp_path / "slow.py"
    ch.write_text("import time; time.sleep(5)")
    _c, rows, _s, _o = go(board, "external", k=2,
                          extra=["--chooser-cmd", f"{sys.executable} {ch}", "--chooser-timeout", "0.5"])
    assert rows[1]["valid"] is False and "timed out" in rows[1]["reason"]


def test_replay_and_edit_input_skipped(board, tmp_path):
    f = tmp_path / "choices.jsonl"
    f.write_text("\n".join(json.dumps(d) for d in (
        {"invocation": 1, "choose": "rotate_part", "set": []},
        {"invocation": 2, "choose": "neckdown", "set": ["neckdown=true"], "reason": "oracle"})) + "\n")
    _c, rows, _s, _o = go(board, "replay", k=3, extra=["--choices", str(f)])
    assert rows[1]["choice"] == "rotate_part" and rows[1]["reason"].startswith("skipped") and rows[1]["knobs"] == []
    assert rows[2]["knobs"] == ["neckdown=true"] and rows[2]["reason"] == "oracle"


def test_joint_spells_bridge_keys(board):
    _c, rows, _s, _o = go(board, "rules", k=3, kind="joint")
    assert rows[2]["knobs"] == ["bridge.neckdown=true"]


def test_check_set_against_registries():
    reg = C.registries()
    assert {"neckdown", "planes"} <= reg["bridge"] and "max_iters" in reg["loop"] and "drc_timeout" in reg["stages"]
    assert C.check_set("neckdown=true", "route", reg) == ("neckdown=true", None)
    assert C.check_set("bridge.neckdown=true", "route", reg) == ("neckdown=true", None)
    assert C.check_set("neckdown=true", "joint", reg) == ("bridge.neckdown=true", None)
    assert C.check_set("max_iters=3", "joint", reg)[0] == "max_iters=3"
    assert C.check_set("max_iters=3", "route", reg)[0] is None
    assert C.check_set("neckdwn=1", "route", reg)[0] is None
    assert C.check_set("novalue", "route", reg)[0] is None


def test_rank_reads_report_shapes():
    assert C.counts({"final": {"unconnected": 3, "errors": 1, "placement_errors": 0}}) == (3, 1, 0)
    assert C.counts({"repair": {"final": {"unconnected": 2}}}) == (2, 0, 0)
    assert C.rank_of({"final": {"unconnected": 0, "errors": 0}}, True)[:2] == (0, 0)
    assert C.rank_of({"final": {"unconnected": 0}}, False) is None
