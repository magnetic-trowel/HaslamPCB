# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""silk_refs.py (F31, F57): geometry helpers and the board-independent placer in pure Python; one synthetic board
through KiCad's Python and kicad-cli DRC (skipped without them)."""
import importlib.util
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "silk_refs.py"
spec = importlib.util.spec_from_file_location("silk_refs", SCRIPT)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def test_geometry_helpers():
    assert S.rdist((0, 0, 1, 1), (2, 0, 3, 1)) == 1.0
    assert S.rdist((0, 0, 1, 1), (4, 5, 5, 6)) == 5.0
    assert S.seg_rect_dist((-1, 0.5, 2, 0.5), (0, 0, 1, 1)) == 0.0                 # crosses the rect
    assert S.seg_rect_dist((2, -5, 2, 5), (0, 0, 1, 1)) == pytest.approx(1.0)
    assert S.seg_rect_dist((2, 2, 3, 3), (0, 0, 1, 1)) == pytest.approx(2 ** 0.5)  # nearest corner
    assert not S.prim_clear((1.2, -1, 1.2, 2, 0.05), (0, 0, 1, 1), 0.2)          # 0.2 - 0.05 half width < 0.2
    assert S.prim_clear((1.3, -1, 1.3, 2, 0.05), (0, 0, 1, 1), 0.2)
    L = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
    assert S.inside_poly(2, 8, L) and not S.inside_poly(8, 8, L)
    assert S.spots((0, 0, 2, 1), 1.0, 0.5, 0.2)[0] == (1.0, -0.45)               # centred above first


def _part(ref, core, side=False, w=1.6, h=0.95):
    return dict(ref=ref, name=ref, side=side, core=core, body=core,
                dims={1.0: {0: (w, h, 0, 0), 90: (h, w, 0, 0)}})


def _placer(parts, outline=None, extra=()):
    hard = {False: S.Grid(), True: S.Grid()}
    for p in parts:
        hard[p["side"]].add(p["body"], 0.0)
    for prim, clr in extra:
        hard[False].add(prim, clr)
    box = outline or [(-20, -20), (20, -20), (20, 20), (-20, 20)]
    return S.Placer(parts, hard, S.Outline([box], []), [1.0])


def test_label_never_over_a_body_or_off_board():
    parts = [_part("U1", (0, 0, 4, 4)), _part("R1", (0, -1.6, 4, -0.6)), _part("R2", (0, 4.6, 4, 5.6))]
    pl = _placer(parts, outline=[(-0.5, -3), (8, -3), (8, 8), (-0.5, 8)])
    assert pl.run() == []
    for ref, (r, *_rest) in pl.at.items():
        assert pl.outline.ok(r)
        for p in parts:
            assert not S.hit(r, p["body"])                       # no label on any body, its own included
    u1 = pl.at["U1"][0]
    assert u1[0] >= 4                                            # U1 boxed in north and south: label east
    labels = [v[0] for v in pl.at.values()]
    assert all(not S.hit(S.grow(a, S.LABEL_CLR), b) for i, a in enumerate(labels) for b in labels[i + 1:])


def test_crossing_another_courtyard_margin_is_allowed():
    """R1's only room is 0.3 mm from R2's body: inside R2's courtyard margin (the old rule refused it)."""
    r1, r2 = _part("R1", (0, 0, 1.6, 0.8)), _part("R2", (0, 2.1, 1.6, 2.9))
    wall = [((-3, -0.1, -0.05, 3), 0.0), ((1.65, -0.1, 5, 3), 0.0), ((-3, -3, 5, -0.05), 0.0)]
    pl = _placer([r1, r2], extra=wall)
    pl.run()
    r = pl.at["R1"][0]
    assert 0.8 <= r[1] and r[3] <= 2.1                           # between the two bodies
    assert S.rdist(r, r2["body"]) < 0.25 + 0.05                  # i.e. within R2's courtyard (0.25 mm margin)


def test_ambiguous_spot_rejected():
    """A spot nearer another part than its own (and not hugging its own) is never taken: to Fab instead."""
    a = _part("R1", (0, 0, 1.6, 0.8))
    b = _part("R2", (0, 1.5, 1.6, 2.3))
    block = [((-5, -5, 5, -0.05), 0.0), ((-5, -5, -0.05, 5), 0.0), ((1.65, -5, 5, 5), 0.0),
             ((-5, 0.85, 5, 1.4), 0.0)]                          # R1's surroundings full; free room only by R2
    pl = _placer([a, b], extra=block)
    pl.run()
    assert "R1" not in pl.at


