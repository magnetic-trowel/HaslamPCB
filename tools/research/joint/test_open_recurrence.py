# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json, os, random, sys

sys.path.insert(0, os.path.dirname(__file__))
import open_recurrence as R  # noqa: E402


def test_opens_of_reads_nets_and_parts():
    drc = {"unconnected_items": [{"items": [{"description": "Pad 1 [Net-(U1-A)] of TP3 on F.Cu"},
                                            {"description": "Pad 20 [Net-(U1-A)] of U1 on F.Cu"}]}]}
    assert R.opens_of(drc) == (["Net-(U1-A)"], ["TP3", "U1"])


def test_pcb_facts_pose_hash_tracks_moves():
    a = '(kicad_pcb\n (net 1 "GND")\n (footprint "R"\n  (at 1 2 90)\n  (property "Reference" "R1")\n )\n)'
    b = a.replace("(at 1 2 90)", "(at 1 2.5 90)")
    pa, na, ra = R.pcb_facts(a)
    pb, _, _ = R.pcb_facts(b)
    assert pa != pb and na == ["GND"] and ra == ["R1"]


def test_recurrence_full_and_none():
    rng = random.Random(0)
    uni = [f"n{i}" for i in range(50)]
    obs, base, tot = R.recurrence([{"n1"}] * 6, 50, rng, uni)
    assert obs == 1.0 and tot == 6 and base < 0.3
    obs, _, _ = R.recurrence([{f"n{i}"} for i in range(6)], 10, rng, uni)
    assert obs == 0.0


def test_analyse_end_to_end(tmp_path, capsys):
    runs = {f"r{i}": dict(pose=f"p{i}", nets=[f"n{j}" for j in range(40)], refs=["U1", "R1"],
                          open_nets=["n1"] + ([f"n{10 + i}"] if i % 2 else []), open_parts=["U1"]) for i in range(6)}
    (tmp_path / "b.json").write_text(json.dumps(runs))
    R.main(["analyse", "--cache", str(tmp_path), "--perm", "20", "--json", str(tmp_path / "o.json")])
    rows = json.loads((tmp_path / "o.json").read_text())
    assert rows[0]["placements"] == 6 and abs(rows[0]["net_share"] - 6 / 9) < 1e-9
    assert "net: recurrent share" in capsys.readouterr().out
