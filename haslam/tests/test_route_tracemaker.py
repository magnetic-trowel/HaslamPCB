# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.route.tracemaker (TraceMaker as a separate program) and the bridge's first_router option,
with a stand-in script for the TraceMaker binary (no TraceMaker or KiCad needed)."""
import json
import os
import stat
import types

import pytest

from haslam.route import bridge, tracemaker

FAKE = """#!/bin/sh
# stand-in for `tracemaker route BOARD -o OUT ... --json J ...`: copies BOARD to OUT, writes a summary
board=$2; out=$4; json=
while [ $# -gt 0 ]; do [ "$1" = --json ] && json=$2; shift; done
echo "$@" > /dev/null
[ -n "$FAKE_TM_ENV" ] && echo "TM_CLOCK=$TM_CLOCK" > "$FAKE_TM_ENV"
[ -n "$FAKE_TM_SPIN" ] && while :; do :; done
cp "$board" "$out"
printf '{"connections": 10, "routed": 9, "open": 1, "rules": {"custom_rule_count": 2, "not_read": ["x"]}}' > "$json"
exit ${FAKE_TM_RC:-3}
"""


@pytest.fixture
def fake_tm(tmp_path, monkeypatch):
    home = tmp_path / "home"
    b = home / "tracemaker-abcd1234" / "bin"
    b.mkdir(parents=True)
    exe = b / "tracemaker"
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    (home / "tracemaker-abcd1234" / "SOURCE").write_text("abcd1234ef v0.12.1\n")
    monkeypatch.setattr(tracemaker, "HASLAM_HOME", home)
    monkeypatch.delenv("HASLAM_TRACEMAKER", raising=False)
    return exe


def test_binary_by_build_and_path(fake_tm):
    assert tracemaker.binary("abcd1234") == fake_tm
    assert tracemaker.binary(str(fake_tm)) == fake_tm
    assert tracemaker.binary() == fake_tm          # the only build installed
    with pytest.raises(tracemaker.TraceMakerError):
        tracemaker.binary("00000000")


def test_layer_args():
    assert tracemaker.layer_args() == []
    assert tracemaker.layer_args(["In2.Cu"], {"In1.Cu": 4, "In2.Cu": 4}) == [
        "--no-tracks-on", "In2.Cu", "--layer-cost", "In1.Cu=4"]
    assert tracemaker.layer_args((), {"In1.Cu": 5000}) == ["--layer-cost", "In1.Cu=1000"]


def test_route_records_wall_and_cpu(fake_tm, tmp_path):
    board = tmp_path / "in.kicad_pcb"
    board.write_text("(kicad_pcb)")
    out = tmp_path / "wd" / "out.kicad_pcb"
    res = tracemaker.route(board, out, tmp_path / "wd", seconds=5, threads=2, seed=1, extra=["--layer-cost", "In1.Cu=4"],
                           log=lambda m: None)
    assert res["ok"] and res["rc"] == 3 and out.read_text() == "(kicad_pcb)"
    assert res["clock"] == "wall" and res["cpu_s"] >= 0 and res["seconds"] >= 0
    assert res["summary"]["open"] == 1 and res["rules"]["not_read"] == ["x"]
    assert res["source"] == "abcd1234ef v0.12.1"
    a = res["args"]
    assert a[a.index("--threads") + 1] == "2" and a[a.index("--seed") + 1] == "1" and "--no-kb" in a
    assert a[-2:] == ["--layer-cost", "In1.Cu=4"]


def test_route_failure_is_not_ok(fake_tm, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TM_RC", "1")
    board = tmp_path / "in.kicad_pcb"
    board.write_text("(kicad_pcb)")
    res = tracemaker.route(board, tmp_path / "o.kicad_pcb", tmp_path / "wd", seconds=5, log=lambda m: None)
    assert not res["ok"] and res["rc"] == 1


def test_tm_layer_args_follow_the_plane_policy(monkeypatch):
    monkeypatch.setattr(bridge.translate, "plane_layers", lambda info: {"In1.Cu": "GND", "In2.Cu": "+3V3"})
    p = types.SimpleNamespace(plane_policy="cost", strict_planes=["In1.Cu"], plane_cost=4.0)
    assert bridge.tm_layer_args(p, {}, {"tm_planes": "haslam"}) == ["--no-tracks-on", "In1.Cu", "--layer-cost", "In2.Cu=4"]
    p.strict_planes = []
    assert bridge.tm_layer_args(p, {}, {}) == ["--layer-cost", "In1.Cu=4,In2.Cu=4"]
    p.plane_policy = "power"
    assert bridge.tm_layer_args(p, {}, {}) == ["--no-tracks-on", "In1.Cu,In2.Cu"]
    p.plane_policy = "signal"
    assert bridge.tm_layer_args(p, {}, {}) == []
    p.plane_policy = "cost"
    assert bridge.tm_layer_args(p, {}, {"tm_planes": "none"}) == []


def test_tracemaker_only_returns_its_board(fake_tm, tmp_path):
    board = tmp_path / "task" / "board.kicad_pcb"
    board.parent.mkdir()
    board.write_text("(kicad_pcb (version 1))")
    out = tmp_path / "out" / "board.kicad_pcb"
    rep = bridge.route(board, out, seed=1, time_s=100, workdir=tmp_path / "wd",
                       opts=dict(first_router="tracemaker-only", tracemaker="abcd1234", tm_seconds=5, tm_threads=2),
                       log=lambda m: None)
    assert rep["status"] == "routed" and out.read_text() == "(kicad_pcb (version 1))"
    assert rep["router"]["clock"] == "wall" and "cpu_s" in rep["router"]
    json.dumps(rep, default=str)


def test_unknown_first_router(tmp_path):
    with pytest.raises(ValueError):
        bridge.route(tmp_path / "x.kicad_pcb", tmp_path / "y.kicad_pcb", workdir=tmp_path / "wd",
                     opts=dict(first_router="topola"))


def test_default_is_freerouting():
    assert bridge.DEFAULT_OPTS["first_router"] == "freerouting"
    assert os.path.basename(tracemaker.__file__) == "tracemaker.py"


@pytest.fixture
def fake_cpu_tm(fake_tm):
    """The stand-in as a build with the thread-cpu-clock patch."""
    d = fake_tm.parent.parent.with_name("tracemaker-abcd1234-thread-cpu-clock")
    (d / "bin").mkdir(parents=True)
    (d / "bin" / "tracemaker").write_bytes(fake_tm.read_bytes())
    (d / "bin" / "tracemaker").chmod(0o755)
    (d / "SOURCE").write_text("abcd1234ef v0.12.1 patch thread-cpu-clock 0123456789abcdef\n")
    return d / "bin" / "tracemaker"


def test_cpu_clock_sets_tm_clock_and_fixes_the_variants(fake_cpu_tm, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TM_ENV", str(tmp_path / "env.txt"))
    monkeypatch.setenv("TM_CLOCK", "from-outside")
    board = tmp_path / "in.kicad_pcb"
    board.write_text("(kicad_pcb)")
    res = tracemaker.route(board, tmp_path / "wd" / "o.kicad_pcb", tmp_path / "wd", seconds=500, threads=8,
                           bin_spec="abcd1234-thread-cpu-clock", clock="cpu", log=lambda m: None)
    assert res["ok"] and res["clock"] == "cpu" and (tmp_path / "env.txt").read_text().strip() == "TM_CLOCK=thread-cpu"
    a = res["args"]
    assert a[a.index("--variants") + 1] == "8" and a[a.index("--threads") + 1] == "8" and a[a.index("--time") + 1] == "500"
    assert res["kill_limits"] == dict(wall_s=6 * 500 + tracemaker.GRACE_S, cpu_s=(500 + tracemaker.GRACE_S) * 8)
    # the wall clock passes no TM_CLOCK on (a stray one from outside would switch a patched build's clock)
    tracemaker.route(board, tmp_path / "wd2" / "o.kicad_pcb", tmp_path / "wd2", seconds=5,
                     bin_spec="abcd1234-thread-cpu-clock", log=lambda m: None)
    assert (tmp_path / "env.txt").read_text().strip() == "TM_CLOCK="


def test_cpu_clock_refuses_an_unpatched_build(fake_tm, tmp_path):
    board = tmp_path / "in.kicad_pcb"
    board.write_text("(kicad_pcb)")
    with pytest.raises(tracemaker.TraceMakerError, match="thread-cpu-clock"):
        tracemaker.route(board, tmp_path / "o.kicad_pcb", tmp_path / "wd", bin_spec="abcd1234", clock="cpu", log=lambda m: None)
    with pytest.raises(ValueError):
        tracemaker.route(board, tmp_path / "o.kicad_pcb", tmp_path / "wd", bin_spec="abcd1234", clock="steps", log=lambda m: None)


def test_cpu_clock_kills_a_process_past_its_cpu_limit(fake_cpu_tm, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TM_SPIN", "1")
    monkeypatch.setattr(tracemaker, "GRACE_S", 0.0)
    board = tmp_path / "in.kicad_pcb"
    board.write_text("(kicad_pcb)")
    res = tracemaker.route(board, tmp_path / "o.kicad_pcb", tmp_path / "wd", seconds=1, threads=1,
                           bin_spec="abcd1234-thread-cpu-clock", clock="cpu", log=lambda m: None)
    assert res["killed"] == "cpu" and not res["ok"] and res["cpu_s"] >= 1


def test_bridge_passes_tm_clock(fake_cpu_tm, tmp_path):
    board = tmp_path / "task" / "board.kicad_pcb"
    board.parent.mkdir()
    board.write_text("(kicad_pcb (version 1))")
    rep = bridge.route(board, tmp_path / "out.kicad_pcb", seed=1, time_s=100, workdir=tmp_path / "wd",
                       opts=dict(first_router="tracemaker-only", tracemaker="abcd1234-thread-cpu-clock", tm_seconds=5,
                                 tm_threads=2, tm_clock="cpu"), log=lambda m: None)
    assert rep["router"]["clock"] == "cpu" and bridge.DEFAULT_OPTS["tm_clock"] == "wall"
