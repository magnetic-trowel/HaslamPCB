# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge runs a Freerouting build that is named, never the newest one installed."""
import os

import pytest

from haslam.route import freerouting as FR


def _build(home, name, age):
    b = home / name / "bin" / "freerouting"
    b.parent.mkdir(parents=True)
    b.write_text("#!/bin/sh\n")
    os.utime(b, (age, age))
    return b


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(FR, "HASLAM_HOME", tmp_path)
    monkeypatch.delenv("HASLAM_BRIDGE_FREEROUTING", raising=False)
    monkeypatch.delenv("HASLAM_FREEROUTING", raising=False)
    return tmp_path


def test_newest_install_is_never_picked(home):
    _build(home, "haslam-freerouting-fork-aaaaaaa", 1_000)
    _build(home, "haslam-freerouting-fork-bbbbbbb-experiment", 2_000)   # newer: an experiment's wrapper
    with pytest.raises(FR.FreeroutingError, match="pinned"):
        FR.command()


def test_pin_names_the_build(home):
    prod = _build(home, "haslam-freerouting-fork-aaaaaaa", 1_000)
    _build(home, "haslam-freerouting-fork-bbbbbbb-experiment", 2_000)
    (home / FR.PIN_FILE).write_text("haslam-freerouting-fork-aaaaaaa/bin/freerouting\n")   # relative to HASLAM_HOME
    assert FR.command() == [str(prod)]
    (home / FR.PIN_FILE).write_text(str(prod))                                         # absolute
    assert FR.command() == [str(prod)]


def test_a_pin_to_a_missing_build_fails(home):
    (home / FR.PIN_FILE).write_text("haslam-freerouting-fork-gone/bin/freerouting")
    with pytest.raises(FR.FreeroutingError, match="not a file"):
        FR.command()


def test_environment_wins_over_the_pin(home, monkeypatch):
    prod = _build(home, "haslam-freerouting-fork-aaaaaaa", 1_000)
    (home / FR.PIN_FILE).write_text(str(prod))
    monkeypatch.setenv("HASLAM_BRIDGE_FREEROUTING", "/opt/fr/freerouting.jar")
    assert FR.command() == ["java", "-jar", "/opt/fr/freerouting.jar"]
    monkeypatch.delenv("HASLAM_BRIDGE_FREEROUTING")
    monkeypatch.setenv("HASLAM_FREEROUTING", "/opt/fr2/bin/freerouting")
    assert FR.command() == [str(prod)], "the pin comes before the generic HASLAM_FREEROUTING"
    (home / FR.PIN_FILE).unlink()
    assert FR.command() == ["/opt/fr2/bin/freerouting"]
