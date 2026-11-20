# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""restart.py's physics tie-break (--phys-tiebreak) and --alt-from-best, with a stand-in kicad-cli
and a stand-in physics_board.py (no KiCad, no kae): boards carry "OPEN=n" and "PHYS=mod:u,...". """
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from test_restart import FAKE_CLI, restart

RESTART = Path(restart.__file__)

# a Python that, run as `python physics_board.py --input I --out O --board name=path ...`, reports each board's
# PHYS=mod:u,... ("-" for a module without a value) as physics_board.py's modules
FAKE_PHYS = """#!/usr/bin/env python3
import json, re, sys
args = sys.argv[2:]
out = args[args.index("--out") + 1]
boards = {}
for i, x in enumerate(args):
    if x == "--board":
        name, _, path = args[i + 1].partition("=")
        m = re.search(r"PHYS=(\\S+)", open(path).read())
        mods = {}
        for kv in (m.group(1).rstrip(")").split(",") if m else []):
            k, _, u = kv.partition(":")
            mods[k] = dict(u=None if u == "-" else float(u))
        boards[name] = dict(modules=mods)
json.dump(dict(boards=boards), open(out, "w"))
"""


def _run(tmp_path, attempt, extra=(), time_s=200, parallel=2, max_attempts=2):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "kicad-cli").write_text(FAKE_CLI)
    (bin_ / "kicad-cli").chmod(0o755)
    (bin_ / "fakepy").write_text(FAKE_PHYS)
    (bin_ / "fakepy").chmod(0o755)
    inp = tmp_path / "in" / "board.kicad_pcb"
    inp.parent.mkdir()
    inp.write_text("(kicad_pcb OPEN=5)\n")
    out = tmp_path / "out" / "board.kicad_pcb"
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", KAE_KICAD_WRAP="")
    work = tmp_path / "work"
    work.mkdir()
    args = [sys.executable, str(RESTART), "--input", str(inp), "--output", str(out), "--time", str(time_s),
            "--parallel", str(parallel), "--first-s", "25", "--max-attempts", str(max_attempts),
            "--phys-python", str(bin_ / "fakepy"), *extra]
    r = subprocess.run([*args, "--", attempt], cwd=work, env=env, capture_output=True, text=True, timeout=300)
    return r, out, json.loads((work / "restarts" / "summary.json").read_text())


# attempt 0 (seed 0) ends first; attempt 1 (seed 1) three seconds later, in the same wave
TWO = ("sleep $((@SEED@ * 3)); if [ @SEED@ = 0 ]; then echo '(kicad_pcb OPEN={o0} first PHYS={p0})' > @OUT@; "
       "else echo '(kicad_pcb OPEN={o1} second PHYS={p1})' > @OUT@; fi")


def test_default_keeps_the_first_clean_attempt_and_stops_the_rest(tmp_path):
    r, out, s = _run(tmp_path, TWO.format(o0=0, o1=0, p0="a:2,b:2,c:1", p1="a:1,b:1,c:2"),
                     extra=["--phys-python", "/nonexistent"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "first" in out.read_text() and s["best_attempt"] == 0
    assert s["attempt_log"][1].get("stopped") and "phys_vote" not in s["attempt_log"][1]


def test_tiebreak_waits_for_the_clean_attempts_wave_and_keeps_the_module_vote_winner(tmp_path):
    # a and b better, c worse: 2 to 1 for the second, although its summed physics is equal
    r, out, s = _run(tmp_path, TWO.format(o0=0, o1=0, p0="a:2,b:2,c:1", p1="a:1.5,b:1.5,c:2"),
                     extra=["--phys-tiebreak"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "second" in out.read_text() and s["best_attempt"] == 1
    a1 = s["attempt_log"][1]
    assert not a1.get("stopped") and a1["phys_vote"] == dict(against=0, better=2, worse=1, voters=3)


def test_tiebreak_tied_vote_keeps_the_first(tmp_path):
    r, out, s = _run(tmp_path, TWO.format(o0=0, o1=0, p0="a:2,b:1", p1="a:1,b:2"), extra=["--phys-tiebreak"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "first" in out.read_text() and s["attempt_log"][1]["phys_vote"]["better"] == 1


def test_tiebreak_modules_without_a_value_do_not_vote(tmp_path):
    # b has no value on the second board: only a votes (worse), so the first stays
    r, out, s = _run(tmp_path, TWO.format(o0=0, o1=0, p0="a:1,b:4", p1="a:1.2,b:-"), extra=["--phys-tiebreak"])
    assert "first" in out.read_text() and s["attempt_log"][1]["phys_vote"]["voters"] == 1


def test_tiebreak_never_changes_the_rank_order(tmp_path):
    # the second is open: better physics never beats a board with fewer open connections
    r, out, s = _run(tmp_path, TWO.format(o0=1, o1=2, p0="a:4", p1="a:0.1"), extra=["--phys-tiebreak"])
    assert "first" in out.read_text() and "phys_vote" not in s["attempt_log"][1]
    # equal open counts: the vote decides
    (tmp_path / "eq").mkdir()
    r, out, s = _run(tmp_path / "eq", TWO.format(o0=1, o1=1, p0="a:4", p1="a:0.1"), extra=["--phys-tiebreak"])
    assert "second" in out.read_text()


def test_wave_of():
    a = SimpleNamespace(screen=False, parallel=4)
    assert restart.wave_of(dict(k=3), a) == restart.wave_of(dict(k=0), a) != restart.wave_of(dict(k=4), a)
    a = SimpleNamespace(screen=True, parallel=4)
    assert restart.wave_of(dict(k=3, rung=1), a) != restart.wave_of(dict(k=4, rung=0), a)


P1 = "echo '(kicad_pcb OPEN=0 P1MARK PHYS={p})' > @OUT@"
ALT = "if grep -q P1MARK @BEST@; then echo '(kicad_pcb OPEN=0 alt PHYS={p})' > @OUT@; fi"


def test_alt_from_best_starts_from_the_clean_board_and_keeps_it_unless_it_loses_the_vote(tmp_path):
    r, out, s = _run(tmp_path, P1.format(p="a:2,b:2"), parallel=1, max_attempts=1,
                     extra=["--alt", ALT.format(p="a:1,b:2"), "--alt-from-best"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert s["second"] == "alt" and s["kept"] == 2 and "alt" in out.read_text()
    (tmp_path / "w").mkdir()
    r, out, s = _run(tmp_path / "w", P1.format(p="a:2,b:2"), parallel=1, max_attempts=1,
                     extra=["--alt", ALT.format(p="a:3,b:2"), "--alt-from-best"])
    assert s["kept"] == 1 and "P1MARK" in out.read_text()
    assert s["phases"][0]["phys_vote"] == dict(against=2, better=1, worse=0, voters=2)


def test_alt_without_from_best_still_starts_from_the_input(tmp_path):
    # today's behaviour: @BEST@ inside the alt phase is the input, so this alt writes nothing and phase 1 stays
    r, out, s = _run(tmp_path, P1.format(p="a:2"), parallel=1, max_attempts=1, extra=["--alt", ALT.format(p="a:1")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert s["second"] == "alt" and s["kept"] == 1 and "P1MARK" in out.read_text()
