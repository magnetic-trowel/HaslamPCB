# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated knob doc (tools/research/commander/knobs.py) must match the code: adding, removing
or renaming a knob without re-running the generator fails here."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/research/commander/knobs.py"


def _knobs():
    spec = importlib.util.spec_from_file_location("kae_knobs_tool", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_doc_and_json_are_current():
    assert _knobs().main(["--check"]) == 0, "re-run: python tools/research/commander/knobs.py"


def test_loopback_names_only_existing_knobs(monkeypatch):
    k = _knobs()
    monkeypatch.setattr(k, "LOOPBACK", k.LOOPBACK + [("x", ["no_such_knob_xyz"], "-", "-", "yes")])
    with pytest.raises(SystemExit, match="no_such_knob_xyz"):
        k.inventory()


def test_inventory_covers_every_surface():
    inv = _knobs().inventory()
    names = {r["name"] for r in inv["set"]}
    assert {"neckdown", "planes", "escape_band", "max_iters", "drc_timeout"} <= names
    assert any(r["name"] == "kae place --fix" for r in inv["cli"])
    assert any(r["var"] == "KAE_PAD_ENTRY" for r in inv["env"])
    assert all(not r["name"].startswith("/") for r in inv["env"] + inv["unregistered"])
