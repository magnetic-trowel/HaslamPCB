# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The quick-physics validation scripts' bookkeeping (no quotes are run: the quote cache is filled by hand)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import find_pairs as FP  # noqa: E402
import validate_pairs as VP  # noqa: E402


def _ev(path, board, L, R, pitch=0.0625):
    path.write_text(json.dumps(dict(board=board, cells=[dict(cell="cell:buck:U1", state="ok", window=dict(
        refined=True, pitch=pitch, L_raw_nH=L, R_raw_mohm=R))])))


def test_find_pairs_fails_naming_a_board_without_operating_facts(tmp_path, capsys):
    ev, i1, i2 = tmp_path / "ev", tmp_path / "i1", tmp_path / "i2"
    for d in (ev, i1, i2):
        d.mkdir()
    for b in ("brd-a", "brd-b"):
        for arm in ("human", "A"):
            _ev(ev / f"{b}.{arm}.ev.json", f"/x/{b}/{arm}/board.kicad_pcb", 1.0, 2.0)
    (i2 / "brd-a.operating.json").write_text("{}")
    args = ["--ev-dir", str(ev), "--pairs", str(tmp_path / "p.json"), "--list", str(tmp_path / "l.json")]
    assert FP.main(args + ["--intents", str(i1), str(i2)]) == 1
    err = capsys.readouterr().err
    assert "no operating facts for brd-b" in err and "brd-a" not in err.replace("brd-b", "")
    (i1 / "brd-b.operating.json").write_text("{}")
    assert FP.main(args + ["--intents", str(i1), str(i2)]) == 0
    pairs = json.loads((tmp_path / "p.json").read_text())
    assert {p["intent"] for p in pairs} == {str(i2 / "brd-a.operating.json"), str(i1 / "brd-b.operating.json")}


def test_validate_pairs_ties_at_the_windows_tolerances_and_strata_by_near_pitch(tmp_path, capsys):
    ba, bb = "/x/b/human/board.kicad_pcb", "/x/b/A/board.kicad_pcb"
    _ev(tmp_path / "a.ev.json", ba, 1.00, 2.00)
    _ev(tmp_path / "b.ev.json", bb, 1.01, 2.04)        # L 1 % apart (not a tie at 0.5 %), R 2 % (a tie at 3 %)
    pairs = [dict(cell="cell:buck:U1", intent=None, a=dict(board=ba, ev=str(tmp_path / "a.ev.json"), arm="human"),
                  b=dict(board=bb, ev=str(tmp_path / "b.ev.json"), arm="A"))]
    (tmp_path / "pairs.json").write_text(json.dumps(pairs))
    cache = tmp_path / "cache"
    cache.mkdir()
    for b, L, P, n in ((ba, 1.1, 0.25, 3000), (bb, 1.2, 0.5, 2000)):
        row = dict(cell="cell:buck:U1", state="ok", L_nH=L, R_mohm=3.0, pitch_near=P, unknowns=n)
        VP._cache_path(cache, b).write_text(json.dumps(dict(board=b, rows={"cell:buck:U1": row})))
    assert VP.main(["--pairs", str(tmp_path / "pairs.json"), "--cache", str(cache), "--out", str(tmp_path / "o.json")]) == 0
    s = json.loads((tmp_path / "o.json").read_text())["summary"]
    assert s["tie"] == dict(L=0.005, R=0.03)
    assert s["by"]["total"] == dict(L=1, R=0) and s["ties"] == dict(L=0, R=1) and s["agree"] == 1
    assert s["by_pitch_near"] == {"0.5": dict(agree=1, total=1, ties=1, unknowns_median=3000, unknowns_max=3000)}


def test_validate_ratio_strata_by_near_pitch(tmp_path):
    import validate_ratio as VR
    lst = []
    cache = tmp_path / "cache"
    cache.mkdir()
    for k, (P, ratio) in enumerate(((0.5, 1.05), (0.5, 0.9), (0.25, 1.3))):
        b = f"/x/b{k}/human/board.kicad_pcb"
        _ev(tmp_path / f"{k}.ev.json", b, 1.0, 2.0)
        lst.append(dict(board_id=f"b{k}", board=b, ev=str(tmp_path / f"{k}.ev.json"), intent=None))
        row = dict(cell="cell:buck:U1", state="ok", L_nH=ratio, R_mohm=2.0 * ratio, pitch_near=P, unknowns=1000 + k,
                   seconds=1.0)
        VP._cache_path(cache, b).write_text(json.dumps(dict(board=b, rows={"cell:buck:U1": row})))
    (tmp_path / "l.json").write_text(json.dumps(lst))
    assert VR.main(["--list", str(tmp_path / "l.json"), "--cache", str(cache), "--out", str(tmp_path / "o.json")]) == 0
    s = json.loads((tmp_path / "o.json").read_text())["summary"]
    assert set(s["by_pitch_near"]) == {"0.5", "0.25"}
    assert s["by_pitch_near"]["0.5"]["cells"] == 2 and s["by_pitch_near"]["0.25"]["unknowns"] == [1002]
    assert abs(s["by_pitch_near"]["0.25"]["L"]["p90"] - 0.3) < 1e-9
