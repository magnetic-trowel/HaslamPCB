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


def test_a_kicad_cli_that_does_not_run_fails(monkeypatch):
    """A wrapper that resolves but cannot run KiCad (missing image, broken HASLAM_KICAD_WRAP) is a FAIL, not ok."""
    monkeypatch.setattr(tools, "kicad_cli", lambda: ["/nonexistent/kicad-cli"])
    lines = cli.kicad_checks()
    assert any(ln.startswith("FAIL kicad version") and "did not run" in ln for ln in lines)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 255, "", "FATAL: no image\n"))
    assert any(ln.startswith("FAIL kicad version") and "no image" in ln for ln in cli.kicad_checks())


def test_benchmark_comparability_warns_on_another_kicad_or_fork(monkeypatch):
    """The stored baselines ran on BASELINE_KICAD with CONTROL_FORK: doctor says when a host differs (review of F2/F3)."""
    _fake_cli(monkeypatch, "10.0.8")
    monkeypatch.setattr(tools, "freerouting_cmd", lambda: ["/h/haslam-freerouting-fork-06d2686/bin/freerouting"])
    lines = cli.kicad_checks()
    assert any(ln.startswith("WARN kicad version for benchmarks") and tools.BASELINE_KICAD in ln for ln in lines)
    assert any(ln.startswith("WARN freerouting fork") and tools.CONTROL_FORK in ln for ln in lines)
    _fake_cli(monkeypatch, tools.BASELINE_KICAD)
    monkeypatch.setattr(tools, "freerouting_cmd",
                        lambda: [f"/h/haslam-freerouting-fork-{tools.CONTROL_FORK}/bin/freerouting"])
    lines = cli.kicad_checks()
    assert not any(ln.startswith("WARN kicad version for benchmarks") or ln.startswith("WARN freerouting") for ln in lines)
    assert any(ln.startswith("ok   freerouting fork") for ln in lines)


def test_freerouting_identity_names_the_source_commit(tmp_path):
    """F63: the control is identified by its fork's source commit (jars of one commit differ byte-wise)."""
    b = tmp_path / "haslam-freerouting-fork-37b1a8b"
    (b / "bin").mkdir(parents=True)
    (b / "lib").mkdir()
    (b / "bin" / "freerouting").write_text("#!/bin/sh\n")
    (b / "lib" / "freerouting.jar").write_bytes(b"jar")
    (b / "VERSION").write_text("37b1a8b autorouter: check max_work per item\n")
    ident = tools.freerouting_identity([str(b / "bin" / "freerouting")])
    assert ident["source_commit"] == "37b1a8b" and len(ident["sha256"]) == 64
    (b / "VERSION").unlink()
    assert tools.freerouting_identity([str(b / "bin" / "freerouting")])["source_commit"] == "37b1a8b"
