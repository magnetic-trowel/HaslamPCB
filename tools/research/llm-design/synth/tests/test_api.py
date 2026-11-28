# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`haslamsynth api` lists every public design.py call, from the code, in a couple of thousand tokens."""
import inspect

from haslamsynth import api, ir, lib, placement
from haslamsynth.cli import main
from haslamsynth.haslam_intent import HaslamIntent


def public(cls):
    skip = api.INTERNAL.get(cls.__name__, set())
    return [n for n, m in vars(cls).items() if not n.startswith("_") and n not in skip
            and (inspect.isfunction(m) or isinstance(m, (property, staticmethod)))]


def test_every_public_call_is_listed():
    t = api.text()
    lines = t.splitlines()
    for cls, prefix in ((ir.Design, "d."), (ir.Block, "blk."), (ir.Part, "u."), (ir.Net, "n."),
                        (placement.Placement, "d.place."), (HaslamIntent, "d.haslam.")):
        for name in public(cls):
            assert any(ln.startswith(f"{prefix}{name}") for ln in lines), f"{prefix}{name}"
    for name, fn in vars(lib).items():
        if inspect.isfunction(fn) and not name.startswith("_") and fn.__module__ == lib.__name__:
            assert any(ln.startswith(f"lib.{name}(") for ln in lines), name


def test_kwargs_show_the_constructor_they_reach():
    lines = {ln.split("(")[0]: ln for ln in api.text().splitlines() if "(" in ln}
    assert "v=None" in lines["d.net"] and "i_max=None" in lines["d.net"] and "**kw" not in lines["d.net"]
    assert "v_across=None" in lines["blk.add"] and "i_through=None" in lines["blk.add"]
    assert "width_mm=None" in lines["d.board"] and "fab='jlc-2layer-1oz'" in lines["d.board"]
    assert "grade" in lines["d.barrier"] and "creepage_mm" in lines["d.barrier"]


def test_one_line_docs():
    assert api.one_line(placement.Placement.separate) == (
        "Keep two domains apart; spacing comes from the matching Barrier.")
    assert api.one_line(ir.PinDef) == ""                  # a dataclass's generated docstring is not repeated
    assert len(api.one_line(placement.Placement.pins_toward)) <= api.DOC_CHARS


def test_small_enough_to_read_whole():
    t = api.text()
    assert len(t) < 10_000, len(t)                        # ~4 characters per token: under ~2.5k tokens


def test_cli(capsys):
    assert main(["api"]) == 0
    assert capsys.readouterr().out == api.text()
