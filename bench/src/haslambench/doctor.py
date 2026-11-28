# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks of the design pipeline's set-up (README.md Part 1), for `haslambench doctor`.

Each check returns (status, name, message) with status "ok", "warn" or "fail". The bench itself needs none of these,
so without --pipeline a missing piece is a warning; `bench/scripts/setup.sh --all` builds all of them and runs
`haslambench doctor --pipeline`, where it is a failure. An env.sh with HASLAM_KICAD_WRAP unset and KiCad libraries
that were never installed passed the old doctor (obd-solar FRICTION.md #5-#7).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import tools

REPO = Path(__file__).resolve().parents[3]          # bench/src/haslambench -> the checkout
HASLAM_VENV = Path("haslam/.venv")
SYNTH_VENV = Path("tools/research/llm-design/synth/.venv")
# what each venv must import: haslam with its compiled deps; haslamsynth with the haslam modules its rules and
# intent checks call (haslam/src on its path, written by setup.sh --all as haslam-src.pth)
IMPORTS = {HASLAM_VENV: "import haslam, haslam.cli, numpy, scipy, shapely, ortools",
           SYNTH_VENV: "import haslamsynth, haslamsynth.cli, haslam.board.dru_check, haslam.intent.facts"}


def _lib_dirs(env):
    out = []
    sym = env.get("KICAD10_SYMBOL_DIR")
    if not sym:
        out.append(("missing", "KICAD10_SYMBOL_DIR", "unset (haslamsynth looks up symbols there)"))
    elif not (Path(sym) / "Device.kicad_sym").is_file():
        out.append(("fail", "KICAD10_SYMBOL_DIR", f"{sym} has no Device.kicad_sym: install kicad-symbols "
                    "(the apt path's --no-install-recommends skips it) or point it at the image's usr/share/kicad/symbols"))
    else:
        out.append(("ok", "KICAD10_SYMBOL_DIR", sym))
    fp = env.get("KICAD10_FOOTPRINT_DIR")
    libs = sorted(Path(fp).glob("*.pretty")) if fp and Path(fp).is_dir() else []
    if not fp:
        out.append(("missing", "KICAD10_FOOTPRINT_DIR", "unset (haslamsynth looks up footprints there)"))
    elif not any(next(p.glob("*.kicad_mod"), None) for p in libs[:20]):
        out.append(("fail", "KICAD10_FOOTPRINT_DIR", f"{fp} has no <lib>.pretty with footprints: install "
                    "kicad-footprints or point it at the image's usr/share/kicad/footprints"))
    else:
        out.append(("ok", "KICAD10_FOOTPRINT_DIR", f"{fp} ({len(libs)} libraries)"))
    return out


def _venv(rel, repo, timeout=120):
    py = repo / rel / "bin" / "python"
    if not py.exists():
        return ("missing", f"venv {rel}", f"{py} does not exist")
    r = subprocess.run([str(py), "-c", IMPORTS[rel]], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        last = (r.stderr.strip().splitlines() or ["?"])[-1]
        return ("fail", f"venv {rel}", f"`{IMPORTS[rel]}` fails: {last}")
    return ("ok", f"venv {rel}", str(py))


def _pin(home):
    pin = home / tools.FR_PIN
    ref = tools.freerouting_ref()
    if not pin.is_file() or not pin.read_text().strip():
        return ("missing", "freerouting pin", f"no {pin}: tools/research/routing/install_freerouting_fork.sh {ref} --pin")
    text = pin.read_text().strip()
    if ref and f"haslam-freerouting-fork-{ref}/" not in text:
        return ("warn", "freerouting pin", f"{text} is not the control's fork {ref} (bench/freerouting.ref)")
    return ("ok", "freerouting pin", text)


def pipeline_checks(env=None, repo=REPO, home=None, strict=False):
    """[(status, name, message)] for the design pipeline. A missing piece is "fail" when strict, else "warn"."""
    env = os.environ if env is None else env
    home = Path(home) if home else tools.HASLAM_HOME
    out = []
    if "HASLAM_KICAD_WRAP" in env:
        out.append(("ok", "HASLAM_KICAD_WRAP", repr(env["HASLAM_KICAD_WRAP"]) + (" (native KiCad)"
                    if not env["HASLAM_KICAD_WRAP"] else "")))
    else:
        out.append(("missing", "HASLAM_KICAD_WRAP", f"undefined: `. {home}/env.sh` (scripts run "
                    "`$HASLAM_KICAD_WRAP kicad-cli` under set -u; empty is right for a native KiCad)"))
    out += _lib_dirs(env)
    if (repo / "haslam").is_dir():
        out += [_venv(HASLAM_VENV, repo), _venv(SYNTH_VENV, repo)]
    else:
        out.append(("missing", "venvs", f"{repo} is not a HaslamPCB checkout"))
    out.append(_pin(home))
    missing = "fail" if strict else "warn"
    return [(missing if s == "missing" else s, n, m) for s, n, m in out]
