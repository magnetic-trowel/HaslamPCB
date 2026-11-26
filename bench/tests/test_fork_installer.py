# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/research/routing/install_freerouting_fork.sh with a stand-in Gradle and JDK: a failed build is retried,
the build is installed under its commit and pinned, and a second run only re-pins."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "research" / "routing" / "install_freerouting_fork.sh"
pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")


def _exe(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def _git(*a, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


def test_retry_install_and_pin(tmp_path):
    up, src, hh, gh = tmp_path / "up", tmp_path / "src", tmp_path / "hh", tmp_path / "gradle"
    up.mkdir()
    tries = tmp_path / "tries"
    # the first build fails (a rate limit), the second writes the executable jar
    _exe(up / "gradlew", f'echo x >> "{tries}"\n[ "$(wc -l < "{tries}")" -ge 2 ] || exit 1\n'
                         'mkdir -p build/libs && echo jar > build/libs/fr-executable.jar\n')
    _git("init", "-q", cwd=up)
    _git("add", ".", cwd=up)
    _git("commit", "-qm", "fork", cwd=up)
    _git("clone", "-q", str(up), str(src), cwd=tmp_path)
    jdk = tmp_path / "jdk"
    _exe(jdk / "bin/java", "echo 'openjdk version \"25.0.1\"' >&2\n")
    _exe(jdk / "bin/jlink", 'while [ "$1" != --output ]; do shift; done\nmkdir -p "$2/bin" && cp "$0" "$2/bin/java"\n')
    env = dict(os.environ, HASLAM_HOME=str(hh), JAVA_HOME=str(jdk), FR_RETRY_WAITS="0 0 0", GRADLE_USER_HOME=str(gh))
    r = subprocess.run(["bash", str(SCRIPT), "HEAD", str(src), "--pin"], env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert tries.read_text().count("x") == 2 and "retrying" in r.stderr
    sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    dest = hh / f"haslam-freerouting-fork-{sha}"
    assert (dest / "lib/freerouting.jar").read_text() == "jar\n" and os.access(dest / "bin/freerouting", os.X_OK)
    assert (hh / "haslam-freerouting.pin").read_text().strip() == str(dest / "bin/freerouting")
    assert not (hh / "jdk-25").exists()                            # a JDK was given: none downloaded
    (hh / "haslam-freerouting.pin").unlink()
    r = subprocess.run(["bash", str(SCRIPT), "HEAD", str(src), "--pin"], env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and "already installed" in r.stdout and tries.read_text().count("x") == 2
    assert (hh / "haslam-freerouting.pin").is_file()
