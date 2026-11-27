# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.place.hpwl_report: the place report's per-net wire-length outliers (bme280-array F34)."""
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

from haslam.place import hpwl_report as H

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _scene():
    """A mux U0 at x=0 serving 6 two-sensor buses whose sensors sit 10..60 mm east, plus 10 short local nets."""
    parts, at = [], []

    def part(ref, x, y):
        parts.append(NS(i=len(parts), ref=ref, area=4.0))
        at.append((x, y))
        return len(parts) - 1
    mux = part("U0", 0.0, 0.0)
    nets = []
    for b in range(6):
        a, c = part(f"U{10 + 2 * b}", 10.0 * (b + 1), 0.0), part(f"U{11 + 2 * b}", 10.0 * (b + 1), 3.0)
        nets.append(NS(name=f"CH{b}", kind="signal", pins=[(mux, 0), (a, 0), (c, 0)]))
    for k in range(10):
        r1, r2 = part(f"R{2 * k}", 0.0, 20.0 + 5 * k), part(f"R{2 * k + 1}", 2.0, 20.0 + 5 * k)
        nets.append(NS(name=f"L{k}", kind="signal", pins=[(r1, 0), (r2, 0)]))
    nets.append(NS(name="GND", kind="ground", pins=[(i, 0) for i in range(len(parts))]))
    P = NS(parts=parts, nets=nets)
    st = NS(pins_xy=lambda i: np.array([at[i]]))
    return P, st


def test_the_far_buses_of_one_mux_are_listed_with_the_mux_shared():
    P, st = _scene()
    r = H.outliers(P, st)
    assert r["n_signal_nets"] == 16                     # ground left out
    names = [n["net"] for n in r["nets"]]
    assert names[:3] == ["CH5", "CH4", "CH3"]           # the largest excess first
    assert not any(n.startswith("L") for n in names)    # compact nets are no outliers
    top = r["nets"][0]
    assert top["hpwl_mm"] == 63.0 and top["cluster_mm"] == round(12 ** 0.5, 1) and top["ratio"] >= H.RATIO
    assert r["shared_parts"][0] == dict(part="U0", outliers=r["n_outliers"])


def test_a_real_board_report_is_cheap_and_well_formed():
    from haslam.board.kicad_file import load
    from haslam.place.problem import Problem
    from haslam.place.state import State
    P = Problem.build(load(FIXTURE))
    r = H.outliers(P, State(P))
    assert r["n_signal_nets"] > 0 and r["n_outliers"] >= len(r["nets"])
    for n in r["nets"]:
        assert n["ratio"] >= H.RATIO and n["x_median"] >= H.X_MEDIAN and n["excess_mm"] > 0
