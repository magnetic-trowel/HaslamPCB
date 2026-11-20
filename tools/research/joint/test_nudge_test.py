# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
import nudge_test as N  # noqa: E402


def gap(kind, net="X", req=0.2, avail=0.1, **kw):
    return dict(kind=kind, net=net, required=req, available=avail, **kw)


def test_classify_verdicts():
    assert N.classify({"net": "A", "near": [gap("via")]})["verdict"] == "vias only"
    assert N.classify({"net": "A", "near": [gap("pad", small=True)]})["verdict"] == "parts only"
    assert N.classify({"net": "A", "near": [gap("via"), gap("pad", small=True)]})["verdict"] == "both"
    c = N.classify({"net": "A", "near": [gap("via"), gap("shape", net=None)]})
    assert c["verdict"] == "not nudgeable" and c["blockers"] == ["fixed shape"]
    assert N.classify({"net": "A", "near": [gap("via", avail=0.3)]}) is None
    assert abs(N.classify({"net": "A", "near": [gap("via")]})["sizes"][0] - 0.12) < 1e-9


def test_main_splits(tmp_path, capsys):
    j = {"board": "b1", "conns": [{"net": "A", "near": [gap("via")]}, {"net": "B", "near": [gap("track")]}]}
    (tmp_path / "b1.json").write_text(json.dumps(j))
    N.main([str(tmp_path), "--json", str(tmp_path / "o.json")])
    res = json.loads((tmp_path / "o.json").read_text())
    assert res[0]["opens"] == 2 and res[0]["verdicts"] == {"vias only": 1, "not nudgeable": 1}
    assert "candidate share 0.500" in capsys.readouterr().out
