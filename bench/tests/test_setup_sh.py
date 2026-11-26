# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""bench/scripts/setup.sh's KiCad branches, run with stand-in tools (HASLAM_SETUP_LIB=1 sources its functions):
the apt branch's packages and the env.sh both branches write, without touching the host's KiCad."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parents[1] / "scripts" / "setup.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _exe(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def _run(tmp_path, script, shims=None, **env):
    """Source setup.sh's functions in bash, run SCRIPT, return (stdout, HASLAM_HOME/env.sh text)."""
    home = tmp_path / "hh"
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (shims or {}).items():
        _exe(bindir / name, body)
    e = dict(os.environ, HASLAM_HOME=str(home), HASLAM_SETUP_LIB="1", PATH=f"{bindir}:{os.environ['PATH']}", **env)
    r = subprocess.run(["bash", "-c", f'set -- --venv "{tmp_path}/venv"; . "{SETUP}"; {script}; write_env'],
                       env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout, (home / "env.sh").read_text()


def _sysroot(tmp_path, pcbnew=True):
    root = tmp_path / "root"
    _exe(root / "usr/bin/python3", "exit 0\n" if pcbnew else "exit 1\n")
    for d in ("symbols", "footprints"):
        (root / "usr/share/kicad" / d).mkdir(parents=True)
    return root


def test_native_env_names_kicads_python_and_libraries(tmp_path):
    root = _sysroot(tmp_path)
    _, env = _run(tmp_path, "native_kicad_env", HASLAM_SETUP_SYSROOT=str(root))
    assert f'export HASLAM_KICAD_PYTHON="{root}/usr/bin/python3"' in env
    assert f"export KICAD10_SYMBOL_DIR={root}/usr/share/kicad/symbols" in env
    assert f"export KICAD10_FOOTPRINT_DIR={root}/usr/share/kicad/footprints" in env
    assert "KICAD10_3DMODEL_DIR" not in env                       # not installed: not exported
    assert f'export HASLAM_HOME="{tmp_path}/hh"' in env


def test_native_env_skips_a_python_without_pcbnew(tmp_path):
    _, env = _run(tmp_path, "native_kicad_env", HASLAM_SETUP_SYSROOT=str(_sysroot(tmp_path, pcbnew=False)))
    assert "HASLAM_KICAD_PYTHON" not in env


@pytest.mark.parametrize("version, three_d", [("", 0), ("10.0.8", 1)])
def test_apt_branch_installs_the_libraries(tmp_path, version, three_d):
    log = tmp_path / "apt.log"
    shims = {
        # launchpad's archive JSON, then the key; gpg/tee/apt-get only record what they were asked
        "curl": 'case "$*" in *launchpad*) echo \'{"signing_key_fingerprint": "ABCD"}\';; *) echo KEY;; esac\n',
        "gpg": "cat >/dev/null\n",
        "tee": "cat >/dev/null\n",
        "apt-get": f'echo "apt-get $*" >> "{log}"\n',
    }
    root = _sysroot(tmp_path)
    _, env = _run(tmp_path, f"DO_3D={three_d}; SUDO=; install_kicad_apt", shims,
                  HASLAM_SETUP_SYSROOT=str(root), KICAD_APT_VERSION=version)
    install = [ln for ln in log.read_text().splitlines() if " install " in ln and "kicad" in ln]
    assert len(install) == 1
    want = ["kicad", "kicad-symbols", "kicad-footprints"] + (["kicad-packages3d"] if three_d else [])
    suffix = f"={version}*" if version else ""
    assert install[0].split("--no-install-recommends ")[1].split() == [p + suffix for p in want]
    assert "HASLAM_KICAD_PYTHON" in env and "KICAD10_FOOTPRINT_DIR" in env


def test_container_env_wraps_kicad_and_exports_the_images_libraries(tmp_path):
    img = tmp_path / "hh" / "kicad-10.0.7"
    _exe(img / "usr/bin/kicad-cli", "exit 0\n")                   # already unpacked: no build
    for d in ("symbols", "footprints", "3dmodels"):
        (img / "usr/share/kicad" / d).mkdir(parents=True)
    _, env = _run(tmp_path, "install_kicad_container", {"apptainer": "exit 0\n"})
    hh = tmp_path / "hh"
    assert f'export HASLAM_KICAD_WRAP="{hh}/kicad-exec {tmp_path}/bin/apptainer {img}"' in env
    for var, d in (("SYMBOL", "symbols"), ("FOOTPRINT", "footprints"), ("3DMODEL", "3dmodels")):
        assert f"export KICAD10_{var}_DIR={img}/usr/share/kicad/{d}" in env
    assert os.access(hh / "kicad-exec", os.X_OK) and (hh / "cpus" / "1").read_text() == "0-0\n"
    assert "HASLAM_KICAD_PYTHON" not in env
