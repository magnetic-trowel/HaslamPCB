# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Counted-budget runs do not depend on the copper's file order or UUIDs.

KiCad breaks ties by load order and UUIDs (which of two equally near items a ratsnest pair or DRC
"unconnected" names, the order of pcbnew's lists). Every determinism bug of HASLAM_BUDGET=work found
so far was a decision taken from such a tie. Here each flow runs twice in work mode
(PYTHONHASHSEED=0, one worker, one thread): on a partly routed board as it is, and on a copy whose
(segment)/(arc)/(via) blocks are shuffled and re-UUIDed (tools/research/budget/shuffle.py). The
outputs' placement and copper, as sorted item sets without UUIDs, must be identical.

The board is the synthetic fixture (or HASLAM_SHUFFLE_BOARD, a board with its project files beside
it), routed once by haslam.route and then thinned to leave opens. HASLAM_SHUFFLE_TIME scales the
budgets (default 1). On a difference the assertion names the first differing log line of the two
runs; their work directories are kept under pytest's tmp_path.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from haslam.board import pcbnew_io
from haslam.route import drc, freerouting

ROOT = Path(__file__).resolve().parents[2]
BUDGET = ROOT / "tools" / "research" / "budget"
FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"
SCALE = float(os.environ.get("HASLAM_SHUFFLE_TIME") or 1.0)


def _have_router():
    try:
        freerouting.command()
        drc.kicad_cli()
        return True
    except Exception:
        return False


pytestmark = [pytest.mark.kicad,
              pytest.mark.skipif(not pcbnew_io.available(), reason="no Python with pcbnew"),
              pytest.mark.skipif(not _have_router(), reason="no Freerouting or kicad-cli"),
              pytest.mark.skipif(not (BUDGET / "shuffle.py").exists(), reason="tools/research/budget not present")]


def _tools():
    if str(BUDGET) not in sys.path:
        sys.path.insert(0, str(BUDGET))
    import acceptance
    import shuffle
    return acceptance, shuffle


def _env():
    env = dict(os.environ, HASLAM_BUDGET="work", PYTHONHASHSEED="0", HASLAM_WORKERS="1", OMP_NUM_THREADS="1")
    src = str(ROOT / "haslam" / "src")
    env["PYTHONPATH"] = os.pathsep.join([src] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    return env


def _haslam(args, d, timeout):
    """Run `python -m haslam...` in work mode in `d`; its stdout+stderr go to d/log."""
    d.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-m"] + [str(a) for a in args], cwd=d, env=_env(), timeout=timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (d / "log").write_text(r.stdout)
    return r.returncode


def _copy_board(src, dst):
    """`src` with its project files, as `dst`."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for f in src.parent.glob(src.stem + ".kicad_*"):
        if f.suffix in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".kicad_prl"):
            shutil.copy2(f, dst.parent / (dst.stem + f.suffix))
    return dst


def _thin(board, every=3):
    """Drop every `every`-th copper block (in content order) from `board`, so the flows have opens to close."""
    drc.canonical_copper_order(board)
    lines, out, i, k = board.read_text().split("\n"), [], 0, 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith(("\t(segment", "\t(arc", "\t(via")) and not ln.startswith("\t(via_"):
            j, depth = i, 0
            while True:
                depth += lines[j].count("(") - lines[j].count(")")
                if depth <= 0:
                    break
                j += 1
            if k % every:
                out.extend(lines[i:j + 1])
            k += 1
            i = j + 1
            continue
        out.append(ln)
        i += 1
    board.write_text("\n".join(out))
    return k


_NOISE = [(re.compile(r"\d+(\.\d+)?\s*(s|ms|sec|seconds)\b"), "#s"),
          (re.compile(r"\d\d:\d\d:\d\d(\.\d+)?"), "#t"),
          (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "#uuid"),
          (re.compile(r"(/tmp|/var/tmp)\S*"), "#path"),
          (re.compile(r"\b(pid|rss|mem)\W*\d+\S*", re.I), "#n")]


def first_log_difference(a, b):
    """The first lines of two logs that differ once times, UUIDs and paths are blanked, or None."""
    def norm(p):
        out = []
        for ln in Path(p).read_text(errors="replace").splitlines():
            for rx, rep in _NOISE:
                ln = rx.sub(rep, ln)
            out.append(ln)
        return out
    la, lb = norm(a), norm(b)
    for n, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return n + 1, x, y
    if len(la) != len(lb):
        n = min(len(la), len(lb))
        return n + 1, la[n] if n < len(la) else "<end>", lb[n] if n < len(lb) else "<end>"
    return None


def _twins(tmp, partial, argv, timeout, seed=7):
    """Run argv(input, output, workdir) on `partial` and on its shuffled copy; assert equal outputs."""
    acc, shuf = _tools()
    plain = _copy_board(partial, tmp / "in-plain" / "board.kicad_pcb")
    mixed = tmp / "in-shuffled" / "board.kicad_pcb"
    n = shuf.shuffle_copper(partial, mixed, seed)
    assert n > 0, "the partial board has no copper to shuffle"
    assert acc._items(plain.read_text()) == acc._items(mixed.read_text())
    res = {}
    for name, inp in (("plain", plain), ("shuffled", mixed)):
        d = tmp / name
        out = d / "out" / "board.kicad_pcb"
        rc = _haslam(argv(inp, out, d / "wd"), d, timeout)
        assert rc == 0 and out.exists(), f"{name}: rc {rc}; log {d / 'log'}"
        res[name] = acc._items(out.read_text())
    if res["plain"] != res["shuffled"]:
        sa, sb = set(res["plain"]), set(res["shuffled"])
        first = first_log_difference(tmp / "plain" / "log", tmp / "shuffled" / "log")
        pytest.fail(f"outputs differ: {len(sa - sb)} items only plain, {len(sb - sa)} only shuffled; "
                    f"first log difference {first}; logs and work dirs under {tmp}")


@pytest.fixture(scope="module")
def partial(tmp_path_factory):
    """A routed board with a third of its copper removed."""
    src = Path(os.environ.get("HASLAM_SHUFFLE_BOARD") or FIXTURE)
    d = tmp_path_factory.mktemp("shuffle-base")
    inp = _copy_board(src, d / "in" / "board.kicad_pcb")
    out = d / "routed" / "board.kicad_pcb"
    rc = _haslam(["haslam.route.cli", "route", inp, out, "--time", 60 * SCALE, "--workdir", d / "wd", "--keep"],
              d, timeout=900 * SCALE)
    assert rc == 0 and out.exists(), f"base route failed: {d / 'log'}"
    part = _copy_board(inp, d / "partial" / "board.kicad_pcb")
    shutil.copy2(out, part)
    if _thin(part) < 3:
        pytest.skip("the base route left too little copper to shuffle")
    return part


def test_shuffle_helper_keeps_copper(tmp_path):
    acc, shuf = _tools()
    out = tmp_path / "s" / "board.kicad_pcb"
    n = shuf.shuffle_copper(FIXTURE, out, 3)
    text = out.read_text()
    assert n > 0 and acc._items(text) == acc._items(FIXTURE.read_text())
    old = set(re.findall(r'\(uuid "([^"]+)"\)', FIXTURE.read_text()))
    new = set(re.findall(r'\(uuid "([^"]+)"\)', text))
    assert len(new - old) == n            # every copper block got a fresh uuid, nothing else changed
    assert out.with_suffix(".kicad_pro").exists()


def test_route_ignores_copper_order_and_uuids(partial, tmp_path):
    _twins(tmp_path, partial,
           lambda i, o, w: ["haslam.route.cli", "route", i, o, "--time", 60 * SCALE, "--workdir", w, "--keep"],
           timeout=900 * SCALE)


def test_lastmile_ignores_copper_order_and_uuids(partial, tmp_path):
    rules = partial.parent.parent / "in" / "board.kicad_pcb"
    _twins(tmp_path, partial,
           lambda i, o, w: ["haslam.route.cli", "lastmile", rules, i, o, "--time", 40 * SCALE, "--workdir", w, "--keep"],
           timeout=600 * SCALE)


def test_joint_ignores_copper_order_and_uuids(partial, tmp_path):
    # smaller finishing and per-window reserves than the defaults, so this short budget still runs
    # windows after iteration 0 (the congestion history and unrouted spots read KiCad's DRC)
    _twins(tmp_path, partial,
           lambda i, o, w: ["haslam.joint.cli", "run", i, o, "--start", i, "--time", 150 * SCALE, "--seed", 1,
                            "--set", "finish_min_s=20", "--set", "min_iter_s=15",
                            "--workdir", w, "--keep"],
           timeout=1800 * SCALE)
