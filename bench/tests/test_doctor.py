# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`haslambench doctor`'s design-flow checks: tested KiCad version, symbol and footprint libraries."""
import subprocess

from haslambench import cli, tools


def _fake_cli(monkeypatch, version):
    monkeypatch.setattr(tools, "kicad_cli", lambda: ["kicad-cli"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, f"{version}\n", ""))


def test_untested_version_warns_with_the_drift_tests(monkeypatch):
    _fake_cli(monkeypatch, "99.0.1")
    lines = cli.kicad_checks()
    v = next(ln for ln in lines if "kicad version" in ln)
    assert v.startswith("WARN") and "test_board_dru_check.py" in v


def test_tested_version_and_library_dirs(monkeypatch, tmp_path):
    _fake_cli(monkeypatch, tools.KICAD_TESTED_VERSIONS[-1])
    (tmp_path / "sym").mkdir()
    (tmp_path / "sym" / "Device.kicad_sym").write_text("")
    (tmp_path / "fp").mkdir()
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(tmp_path / "sym"))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(tmp_path / "fp"))      # empty: no .pretty
    monkeypatch.delenv("HASLAM_KICAD_WRAP", raising=False)
    lines = cli.kicad_checks()
    assert any(ln.startswith("ok   kicad version") for ln in lines)
    assert any(ln.startswith("ok   kicad symbol libraries") and "1 libraries" in ln for ln in lines)
    assert any(ln.startswith("WARN kicad footprint libraries") for ln in lines)