def test_eviction_frees_a_spot_and_runs_are_deterministic():
    parts = [_part(f"R{i}", (i * 2.0, 0, i * 2.0 + 1.6, 0.8)) for i in range(6)]
    runs = []
    for _ in range(2):
        pl = _placer([dict(p) for p in parts])
        assert pl.run() == []
        runs.append({k: v[:3] for k, v in pl.at.items()})
    assert runs[0] == runs[1]


KICAD_PY = os.environ.get("HASLAM_KICAD_PYTHON", "/usr/bin/python3")
FP = "/usr/share/kicad/footprints"
HAVE = (shutil.which("kicad-cli") and Path(KICAD_PY).exists() and Path(FP, "Resistor_SMD.pretty").exists()
        and subprocess.run([KICAD_PY, "-c", "import pcbnew"], capture_output=True).returncode == 0)

MAKE = textwrap.dedent('''
    import sys, pcbnew
    MM = pcbnew.FromMM
    b = pcbnew.BOARD()
    r = pcbnew.PCB_SHAPE(b); r.SetShape(pcbnew.SHAPE_T_RECTANGLE); r.SetLayer(pcbnew.Edge_Cuts)
    r.SetStart(pcbnew.VECTOR2I(MM(0), MM(0))); r.SetEnd(pcbnew.VECTOR2I(MM(21), MM(10))); r.SetWidth(MM(0.1))
    b.Add(r)                                   # one rectangle outline: the old script's bounding box blocked all
    io = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    k = 0
    for lib, name, xs, ys in (("Resistor_SMD", "R_0603_1608Metric", (2.5, 6.0, 9.5, 13.0), (2.5, 5.0, 7.5)),
                              ("Package_SO", "SOIC-8_3.9x4.9mm_P1.27mm", (), ())):
        for x in xs:
            for y in ys:
                k += 1
                f = io.FootprintLoad(sys.argv[2] + "/" + lib + ".pretty", name)
                f.SetReference(f"R{k}"); f.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                f.Reference().SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))   # the library spot after a move: on pads
                b.Add(f)
    f = io.FootprintLoad(sys.argv[2] + "/Package_SO.pretty", "SOIC-8_3.9x4.9mm_P1.27mm")
    f.SetReference("U1"); f.SetPosition(pcbnew.VECTOR2I(MM(18), MM(5))); f.Reference().SetPosition(f.GetPosition())
    b.Add(f)
    pcbnew.SaveBoard(sys.argv[1], b)
''')


@pytest.mark.skipif(not HAVE, reason="needs KiCad's Python (pcbnew), kicad-cli and the footprint library")
def test_synthetic_board_through_kicad(tmp_path):
    src, out, rep = tmp_path / "in.kicad_pcb", tmp_path / "out.kicad_pcb", tmp_path / "silk.json"
    (tmp_path / "make.py").write_text(MAKE)
    subprocess.run([KICAD_PY, str(tmp_path / "make.py"), str(src), FP], check=True, capture_output=True)
    r = subprocess.run([KICAD_PY, str(SCRIPT), str(src), str(out), "--json", str(rep)], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr[-1000:]
    silk = json.loads(rep.read_text())
    # default: JLC's 1.0 mm minimum everywhere (a fab-ready board never goes below it); this dense board then sends
    # some references to F.Fab
    assert silk["silk"] + len(silk["to_fab"]) == 13 and silk["silk"] >= 8 and silk["below_jlc_min_height"] == 0
    # opt-in fallback to 0.8 mm: more references fit on silk
    rep08 = tmp_path / "silk08.json"
    r08 = subprocess.run([KICAD_PY, str(SCRIPT), str(src), str(tmp_path / "o08.kicad_pcb"), "--min-size", "0.8",
                          "--json", str(rep08)], capture_output=True, text=True)
    assert r08.returncode == 0, r08.stderr[-1000:]
    assert json.loads(rep08.read_text())["silk"] >= 10
    drc = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "-o", str(drc), str(out)],
                   capture_output=True)
    v = [x for x in json.loads(drc.read_text())["violations"] if x["type"].startswith("silk")
         or x["type"] in ("text_height", "text_thickness")]
    assert v == [], v
    r2 = subprocess.run([KICAD_PY, str(SCRIPT), str(src), str(tmp_path / "again.kicad_pcb")], capture_output=True)
    assert r2.returncode == 0
    strip = lambda p: [ln for ln in p.read_text().splitlines() if "(uuid" not in ln]   # noqa: E731
    assert strip(out) == strip(tmp_path / "again.kicad_pcb")
