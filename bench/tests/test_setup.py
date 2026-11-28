# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""setup.sh --all plans every venv and writes every pipeline variable; doctor checks them (obd-solar FRICTION.md #5-#8).

setup.sh runs with --dry-run --kicad none against a temporary HASLAM_HOME: nothing is installed or downloaded."""
import os
import subprocess
from pathlib import Path

import pytest

from haslambench import doctor, tools

SETUP = Path(__file__).resolve().parents[1] / "scripts" / "setup.sh"


def setup(home, *args):
    env = dict(os.environ, HASLAM_HOME=str(home))
    r = subprocess.run(["bash", str(SETUP), "--kicad", "none", "--dry-run", *args], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout, (home / "env.sh").read_text()


def exports(text):
    return [ln.split("=", 1)[0].removeprefix("export ") for ln in text.splitlines() if ln.startswith("export ")]


def test_all_plans_every_venv_and_the_fork(tmp_path):
    out, env = setup(tmp_path, "--all")
    assert "haslam[dev,fast]" in out and "synth[test]" in out and "bench[test]" in out
    assert "haslam-src.pth" in out
    assert f"install_freerouting_fork.sh {tools.freerouting_ref()} --pin" in out
    names = exports(env)
    assert names[:2] == ["HASLAM_HOME", "HASLAM_KICAD_WRAP"] and len(names) == len(set(names)), names


def test_without_all_only_the_bench_venv(tmp_path):
    out, env = setup(tmp_path)
    assert "bench[test]" in out and "haslam[dev,fast]" not in out and "synth[test]" not in out
    assert "install_freerouting_fork.sh" in out and "--all" in out       # named, not run
    assert "HASLAM_KICAD_WRAP" in exports(env)


def test_an_existing_pin_is_kept(tmp_path):
    (tmp_path / tools.FR_PIN).write_text(f"{tmp_path}/haslam-freerouting-fork-0000000/bin/freerouting\n")
    out, _ = setup(tmp_path, "--all")
    assert "+ env HASLAM_HOME" not in out and "is not the control" in out


def test_kicad_none_keeps_an_earlier_container_setup(tmp_path):
    (tmp_path / "env.sh").write_text('export HASLAM_HOME="x"\nexport HASLAM_KICAD_WRAP="/k/kicad-exec apptainer /img"\n'
                                     'export KICAD10_SYMBOL_DIR="/img/usr/share/kicad/symbols"\n'
                                     'export KICAD10_FOOTPRINT_DIR="/img/usr/share/kicad/footprints"\n'
                                     'export APPTAINER_BIND="${APPTAINER_BIND:-/repo}"\n')
    _, env = setup(tmp_path, "--all")
    names = exports(env)
    assert len(names) == len(set(names)), names
    assert 'HASLAM_KICAD_WRAP="/k/kicad-exec apptainer /img"' in env and "/img/usr/share/kicad/symbols" in env
    assert "APPTAINER_BIND" in names and f'HASLAM_HOME="{tmp_path}"' in env


# -- doctor --------------------------------------------------------------------------------------------------------

@pytest.fixture
def world(tmp_path):
    """A KiCad library pair, a checkout with both venvs (fake pythons) and a HASLAM_HOME with the control pinned."""
    sym, fp = tmp_path / "symbols", tmp_path / "footprints"
    sym.mkdir()
    (sym / "Device.kicad_sym").write_text("(kicad_symbol_lib)")
    (fp / "Resistor_SMD.pretty").mkdir(parents=True)
    (fp / "Resistor_SMD.pretty" / "R_0603.kicad_mod").write_text("(footprint)")
    repo = tmp_path / "repo"
    (repo / "haslam").mkdir(parents=True)
    for rel in (doctor.HASLAM_VENV, doctor.SYNTH_VENV):
        py = repo / rel / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    (home / tools.FR_PIN).write_text(f"{home}/haslam-freerouting-fork-{tools.freerouting_ref()}/bin/freerouting\n")
    env = {"HASLAM_KICAD_WRAP": "", "KICAD10_SYMBOL_DIR": str(sym), "KICAD10_FOOTPRINT_DIR": str(fp)}
    return env, repo, home


def by_name(checks):
    return {name: status for status, name, _ in checks}


def test_doctor_all_present(world):
    env, repo, home = world
    st = by_name(doctor.pipeline_checks(env, repo, home, strict=True))
    assert set(st.values()) == {"ok"}, st


def test_doctor_empty_library_dirs_fail(world, tmp_path):
    env, repo, home = world
    (tmp_path / "empty").mkdir()
    env = dict(env, KICAD10_SYMBOL_DIR=str(tmp_path / "empty"), KICAD10_FOOTPRINT_DIR=str(tmp_path / "empty"))
    st = by_name(doctor.pipeline_checks(env, repo, home))
    assert st["KICAD10_SYMBOL_DIR"] == "fail" and st["KICAD10_FOOTPRINT_DIR"] == "fail"


def test_doctor_missing_pieces_warn_unless_strict(world):
    env, repo, home = world
    env = {k: v for k, v in env.items() if k != "HASLAM_KICAD_WRAP"}
    (repo / doctor.SYNTH_VENV / "bin" / "python").unlink()
    (home / tools.FR_PIN).unlink()
    loose = by_name(doctor.pipeline_checks(env, repo, home))
    strict = by_name(doctor.pipeline_checks(env, repo, home, strict=True))
    for name in ("HASLAM_KICAD_WRAP", f"venv {doctor.SYNTH_VENV}", "freerouting pin"):
        assert loose[name] == "warn" and strict[name] == "fail", name


def test_doctor_a_venv_that_cannot_import_fails(world):
    env, repo, home = world
    (repo / doctor.HASLAM_VENV / "bin" / "python").write_text("#!/bin/sh\necho 'ModuleNotFoundError: numba' >&2\nexit 1\n")
    checks = doctor.pipeline_checks(env, repo, home)
    bad = [c for c in checks if c[1] == f"venv {doctor.HASLAM_VENV}"][0]
    assert bad[0] == "fail" and "numba" in bad[2]


def test_doctor_a_pin_other_than_the_control_warns(world):
    env, repo, home = world
    (home / tools.FR_PIN).write_text(f"{home}/haslam-freerouting-fork-0000000/bin/freerouting\n")
    assert by_name(doctor.pipeline_checks(env, repo, home, strict=True))["freerouting pin"] == "warn"


def test_doctor_runs_on_this_host():
    """The real checks complete without raising (their verdicts depend on the host)."""
    assert {s for s, _, _ in doctor.pipeline_checks()} <= {"ok", "warn", "fail"}
