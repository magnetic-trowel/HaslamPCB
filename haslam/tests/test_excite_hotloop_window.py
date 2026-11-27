# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.excite.hotloop.window_pads: which far parts leave a cell's window (FAR_MM), on a stub circuit."""
from types import SimpleNamespace

from haslam.excite import hotloop as HL


class _Circuit:
    """solve() -> the cell's pad currents: J on every pad, Ja on the pads outside the copper model."""

    def __init__(self, J, Ja):
        self.J, self.Ja = J, Ja

    def solve(self, f, sources):
        return {sources[0].name: dict(J=dict(self.J), Ja=dict(self.Ja))}


def _bd(J, Ja, xy):
    return SimpleNamespace(circuit=_Circuit(J, Ja), pad_xy=xy, cell_refs={"buck:U1": {"U1", "C1"}})


def _run(monkeypatch, J, Ja, xy):
    monkeypatch.setattr(HL.O, "pattern", lambda bd, o, f, active=False: {})
    s = SimpleNamespace(name="cell:buck:U1", meta={"cell": "buck:U1"})
    return {p.rsplit(".", 1)[0] for p in HL.window_pads(_bd(J, Ja, xy), s, None, [1e6], own=True)}


# U1 and C1 (its own loop) at x 0-2 mm; C9 (a lumped decoupler) and J1 (a connector: current enters there) 30 mm away
XY = {"U1.1": (0, 0), "U1.2": (2, 0), "C1.1": (0, 1), "C1.2": (2, 1), "C9.1": (30, 0), "C9.2": (31, 0),
      "J1.1": (30, 5), "J1.2": (31, 5)}


def test_far_lumped_part_leaves_the_window(monkeypatch):
    J = {"U1.1": -1.0, "U1.2": 1.0, "C1.1": 0.8, "C1.2": -0.8, "C9.1": 0.2, "C9.2": -0.2}
    Ja = {"U1.1": -1.0, "U1.2": 1.0}
    assert _run(monkeypatch, J, Ja, XY) == {"U1", "C1"}


def test_far_injection_part_stays(monkeypatch):
    # the loop closes through the connector 30 mm away: left out, the window solve would lose that current outright
    J = {"U1.1": -1.0, "U1.2": 1.0, "C1.1": 0.4, "C1.2": -0.4, "J1.1": 0.6, "J1.2": -0.6}
    Ja = {"U1.1": -1.0, "U1.2": 1.0, "J1.1": 0.6, "J1.2": -0.6}
    assert _run(monkeypatch, J, Ja, XY) == {"U1", "C1", "J1"}


def test_without_cell_refs_every_share_part_stays(monkeypatch):
    J = {"U1.1": -1.0, "U1.2": 1.0, "C9.1": 0.2, "C9.2": -0.2}
    monkeypatch.setattr(HL.O, "pattern", lambda bd, o, f, active=False: {})
    bd = _bd(J, {}, XY)
    bd.cell_refs = {}
    s = SimpleNamespace(name="cell:buck:U1", meta={"cell": "buck:U1"})
    assert {p.rsplit(".", 1)[0] for p in HL.window_pads(bd, s, None, [1e6], own=True)} == {"U1", "C9"}
