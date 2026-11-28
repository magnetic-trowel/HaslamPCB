# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""board_spec.py (edge-anchored board.json) and size_search.py's outline arithmetic; no KiCad needed."""
import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_anchors_follow_the_outline():
    bs = _load("board_spec")
    spec = {"outline": [80, 55], "holes": {"inset": 3.5},
            "fixed": {"J1": {"edge": "west", "along": 0.5, "inset": 5, "rot": 90},
                      "J2": {"edge": "east", "along": 0.5, "inset": 4},
                      "J3": {"edge": "south", "along_mm": 10, "inset": 3},
                      "J4": {"x": 20, "y": 20}},
            "seed_area": {"margin": 10}, "keepouts": [{"edge": "north", "depth": 5, "from": 0.25, "to": 0.75}]}
    a = bs.resolve(spec)
    assert a["holes"] == [[3.5, 3.5], [76.5, 3.5], [3.5, 51.5], [76.5, 51.5]]
    assert (a["fixed"]["J1"]["x"], a["fixed"]["J1"]["y"]) == (5, 27.5)
    assert (a["fixed"]["J2"]["x"], a["fixed"]["J2"]["y"]) == (76, 27.5)
    assert (a["fixed"]["J3"]["x"], a["fixed"]["J3"]["y"]) == (10, 52)
    assert (a["fixed"]["J4"]["x"], a["fixed"]["J4"]["y"]) == (20, 20)            # absolute entries untouched
    assert a["seed_area"] == [10, 10, 70, 45] and a["keepouts"][0]["rect"] == [20, 0, 60, 5]
    b = bs.resolve(spec, (100, 70))
    assert (b["fixed"]["J2"]["x"], b["fixed"]["J2"]["y"]) == (96, 35) and b["holes"][3] == [96.5, 66.5]
    assert spec["holes"] == {"inset": 3.5}                                        # the input is not modified


def test_size_search_outline_keeps_aspect_and_density():
    ss = _load("size_search")
    w, h = ss.outline_for(1000.0, 80 / 55, 0.25)
    assert abs(w / h - 80 / 55) < 0.05 and 1000 / (w * h) <= 0.25 and 1000 / ((w - 1) * (h - 1)) > 0.24
