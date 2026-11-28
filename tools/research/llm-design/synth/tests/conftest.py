# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from haslamsynth.kicadlib import footprint_dir, symbol_dir

# The build's rules and intent checks import haslam (setup.sh --all puts haslam/src on the synth venv's path). In a
# venv without it, use the checkout's: otherwise the KiCad tests see "dru_check not importable" instead of the
# verdict they test (obd-solar FRICTION.md #30).
_HASLAM_SRC = Path(__file__).resolve().parents[5] / "haslam" / "src"
if importlib.util.find_spec("haslam") is None and (_HASLAM_SRC / "haslam").is_dir():
    sys.path.insert(0, str(_HASLAM_SRC))

HAVE_LIBS = symbol_dir() is not None and footprint_dir() is not None
HAVE_KICAD = HAVE_LIBS and shutil.which("kicad-cli") is not None


def pytest_collection_modifyitems(config, items):
    for it in items:
        if "kicad" in it.keywords and not HAVE_KICAD:
            it.add_marker(pytest.mark.skip(reason="needs kicad-cli and KiCad libraries"))
